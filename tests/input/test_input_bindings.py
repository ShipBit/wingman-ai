"""Which binding an input event triggers. On Windows left and right Ctrl share
scan code 29 and differ only in the extended flag."""

from types import SimpleNamespace

from api.enums import RecordingDevice
from api.interface import CommandJoystickConfig, InputBinding, KeyStroke
from services import input_bindings as ib

LEFT_CTRL = (29, False)
RIGHT_CTRL = (29, True)
F1 = (59, False)
X = (45, False)


def keys(*pairs):
    return InputBinding(
        device=RecordingDevice.KEYBOARD,
        keys=[KeyStroke(scan_code=c, extended=e, name=str(c)) for c, e in pairs],
    )


def test_right_ctrl_is_not_left_ctrl():
    binding = keys(RIGHT_CTRL)
    assert ib.matches(binding, [RIGHT_CTRL], key=RIGHT_CTRL)
    assert not ib.matches(binding, [LEFT_CTRL], key=LEFT_CTRL)


def test_a_combination_with_right_ctrl():
    binding = keys(RIGHT_CTRL, F1)
    assert ib.matches(binding, [RIGHT_CTRL, F1], key=F1)
    assert not ib.matches(binding, [LEFT_CTRL, F1], key=F1)
    assert not ib.matches(binding, [F1], key=F1)


def test_a_held_combination_does_not_fire_on_other_keys():
    binding = keys(RIGHT_CTRL, F1)
    assert not ib.matches(binding, [RIGHT_CTRL, F1, X], key=X)


def test_the_binding_with_more_keys_wins():
    candidates = [(keys(X), "plain"), (keys(LEFT_CTRL, X), "ctrl")]
    assert ib.best_match(candidates, [LEFT_CTRL, X], key=X) == "ctrl"
    assert ib.best_match(candidates, [X], key=X) == "plain"
    assert ib.best_match(candidates, [F1], key=F1) is None


def test_mouse_with_a_modifier():
    binding = InputBinding(
        device=RecordingDevice.MOUSE,
        keys=[KeyStroke(scan_code=29, extended=False, name="ctrl")],
        mouse_button="x2",
    )
    assert ib.matches(binding, [LEFT_CTRL], mouse_button="x2")
    assert not ib.matches(binding, [], mouse_button="x2")
    assert not ib.matches(binding, [LEFT_CTRL], mouse_button="x")


def test_joystick_with_and_without_modifier():
    stick = CommandJoystickConfig(guid="abc", button=3, name="Stick")
    plain = InputBinding(device=RecordingDevice.JOYSTICK, keys=[], joystick=stick)
    shifted = InputBinding(
        device=RecordingDevice.JOYSTICK,
        keys=[KeyStroke(scan_code=42, extended=False, name="shift")],
        joystick=stick,
    )
    pressed = CommandJoystickConfig(guid="abc", button=3)
    assert ib.matches(plain, [], joystick=pressed)
    assert not ib.matches(shifted, [], joystick=pressed)
    assert ib.best_match([(plain, "a"), (shifted, "b")], [(42, False)], joystick=pressed) == "b"
    assert not ib.matches(plain, [], joystick=CommandJoystickConfig(guid="abc", button=4))


def test_a_key_known_by_name_uses_this_machines_codes(monkeypatch):
    monkeypatch.setattr(ib, "_codes_for_name", lambda name: (79,) if name == "end" else ())
    binding = InputBinding(
        device=RecordingDevice.KEYBOARD, keys=[KeyStroke(name="end", extended=False)]
    )
    assert ib.matches(binding, [(79, True)], key=(79, True))
    assert not ib.matches(binding, [(80, False)], key=(80, False))


def test_an_event_without_a_flag_counts_as_not_extended():
    """macOS and Linux report is_extended as None."""
    event = SimpleNamespace(scan_code=59, is_extended=None, name="f1")
    assert ib.held_key(event) == (59, False)
    assert ib.stroke_from_event(event) == KeyStroke(scan_code=59, extended=False, name="f1")


def test_mouse_and_joystick_hooks_are_needed_for_any_binding():
    stick = CommandJoystickConfig(guid="abc", button=1)
    bindings = [
        keys(F1),
        InputBinding(device=RecordingDevice.MOUSE, keys=[], mouse_button="x"),
        InputBinding(device=RecordingDevice.JOYSTICK, keys=[], joystick=stick),
    ]
    assert ib.uses_mouse(bindings)
    assert ib.joystick_configs(bindings) == [stick]
    assert not ib.uses_mouse([keys(F1)])
