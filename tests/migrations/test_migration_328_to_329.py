"""3.2.9: the system prompt learns when to run a command and how long to talk,
inside the user's own prompt. The HUD skill is retired: the first HUD
Wingman's skill settings become the default HUD profile, placed where the
skill drew the HUD, and every Wingman gets the shared chat and info panel."""

import os
from os import path
from unittest.mock import MagicMock

import pytest

import hud_server.platform as hud_platform
from api.interface import HudProfile, NestedConfig, SettingsConfig
from hud_server.layout import Align, LayoutManager, LayoutMode
from hud_server.platform import Monitor
from services.migrations.migration_328_to_329 import (
    OLD_MARGIN,
    SKILL_DEFAULTS,
    Migration328To329,
    build_profile,
    container_areas,
)
from tests.support import TEMPLATES, FakeHudBackend, read_yaml, template, write_yaml

OLD_PROMPT = (
    "# OUTPUT FORMAT\n"
    "- Keep responses concise (1-3 sentences unless more detail is needed)\n\n"
    "# YOUR CAPABILITIES\nUse tools.\n"
)
SCREEN = (2560, 1440)


def migration():
    service = MagicMock()
    service.config_manager.read_config = read_yaml
    service.templates_dir = path.dirname(TEMPLATES)
    return Migration328To329(service)


# ─────────────────────────────── system prompt ─────────────────────────────── #


def test_the_shipped_prompt_has_the_rules_after_migrating():
    shipped = template("defaults.yaml")["prompts"]["system_prompt"]
    out = migration().migrate_defaults({"prompts": {"system_prompt": OLD_PROMPT}})
    prompt = out["prompts"]["system_prompt"]
    assert "# ACTIONS" in prompt and "# ACTIONS" in shipped
    assert "1-3 sentences, the answer first" in prompt
    assert prompt.index("# ACTIONS") < prompt.index("# YOUR CAPABILITIES")


def test_an_edited_prompt_keeps_its_edits():
    mine = OLD_PROMPT + "Always speak like a pirate.\n"
    out = migration().migrate_wingman({"name": "KAT", "prompts": {"system_prompt": mine}})
    assert "Always speak like a pirate." in out["prompts"]["system_prompt"]
    assert "# ACTIONS" in out["prompts"]["system_prompt"]


def test_running_twice_adds_nothing():
    once = migration().migrate_defaults({"prompts": {"system_prompt": OLD_PROMPT}})
    twice = migration().migrate_defaults(once)
    assert twice["prompts"]["system_prompt"].count("# ACTIONS") == 1


def test_a_wingman_without_its_own_prompt_is_left_alone():
    assert "prompts" not in migration().migrate_wingman({"name": "KAT"})


def test_the_328_prompt_becomes_exactly_the_shipped_one():
    from services.migrations.migration_328_to_329 import (
        ACTIONS_BLOCK,
        NEW_LENGTH_RULE,
        OLD_LENGTH_RULE,
    )

    shipped = template("defaults.yaml")["prompts"]["system_prompt"]
    before = shipped.replace(ACTIONS_BLOCK, "").replace(NEW_LENGTH_RULE, OLD_LENGTH_RULE)
    assert before != shipped
    out = migration().migrate_defaults({"prompts": {"system_prompt": before}})
    assert out["prompts"]["system_prompt"] == shipped


# ─────────────────────────────── HUD ─────────────────────────────── #


def hud_wingman(disabled=False, **values):
    return {
        "disabled": disabled,
        "discoverable_skills": ["HUD", "Timer"],
        "skills": [{
            "module": "skills.hud.main",
            "custom_properties": [{"id": k, "value": v} for k, v in values.items()],
        }],
        "disabled_skill_tools": ["hud_clear_all", "timer_start"],
    }


def values(**changes):
    return {**SKILL_DEFAULTS, **changes}


def shown_at(area, window_height, screen=SCREEN):
    """Where the new HUD puts a window of this height in the area."""
    layout = LayoutManager(screen_width=screen[0], screen_height=screen[1])
    layout.register_window(
        "w", mode=LayoutMode.MANUAL, manual_x=area["x1"], manual_y=area["y1"],
        width=area["x2"] - area["x1"], height=window_height,
        align=Align(area["align"]), area_height=area["y2"] - area["y1"],
    )
    return layout.get_position("w")


@pytest.mark.parametrize(
    "anchor, align",
    [
        ("top_left", "top"), ("top_center", "top"), ("top_right", "top"),
        ("left_center", "center"), ("right_center", "center"), ("center", "center"),
        ("bottom_left", "bottom"), ("bottom_center", "bottom"), ("bottom_right", "bottom"),
    ],
)
def test_each_anchor_turns_into_its_alignment(anchor, align):
    chat, _info = container_areas(values(chat_anchor=anchor, persistent_layout_mode="manual"), SCREEN)

    assert chat["align"] == align


def test_the_screens_center_counts_as_its_left_center():
    centered, _ = container_areas(values(chat_anchor="center", persistent_layout_mode="manual"), SCREEN)
    left, _ = container_areas(values(chat_anchor="left_center", persistent_layout_mode="manual"), SCREEN)

    assert centered == left
    assert centered["x1"] == OLD_MARGIN


@pytest.mark.parametrize(
    "anchor, old_position",
    [
        # The old HUD: margin 20 from the edges, 400 wide, here 150 high
        ("top_left", (20, 20)),
        ("top_center", (1080, 20)),
        ("top_right", (2140, 20)),
        ("left_center", (20, 645)),
        ("right_center", (2140, 645)),
        ("bottom_left", (20, 1270)),
        ("bottom_center", (1080, 1270)),
        ("bottom_right", (2140, 1270)),
    ],
)
def test_a_chat_message_shows_where_the_hud_skill_put_it(anchor, old_position):
    chat, _ = container_areas(values(chat_anchor=anchor, persistent_layout_mode="manual"), SCREEN)

    assert shown_at(chat, 150) == old_position


def test_a_container_keeps_its_place_as_its_content_grows():
    chat, _ = container_areas(values(chat_anchor="bottom_right", hud_max_height=500, persistent_layout_mode="manual"), SCREEN)

    # The old HUD kept the bottom edge at the margin and grew up
    assert shown_at(chat, 100)[1] + 100 == SCREEN[1] - OLD_MARGIN
    assert shown_at(chat, 400)[1] + 400 == SCREEN[1] - OLD_MARGIN


def test_a_freely_placed_container_keeps_its_corner():
    _, info = container_areas(
        values(persistent_layout_mode="manual", persistent_x=900, persistent_y=300, persistent_width=600),
        SCREEN,
    )

    assert info == {"x1": 900, "y1": 300, "x2": 1500, "y2": 900, "align": "top"}


def test_chat_and_info_at_one_anchor_stay_stacked_without_overlapping():
    chat, info = container_areas(values(), (1920, 1080))

    assert chat == {"x1": 20, "y1": 20, "x2": 420, "y2": 620, "align": "top"}
    # Right below the chat's full height, cut off at the screen's edge
    assert info == {"x1": 20, "y1": 630, "x2": 420, "y2": 1080, "align": "top"}


def test_at_a_bottom_anchor_the_stack_grows_up():
    chat, info = container_areas(
        values(chat_anchor="bottom_right", persistent_anchor="bottom_right", hud_max_height=300, persistent_max_height=200),
        SCREEN,
    )

    assert (chat["y1"], chat["y2"]) == (1120, 1420)
    assert (info["y1"], info["y2"]) == (910, 1110)
    assert chat["align"] == info["align"] == "bottom"


def test_the_higher_priority_sits_closer_to_the_anchor():
    chat, info = container_areas(values(persistent_priority=40), (1920, 1080))

    assert info["y1"] == OLD_MARGIN
    assert chat["y1"] == info["y2"] + 10


def test_in_a_stack_at_the_left_center_the_chat_stays_where_it_was_on_its_own():
    stacked = values(chat_anchor="left_center", persistent_anchor="left_center", hud_max_height=300)
    alone = values(chat_anchor="left_center", hud_max_height=300, persistent_layout_mode="manual")

    chat, info = container_areas(stacked, SCREEN)

    assert chat == container_areas(alone, SCREEN)[0]
    assert info["y1"] == chat["y2"] + 10
    assert chat["align"] == info["align"] == "center"


def test_a_config_saved_before_bg_opacity_keeps_its_transparent_background():
    profile = build_profile(hud_wingman(bg_color="#1e212bb3"), SCREEN)

    assert (profile["style"]["bg_color"], profile["style"]["bg_opacity"]) == ("#1e212b", 70)
    HudProfile(**profile)


def test_the_profile_carries_the_skills_look_and_timing():
    profile = build_profile(
        hud_wingman(accent_color="#d84f4f", font_size=18, opacity=70, max_display_time=8, display_tool_names=True),
        SCREEN,
    )

    assert profile["style"]["accent_color"] == "#d84f4f"
    assert (profile["style"]["font_size"], profile["style"]["opacity"]) == (18, 70)
    assert (profile["max_display_time"], profile["display_tool_names"]) == (8.0, True)
    assert profile["is_default"] and profile["configs"] == []
    HudProfile(**profile)


# ── the migration step ─────────────────────────────────────────────────


def old_config(users_dir, config, wingmen, start_config="Star Citizen"):
    configs = os.path.join(users_dir, "3_2_8", "configs")
    os.makedirs(os.path.join(configs, config), exist_ok=True)
    write_yaml(os.path.join(configs, "context.yaml"), {"default_config": start_config})
    for name, wingman in wingmen.items():
        write_yaml(os.path.join(configs, config, f"{name}.yaml"), wingman)


@pytest.fixture
def screen(monkeypatch):
    """The HUD screen as the overlay measures it: a 4K monitor at 125 %."""
    backend = FakeHudBackend([Monitor(0, 0, 3072, 1728, primary=True, scale=1.25)])
    monkeypatch.setattr(hud_platform, "get_backend", lambda: backend)
    return backend


def test_the_areas_are_measured_in_the_hud_screens_scaled_pixels(users_dir, screen):
    old_config(users_dir, "Star Citizen", {"Computer": hud_wingman(chat_anchor="bottom_right")})

    settings = migration().migrate_settings({"hud_server": {"enabled": True, "screen": 1}})

    chat = settings["hud_profiles"][0]["chat"]
    assert (chat["x2"], chat["y2"]) == (3072 - OLD_MARGIN, 1728 - OLD_MARGIN)


def test_only_the_first_hud_wingman_becomes_the_profile(users_dir, screen):
    old_config(users_dir, "Elite", {"Ship": hud_wingman(accent_color="#111111")}, start_config="Star Citizen")
    old_config(users_dir, "Star Citizen", {
        "Zed": hud_wingman(accent_color="#333333"),
        "Board": hud_wingman(accent_color="#222222"),
        "Asleep": hud_wingman(disabled=True, accent_color="#444444"),
    })

    settings = migration().migrate_settings({"hud_server": {"screen": 1}})

    # The config Core started with, switched-on Wingmen, then by name
    [profile] = settings["hud_profiles"]
    assert profile["style"]["accent_color"] == "#222222"


def test_without_hud_wingmen_the_template_profile_comes_in(users_dir, screen):
    old_config(users_dir, "Star Citizen", {"Computer": {"discoverable_skills": ["Timer"]}})

    settings = migration().migrate_settings({"hud_server": {"screen": 1}})

    assert "hud_profiles" not in settings


def test_profiles_a_user_already_has_stay(users_dir, screen):
    old_config(users_dir, "Star Citizen", {"Computer": hud_wingman(accent_color="#123456")})
    existing = [{**template("settings.yaml")["hud_profiles"][0], "name": "Mine"}]
    del existing[0]["user_name"], existing[0]["chat_flow"]

    settings = migration().migrate_settings({"hud_profiles": existing})

    # Kept as they were, only completed with what newer profiles have
    [profile] = settings["hud_profiles"]
    assert profile["name"] == "Mine" and profile["style"]["accent_color"] != "#123456"
    assert (profile["user_name"], profile["chat_flow"]) == ("", False)
    HudProfile(**profile)


def test_the_migrated_settings_load(users_dir, screen):
    old_config(users_dir, "Star Citizen", {"Computer": hud_wingman(chat_anchor="right_center")})
    settings = template("settings.yaml")
    del settings["hud_profiles"]

    migrated = migration().migrate_settings(settings)

    SettingsConfig(**migrated)


def test_every_wingman_gets_the_chat_and_info_panel():
    step = migration()

    with_skill = step.migrate_wingman(hud_wingman(show_chat_messages=False))
    without = step.migrate_wingman({"discoverable_skills": ["Timer"], "hud": {"chat": False, "info": False}})

    assert with_skill["hud"] == without["hud"] == {"chat": True, "info": True}


def test_the_skill_is_gone_from_the_wingman():
    wingman = migration().migrate_wingman(hud_wingman())

    assert wingman["skills"] == []
    assert wingman["discoverable_skills"] == ["Timer"]
    assert wingman["disabled_skill_tools"] == ["timer_start"]


def test_new_wingmen_get_the_chat_and_info_panel_too():
    defaults = migration().migrate_defaults(template("defaults.yaml"))

    assert defaults["hud"] == {"chat": True, "info": True}
    NestedConfig(**defaults)


def test_a_custom_copy_of_the_skill_moves_out_of_custom_skills(users_dir, screen):
    custom = os.path.join(users_dir, "custom_skills", "hud")
    os.makedirs(custom)
    with open(os.path.join(custom, "main.py"), "w") as f:
        f.write("# the user's changes")

    migration().migrate_settings({})

    assert not os.path.exists(custom)
    assert os.path.isfile(os.path.join(users_dir, "retired_skills", "hud", "main.py"))
