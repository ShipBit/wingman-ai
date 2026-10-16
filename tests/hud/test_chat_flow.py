"""The chat flow: a chat window in the shared chat area that keeps the
conversation, driven through the HUD server the way Core drives it."""

from hud_server.constants import GROUP_CHAT
from hud_server.hud_manager import HudManager
from tests.support import FakeHudBackend, make_overlay, overlay_errors, run_frames

AREA = {"layout_mode": "manual", "x": 300, "y": 200, "width": 500, "max_height": 400, "align": "top"}


def wired(**style):
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    manager = HudManager()
    manager.register_command_callback(overlay._handle_message)
    manager.set_defaults({"typewriter_effect": False, **style}, {GROUP_CHAT: AREA})
    manager.create_group(GROUP_CHAT, "chat")
    return backend, overlay, manager


def test_the_conversation_shows_in_the_chat_area():
    backend, overlay, manager = wired()

    manager.send_chat_message(GROUP_CHAT, "chat", "Jan", "Status?")
    manager.send_chat_message(GROUP_CHAT, "chat", "Computer", "All green.")
    run_frames(overlay)

    window = backend.window(f"HUD_chat_{GROUP_CHAT}")
    assert window.shown
    assert window.rect[:3] == (300, 200, 500)
    assert overlay_errors(overlay) == []


def test_a_hidden_chat_stays_hidden_until_the_next_message():
    backend, overlay, manager = wired()
    manager.send_chat_message(GROUP_CHAT, "chat", "Jan", "Status?")
    run_frames(overlay)
    window = backend.window(f"HUD_chat_{GROUP_CHAT}")

    manager.hide_chat_window(GROUP_CHAT, "chat")
    run_frames(overlay, 20)
    assert not window.shown

    manager.send_chat_message(GROUP_CHAT, "chat", "Computer", "All green.")
    run_frames(overlay)
    assert window.shown


def test_the_chat_runs_the_loader_in_the_accent_color():
    backend, overlay, manager = wired(accent_color="#ff0000")
    manager.send_chat_message(GROUP_CHAT, "chat", "Jan", "Status?")

    manager.set_loader(GROUP_CHAT, "chat", True)
    run_frames(overlay)

    assert (255, 0, 0, 255) in list(backend.window(f"HUD_chat_{GROUP_CHAT}").image.getdata())


def test_tool_calls_stay_and_the_answer_comes_after_them():
    backend, overlay, manager = wired(accent_color="#00ff00", bg_color="#000000")
    manager.send_chat_message(GROUP_CHAT, "chat", "Jan", "Status?", own=True)
    manager.send_chat_message(GROUP_CHAT, "chat", "Computer", "", tools=[{"name": "get_fuel", "source": "Ship Status"}])
    manager.send_chat_message(GROUP_CHAT, "chat", "Computer", "All green.")
    run_frames(overlay)

    image = backend.window(f"HUD_chat_{GROUP_CHAT}").image
    rows = lambda test: [i // image.width for i, p in enumerate(image.getdata()) if test(p)]
    chip_outline = rows(lambda p: p[1] > 200 and p[0] < 100 and p[2] < 100)
    light_text = rows(lambda p: p[0] > 200 and p[1] > 200 and p[2] > 200)
    assert chip_outline and max(chip_outline) < max(light_text)  # the answer is the lowest line
    assert overlay_errors(overlay) == []


def test_text_never_joins_a_message_that_shows_tool_chips():
    manager = HudManager()
    manager.create_group(GROUP_CHAT, "chat")

    said = manager.send_chat_message(GROUP_CHAT, "chat", "Computer", "Checking.")
    called = manager.send_chat_message(GROUP_CHAT, "chat", "Computer", "", tools=[{"name": "get_fuel"}])
    called_again = manager.send_chat_message(GROUP_CHAT, "chat", "Computer", "", tools=[{"name": "get_cargo"}])
    answered = manager.send_chat_message(GROUP_CHAT, "chat", "Computer", "All green.")

    # Chips join the text before them; the answer comes after them, on its own
    assert said == called == called_again
    assert answered != called
