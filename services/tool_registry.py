"""
Skill Registry with Enum-Based Tool Discovery

This module implements enum-based progressive tool disclosure to reduce token usage
and improve reliability across all languages.

Key concepts:
- SkillManifest: Lightweight metadata about a skill (name, description)
- SkillRegistry: Central registry that tracks all skills and their manifests
- Unified activation: LLM selects from enum of available skills (no fuzzy search)

The enum approach ensures:
- 100% reliable activation (LLM must pick from valid options)
- Works in any language (LLM translates user intent to enum value)
- Fewer LLM calls (no separate search step needed)
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from api.enums import LogType
from services.printr import Printr

if TYPE_CHECKING:
    from skills.skill_base import Skill

printr = Printr()


@dataclass
class SkillManifest:
    """Lightweight metadata about a skill for enum-based discovery."""

    name: str
    """Internal skill class name (e.g., 'FileManager')"""

    display_name: str
    """Human-readable name (e.g., 'File Manager')"""

    description: str
    """What the skill does - shown in enum tool description"""

    tags: list[str] = field(default_factory=list)
    """Categorical tags like ['Utility', 'Image']"""

    tool_names: list[str] = field(default_factory=list)
    """Names of tools this skill provides"""

    tool_summaries: list[str] = field(default_factory=list)
    """One-line descriptions of each tool"""

    is_auto_activated: bool = False
    """If True, this skill is always active and hidden from progressive disclosure."""

    @classmethod
    def from_skill(cls, skill: "Skill") -> "SkillManifest":
        """Create a manifest from a Skill instance."""
        # Get tool info
        tool_names = []
        tool_summaries = []
        for tool_name, tool_def in skill.get_tools():
            tool_names.append(tool_name)
            # Extract description from tool definition
            if isinstance(tool_def, dict):
                func_def = tool_def.get("function", tool_def)
                desc = func_def.get("description", "No description")
                # Truncate to one line
                tool_summaries.append(desc.split("\n")[0][:100])
            else:
                tool_summaries.append("No description")

        return cls(
            name=skill.name,
            display_name=skill.config.display_name,
            description=skill.config.description.en if skill.config.description else "",
            tags=skill.config.tags or [],
            tool_names=tool_names,
            tool_summaries=tool_summaries,
            is_auto_activated=skill.config.auto_activate or False,
        )

    def get_short_description(self, max_length: int = 80) -> str:
        """Get a shortened description for enum display."""
        if len(self.description) <= max_length:
            return self.description
        return self.description[: max_length - 3] + "..."

    def to_summary(self) -> str:
        """Returns a compact string representation for LLM context."""
        tools_str = ", ".join(self.tool_names) if self.tool_names else "No tools"
        return f"**{self.display_name}** (id: {self.name})\n  {self.description}\n  Tools: {tools_str}"


class SkillRegistry:
    """
    Central registry for skills with enum-based discovery.

    Enum-based discovery:
    - The activate_skill tool has an enum of all available skill IDs
    - LLM sees descriptions in tool definition and picks the right one
    - No fuzzy search needed - works reliably in any language
    - Activated skills' tools are added to the conversation
    """

    def __init__(self):
        self._skills: dict[str, "Skill"] = {}
        """All registered skills by name"""

        self._manifests: dict[str, SkillManifest] = {}
        """Skill manifests for progressive disclosure"""

        self._active_skills: set[str] = set()
        """Currently activated skills (their tools are available to LLM)"""

        self._auto_activated_skills: set[str] = set()
        """Skills that are always active (configured with auto_activate=True)"""

        self._tool_to_skill: dict[str, str] = {}
        """Maps tool names to skill names"""

    def register_skill(self, skill: "Skill") -> None:
        """Register a skill and create its manifest."""
        self._skills[skill.name] = skill
        manifest = SkillManifest.from_skill(skill)
        self._manifests[skill.name] = manifest

        # Map tool names to this skill
        for tool_name, _ in skill.get_tools():
            self._tool_to_skill[tool_name] = skill.name

        # Auto-activate if configured
        if manifest.is_auto_activated:
            self._auto_activated_skills.add(skill.name)
            printr.print(
                f"Auto-activated skill: {manifest.display_name}",
                color=LogType.SKILL,
                server_only=True,
            )

    def unregister_skill(self, skill_name: str) -> None:
        """Remove a skill from the registry."""
        if skill_name in self._skills:
            # Remove tool mappings
            manifest = self._manifests.get(skill_name)
            if manifest:
                for tool_name in manifest.tool_names:
                    self._tool_to_skill.pop(tool_name, None)

            self._skills.pop(skill_name, None)
            self._manifests.pop(skill_name, None)
            self._active_skills.discard(skill_name)
            self._auto_activated_skills.discard(skill_name)

    def clear(self) -> None:
        """Clear all registered skills."""
        self._skills.clear()
        self._manifests.clear()
        self._active_skills.clear()
        self._auto_activated_skills.clear()
        self._tool_to_skill.clear()

    def get_discoverable_skills(self) -> list[SkillManifest]:
        """
        Get all skills that can be activated by the LLM.
        Excludes auto-activated skills (they're always available).
        """
        return [m for m in self._manifests.values() if not m.is_auto_activated]

    def activate_skill(self, skill_name: str) -> tuple[bool, str, bool]:
        """
        Activate a skill, making its tools available to the LLM.

        Note: This only marks the skill as active. Lazy validation should be
        performed by calling skill.ensure_activated() before first use.

        Returns:
            (success, message, needs_validation) tuple
            - success: Whether the skill was found and marked active
            - message: Status message
            - needs_validation: Whether the skill needs validation before use
        """
        if skill_name not in self._skills:
            available = ", ".join(self._manifests.keys())
            printr.print(
                f"Skill '{skill_name}' not found",
                color=LogType.WARNING,
                server_only=True,  # Internal warning, keep in log
            )
            return (
                False,
                f"Skill '{skill_name}' not found. Available skills: {available}",
                False,
            )

        skill = self._skills[skill_name]
        needs_validation = skill.needs_activation()

        self._active_skills.add(skill_name)
        manifest = self._manifests[skill_name]
        tools_str = ", ".join(manifest.tool_names)

        if needs_validation:
            printr.print(
                f"Activating skill: {manifest.display_name} (validating...)",
                color=LogType.SKILL,
                # Always show activation in UI - important for users to know
            )
            return (
                True,
                f"Activating '{manifest.display_name}' (validation pending). Tools: {tools_str}",
                True,
            )

        printr.print(
            f"Skill activated: {manifest.display_name}",
            color=LogType.SKILL,
            # Always show activation in UI - important for users to know
        )
        return (
            True,
            f"Activated '{manifest.display_name}'. Available tools: {tools_str}",
            False,
        )

    def deactivate_skill(self, skill_name: str) -> tuple[bool, str]:
        """Deactivate a skill, removing its tools from availability."""
        if skill_name not in self._active_skills:
            return False, f"Skill '{skill_name}' is not currently active."

        self._active_skills.discard(skill_name)
        manifest = self._manifests.get(skill_name)
        display_name = manifest.display_name if manifest else skill_name
        printr.print(
            f"Skill deactivated: {display_name}",
            color=LogType.SKILL,
            server_only=True,  # Deactivation is internal, keep in log
        )
        return True, f"Deactivated skill '{skill_name}'."

    def reset_activations(self) -> None:
        """Reset all skill activations except auto-activated skills.

        Called when conversation history is reset, since the LLM loses
        all memory of which skills were activated and why.
        Auto-activated skills remain active since they don't require LLM activation.
        """
        # Only count non-auto-activated skills being reset
        manual_activations = self._active_skills - self._auto_activated_skills
        if manual_activations:
            count = len(manual_activations)
            printr.print(
                f"Conversation reset: deactivating {count} skill(s)",
                color=LogType.SKILL,
                server_only=True,
            )
        self._active_skills = self._auto_activated_skills.copy()

    def get_skill_for_tool(self, tool_name: str) -> Optional["Skill"]:
        """Get the skill that provides a given tool."""
        skill_name = self._tool_to_skill.get(tool_name)
        if skill_name:
            return self._skills.get(skill_name)
        return None

    def get_skill_for_activation(self, skill_name: str) -> Optional["Skill"]:
        """Get a skill by name for activation purposes."""
        return self._skills.get(skill_name)

    def get_skill_display_name(self, skill_name: str) -> str:
        """Get the display name for a skill, or the skill name if not found."""
        manifest = self._manifests.get(skill_name)
        return manifest.display_name if manifest else skill_name

    def get_active_tools(self) -> list[tuple[str, dict]]:
        """
        Get tools from all active skills (both explicitly activated and auto-activated).
        """
        tools = []
        # Combine manually activated and auto-activated skills
        all_active = self._active_skills | self._auto_activated_skills
        for skill_name in all_active:
            skill = self._skills.get(skill_name)
            if skill:
                tools.extend(skill.get_tools())
        return tools

    def get_meta_tools(self) -> list[tuple[str, dict]]:
        """
        Returns meta-tools for enum-based skill discovery.
        Uses enum constraint for reliable activation in any language.
        """
        discoverable = self.get_discoverable_skills()

        if not discoverable:
            return []  # No discoverable skills available

        # Build enum values (skill IDs)
        skill_ids = [m.name for m in discoverable]

        # Build descriptions for the tool (helps LLM choose correctly)
        skill_descriptions = []
        for m in discoverable:
            short_desc = m.get_short_description(60)
            skill_descriptions.append(f"- {m.name}: {short_desc}")

        descriptions_block = "\n".join(skill_descriptions)

        return [
            (
                "activate_skill",
                {
                    "type": "function",
                    "function": {
                        "name": "activate_skill",
                        "description": f"Activate a skill to use its tools. Pick based on what you need:\n\n{descriptions_block}",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "skill_name": {
                                    "type": "string",
                                    "enum": skill_ids,
                                    "description": "The skill to activate",
                                },
                            },
                            "required": ["skill_name"],
                        },
                    },
                },
            ),
            (
                "list_active_skills",
                {
                    "type": "function",
                    "function": {
                        "name": "list_active_skills",
                        "description": "List currently activated skills and their available tools.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                },
            ),
        ]

    def execute_meta_tool(self, tool_name: str, parameters: dict) -> tuple[str, bool]:
        """
        Execute a meta-tool.

        Returns:
            (result_string, tools_changed) - tools_changed indicates if the LLM
            should receive an updated tool list
        """
        # Debug logging for developers (server-only)
        printr.print(
            f"Meta-tool called: {tool_name}({parameters})",
            color=LogType.SKILL,
            server_only=True,
        )

        if tool_name == "activate_skill":
            skill_name = parameters.get("skill_name", "")
            success, message, _ = self.activate_skill(skill_name)
            # Return success status and whether tools changed
            # Note: needs_validation is handled async in OpenAiWingman
            return message, success

        elif tool_name == "list_active_skills":
            if not self._active_skills and not self._auto_activated_skills:
                return (
                    "No skills are currently active. Use activate_skill to enable one.",
                    False,
                )

            all_active = self._active_skills | self._auto_activated_skills
            parts = [f"Currently active skills ({len(all_active)} total):\n"]
            for skill_name in all_active:
                manifest = self._manifests.get(skill_name)
                if manifest:
                    tools = (
                        ", ".join(manifest.tool_names)
                        if manifest.tool_names
                        else "no tools"
                    )
                    auto_tag = " (auto)" if manifest.is_auto_activated else ""
                    parts.append(f"- {manifest.display_name}{auto_tag}: {tools}")
            return "\n".join(parts), False

        return f"Unknown meta-tool: {tool_name}", False

    def is_meta_tool(self, tool_name: str) -> bool:
        """Check if a tool name is a meta-tool."""
        return tool_name in {"activate_skill", "list_active_skills"}

    @property
    def skill_count(self) -> int:
        """Number of registered skills."""
        return len(self._skills)

    @property
    def active_skill_count(self) -> int:
        """Number of currently active skills (including auto-activated)."""
        return len(self._active_skills | self._auto_activated_skills)

    @property
    def active_skill_names(self) -> set[str]:
        """Names of currently active skills (including auto-activated)."""
        return (self._active_skills | self._auto_activated_skills).copy()
