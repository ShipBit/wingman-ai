"""Core shows the HUD profile that names the loaded config, the default for
every other config, and keeps that right as configs are switched, renamed and
deleted. Real configs, config service and HUD server state; only the screen is
a fake."""

import asyncio
from types import SimpleNamespace

import pytest

from api.interface import HudProfile
from hud_server.hud_manager import HudManager
from services import hud_profiles
from services.config_service import ConfigService
from services.hud_service import HudService
from tests.support import FakeHudBackend, make_overlay, template

RED = "#ff0000"


@pytest.fixture
def core(boot_config_manager, users_dir, monkeypatch):
    import services.hud_service as hud_service_module

    # The info panels are saved next to the version folders: the test's, not yours
    monkeypatch.setattr(hud_service_module, "get_users_dir", lambda: users_dir)
    HudService._instance = None
    config_manager = boot_config_manager()
    config_service = ConfigService(config_manager=config_manager)
    hud = HudService()
    hud.configure(config_manager, config_service)

    async def tower(info):
        """What WingmanCore does on a load once the client is signed in."""
        await hud.channel_loaded(info.config_dir.name)

    config_service.config_events.subscribe("config_loaded", tower)

    overlay = make_overlay(FakeHudBackend())
    manager = HudManager()
    manager.register_command_callback(overlay._handle_message)

    default = HudProfile(**template("settings.yaml")["hud_profiles"][0])
    racing = hud_profiles.new_profile("Racing", default)
    racing.style.accent_color = RED
    racing.configs = ["General"]
    config_manager.settings_config.hud_profiles = [default, racing]

    # Started the way Core starts it: the shared containers come with it
    server = SimpleNamespace(
        is_running=True, manager=manager,
        add_event_listener=lambda listener: None, remove_event_listener=lambda listener: None,
    )
    asyncio.run(hud.attach_server(server))

    def load(name):
        config_dir = next(d for d in config_manager.get_config_dirs() if d.name == name)
        asyncio.run(config_service.load_config(config_dir))
        return config_dir

    yield SimpleNamespace(
        config_manager=config_manager, config_service=config_service, hud=hud,
        manager=manager, overlay=overlay, default=default, racing=racing, load=load,
    )
    HudService._instance = None


def shown_accent(core) -> str:
    """The accent the overlay draws new windows with."""
    return core.overlay._resolve_window_props("message", "wingman_chat")["accent_color"]


def test_a_config_a_profile_names_shows_that_profile_and_every_other_the_default(core):
    core.load("General")
    assert shown_accent(core) == RED
    assert core.hud.state().active_profile_id == core.racing.id

    core.load("Star Citizen")
    assert shown_accent(core) == core.default.style.accent_color
    assert core.hud.state().active_profile_id == core.default.id

    core.load("General")
    assert shown_accent(core) == RED


def test_giving_the_loaded_config_to_a_profile_switches_at_once(core):
    core.load("Star Citizen")
    edited = core.racing.model_copy(update={"configs": ["Star Citizen"]})

    asyncio.run(core.hud.update_hud_profile(core.racing.id, edited))

    assert shown_accent(core) == RED
    assert core.hud.state().active_profile_id == core.racing.id


def test_a_save_during_the_preview_keeps_the_dragged_areas(core):
    from api.interface import HudProfilePreviewRequest

    asyncio.run(core.hud.set_hud_profile_preview(core.racing.id, HudProfilePreviewRequest(enabled=True)))
    page = core.racing.model_copy(deep=True)
    asyncio.run(core.hud._preview_moved(
        {"container": "chat", "x1": 600, "y1": 100, "x2": 900, "y2": 400, "final": True}
    ))
    page.name = "Renamed"

    asyncio.run(core.hud.update_hud_profile(core.racing.id, page))

    saved = hud_profiles.find_profile(core.hud.state().profiles, core.racing.id)
    assert saved.name == "Renamed"
    assert (saved.chat.x1, saved.chat.y1, saved.chat.x2, saved.chat.y2) == (600, 100, 900, 400)


def test_without_a_preview_a_save_sets_the_areas(core):
    page = core.racing.model_copy(deep=True)
    page.chat.x1 = 300

    asyncio.run(core.hud.update_hud_profile(core.racing.id, page))

    assert hud_profiles.find_profile(core.hud.state().profiles, core.racing.id).chat.x1 == 300


def test_making_another_profile_the_default_switches_the_configs_no_profile_names(core):
    core.load("Star Citizen")

    asyncio.run(core.hud.set_default_hud_profile(core.racing.id))

    assert shown_accent(core) == RED


def test_a_renamed_config_keeps_its_profile(core):
    general = core.load("General")

    asyncio.run(core.config_service.rename_config(general, "Racing Rig"))

    assert core.racing.configs == ["Racing Rig"]
    assert core.config_service.current_config_dir.name == "Racing Rig"
    assert shown_accent(core) == RED


def test_a_deleted_config_leaves_its_profile(core):
    general = core.load("General")

    asyncio.run(core.config_service.delete_config(general))

    assert core.racing.configs == []
    assert shown_accent(core) == core.default.style.accent_color


def test_a_hud_problem_does_not_stop_the_config_from_loading(core):
    after = []
    core.config_service.config_events.subscribe("config_loaded", lambda info: after.append(info))

    def broken(*args, **kwargs):
        raise RuntimeError("HUD server gone")

    core.manager.set_defaults = broken
    core.load("General")

    assert len(after) == 1
    assert core.config_service.current_config_dir.name == "General"


def test_deleting_the_profile_on_screen_shows_the_default(core):
    core.load("General")

    asyncio.run(core.hud.delete_hud_profile(core.racing.id))

    assert shown_accent(core) == core.default.style.accent_color


def test_a_hud_server_that_starts_after_the_config_loaded_shows_its_profile(core):
    server = core.hud._server
    asyncio.run(core.hud.detach_server())
    core.load("General")

    asyncio.run(core.hud.attach_server(server))

    assert shown_accent(core) == RED



# ─────────────────────────────── content per profile ─────────────────────────────── #


def info_titles(core) -> list[str]:
    return [item["title"] for item in core.manager.get_items("wingman_info", "persistent")]


def wingman(name="Computer"):
    return SimpleNamespace(
        name=name,
        config=SimpleNamespace(hud=SimpleNamespace(chat=True, info=True)),
        get_avatar_path=lambda: None,
        build_tools=lambda: [],
    )


def test_each_profile_keeps_its_own_info_panel(core):
    core.load("General")
    core.hud.add_info("wingman_info", "Fuel", "80 %")

    core.load("Star Citizen")
    assert info_titles(core) == []
    core.hud.add_info("wingman_info", "Cargo", "Gold")

    core.load("General")
    assert info_titles(core) == ["Fuel"]

    core.load("Star Citizen")
    assert info_titles(core) == ["Cargo"]


def test_a_switch_makes_both_containers_anew_in_the_new_profiles_look(core):
    core.load("Star Citizen")
    core.hud.add_info("wingman_info", "Cargo", "Gold")
    from tests.support import run_frames

    run_frames(core.overlay)
    before = core.overlay._windows["persistent_wingman_info"]

    core.load("General")
    core.hud.add_info("wingman_info", "Fuel", "80 %")
    run_frames(core.overlay)

    after = core.overlay._windows["persistent_wingman_info"]
    assert after is not before
    assert after["props"]["accent_color"] == RED
    assert list(after["items"]) == ["Fuel"]


def test_each_profile_keeps_its_own_chat_flow(core):
    core.default.chat_flow = core.racing.chat_flow = True
    computer = wingman()

    core.load("General")
    asyncio.run(core.hud.on_conversation_message(computer, "user", "Status?", None))
    asyncio.run(core.hud.on_conversation_message(computer, "assistant", "All green.", []))

    core.load("Star Citizen")
    assert core.manager.get_chat_messages("wingman_chat", "chat") == []

    core.load("General")
    history = core.manager.get_chat_messages("wingman_chat", "chat")
    assert [(m["sender"], m["text"]) for m in history] == [("User", "Status?"), ("Computer", "All green.")]
    # Back, but out of sight until the conversation goes on
    window = core.overlay._windows["chat_wingman_chat"]
    assert window["visible"] is False and window.get("typing") is None


def test_the_info_panels_come_back_per_profile_after_a_restart(core):
    core.load("General")
    core.hud.add_info("wingman_info", "Fuel", "80 %")
    core.load("Star Citizen")
    core.hud.add_info("wingman_info", "Cargo", "Gold")
    server = core.hud._server

    asyncio.run(core.hud.detach_server())
    server.manager = HudManager()
    server.manager.register_command_callback(core.overlay._handle_message)
    core.manager = server.manager
    asyncio.run(core.hud.attach_server(server))

    assert info_titles(core) == ["Cargo"]
    core.load("General")
    assert info_titles(core) == ["Fuel"]


def test_a_profile_that_does_not_keep_its_panels_starts_without_them(core):
    core.racing.restore_info_items = False
    core.load("General")
    core.hud.add_info("wingman_info", "Fuel", "80 %")
    core.load("Star Citizen")
    server = core.hud._server

    asyncio.run(core.hud.detach_server())
    server.manager = HudManager()
    core.manager = server.manager
    asyncio.run(core.hud.attach_server(server))
    core.load("General")

    assert info_titles(core) == []


def test_no_profile_is_active_until_a_configs_wingmen_load(core, users_dir):
    import json
    import os

    server = core.hud._server
    asyncio.run(core.hud.detach_server())
    folder = os.path.join(users_dir, "hud")
    os.makedirs(folder, exist_ok=True)
    saved = {"profiles": {core.default.id: [{"title": "Cargo", "description": "Gold", "added_at": 1}]}}
    with open(os.path.join(folder, "info_panel.json"), "w", encoding="utf-8") as f:
        json.dump(saved, f)

    # On start: the HUD server runs, the start config is read, no Wingmen yet
    asyncio.run(core.hud.attach_server(server))
    assert core.hud.state().active_profile_id is None
    assert info_titles(core) == []
    asyncio.run(core.hud.detach_server())
    asyncio.run(core.hud.attach_server(server))

    core.load("Star Citizen")
    assert core.hud.state().active_profile_id == core.default.id
    assert info_titles(core) == ["Cargo"]
