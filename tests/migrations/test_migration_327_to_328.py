"""3.2.8: the HUD skill is retired. Its settings become HUD profiles, and each
Wingman gets its own switches for the shared chat and info containers."""

import os
from unittest.mock import MagicMock

import yaml

from api.interface import HudProfile, NestedConfig
from services.migrations import migration_327_to_328
from services.migrations.migration_327_to_328 import Migration327To328, build_profiles
from tests.support import template

SCREEN = (1920, 1080)


def migration(hud_server_enabled=False):
    step = Migration327To328(MagicMock())
    step._hud_server_enabled = hud_server_enabled
    return step


def hud_wingman(**values):
    return {
        "discoverable_skills": ["HUD", "Timer"],
        "skills": [{
            "module": "skills.hud.main",
            "custom_properties": [{"id": k, "value": v} for k, v in values.items()],
        }],
        "disabled_skill_tools": ["hud_clear_all", "timer_start"],
    }


def values(**changes):
    return {**migration_327_to_328._SKILL_DEFAULTS, **changes}


def test_an_anchored_container_gets_the_area_it_had_on_screen():
    [profile] = build_profiles(
        {"Star Citizen": [values(persistent_anchor="right_center", persistent_width=700)]},
        SCREEN, margin=20, spacing=15,
    )

    assert profile["info"] == {"x1": 1200, "y1": 240, "x2": 1900, "y2": 840, "align": "top"}
    HudProfile(**profile)


def test_chat_and_info_at_the_same_anchor_stay_stacked():
    [profile] = build_profiles({"SC": [values()]}, SCREEN, margin=20, spacing=15)

    assert profile["chat"] == {"x1": 20, "y1": 20, "x2": 420, "y2": 620, "align": "top"}
    assert (profile["info"]["y1"], profile["info"]["y2"]) == (635, 1080)


def test_a_bottom_anchor_grows_up_from_the_bottom():
    [profile] = build_profiles(
        {"SC": [values(chat_anchor="bottom_left", hud_max_height=300)]}, SCREEN, margin=20, spacing=15
    )

    assert profile["chat"] == {"x1": 20, "y1": 760, "x2": 420, "y2": 1060, "align": "bottom"}


def test_the_set_most_configs_use_is_the_default_the_rest_get_their_own():
    red = values(accent_color="#d84f4f")
    profiles = build_profiles(
        {"Star Citizen": [red, red, values()], "Elite": [red], "MSFS": [values()]},
        SCREEN, margin=20, spacing=15,
    )

    default, other = profiles
    assert (default["is_default"], default["configs"], default["style"]["accent_color"]) == (True, [], "#d84f4f")
    assert (other["is_default"], other["configs"], other["name"]) == (False, ["MSFS"], "MSFS")


def test_a_hud_wingman_keeps_its_chat_switch_and_loses_the_skill():
    out = migration().migrate_wingman(hud_wingman(show_chat_messages=False))

    assert out["hud"] == {"chat": False, "info": True}
    assert out["skills"] == []
    assert out["discoverable_skills"] == ["Timer"]
    assert out["disabled_skill_tools"] == ["timer_start"]


def test_with_the_hud_on_a_wingman_without_the_skill_shows_nothing_new():
    assert migration(hud_server_enabled=True).migrate_wingman({"name": "ATC"})["hud"] == {
        "chat": False, "info": False,
    }
    assert "hud" not in migration().migrate_wingman({"name": "ATC"})


def test_profiles_come_from_the_old_wingman_files(tmp_path, monkeypatch):
    configs = tmp_path / "3_2_7" / "configs"
    (configs / "Star Citizen").mkdir(parents=True)
    (configs / "Star Citizen" / "Orionis.yaml").write_text(
        yaml.safe_dump(hud_wingman(accent_color="#d84f4f", chat_anchor="left_center")), encoding="utf-8"
    )
    (configs / "Star Citizen" / "ATC.yaml").write_text(yaml.safe_dump({"name": "ATC"}), encoding="utf-8")
    monkeypatch.setattr(migration_327_to_328, "get_users_dir", lambda: str(tmp_path))
    monkeypatch.setattr(migration_327_to_328, "get_custom_skills_dir", lambda: str(tmp_path / "custom"))
    step = migration()
    step.config_manager.read_config = lambda file: yaml.safe_load(open(file, encoding="utf-8"))
    monkeypatch.setattr(step, "_screen_size", lambda screen: SCREEN)

    out = step.migrate_settings({"hud_server": {"enabled": True, "screen": 1}})

    [profile] = out["hud_profiles"]
    assert profile["style"]["accent_color"] == "#d84f4f"
    assert profile["chat"]["x1"] == 20
    assert step._hud_server_enabled


def test_without_hud_users_the_templates_profile_comes_in(tmp_path, monkeypatch):
    os.makedirs(tmp_path / "3_2_7" / "configs")
    monkeypatch.setattr(migration_327_to_328, "get_users_dir", lambda: str(tmp_path))
    monkeypatch.setattr(migration_327_to_328, "get_custom_skills_dir", lambda: str(tmp_path / "custom"))

    assert "hud_profiles" not in migration().migrate_settings({})


def test_the_templates_carry_a_default_profile_and_the_wingman_switches():
    [profile] = template("settings.yaml")["hud_profiles"]
    assert HudProfile(**profile).is_default
    NestedConfig(**template("defaults.yaml"))


def test_a_deleted_wingman_file_has_no_say_in_the_profiles(tmp_path, monkeypatch):
    configs = tmp_path / "3_2_7" / "configs" / "Star Citizen"
    configs.mkdir(parents=True)
    (configs / "Orionis.yaml").write_text(yaml.safe_dump(hud_wingman(accent_color="#d84f4f")), encoding="utf-8")
    (configs / ".Old.yaml").write_text(yaml.safe_dump(hud_wingman(accent_color="#00ff00")), encoding="utf-8")
    monkeypatch.setattr(migration_327_to_328, "get_users_dir", lambda: str(tmp_path))
    step = migration()
    step.config_manager.read_config = lambda file: yaml.safe_load(open(file, encoding="utf-8"))

    assert step._old_hud_users() == {"Star Citizen": [values(accent_color="#d84f4f")]}


def test_a_command_bound_to_hide_hud_is_reported():
    step = migration()
    wingman = {"commands": [{"name": "Hide HUD", "actions": [
        {"skill_action": {"skill_name": "HUD", "function_name": "hud_hide"}},
    ]}]}

    step.migrate_wingman(wingman)

    [message] = [c.args[0] for c in step.service.log_warning.call_args_list]
    assert "'Hide HUD'" in message and "hud_hide" in message
