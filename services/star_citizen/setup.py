"""The Star Citizen step of the first-start setup.

The client asks once whether the user plays Star Citizen. The answer switches
every Star Citizen feature on or off in one go: the log reader, the bundled
pronunciation and transcription lists, and the Star Citizen skills and MCP
servers on the Wingmen Wingman ships for the game (ATC and Computer). After
that the step lists those features with a switch each, and the switches are
the normal toggle endpoints.

Wingmen the user made are left alone: the client tells the user to set them
up themselves.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from api.enums import StarCitizenFeatureKind
from api.interface import (
    ConfigDirInfo,
    SkillBase,
    StarCitizenFeature,
    StarCitizenGameFolder,
    StarCitizenSetup,
    StarCitizenSetupWingman,
    WingmanConfigFileInfo,
)
from services.module_manager import ModuleManager
from services.platform_utils import normalize_platform
from services.printr import Printr
from services.star_citizen.game_folder import (
    find_game_folder,
    inspect_game_folder,
    normalize_game_path,
)

if TYPE_CHECKING:
    from services.config_service import ConfigService
    from services.settings_service import SettingsService

STAR_CITIZEN_CONFIG = "Star Citizen"
"""The config the Star Citizen Wingmen ship in (templates/configs)."""
PRESET = "star_citizen"
"""The id of the bundled pronunciation and transcription lists."""
ALL_WINGMEN = None


@dataclass(frozen=True)
class _Feature:
    kind: StarCitizenFeatureKind
    name: str
    on_for: tuple[str, ...] | None
    """The shipped Wingmen it is switched on for when the user plays the
    game; None for all of them, () for none."""


FEATURES = (
    _Feature(StarCitizenFeatureKind.MCP, "wingman_starhead", ALL_WINGMEN),
    _Feature(StarCitizenFeatureKind.MCP, "wingman_galactapedia", ALL_WINGMEN),
    # Both react to the game log. On one Wingman only, or every event is
    # answered twice.
    _Feature(StarCitizenFeatureKind.SKILL, "ScGameEvents", ("Computer",)),
    _Feature(StarCitizenFeatureKind.SKILL, "SC_Accountant", ("Computer",)),
    _Feature(StarCitizenFeatureKind.MCP, "wingman_versetime", ()),
    # StarHead covers trading by default; UEX is the alternative to switch on.
    _Feature(StarCitizenFeatureKind.SKILL, "UEXCorp", ()),
)


def on_by_default(feature: _Feature, wingman_name: str) -> bool:
    return feature.on_for is None or wingman_name in feature.on_for


class StarCitizenSetupService:
    def __init__(
        self, config_service: "ConfigService", settings_service: "SettingsService"
    ):
        self.config_service = config_service
        self.settings_service = settings_service
        self.config_manager = config_service.config_manager
        self.printr = Printr()

    # GET /star-citizen/game-folder
    def check_game_folder(self, path: str) -> StarCitizenGameFolder:
        """What is in a folder the user picked or typed. An environment
        folder or a Game.log stands for the StarCitizen folder above it."""
        return inspect_game_folder(normalize_game_path(path))

    # GET /star-citizen/setup
    def get_setup(self) -> StarCitizenSetup:
        available = self._available()
        return StarCitizenSetup(
            game_folder=self._game_folder(),
            wingmen=[
                StarCitizenSetupWingman(
                    config_dir=config_dir,
                    wingman_file=wingman_file,
                    features=self._features(config_dir, wingman_file, available),
                )
                for config_dir, wingman_file in self._shipped_wingmen()
            ],
        )

    # POST /star-citizen/plays
    async def apply_answer(self, plays: bool) -> StarCitizenSetup:
        """Switch every Star Citizen feature on or off. On only switches on
        what is on by default and leaves the rest as the user had it; off
        switches everything off. The answer itself is saved by the client
        with the settings once the step is done."""
        settings = deepcopy(self.settings_service.settings)
        settings.sc_gamelog.enabled = plays
        _set_preset(settings.pronunciation.presets, plays)
        _set_preset(settings.stt.presets, plays)
        if plays:
            folder = self._game_folder()
            if folder.environments:
                settings.star_citizen.game_path = folder.path
        await self.settings_service.save_settings(settings)

        available = self._available()
        for config_dir, wingman_file in self._shipped_wingmen():
            for feature in FEATURES:
                if (feature.kind, feature.name) not in available:
                    continue
                if plays and not on_by_default(feature, wingman_file.name):
                    continue
                await self.toggle(config_dir, wingman_file, feature, plays)

        self.printr.print(
            f"Star Citizen features switched {'on' if plays else 'off'}.",
            server_only=True,
        )
        return self.get_setup()

    async def toggle(
        self,
        config_dir: ConfigDirInfo,
        wingman_file: WingmanConfigFileInfo,
        feature: _Feature,
        enabled: bool,
    ) -> None:
        if feature.kind == StarCitizenFeatureKind.SKILL:
            await self.config_service.toggle_wingman_skill(
                config_dir, wingman_file, feature.name, enabled
            )
        else:
            await self.config_service.toggle_wingman_mcp(
                config_dir, wingman_file, feature.name, enabled
            )

    def _game_folder(self) -> StarCitizenGameFolder:
        """The folder from the settings if the game is there, else the one
        Core found, else the one from the settings anyway."""
        configured = inspect_game_folder(
            self.settings_service.settings.star_citizen.game_path
        )
        if configured.environments:
            return configured
        found = find_game_folder()
        return inspect_game_folder(found) if found else configured

    def _shipped_wingmen(self) -> list[tuple[ConfigDirInfo, WingmanConfigFileInfo]]:
        config_dir = self.config_manager.get_config_dir(STAR_CITIZEN_CONFIG)
        if not config_dir:
            return []
        return [
            (config_dir, wingman_file)
            for wingman_file in self.config_manager.get_wingmen_configs(config_dir)
            if self.config_manager.can_restore_wingman_from_template(
                config_dir=config_dir, wingman_file=wingman_file
            )
        ]

    def _available(self) -> dict[tuple[StarCitizenFeatureKind, str], tuple[str, list]]:
        """Display name and requirements of every feature installed here."""
        available: dict[tuple[StarCitizenFeatureKind, str], tuple[str, list]] = {}
        platform = normalize_platform()
        skills: dict[str, SkillBase] = {
            skill.name: skill for skill in ModuleManager.read_available_skills()
        }
        mcp_config = self.config_manager.mcp_config
        servers = {server.name: server for server in (mcp_config.servers if mcp_config else [])}
        for feature in FEATURES:
            if feature.kind == StarCitizenFeatureKind.SKILL:
                skill = skills.get(feature.name)
                if not skill:
                    continue
                if skill.config.platforms and platform not in skill.config.platforms:
                    continue
                available[(feature.kind, feature.name)] = (
                    skill.config.display_name,
                    list(skill.config.requires or []),
                )
            elif feature.name in servers:
                server = servers[feature.name]
                available[(feature.kind, feature.name)] = (
                    server.display_name or server.name,
                    [],
                )
        return available

    def _features(
        self,
        config_dir: ConfigDirInfo,
        wingman_file: WingmanConfigFileInfo,
        available: dict,
    ) -> list[StarCitizenFeature]:
        config = self.config_manager.load_wingman_config(
            config_dir=config_dir, wingman_file=wingman_file
        )
        skills = set(config.discoverable_skills or [])
        mcps = set(config.discoverable_mcps or [])
        features = []
        for feature in FEATURES:
            found = available.get((feature.kind, feature.name))
            if not found:
                continue
            display_name, requires = found
            enabled = feature.name in (
                skills if feature.kind == StarCitizenFeatureKind.SKILL else mcps
            )
            features.append(
                StarCitizenFeature(
                    kind=feature.kind,
                    name=feature.name,
                    display_name=display_name,
                    enabled=enabled,
                    on_by_default=on_by_default(feature, wingman_file.name),
                    requires=requires,
                )
            )
        return features


def _set_preset(presets: list[str], on: bool) -> None:
    if on and PRESET not in presets:
        presets.append(PRESET)
    elif not on and PRESET in presets:
        presets.remove(PRESET)
