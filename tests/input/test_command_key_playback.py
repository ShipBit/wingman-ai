"""Command actions recorded before 3.2.12 must press exactly the same keys as
before. Only combinations with a flag per key (`keys`) play the new way."""

import asyncio

import pytest

import services.command_executor as executor_module
from api.interface import CommandActionConfig, CommandConfig, CommandKeyboardConfig, KeyStroke
from services.command_executor import CommandExecutor


class FakeKeyboard:
    def __init__(self):
        self.calls = []

    def direct_event(self, code, event_type):
        self.calls.append(("direct_event", code, event_type))

    def press(self, code):
        self.calls.append(("press", code))

    def release(self, code):
        self.calls.append(("release", code))

    def send(self, code, press, release):
        self.calls.append(("send", code, press, release))


@pytest.fixture
def keyboard(monkeypatch):
    fake = FakeKeyboard()
    monkeypatch.setattr(executor_module, "keyboard", fake)
    monkeypatch.setattr(executor_module.time, "sleep", lambda _s: None)
    return fake


def play(**keyboard_config):
    executor = CommandExecutor(
        config=None, audio_library=None, wingman_name="Computer", on_reset_history=None
    )
    command = CommandConfig(
        name="Test",
        actions=[CommandActionConfig(keyboard=CommandKeyboardConfig(**keyboard_config))],
    )
    asyncio.run(executor.execute_action(command))


# What 3.2.11 did with these actions, call for call.
OLD_ACTIONS = [
    (
        {"hotkey": "end", "hotkey_codes": [79], "hotkey_extended": True},
        [("direct_event", 79, 1), ("direct_event", 79, 3)],
    ),
    (
        {"hotkey": "left windows+s", "hotkey_codes": [91, 31], "hotkey_extended": True},
        [("press", [91, 31]), ("release", [91, 31])],
    ),
    (
        {"hotkey": "ctrl+c", "hotkey_codes": [29, 46], "hotkey_extended": False},
        [("press", [29, 46]), ("release", [29, 46])],
    ),
    (
        {"hotkey": "num 8", "hotkey_codes": [72]},
        [("press", "num 8"), ("release", "num 8")],
    ),
    (
        {"hotkey": "shift", "hotkey_codes": [42], "press": True},
        [("direct_event", 42, 0)],
    ),
    (
        {"hotkey": "ctrl+x", "hotkey_codes": [29, 45], "release": True},
        [("send", [29, 45], None, True)],
    ),
    ({"hotkey": "f5"}, [("press", "f5"), ("release", "f5")]),
]


@pytest.mark.parametrize("config,calls", OLD_ACTIONS)
def test_old_actions_play_as_before(keyboard, config, calls):
    play(**config)
    assert keyboard.calls == calls


def strokes(*keys):
    return [KeyStroke(scan_code=c, extended=e, name=n) for c, e, n in keys]


def test_a_combination_with_flags_keeps_right_ctrl(keyboard):
    play(
        hotkey="right ctrl+up",
        hotkey_codes=[29, 72],
        keys=strokes((29, True, "right ctrl"), (72, True, "up")),
    )
    assert keyboard.calls == [
        ("direct_event", 29, 1),
        ("direct_event", 72, 1),
        ("direct_event", 72, 3),
        ("direct_event", 29, 3),
    ]


def test_a_mixed_combination_presses_each_key_with_its_flag(keyboard):
    play(
        hotkey="right ctrl+f1",
        hotkey_codes=[29, 59],
        keys=strokes((29, True, "right ctrl"), (59, False, "f1")),
        press=True,
    )
    assert keyboard.calls == [("direct_event", 29, 1), ("direct_event", 59, 0)]


def test_a_numpad_combination_keeps_the_old_way(keyboard):
    play(
        hotkey="ctrl+num 8",
        hotkey_codes=[29, 72],
        keys=strokes((29, False, "ctrl"), (72, False, "num 8")),
    )
    assert keyboard.calls == [("press", "ctrl+num 8"), ("release", "ctrl+num 8")]
