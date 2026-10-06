"""Elite's key bindings become Wingman commands and follow the game."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from api.interface import CommandConfig
from skills.elite_dangerous_controls.bindings import (
    active_presets,
    blocked_keys,
    preset_file,
    read_bindings,
)
from skills.elite_dangerous_controls.catalog import CATALOG, NAMES
from skills.elite_dangerous_controls.main import apply_bindings
from wingmen.facade import SkillCommands

BINDS = """<?xml version="1.0" encoding="UTF-8" ?>
<Root PresetName="{name}" MajorVersion="4" MinorVersion="0">
{body}
</Root>
"""


def key(tag, primary="", secondary="", modifiers=(), toggle=None):
    def slot(name, value):
        if not value:
            return f'<{name} Device="{{NoDevice}}" Key="" />'
        device, _, k = value.partition(":")
        mods = "".join(f'<Modifier Device="Keyboard" Key="{m}" />' for m in modifiers)
        return f'<{name} Device="{device}" Key="{k}">{mods}</{name}>'

    toggle_on = f'<ToggleOn Value="{toggle}" />' if toggle is not None else ""
    return f"<{tag}>{slot('Primary', primary)}{slot('Secondary', secondary)}{toggle_on}</{tag}>"


def write_preset(folder: Path, body: str, name="Custom", filename="Custom.4.0.binds"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "StartPreset.4.start").write_text("\n".join([name] * 4), encoding="utf-8")
    (folder / filename).write_text(BINDS.format(name=name, body=body), encoding="utf-8")


@pytest.fixture
def bindings_dir(tmp_path):
    folder = tmp_path / "Bindings"
    write_preset(folder, "\n".join([
        key("LandingGearToggle", "Keyboard:Key_L"),
        key("ShipSpotLightToggle", "Keyboard:Key_L", modifiers=("Key_LeftShift",)),
        key("NightVisionToggle", "ThrustMasterHOTAS:Joy_3", "Keyboard:Key_N"),
        key("SetSpeed50", "Keyboard:Key_Numpad_8"),
        key("HyperSuperCombination", "Keyboard:Key_UpArrow"),
        key("HeadlightsBuggyButton", "Keyboard:Key_H", toggle=0),
        key("HumanoidToggleFlashlightButton", "Keyboard:Key_End"),
    ]))
    return folder


def test_a_plain_key_is_one_press_by_scan_code(bindings_dir):
    result = read_bindings(bindings_dir, [])
    [action] = result.actions["Toggle Landing Gear"]
    assert action["keyboard"] == {
        "hotkey": "l", "hotkey_codes": [38], "hotkey_extended": False, "hold": 0.1,
    }


def test_a_modifier_is_held_around_the_key(bindings_dir):
    result = read_bindings(bindings_dir, [])
    actions = [a["keyboard"] for a in result.actions["Toggle Ship Lights"]]
    assert actions[0] == {"hotkey": "left shift", "hotkey_codes": [42],
                          "hotkey_extended": False, "press": True}
    assert actions[1]["hotkey_codes"] == [38]
    assert actions[2] == {"hotkey": "left shift", "hotkey_codes": [42],
                          "hotkey_extended": False, "release": True}
    assert result.keys["Toggle Ship Lights"] == "left shift+l"


def test_the_secondary_key_is_used_when_the_primary_is_a_joystick(bindings_dir):
    result = read_bindings(bindings_dir, [])
    assert result.keys["Toggle Night Vision"] == "n"


def test_numpad_and_arrow_keys_keep_their_physical_key(bindings_dir):
    """Numpad 8 and the up arrow share scan code 72; the extended flag tells them apart.
    The label must not start with 'num ', or Core sends the key by name."""
    result = read_bindings(bindings_dir, [])
    numpad = result.actions["Half Throttle"][0]["keyboard"]
    arrow = result.actions["Engage Frame Shift Drive"][0]["keyboard"]
    assert (numpad["hotkey_codes"], numpad["hotkey_extended"]) == ([72], False)
    assert (arrow["hotkey_codes"], arrow["hotkey_extended"]) == ([72], True)
    assert numpad["hotkey"] == "numpad 8"


def test_a_control_set_to_hold_gets_no_command(bindings_dir):
    result = read_bindings(bindings_dir, [])
    assert "SRV Lights" in result.unbound


def test_the_push_to_talk_key_is_never_pressed(bindings_dir):
    result = read_bindings(bindings_dir, [], blocked_keys("end", None))
    assert "Toggle Flashlight" in result.unbound
    assert "Toggle Flashlight" in read_bindings(bindings_dir, []).actions


def test_the_newest_saved_preset_wins(tmp_path):
    folder = tmp_path / "Bindings"
    write_preset(folder, key("LandingGearToggle", "Keyboard:Key_L"), filename="Custom.4.0.binds")
    (folder / "Custom.4.1.binds").write_text(
        BINDS.format(name="Custom", body=key("LandingGearToggle", "Keyboard:Key_G")), encoding="utf-8"
    )
    assert preset_file("Custom", folder, []).name == "Custom.4.1.binds"


def test_a_built_in_preset_comes_from_the_game_folder(tmp_path):
    folder = tmp_path / "Bindings"
    folder.mkdir()
    (folder / "StartPreset.4.start").write_text("KeyboardMouseOnly\n" * 4, encoding="utf-8")
    schemes = tmp_path / "Elite Dangerous" / "Products" / "elite-dangerous-odyssey-64" / "ControlSchemes"
    schemes.mkdir(parents=True)
    (schemes / "KeyboardMouseOnly.binds").write_text(
        BINDS.format(name="KeyboardMouseOnly", body=key("LandingGearToggle", "Keyboard:Key_L")),
        encoding="utf-8",
    )
    result = read_bindings(folder, [schemes])
    assert "Toggle Landing Gear" in result.actions
    with pytest.raises(FileNotFoundError):
        read_bindings(folder, [])


def test_the_older_single_line_selector_covers_every_mode(tmp_path):
    folder = tmp_path / "Bindings"
    folder.mkdir()
    (folder / "StartPreset.start").write_text("Custom", encoding="utf-8")
    assert set(active_presets(folder).values()) == {"Custom"}


def test_a_bindings_file_with_entities_is_refused(tmp_path):
    folder = tmp_path / "Bindings"
    write_preset(folder, "")
    (folder / "Custom.4.0.binds").write_text(
        '<!DOCTYPE x [<!ENTITY a "b">]><Root PresetName="Custom"/>', encoding="utf-8"
    )
    with pytest.raises(ValueError):
        read_bindings(folder, [])


# --- keeping the commands in step ----------------------------------------------


def commands_facade():
    config = SimpleNamespace(commands=[], command_categories=[])
    executor = SimpleNamespace(
        get_command=lambda name: next((c for c in config.commands if c.name == name), None)
    )
    return SkillCommands(SimpleNamespace(config=config, command_executor=executor)), config


def test_bound_controls_become_commands_in_their_category(bindings_dir):
    commands, config = commands_facade()
    assert apply_bindings(commands, read_bindings(bindings_dir, []))
    gear = commands.get("Toggle Landing Gear")
    assert gear.instant_activation == ["toggle landing gear"]
    categories = {c.id: c.name for c in config.command_categories}
    assert categories[gear.category_id] == "Elite Ship"
    # A mode without a single key gets no empty category.
    assert "Elite SRV" not in categories.values()


def test_a_second_sync_changes_nothing(bindings_dir):
    commands, _ = commands_facade()
    bindings = read_bindings(bindings_dir, [])
    apply_bindings(commands, bindings)
    assert not apply_bindings(commands, bindings)


def test_a_changed_key_updates_the_command_and_keeps_the_users_phrases(bindings_dir):
    commands, _ = commands_facade()
    apply_bindings(commands, read_bindings(bindings_dir, []))
    commands.get("Toggle Landing Gear").instant_activation.append("gear down")

    write_preset(bindings_dir, key("LandingGearToggle", "Keyboard:Key_G"))
    assert apply_bindings(commands, read_bindings(bindings_dir, []))
    gear = commands.get("Toggle Landing Gear")
    assert gear.actions[0].keyboard.hotkey == "g"
    assert "gear down" in gear.instant_activation


def test_an_unbound_control_loses_its_command(bindings_dir):
    commands, _ = commands_facade()
    apply_bindings(commands, read_bindings(bindings_dir, []))
    write_preset(bindings_dir, key("LandingGearToggle", "Keyboard:Key_L"))
    apply_bindings(commands, read_bindings(bindings_dir, []))
    assert commands.get("Toggle Ship Lights") is None
    assert commands.get("Toggle Landing Gear") is not None


def test_a_users_own_command_with_the_same_name_is_left_alone(bindings_dir):
    commands, _ = commands_facade()
    mine = CommandConfig(name="Toggle Landing Gear", actions=[])
    commands.add(mine)
    apply_bindings(commands, read_bindings(bindings_dir, []))
    assert commands.get("Toggle Landing Gear") is mine
    assert mine.actions == []


def test_command_names_are_unique():
    rows = [name for entries in CATALOG.values() for _, name in entries]
    assert len(rows) == len(NAMES)
