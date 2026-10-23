"""A Wingman switched off in the client kept answering.

The client saves the config with `disabled: true`. The save only wrote the flag
into the running Wingman's config, but the Tower routes by its list of Wingmen
and never looks at the flag, so the Wingman stayed in the list and kept
listening and speaking until the next restart.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from api.enums import WingmanInitializationErrorType
from api.interface import WingmanConfig, WingmanInitializationError
from services.config_manager import deep_merge_configs
from services.config_service import ConfigService
from services.tower import Tower
from tests.support import template
from wingmen.wingman import Wingman

WINGMAN = {"name": "Computer", "description": "test", "record_key": "end"}


def config(**fields) -> WingmanConfig:
    return WingmanConfig(**deep_merge_configs(template("defaults.yaml"), {**WINGMAN, **fields}))


def running_wingman(wingman_config: WingmanConfig):
    return SimpleNamespace(
        name="Computer",
        config=wingman_config,
        unload=AsyncMock(),
        unload_mcps=AsyncMock(),
        update_config=AsyncMock(return_value=True),
    )


def service_with(tower: Tower, on_disk: WingmanConfig) -> ConfigService:
    service = ConfigService.__new__(ConfigService)
    service.config_manager = MagicMock()
    service.config_manager.load_wingman_config.return_value = on_disk
    service.tower = tower
    service.current_config_dir = CONFIG_DIR
    service.printr = MagicMock()
    service.config_events = MagicMock(publish=AsyncMock())
    return service


def tower_with(*wingmen) -> Tower:
    tower = Tower.__new__(Tower)
    tower.wingmen = list(wingmen)
    tower.disabled_wingmen = []
    tower.log_source_name = "Tower"
    tower.audio_player = SimpleNamespace(is_playing=False, wingman_name="", stop_playback=AsyncMock())
    tower.local_ai_service = SUPPORT_MODEL
    tower.pocket_tts = None
    tower.settings_service = None
    tower.audio_library = tower.xvasynth = None
    return tower


SUPPORT_MODEL = object()
CONFIG_DIR = SimpleNamespace(name="c", directory="c")


class BuiltWingman:
    """Stands in for OpenAiWingman when the Tower builds one on Enable."""

    errors: list[WingmanInitializationError] = []

    def __init__(self, name, config, **_):
        self.name = name
        self.config = config
        self.local_ai_service = None
        self.unload = AsyncMock()
        self.unload_mcps = AsyncMock()
        self.update_config = AsyncMock(return_value=True)

    async def validate(self):
        return list(self.errors)

    async def init_skills(self):
        return []

    async def init_mcps(self):
        return []


def save(service: ConfigService, wingman_config: WingmanConfig, file_name: str = "Computer"):
    with patch("services.tower.OpenAiWingman", BuiltWingman):
        asyncio.run(
            service.save_wingman_config(
                CONFIG_DIR,
                SimpleNamespace(name=file_name, file=f"{file_name}.yaml"),
                wingman_config,
            )
        )


def test_switching_off_takes_the_wingman_out_of_the_tower():
    wingman = running_wingman(config())
    tower = tower_with(wingman)
    service = service_with(tower, config())

    save(service, config(disabled=True))

    assert tower.get_wingman_by_name("Computer") is None
    assert tower.get_wingman_from_text("Computer, open the map") is None
    assert tower.get_disabled_wingman_by_name("Computer").disabled
    wingman.unload.assert_awaited_once()
    wingman.unload_mcps.assert_awaited_once()
    assert service.config_manager.save_wingman_config.call_args.kwargs["wingman_config"].disabled


def test_editing_a_switched_off_wingman_is_saved():
    tower = tower_with()
    tower.disabled_wingmen.append(config(disabled=True))
    service = service_with(tower, config(disabled=True))

    save(service, config(disabled=True, description="changed"))

    service.printr.toast_error.assert_not_called()
    saved = service.config_manager.save_wingman_config.call_args.kwargs["wingman_config"]
    assert saved.description == "changed"
    assert tower.wingmen == []
    # Enable builds the Wingman from this copy, so it must have the edit.
    assert tower.get_disabled_wingman_by_name("Computer").description == "changed"


def test_a_wingman_renamed_while_off_can_be_switched_on():
    tower = tower_with()
    tower.disabled_wingmen.append(config(disabled=True))
    service = service_with(tower, config(disabled=True))

    save(service, config(disabled=True, name="Jarvis"))
    assert tower.get_disabled_wingman_by_name("Computer") is None

    service.config_manager.load_wingman_config.return_value = config(disabled=True, name="Jarvis")
    save(service, config(disabled=False, name="Jarvis"), file_name="Jarvis")

    service.printr.toast_error.assert_not_called()
    assert tower.get_wingman_by_name("Jarvis") is not None
    assert tower.disabled_wingmen == []


def test_switching_off_and_on_again_gives_a_complete_wingman():
    wingman = running_wingman(config())
    tower = tower_with(wingman)
    service = service_with(tower, config())

    save(service, config(disabled=True))
    service.config_manager.load_wingman_config.return_value = config(disabled=True)
    save(service, config(disabled=True, description="changed"))
    save(service, config(disabled=False, description="changed"))

    service.printr.toast_error.assert_not_called()
    enabled = tower.get_wingman_by_name("Computer")
    assert enabled is not wingman
    assert enabled.config.description == "changed"
    # Memory and skills need the support model, like after a start.
    assert enabled.local_ai_service is SUPPORT_MODEL
    assert tower.disabled_wingmen == []
    assert service.config_manager.save_wingman_config.call_count == 3


def test_a_wingman_that_cannot_be_built_stays_off_and_says_why(monkeypatch):
    tower = tower_with()
    tower.disabled_wingmen.append(config(disabled=True))
    service = service_with(tower, config(disabled=True))
    monkeypatch.setattr(
        BuiltWingman,
        "errors",
        [
            WingmanInitializationError(
                wingman_name="Computer",
                message="broken provider",
                error_type=WingmanInitializationErrorType.INVALID_CONFIG,
            )
        ],
    )
    tower_printr = MagicMock()
    monkeypatch.setattr("services.tower.printr", tower_printr)

    save(service, config(disabled=False))

    tower_printr.toast_error.assert_called_once_with("broken provider")
    service.printr.toast_error.assert_called_once()
    service.config_manager.save_wingman_config.assert_not_called()
    assert tower.wingmen == []
    # Still switched off, so the next Enable tries again.
    assert tower.get_disabled_wingman_by_name("Computer").disabled

    monkeypatch.setattr(BuiltWingman, "errors", [])
    save(service, config(disabled=False))
    assert tower.get_wingman_by_name("Computer") is not None
    assert tower.disabled_wingmen == []


def test_switching_off_stops_its_answer_playing():
    wingman = running_wingman(config())
    tower = tower_with(wingman)
    tower.audio_player.is_playing = True
    tower.audio_player.wingman_name = "Computer"
    service = service_with(tower, config())

    save(service, config(disabled=True))

    tower.audio_player.stop_playback.assert_awaited_once()


def test_a_switched_off_wingman_neither_speaks_nor_remembers_a_late_answer():
    wingman = Wingman.__new__(Wingman)
    wingman._unloaded = True
    wingman.persistent_memory_service = MagicMock()
    wingman.audio_player = MagicMock()

    asyncio.run(wingman.play_to_user("the answer that came too late"))
    wingman._memory_after_turn("the answer that came too late")

    assert wingman.audio_player.mock_calls == []
    assert wingman.persistent_memory_service.mock_calls == []
