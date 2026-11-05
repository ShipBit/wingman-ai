"""One input, one job: a binding the user records is taken from everything
else that used it. Two owners of one key meant only one of them ever fired:
a Wingman's own push-to-talk on the same key as the global one won silently,
and the global key looked broken."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from api.enums import RecordingDevice
from api.interface import (
    CommandJoystickConfig,
    InputBinding,
    KeyStroke,
    SettingsConfig,
    WingmanConfig,
)
from services.config_manager import deep_merge_configs
from services.config_service import ConfigService
from services.input_bindings import added_bindings, same_input
from services.settings_service import SettingsService
from tests.support import template

CONFIG_DIR = SimpleNamespace(name="c", directory="c")


def key(name: str, scan_code: int | None = None) -> InputBinding:
    return InputBinding(
        device=RecordingDevice.KEYBOARD,
        keys=[KeyStroke(name=name, scan_code=scan_code, extended=False)],
    )


def stick(button: int) -> InputBinding:
    return InputBinding(
        device=RecordingDevice.JOYSTICK,
        keys=[],
        joystick=CommandJoystickConfig(guid="g", name="Stick", button=button),
    )


def wingman(name: str, *bindings: InputBinding) -> WingmanConfig:
    fields = {"name": name, "description": "test", "record_bindings": list(bindings)}
    return WingmanConfig(**deep_merge_configs(template("defaults.yaml"), fields))


def settings(**lists) -> SettingsConfig:
    data = template("settings.yaml")
    data["global_ptt_bindings"] = [b.model_dump() for b in lists.get("global_ptt", [])]
    data["cancel_tts_bindings"] = [b.model_dump() for b in lists.get("shut_up", [])]
    data["voice_activation"]["mute_toggle_bindings"] = [
        b.model_dump() for b in lists.get("mute", [])
    ]
    return SettingsConfig(**data)


# ── the same input ──────────────────────────────────────────────────


def test_a_key_known_by_name_is_the_recorded_key_of_that_name():
    assert same_input(key("end"), key("End", scan_code=79))


def test_two_scan_codes_are_two_keys():
    assert not same_input(key("end", 79), key("end", 80))


def test_only_the_new_binding_counts_as_recorded():
    assert added_bindings([key("end"), stick(3)], [key("end")]) == [stick(3)]


# ── a Wingman records a key ─────────────────────────────────────────


class Disk:
    """The Wingman files of one config, in memory."""

    def __init__(self, *configs: WingmanConfig):
        self.configs = {c.name: c for c in configs}

    def files(self, _config_dir):
        return [SimpleNamespace(name=n, file=f"{n}.yaml") for n in self.configs]

    def load(self, config_dir, wingman_file):
        return self.configs[wingman_file.name].model_copy(deep=True)


def config_service(disk: Disk, app_settings: SettingsConfig) -> ConfigService:
    service = ConfigService.__new__(ConfigService)
    service.config_manager = MagicMock()
    service.config_manager.settings_config = app_settings
    service.config_manager.get_wingmen_configs.side_effect = disk.files
    service.config_manager.load_wingman_config.side_effect = disk.load

    def save(config_dir, wingman_file, wingman_config):
        disk.configs[wingman_config.name] = wingman_config

    service.config_manager.save_wingman_config.side_effect = save
    service.tower = None
    service.current_config_dir = CONFIG_DIR
    service.printr = MagicMock()
    service.config_events = MagicMock(publish=AsyncMock())
    service.load_config = AsyncMock()
    return service


def save_wingman(service: ConfigService, wingman_config: WingmanConfig):
    with patch("services.binding_owners.printr") as printr:
        asyncio.run(
            service.save_wingman_config(
                CONFIG_DIR,
                SimpleNamespace(name=wingman_config.name, file=f"{wingman_config.name}.yaml"),
                wingman_config,
            )
        )
    return [call.kwargs["additional_data"] for call in printr.print.call_args_list]


def test_a_wingman_takes_the_key_from_the_global_one_and_from_other_wingmen():
    disk = Disk(wingman("Bob"), wingman("Alice", key("end")))
    app_settings = settings(global_ptt=[key("end")], shut_up=[key("pause")])
    service = config_service(disk, app_settings)

    moved = save_wingman(service, wingman("Bob", key("end")))

    assert disk.configs["Bob"].record_bindings == [key("end")]
    assert disk.configs["Alice"].record_bindings == []
    assert app_settings.global_ptt_bindings == []
    assert app_settings.cancel_tts_bindings == [key("pause")]
    service.config_manager.save_settings_config.assert_called_once()
    assert {m["taken_from"]["kind"] for m in moved} == {"global_ptt", "wingman"}
    assert all(m["owner"] == {"kind": "wingman", "wingman": "Bob", "config": None} for m in moved)
    assert all(m["binding"] == "end" for m in moved)


def test_saving_a_wingman_without_a_new_key_takes_nothing():
    disk = Disk(wingman("Bob", key("end")), wingman("Alice", key("end")))
    service = config_service(disk, settings())

    moved = save_wingman(service, wingman("Bob", key("end")))

    assert moved == []
    assert disk.configs["Alice"].record_bindings == [key("end")]


# ── a settings key is recorded ──────────────────────────────────────


def settings_service(app_settings: SettingsConfig, take_from_wingmen) -> SettingsService:
    service = SettingsService.__new__(SettingsService)
    service.config_manager = MagicMock(settings_config=app_settings)
    service.config_service = MagicMock(take_bindings_from_wingmen=take_from_wingmen)
    return service


def test_the_global_key_takes_the_key_from_a_wingman_and_from_shut_up():
    old = settings(shut_up=[key("end")])
    new = settings(global_ptt=[key("end")], shut_up=[key("end")])
    wingman_lost = [({"kind": "wingman", "wingman": "Alice", "config": None}, key("end"))]
    take = AsyncMock(return_value=wingman_lost)
    service = settings_service(old, take)

    with patch("services.binding_owners.printr") as printr:
        asyncio.run(service._give_recorded_bindings_one_owner(new, old))

    assert new.global_ptt_bindings == [key("end")]
    assert new.cancel_tts_bindings == []
    assert take.await_args.args[0] == [key("end")]
    moved = [call.kwargs["additional_data"] for call in printr.print.call_args_list]
    assert [m["taken_from"]["kind"] for m in moved] == ["shut_up", "wingman"]
    assert all(m["owner"] == {"kind": "global_ptt"} for m in moved)


def test_an_unchanged_settings_save_takes_nothing():
    current = settings(global_ptt=[key("end")])
    take = AsyncMock(return_value=[])
    service = settings_service(current, take)

    asyncio.run(service._give_recorded_bindings_one_owner(settings(global_ptt=[key("end")]), current))

    take.assert_not_awaited()
