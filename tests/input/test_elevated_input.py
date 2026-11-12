"""A window that runs as administrator gets its input through the helper,
and the helper hears the keys there in Core's place. Every other window, and
every case where the helper is not there, keeps the direct way."""

import json

import pytest

from keyboard.keyboard._keyboard_event import KeyboardEvent
from mouse.mouse._mouse_event import ButtonEvent
from services import elevated_input
from services.elevated_input import ElevatedInput, button_message, key_message, perform, receive, routed


class FakeConnection:
    def __init__(self, broken=False):
        self.broken = broken
        self.sent = []
        self.closed = False

    def send_bytes(self, message):
        if self.broken:
            raise OSError("pipe closed")
        self.sent.append(message)

    def close(self):
        self.closed = True


@pytest.fixture
def helper(monkeypatch):
    """A helper that is already connected."""
    connected = ElevatedInput()
    connected._connection = FakeConnection()
    monkeypatch.setattr(elevated_input, "_elevated_input", connected)
    return connected


def window_in_front(monkeypatch, elevated):
    monkeypatch.setattr(elevated_input, "_out_of_reach", lambda: elevated)


def test_normal_window_gets_the_input_directly(monkeypatch, helper):
    window_in_front(monkeypatch, elevated=False)
    pressed = []

    routed("key", lambda *arguments: pressed.append(arguments))(30, 0)

    assert pressed == [(30, 0)]
    assert helper._connection.sent == []


def test_elevated_window_gets_the_input_from_the_helper(monkeypatch, helper):
    window_in_front(monkeypatch, elevated=True)
    pressed = []

    routed("key", lambda *arguments: pressed.append(arguments))(30, 0)

    assert pressed == []
    assert [json.loads(message) for message in helper._connection.sent] == [["key", 30, 0]]


def test_input_does_not_wait_for_a_helper_that_is_not_there(monkeypatch, helper):
    window_in_front(monkeypatch, elevated=True)
    monkeypatch.setattr(elevated_input, "_helper_path", lambda: None)
    monkeypatch.setattr(elevated_input, "_log", lambda *_a, **_k: None)
    helper._connection = None
    pressed = []

    routed("key", lambda *arguments: pressed.append(arguments))(30, 0)

    assert pressed == [(30, 0)]


def test_helper_that_died_is_dropped_and_the_input_goes_out_directly(monkeypatch, helper):
    window_in_front(monkeypatch, elevated=True)
    monkeypatch.setattr(elevated_input, "_helper_path", lambda: None)
    dead = helper._connection
    dead.broken = True
    pressed = []

    routed("key", lambda *arguments: pressed.append(arguments))(30, 0)

    assert pressed == [(30, 0)]
    assert dead.closed
    assert helper._connection is None


def test_helper_runs_what_core_sends(helper):
    done = []
    functions = {"move_to": lambda x, y: done.append((x, y))}

    helper.send("move_to", (10, 20.5))

    assert perform(helper._connection.sent[0], functions)
    assert done == [(10, 20.5)]


def test_core_tells_the_helper_when_to_listen(helper):
    asked = []

    helper.send(elevated_input.LISTEN, (True, False))

    assert perform(helper._connection.sent[0], {elevated_input.LISTEN: lambda *devices: asked.append(devices)})
    assert asked == [(True, False)]


def test_key_the_helper_heard_reaches_core_as_the_same_key():
    heard = KeyboardEvent("down", 29, name="ctrl", is_keypad=False, is_extended=1)
    keys = []

    assert receive(key_message(heard), keys.append, None)

    (key,) = keys
    assert (key.event_type, key.scan_code, key.name, key.is_keypad, key.is_extended) == ("down", 29, "ctrl", False, 1)


def test_mouse_button_the_helper_heard_reaches_core():
    buttons = []

    assert receive(button_message(ButtonEvent("down", "x2", 0)), None, buttons.append)

    assert [(button.event_type, button.button) for button in buttons] == [("down", "x2")]


@pytest.mark.parametrize("message", [b"not json", b'["key", "down"]', b'["key", "held", 29, "ctrl", false, 0]', b'["move", 1, 2]'])
def test_core_drops_what_is_not_a_key_or_button(message):
    events = []

    assert receive(message, events.append, events.append) is False
    assert events == []


@pytest.mark.parametrize(
    "message",
    [
        b"not json",
        b'{"key": 30}',
        b'["shell", "calc.exe"]',
        b'["key", 30]',
        b'["key", 30, 0, 1]',
        b'["key", "30", 0]',
        b'["key", true, 0]',
        b'["text", 65]',
        b'["listen", 1, 0]',
    ],
)
def test_helper_drops_everything_else(message):
    done = []
    functions = {action: lambda *arguments: done.append(arguments) for action in elevated_input.ACTIONS}

    assert perform(message, functions) is False
    assert done == []
