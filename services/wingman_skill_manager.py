"""WingmanSkillManager — skill discovery, lifecycle, and state.

Owns ``skills``, ``tool_skills``, and ``skill_tools``; the parent ``Wingman``
exposes them as read-through properties.
"""

import traceback
from typing import TYPE_CHECKING

from api.interface import (
    SkillConfig,
    SettingsConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from api.enums import (
    LogSource,
    LogType,
    WingmanInitializationErrorType,
)
from services.module_manager import ModuleManager
from services.platform_utils import normalize_platform
from services.printr import Printr
from services.skill_registry import SkillRegistry
from skills.skill_base import Skill
from wingmen.wingman_context import WingmanContext

if TYPE_CHECKING:
    from wingmen.wingman import Wingman

printr = Printr()


def _get_skill_folder_from_module(module: str) -> str:
    """Extract folder name from module path like 'skills.star_head.main' -> 'star_head'"""
    return module.replace(".main", "").replace(".", "/").split("/")[1]


class WingmanSkillManager:
    """Manages skill discovery, loading, preparation, enable/disable, and teardown."""

    def __init__(
        self,
        wingman: "Wingman",
        config: WingmanConfig,
        settings: SettingsConfig,
        skill_registry: SkillRegistry,
    ):
        self._wingman = wingman
        self.config = config
        self.settings = settings
        self.skill_registry = skill_registry

        # Manager owns skill state
        self.skills: list[Skill] = []
        self.tool_skills: dict[str, Skill] = {}
        self.skill_tools: list[dict] = []

    # ──────────────────────────── Private helpers ─────────────────────────────── #

    def _sync_conversation_skill_context(self) -> None:
        """Push current skill state into the conversation manager.

        Called after every mutation (init/enable/disable/unload) so that
        ConversationManager does not need per-call skill kwargs.
        """
        self._wingman.conversation.set_skill_context(
            self.skills, self.skill_registry, self.tool_skills
        )

    def _build_user_skill_configs(self) -> dict[str, SkillConfig]:
        """Map folder name → user SkillConfig for each entry in wingman config."""
        result: dict[str, SkillConfig] = {}
        if self.config.skills:
            for skill_config in self.config.skills:
                folder_name = _get_skill_folder_from_module(skill_config.module)
                result[folder_name] = skill_config
        return result

    def _load_skill_config(
        self,
        skill_folder_name: str,
        skill_config_path: str,
        user_skill_configs: dict[str, SkillConfig],
    ) -> SkillConfig | None:
        """Read yaml config + merge user overrides; return SkillConfig or None."""
        skill_config_dict = ModuleManager.read_config(skill_config_path)
        if not skill_config_dict:
            return None

        if skill_folder_name in user_skill_configs:
            user_config = user_skill_configs[skill_folder_name]
            if user_config.custom_properties:
                skill_config_dict["custom_properties"] = [
                    prop.model_dump() for prop in user_config.custom_properties
                ]
            if user_config.prompt:
                skill_config_dict["prompt"] = user_config.prompt

        return SkillConfig(**skill_config_dict)

    def _check_platform_supported(
        self, skill_config: SkillConfig
    ) -> tuple[bool, str]:
        """Return (ok, reason) for whether the skill supports the current platform."""
        if not skill_config.platforms:
            return True, ""
        normalized = normalize_platform()
        if normalized not in skill_config.platforms:
            return (
                False,
                f"Skill '{skill_config.name}' is not supported on {normalized}.",
            )
        return True, ""

    def _instantiate_skill(self, skill_config: SkillConfig) -> Skill | None:
        """Create WingmanContext, call ModuleManager.load_skill, bind helpers."""
        context = WingmanContext(self._wingman)
        skill = ModuleManager.load_skill(
            config=skill_config,
            settings=self.settings,
            wingman=context,
        )
        if skill:
            skill.threaded_execution = self._wingman.threaded_execution
        return skill

    # ──────────────────────────── Public API ─────────────────────────────────── #

    async def init_skills(self) -> list[WingmanInitializationError]:
        if self.skills:
            await self.unload_skills()

        errors = []
        self.skills = []

        user_skill_configs = self._build_user_skill_configs()
        available_skills = ModuleManager.read_available_skill_configs()
        discoverable_skills = self.config.discoverable_skills

        for (
            skill_folder_name,
            skill_config_path,
            _is_custom,
            _is_local,
        ) in available_skills:
            try:
                skill_config = self._load_skill_config(
                    skill_folder_name, skill_config_path, user_skill_configs
                )
                if not skill_config:
                    continue

                if skill_config.name not in discoverable_skills:
                    continue

                ok, reason = self._check_platform_supported(skill_config)
                if not ok:
                    printr.print(
                        f"Skipping skill - {reason}",
                        color=LogType.WARNING,
                        server_only=True,
                    )
                    continue

                skill = self._instantiate_skill(skill_config)
                if skill:
                    self.skills.append(skill)
                    await self.prepare_skill(skill)

            except Exception as e:
                skill_name = skill_folder_name
                error_msg = f"Error loading skill '{skill_name}': {str(e)}"
                await printr.print_async(
                    error_msg,
                    color=LogType.ERROR,
                )
                printr.print(
                    traceback.format_exc(), color=LogType.ERROR, server_only=True
                )
                errors.append(
                    WingmanInitializationError(
                        wingman_name=self._wingman.name,
                        message=error_msg,
                        error_type=WingmanInitializationErrorType.SKILL_INITIALIZATION_FAILED,
                    )
                )

        if self.skills:
            skill_names = [s.config.name for s in self.skills]
            await printr.print_async(
                f"Discoverable skills ({len(skill_names)}): {', '.join(skill_names)}",
                color=LogType.WINGMAN,
                source=LogSource.WINGMAN,
                source_name=self._wingman.name,
                server_only=not self.settings.debug_mode,
            )

        self._sync_conversation_skill_context()
        return errors

    async def prepare_skill(self, skill: Skill):
        try:
            for tool_name, tool in skill.get_tools():
                self.tool_skills[tool_name] = skill
                self.skill_tools.append(tool)

            self.skill_registry.register_skill(skill)

            if skill.config.auto_activate:
                success, message = await skill.ensure_activated()
                if not success:
                    await printr.print_async(
                        f"Auto-activated skill '{skill.config.display_name}' failed to activate: {message}",
                        color=LogType.ERROR,
                    )
        except Exception as e:
            await printr.print_async(
                f"Error while preparing skill '{skill.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

        skill.llm_call = self._wingman.actual_llm_call

    async def unprepare_skill(self, skill: Skill):
        try:
            for tool_name, _ in skill.get_tools():
                self.tool_skills.pop(tool_name, None)
                self.skill_tools = [
                    t
                    for t in self.skill_tools
                    if t.get("function", {}).get("name") != tool_name
                ]
            self.skill_registry.unregister_skill(skill.name)
        except Exception as e:
            await printr.print_async(
                f"Error while unpreparing skill '{skill.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
        self._sync_conversation_skill_context()

    async def enable_skill(self, skill_name: str) -> tuple[bool, str]:
        for existing_skill in self.skills:
            if existing_skill.config.name == skill_name:
                return True, f"Skill '{skill_name}' is already enabled."

        available_skills = ModuleManager.read_available_skill_configs()
        user_skill_configs = self._build_user_skill_configs()

        for (
            skill_folder_name,
            skill_config_path,
            _is_custom,
            _is_local,
        ) in available_skills:
            try:
                skill_config = self._load_skill_config(
                    skill_folder_name, skill_config_path, user_skill_configs
                )
                if not skill_config:
                    continue

                if skill_config.name != skill_name:
                    continue

                ok, reason = self._check_platform_supported(skill_config)
                if not ok:
                    return False, reason

                skill = self._instantiate_skill(skill_config)
                if skill:
                    self.skills.append(skill)
                    await self.prepare_skill(skill)
                    self._sync_conversation_skill_context()

                    printr.print(
                        f"Skill '{skill_name}' activated (loaded and made discoverable).",
                        color=LogType.POSITIVE,
                        server_only=True,
                    )
                    return True, f"Skill '{skill_name}' activated successfully."

            except Exception as e:
                error_msg = f"Error activating skill '{skill_name}': {str(e)}"
                await printr.print_async(error_msg, color=LogType.ERROR)
                printr.print(
                    traceback.format_exc(), color=LogType.ERROR, server_only=True
                )
                return False, error_msg

        return False, f"Skill '{skill_name}' not found."

    async def disable_skill(self, skill_name: str) -> tuple[bool, str]:
        skill_to_remove = None
        for skill in self.skills:
            if skill.config.name == skill_name:
                skill_to_remove = skill
                break

        if not skill_to_remove:
            return True, f"Skill '{skill_name}' is already deactivated."

        try:
            await skill_to_remove.unload()
            self.skills.remove(skill_to_remove)
            await self.unprepare_skill(skill_to_remove)

            printr.print(
                f"Skill '{skill_name}' deactivated (unloaded and removed from discoverable skills).",
                color=LogType.WARNING,
                server_only=True,
            )
            return True, f"Skill '{skill_name}' deactivated successfully."

        except Exception as e:
            error_msg = f"Error deactivating skill '{skill_name}': {str(e)}"
            await printr.print_async(error_msg, color=LogType.ERROR)
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return False, error_msg

    async def unload_skills(self):
        for skill in self.skills:
            if not skill.is_prepared:
                continue
            try:
                await skill.unload()
            except Exception as e:
                await printr.print_async(
                    f"Error unloading skill '{skill.name}': {str(e)}",
                    color=LogType.ERROR,
                )
                printr.print(
                    traceback.format_exc(), color=LogType.ERROR, server_only=True
                )
        self.tool_skills = {}
        self.skill_tools = []
        self.skill_registry.clear()
        self._sync_conversation_skill_context()
