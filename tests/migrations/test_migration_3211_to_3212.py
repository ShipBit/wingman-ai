"""3.2.12 turns every key, mouse and joystick binding into a list of bindings
with an extended flag per key. Command actions stay as they were."""

from copy import deepcopy
from unittest.mock import MagicMock

from api.interface import InputBinding, SettingsConfig
from services.migrations.migration_3211_to_3212 import Migration3211To3212
from tests.support import template


def _migration(is_windows: bool = True) -> Migration3211To3212:
    migration = Migration3211To3212(MagicMock())
    migration.is_windows = is_windows
    return migration


def test_push_to_talk_key_mouse_and_joystick_become_three_bindings():
    old = {
        "name": "Computer",
        "record_key": "right ctrl+f1",
        "record_key_codes": [29, 59],
        "record_mouse_button": "x2",
        "record_joystick_button": {"guid": "abc", "button": 4, "name": "Stick"},
    }
    out = _migration().migrate_wingman(old)
    for field in ("record_key", "record_key_codes", "record_mouse_button", "record_joystick_button"):
        assert field not in out
    keyboard, mouse, joystick = [InputBinding(**b) for b in out["record_bindings"]]
    assert [(k.scan_code, k.extended, k.name) for k in keyboard.keys] == [
        (29, True, "right ctrl"),
        (59, False, "f1"),
    ]
    assert mouse.mouse_button == "x2" and mouse.keys == []
    assert joystick.joystick.guid == "abc" and joystick.joystick.button == 4


def test_the_flag_is_windows_only():
    old = {"record_key": "right ctrl", "record_key_codes": [62]}
    out = _migration(is_windows=False).migrate_wingman(old)
    assert out["record_bindings"][0]["keys"][0]["extended"] is False


def test_a_key_without_codes_is_kept_by_name():
    out = _migration().migrate_wingman({"record_key": "end"})
    assert out["record_bindings"][0]["keys"] == [
        {"scan_code": None, "extended": False, "name": "end"}
    ]


def test_an_unbound_wingman_gets_no_bindings():
    old = {"record_key": "", "record_key_codes": None, "record_mouse_button": "", "record_joystick_button": None}
    assert _migration().migrate_wingman(old)["record_bindings"] == []


def test_commands_are_not_touched():
    commands = [
        {
            "name": "Search",
            "actions": [
                {"keyboard": {"hotkey": "left windows+s", "hotkey_codes": [91, 31], "hotkey_extended": True}}
            ],
        }
    ]
    old = {"record_key": "end", "commands": deepcopy(commands)}
    assert _migration().migrate_wingman(old)["commands"] == commands


def test_settings_shut_up_and_mute():
    settings = template("settings.yaml")
    settings.pop("cancel_tts_bindings")
    settings.pop("global_ptt_bindings")
    settings["voice_activation"].pop("mute_toggle_bindings")
    settings["cancel_tts_key"] = "shift+y"
    settings["cancel_tts_key_codes"] = [42, 21]
    settings["cancel_tts_joystick_button"] = {"guid": "abc", "button": 2, "name": "Stick"}
    settings["voice_activation"]["mute_toggle_key"] = "shift+x"
    settings["voice_activation"]["mute_toggle_key_codes"] = None

    out = _migration().migrate_settings(settings)

    assert "cancel_tts_key" not in out and "mute_toggle_key" not in out["voice_activation"]
    parsed = SettingsConfig(**out)
    keyboard, joystick = parsed.cancel_tts_bindings
    assert [(k.scan_code, k.name) for k in keyboard.keys] == [(42, "shift"), (21, "y")]
    assert joystick.joystick.button == 2
    assert [k.name for k in parsed.voice_activation.mute_toggle_bindings[0].keys] == ["shift", "x"]
    (period,) = parsed.global_ptt_bindings
    assert [(k.name, k.scan_code) for k in period.keys] == [(".", None)]


def test_settings_without_any_key():
    settings = template("settings.yaml")
    settings.pop("cancel_tts_bindings")
    settings.pop("global_ptt_bindings")
    settings["voice_activation"].pop("mute_toggle_bindings")
    settings["cancel_tts_key"] = ""
    settings["cancel_tts_joystick_button"] = None
    settings["voice_activation"]["mute_toggle_key"] = ""
    out = _migration().migrate_settings(settings)
    parsed = SettingsConfig(**out)
    assert parsed.cancel_tts_bindings == []
    assert parsed.voice_activation.mute_toggle_bindings == []


def test_everyone_gets_the_period_key():
    for before in ({}, {"global_ptt_bindings": []}, {"global_ptt_bindings": None}):
        out = _migration().migrate_settings(dict(before))
        assert out["global_ptt_bindings"] == [
            {"device": "keyboard", "keys": [{"name": ".", "scan_code": None, "extended": False}]}
        ]


def test_a_chosen_global_key_stays():
    chosen = [{"device": "mouse", "keys": [], "mouse_button": "x2"}]
    out = _migration().migrate_settings({"global_ptt_bindings": list(chosen)})
    assert out["global_ptt_bindings"] == chosen


def test_elevenlabs_defaults_move_to_v4_turbo_unless_the_user_changed_them():
    old = {
        "elevenlabs": {
            "model": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.71,
                "similarity_boost": 0.5,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }
    }
    out = _migration().migrate_defaults(old)
    assert out["elevenlabs"]["model"] == "eleven_v4_turbo"
    assert out["elevenlabs"]["voice_settings"] == {
        "stability": 0.5,
        "similarity_boost": 0.75,
        "style": 0.0,
        "use_speaker_boost": True,
        "speed": 1.0,
    }

    old = {
        "elevenlabs": {
            "model": "eleven_v3",
            "voice_settings": {"stability": 0.3, "similarity_boost": 0.9, "speed": 1.1},
        }
    }
    out = _migration().migrate_defaults(old)
    assert out["elevenlabs"]["model"] == "eleven_v3"
    assert out["elevenlabs"]["voice_settings"] == {
        "stability": 0.3,
        "similarity_boost": 0.9,
        "speed": 1.1,
    }


def test_the_new_defaults_are_the_template():
    elevenlabs = template("defaults.yaml")["elevenlabs"]
    out = _migration().migrate_defaults(
        {"elevenlabs": {"model": "eleven_multilingual_v2", "voice_settings": {"stability": 0.71, "similarity_boost": 0.5}}}
    )
    assert out["elevenlabs"]["model"] == elevenlabs["model"]
    for field, value in out["elevenlabs"]["voice_settings"].items():
        assert elevenlabs["voice_settings"][field] == value
