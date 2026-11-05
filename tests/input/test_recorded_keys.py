"""A recorded key combination stays one combination with a flag per key, also
when right Ctrl (extended) meets F1 (not extended). Before 3.2.12 that mix
fell back to the macro recorder, and the client kept only its first step:
the binding came out as "right ctrl" alone."""

from types import SimpleNamespace

from api.enums import RecordingDevice
from api.interface import CommandActionConfig, CommandJoystickConfig, CommandMouseConfig, KeyStroke
from services.command_handler import CommandHandler


def event(kind, scan_code, extended, name, t):
    return SimpleNamespace(
        event_type=kind, scan_code=scan_code, is_extended=extended, name=name, time=t
    )


def recorded(*events):
    handler = CommandHandler.__new__(CommandHandler)
    return handler._get_actions_from_recorded_hotkey(list(events))


def test_right_ctrl_and_f1_are_one_combination():
    actions = recorded(
        event("down", 29, 1, "right ctrl", 0.0),
        event("down", 59, 0, "f1", 0.05),
        event("up", 59, 0, "f1", 0.1),
        event("up", 29, 1, "right ctrl", 0.12),
    )
    assert len(actions) == 1
    keyboard = actions[0].keyboard
    assert keyboard.hotkey == "right ctrl+f1"
    assert keyboard.hotkey_codes == [29, 59]
    assert keyboard.keys == [
        KeyStroke(scan_code=29, extended=True, name="right ctrl"),
        KeyStroke(scan_code=59, extended=False, name="f1"),
    ]
    # The keys disagree, so there is no single flag for the combination.
    assert keyboard.hotkey_extended is None
    binding = CommandHandler._binding_from_action(actions[0], [])
    assert binding.device == RecordingDevice.KEYBOARD
    assert binding.keys == keyboard.keys


def test_a_single_key_keeps_its_single_flag():
    actions = recorded(
        event("down", 29, 1, "right ctrl", 0.0),
        event("up", 29, 1, "right ctrl", 0.1),
    )
    assert actions[0].keyboard.hotkey_extended is True
    assert actions[0].keyboard.keys == [KeyStroke(scan_code=29, extended=True, name="right ctrl")]


def test_mouse_and_joystick_bindings_take_the_held_keys():
    ctrl = [KeyStroke(scan_code=29, extended=False, name="ctrl")]
    mouse = CommandHandler._binding_from_action(
        CommandActionConfig(mouse=CommandMouseConfig(button="x2")), ctrl
    )
    assert mouse.device == RecordingDevice.MOUSE
    assert mouse.mouse_button == "x2" and mouse.keys == ctrl
    stick = CommandJoystickConfig(guid="abc", button=1, name="Stick")
    joystick = CommandHandler._binding_from_action(CommandActionConfig(joystick=stick), [])
    assert joystick.device == RecordingDevice.JOYSTICK and joystick.joystick == stick


class _Broadcast:
    def __init__(self):
        self.sent = []

    async def broadcast(self, command):
        self.sent.append(command)


def stopped(add_key, recording_type="single", recorded=()):
    """Stop a keyboard recording with a key picked from a button."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from api.commands import StopRecordingCommand

    handler = CommandHandler.__new__(CommandHandler)
    handler.keyboard_hook_callback = None
    handler.timeout_task = None
    handler.recorded_keys = list(recorded)
    handler._recorded_modifiers = []
    handler._mouse_hooked = False
    handler.connection_manager = _Broadcast()
    handler.printr = MagicMock(print_async=AsyncMock())
    handler.source_name = "test"
    asyncio.run(
        handler.handle_stop_recording(
            StopRecordingCommand(add_key=add_key, recording_type=recording_type), None
        )
    )
    return handler.connection_manager.sent[0]


def test_a_picked_f_key_is_the_single_recording():
    """Esc and the F keys cannot be pressed into the recorder, so the client
    sends them from a button. Kept by name, which every OS resolves."""
    sent = stopped("F1")
    (action,) = sent.actions
    assert action.keyboard.hotkey == "f1"
    assert sent.binding.keys == [KeyStroke(scan_code=None, extended=False, name="f1")]


def test_a_picked_key_is_appended_to_a_macro():
    sent = stopped(
        "esc",
        recording_type="macro",
        recorded=[event("down", 30, 0, "a", 0.0), event("up", 30, 0, "a", 0.1)],
    )
    assert [a.keyboard.hotkey for a in sent.actions] == ["a", "esc"]
    assert sent.binding is None


def test_only_the_offered_keys_can_be_picked():
    sent = stopped("delete")
    assert sent.actions == []
