"""Key, mouse and joystick bindings: matching them against what is held, and
turning the fields from before 3.2.12 into bindings.

A keyboard key is identified by its scan code AND its extended flag. On
Windows left and right Ctrl share scan code 29 and differ only in the flag,
and so do Alt and AltGr, Enter and numpad Enter, and the arrow keys against
the numpad. macOS and Linux report no flag; there it is always False.
"""

from functools import lru_cache
from typing import Iterable, Optional

from api.enums import RecordingDevice
from api.interface import CommandJoystickConfig, InputBinding, KeyStroke

# A held key: (scan_code, extended).
HeldKey = tuple[int, bool]

# Names the keyboard library gives extended keys on Windows. Used only to
# guess the flag for bindings saved before 3.2.12, which stored scan codes
# without it. The numpad twins of the navigation keys are called "num ...".
_EXTENDED_NAMES = {
    "right ctrl",
    "right alt",
    "alt gr",
    "left windows",
    "right windows",
    "windows",
    "menu",
    "apps",
    "insert",
    "delete",
    "home",
    "end",
    "page up",
    "page down",
    "up",
    "down",
    "left",
    "right",
    "print screen",
    "num lock",
}


def held_key(event) -> HeldKey:
    """The identity of a keyboard event from the hook."""
    return (event.scan_code, bool(event.is_extended))


def stroke_from_event(event) -> KeyStroke:
    return KeyStroke(
        scan_code=event.scan_code,
        extended=bool(event.is_extended),
        name=(event.name or str(event.scan_code)).lower(),
    )


@lru_cache(maxsize=256)
def _codes_for_name(name: str) -> tuple[int, ...]:
    """Scan codes the keyboard library knows for a key name on this OS. Empty
    when the name is unknown here."""
    import keyboard.keyboard as keyboard

    try:
        return tuple(keyboard.key_to_scan_codes(name, error_if_missing=False))
    except Exception:
        return ()


def stroke_is_held(stroke: KeyStroke, held: Iterable[HeldKey]) -> bool:
    held = list(held)
    if stroke.scan_code is not None:
        return (stroke.scan_code, stroke.extended) in held
    codes = _codes_for_name(stroke.name)
    return any(code in codes for code, _ in held)


def stroke_is(stroke: KeyStroke, key: HeldKey) -> bool:
    """Whether `key` is this stroke."""
    return stroke_is_held(stroke, [key])


def keys_held(binding: InputBinding, held: Iterable[HeldKey]) -> bool:
    held = list(held)
    return all(stroke_is_held(stroke, held) for stroke in binding.keys)


def matches_key(binding: InputBinding, pressed: HeldKey, held: Iterable[HeldKey]) -> bool:
    """A keyboard binding fires when the key just pressed belongs to it and all
    of its keys are down. Without the first check a held combination would
    fire again on every other key the user presses."""
    if binding.device != RecordingDevice.KEYBOARD or not binding.keys:
        return False
    if not any(stroke_is(stroke, pressed) for stroke in binding.keys):
        return False
    return keys_held(binding, held)


def matches_mouse(binding: InputBinding, button: str, held: Iterable[HeldKey]) -> bool:
    return (
        binding.device == RecordingDevice.MOUSE
        and bool(binding.mouse_button)
        and binding.mouse_button == button
        and keys_held(binding, held)
    )


def matches_joystick(
    binding: InputBinding, joystick: CommandJoystickConfig, held: Iterable[HeldKey]
) -> bool:
    return (
        binding.device == RecordingDevice.JOYSTICK
        and binding.joystick is not None
        and binding.joystick.guid is not None
        and binding.joystick.guid == joystick.guid
        and binding.joystick.button == joystick.button
        and keys_held(binding, held)
    )


def matches(
    binding: InputBinding,
    held: Iterable[HeldKey],
    key: Optional[HeldKey] = None,
    mouse_button: Optional[str] = None,
    joystick: Optional[CommandJoystickConfig] = None,
) -> bool:
    """Whether the input event that just came in triggers the binding."""
    held = list(held)
    if key is not None:
        return matches_key(binding, key, held)
    if mouse_button is not None:
        return matches_mouse(binding, mouse_button, held)
    if joystick is not None:
        return matches_joystick(binding, joystick, held)
    return False


def best_match(candidates, held: Iterable[HeldKey], **event):
    """From (binding, owner) pairs, the owner whose binding fires and needs the
    most keys: with "x" and "ctrl+x" both bound, Ctrl+X is the second one.
    Earlier candidates win a tie. None when nothing fires."""
    held = list(held)
    best = None
    best_size = -1
    for binding, owner in candidates:
        if matches(binding, held, **event) and len(binding.keys) > best_size:
            best, best_size = owner, len(binding.keys)
    return best


def any_matches(bindings: Iterable[InputBinding], held: Iterable[HeldKey], **event) -> bool:
    held = list(held)
    return any(matches(binding, held, **event) for binding in bindings)


def joystick_configs(bindings: Iterable[InputBinding]) -> list[CommandJoystickConfig]:
    return [
        binding.joystick
        for binding in bindings
        if binding.device == RecordingDevice.JOYSTICK
        and binding.joystick is not None
        and binding.joystick.guid
    ]


def uses_mouse(bindings: Iterable[InputBinding]) -> bool:
    return any(
        binding.device == RecordingDevice.MOUSE and binding.mouse_button
        for binding in bindings
    )


# ───────────────── Fields from before 3.2.12 ───────────────── #


def legacy_keyboard(
    hotkey: Optional[str], codes: Optional[list[int]], is_windows: bool
) -> Optional[dict]:
    """A binding (as a dict, for a migration) from an old hotkey string and
    its scan codes. Without codes the keys are stored by name and resolved on
    the machine that runs them, as the old string was."""
    names = [name.strip().lower() for name in (hotkey or "").split("+")]
    names = [name for name in names if name]
    if codes:
        if len(names) != len(codes):
            names = [str(code) for code in codes]
        keys = [
            {
                "scan_code": code,
                "extended": is_windows and name in _EXTENDED_NAMES,
                "name": name,
            }
            for name, code in zip(names, codes)
        ]
    elif names:
        keys = [{"scan_code": None, "extended": False, "name": name} for name in names]
    else:
        return None
    return {"device": RecordingDevice.KEYBOARD.value, "keys": keys}


def legacy_mouse(button: Optional[str]) -> Optional[dict]:
    if not button:
        return None
    return {"device": RecordingDevice.MOUSE.value, "keys": [], "mouse_button": button}


def legacy_joystick(joystick: Optional[dict]) -> Optional[dict]:
    if not isinstance(joystick, dict) or not joystick.get("guid"):
        return None
    if joystick.get("button") is None:
        return None
    return {
        "device": RecordingDevice.JOYSTICK.value,
        "keys": [],
        "joystick": {
            "guid": joystick["guid"],
            "button": joystick["button"],
            "name": joystick.get("name"),
        },
    }
