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
def service():
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
