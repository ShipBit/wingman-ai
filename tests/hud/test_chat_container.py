"""The conversation in the shared chat container."""

import asyncio
from os import path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api.interface import HudProfile
from hud_server.constants import GROUP_CHAT
from services.hud_service import HudService
from tests.support import TEMPLATES, template


@pytest.fixture
def service(tmp_path, monkeypatch):
    import services.hud_service as hud_service_module

    monkeypatch.setattr(hud_service_module, "get_users_dir", lambda: str(tmp_path))
    HudService._instance = None
    profile = HudProfile(**template("settings.yaml")["hud_profiles"][0])
    profile.max_display_time = 0.05
    profile.audio_stop_delay = 0.01
    config_manager = SimpleNamespace(
        settings_config=SimpleNamespace(hud_profiles=[profile], user_name="Jan"),
        save_settings_config=MagicMock(),
        templates_dir=path.dirname(TEMPLATES),
    )
    hud = HudService()
    hud.configure(config_manager, SimpleNamespace(current_config_dir=None, config_events=MagicMock()))
    hud._server = MagicMock(is_running=True)
    asyncio.run(hud.channel_loaded("General"))
    hud._server.manager.reset_mock()
    yield hud
    HudService._instance = None


def _wingman(chat=True):
    return SimpleNamespace(
        name="Computer",
        config=SimpleNamespace(hud=SimpleNamespace(chat=chat, info=True)),
        get_avatar_path=lambda: "avatar.png",
    )


def test_a_wingman_with_chat_off_stays_off_the_hud(service):
    asyncio.run(service.on_conversation_message(_wingman(chat=False), "user", "Hello", None))

    service._server.manager.show_message.assert_not_called()


def test_the_answer_stays_while_the_wingman_speaks_and_goes_after(service):
    manager = service._server.manager

    async def run():
        wingman = _wingman()
        await service.on_conversation_message(wingman, "user", "Status?", None)
        await service.on_conversation_message(wingman, "assistant", "All green.", [])
        service.playback_started("Computer")
        await asyncio.sleep(0.3)  # longer than max_display_time: speaking keeps it
        assert manager.hide_message.call_count == 0
        service.playback_finished("Computer")
        await asyncio.sleep(0.3)

    asyncio.run(run())

    titles = [c.args[2] for c in manager.show_message.call_args_list]
    assert titles == ["Jan", "Computer"]
    assert manager.show_message.call_args.kwargs["title_icon"] == "avatar.png"
    assert manager.show_message.call_args.args[0] == GROUP_CHAT
    manager.hide_message.assert_called_once_with(GROUP_CHAT, "message")


def test_speech_that_starts_late_brings_the_answer_back(service):
    manager = service._server.manager

    async def run():
        await service.on_conversation_message(_wingman(), "assistant", "All green.", [])
        await asyncio.sleep(0.3)  # no speech within max_display_time: hidden
        service.playback_started("Computer")

    asyncio.run(run())

    assert manager.hide_message.call_count == 1
    assert manager.show_message.call_count == 2


def test_a_filler_line_ending_does_not_hide_the_answer_still_to_be_spoken(service):
    manager = service._server.manager
    service.active_profile().max_display_time = 5.0

    async def run():
        wingman = _wingman()
        service.playback_started("Computer")  # the filler, before the answer exists
        await service.on_conversation_message(wingman, "assistant", "All green.", [])
        service.playback_finished("Computer")  # the filler ends
        await asyncio.sleep(0.3)
        assert manager.hide_message.call_count == 0
        service.playback_started("Computer")  # the answer
        service.playback_finished("Computer")
        await asyncio.sleep(0.3)

    asyncio.run(run())

    manager.hide_message.assert_called_once_with(GROUP_CHAT, "message")


def test_a_message_from_a_skills_thread_is_hidden_on_cores_loop(service):
    import threading

    manager = service._server.manager

    async def run():
        service._loop = asyncio.get_running_loop()
        thread = threading.Thread(target=lambda: asyncio.run(
            service.on_conversation_message(_wingman(), "assistant", "UEX is ready.", [])
        ))
        thread.start()
        thread.join()
        await asyncio.sleep(0.3)  # the thread's loop is gone; Core's loop hides it

    asyncio.run(run())

    manager.show_message.assert_called_once()
    manager.hide_message.assert_called_once_with(GROUP_CHAT, "message")


def test_speech_reported_from_a_speaking_threads_loop_still_hides_the_answer(service):
    import threading

    manager = service._server.manager
    service.active_profile().audio_stop_delay = 0.1

    async def speak():
        service.playback_started("Computer")
        service.playback_finished("Computer")

    async def run():
        service._loop = asyncio.get_running_loop()
        await service.on_conversation_message(_wingman(), "assistant", "All green.", [])
        # Streaming TTS: the events come from play_to_user's own loop, closed right after
        thread = threading.Thread(target=lambda: asyncio.run(speak()))
        thread.start()
        thread.join()
        await asyncio.sleep(0.3)

    asyncio.run(run())

    manager.hide_message.assert_called_once_with(GROUP_CHAT, "message")


def test_speech_does_not_hide_the_tool_chips_while_tools_run(service):
    manager = service._server.manager
    tool_call = {"function": {"name": "get_weather"}}

    async def run():
        await service.on_conversation_message(_wingman(), "assistant", "", [tool_call])
        service.playback_started("Computer")  # "One moment..." while the tool runs
        service.playback_finished("Computer")
        await asyncio.sleep(0.3)

    asyncio.run(run())

    assert manager.hide_message.call_count == 0


@pytest.mark.parametrize(
    "profile_name, account_name, title",
    [("Commander", "Jan", "Commander"), ("", "Jan", "Jan"), ("", None, "User")],
)
def test_the_chat_calls_the_user_by_the_profiles_name_else_the_account_name(
    service, profile_name, account_name, title
):
    service.active_profile().user_name = profile_name
    service.config_manager.settings_config.user_name = account_name

    asyncio.run(service.on_conversation_message(_wingman(), "user", "Status?", None))

    assert service._server.manager.show_message.call_args.args[2] == title


def test_with_the_chat_flow_the_conversation_runs_in_the_chat_window(service):
    service.active_profile().chat_flow = True
    manager = service._server.manager

    async def run():
        wingman = _wingman()
        await service.on_conversation_message(wingman, "user", "Status?", None)
        await service.on_conversation_message(wingman, "assistant", "All green.", [])
        service.playback_started("Computer")
        service.playback_finished("Computer")
        await asyncio.sleep(0.3)

    asyncio.run(run())

    sent = [(c.args[2], c.kwargs["own"], c.kwargs["icon"]) for c in manager.send_chat_message.call_args_list]
    assert sent == [("Jan", True, None), ("Computer", False, "avatar.png")]
    manager.show_message.assert_not_called()
    manager.hide_message.assert_not_called()
    manager.hide_chat_window.assert_called_once_with(GROUP_CHAT, "chat")


def test_switching_the_chat_flow_hides_the_container_the_chat_leaves(service):
    profile = service.active_profile()
    manager = service._server.manager

    profile.chat_flow = True
    service._apply_active_profile()
    manager.hide_message.assert_called_once_with(GROUP_CHAT, "message")

    profile.chat_flow = False
    service._apply_active_profile()
    manager.hide_chat_window.assert_called_once_with(GROUP_CHAT, "chat")


def test_in_the_chat_flow_tool_calls_stay_and_the_answer_follows(service):
    service.active_profile().chat_flow = True
    manager = service._server.manager

    async def run():
        wingman = _wingman()
        await service.on_conversation_message(wingman, "user", "Status?", None)
        await service.on_conversation_message(wingman, "assistant", "", [{"function": {"name": "get_fuel"}}])
        await service.on_conversation_message(wingman, "assistant", "All green.", [])

    asyncio.run(run())

    sent = [(c.args[3], len(c.kwargs["tools"])) for c in manager.send_chat_message.call_args_list]
    assert sent == [("Status?", 0), ("", 1), ("All green.", 0)]
