"""Read Elite's active key bindings and turn them into command actions.

Elite stores the bindings as XML. StartPreset.4.start names the active preset
for menus, ship, SRV and on foot, one per line. A preset the user changed lives
next to it as <name>.4.<minor>.binds; an untouched built-in preset only exists
in the game's ControlSchemes folder.

Key names like Key_L describe the physical key, not the letter on it, so the
actions use scan codes. That keeps them right on every keyboard layout.
Standard library only, so it is tested without Core.
"""

import os
import platform
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from skills.elite_dangerous_controls.catalog import CATALOG, MODES

MAX_XML_BYTES = 512 * 1024
HOLD_SECONDS = 0.1

# Elite key name -> (scan code, extended). From S-Foxx (wingman-ai#442).
SCAN: dict[str, tuple[int, bool]] = {}
for _row, _start in (("1 2 3 4 5 6 7 8 9 0", 2), ("Q W E R T Y U I O P", 16),
                     ("A S D F G H J K L", 30), ("Z X C V B N M", 44)):
    SCAN.update({"Key_" + key: (_start + i, False) for i, key in enumerate(_row.split())})
SCAN.update({"Key_F" + str(i): (58 + i, False) for i in range(1, 11)})
SCAN.update({"Key_" + key: (code, False) for key, code in {
    "Escape": 1, "Minus": 12, "Equals": 13, "Backspace": 14, "Tab": 15,
    "LeftBracket": 26, "RightBracket": 27, "Return": 28, "LeftControl": 29,
    "SemiColon": 39, "Semicolon": 39, "Apostrophe": 40, "Grave": 41, "LeftShift": 42,
    "BackSlash": 43, "Comma": 51, "Period": 52, "Slash": 53,
    "RightShift": 54, "Numpad_Multiply": 55, "LeftAlt": 56, "Space": 57,
    "CapsLock": 58, "NumLock": 69, "ScrollLock": 70, "Numpad_7": 71,
    "Numpad_8": 72, "Numpad_9": 73, "Numpad_Subtract": 74, "Numpad_4": 75,
    "Numpad_5": 76, "Numpad_6": 77, "Numpad_Add": 78, "Numpad_1": 79,
    "Numpad_2": 80, "Numpad_3": 81, "Numpad_0": 82, "Numpad_Decimal": 83,
    "F11": 87, "F12": 88, "OEM_102": 86,
}.items()})
SCAN.update({"Key_" + key: (code, True) for key, code in {
    "Numpad_Enter": 28, "RightControl": 29, "Numpad_Divide": 53, "RightAlt": 56,
    "Home": 71, "UpArrow": 72, "PageUp": 73, "LeftArrow": 75,
    "RightArrow": 77, "End": 79, "DownArrow": 80, "PageDown": 81,
    "Insert": 82, "Delete": 83,
}.items()})
MODIFIERS = frozenset({"Key_LeftControl", "Key_RightControl", "Key_LeftShift",
                       "Key_RightShift", "Key_LeftAlt", "Key_RightAlt"})

_LABELS = {
    "Return": "enter", "Escape": "esc", "UpArrow": "up", "DownArrow": "down",
    "LeftArrow": "left", "RightArrow": "right", "PageUp": "page up",
    "PageDown": "page down", "LeftControl": "left ctrl", "RightControl": "right ctrl",
    "LeftShift": "left shift", "RightShift": "right shift", "LeftAlt": "left alt",
    "RightAlt": "right alt", "BackSlash": "\\", "Minus": "-", "Equals": "=",
    "Comma": ",", "Period": ".", "Slash": "/", "SemiColon": ";", "Semicolon": ";", "Apostrophe": "'",
    "Grave": "`", "LeftBracket": "[", "RightBracket": "]", "CapsLock": "caps lock",
    "NumLock": "num lock", "ScrollLock": "scroll lock",
}


def key_label(key: str) -> str:
    """The name the command editor shows, e.g. 'l', 'left shift', 'numpad 8'.

    Never 'num 8': Core sends keys whose name starts with 'num ' by name
    instead of by scan code (services/command_executor.py).
    """
    name = key.removeprefix("Key_")
    if name.startswith("Numpad_"):
        return "numpad " + name.removeprefix("Numpad_").lower()
    return _LABELS.get(name, name.lower())


@dataclass
class Bindings:
    """What one read of Elite's bindings found."""

    actions: dict[str, list[dict]] = field(default_factory=dict)
    """Command name -> CommandActionConfig dicts, ready to press."""
    keys: dict[str, str] = field(default_factory=dict)
    """Command name -> the chord, e.g. 'left shift+l', for the summary."""
    unbound: list[str] = field(default_factory=list)
    """Command names with no keyboard key, or only one Wingman cannot press."""
    presets: dict[str, str] = field(default_factory=dict)
    """Mode -> the preset file that was read."""


# --- where Elite keeps things ------------------------------------------------


def default_bindings_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "Frontier Developments" / "Elite Dangerous" / "Options" / "Bindings"


def _steam_libraries() -> list[Path]:
    roots = []
    if platform.system() == "Windows":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                roots.append(Path(winreg.QueryValueEx(key, "SteamPath")[0]))
        except OSError:
            pass
    roots.append(Path("C:/Program Files (x86)/Steam"))
    libraries = []
    for root in roots:
        libraries.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        try:
            text = vdf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in re.finditer(r'"path"\s+"([^"]+)"', text):
            libraries.append(Path(match.group(1).replace("\\\\", "\\")))
    return libraries


def game_dirs() -> list[Path]:
    """Where an installed Elite usually is: Steam, Epic, the Frontier launcher."""
    dirs = [library / "steamapps" / "common" / "Elite Dangerous" for library in _steam_libraries()]
    dirs += [
        Path("C:/Program Files/Epic Games/EliteDangerous"),
        Path("C:/Program Files (x86)/Frontier"),
        Path("C:/Program Files/Frontier"),
    ]
    return dirs


def control_schemes_dirs(game_dir: Path) -> list[Path]:
    """ControlSchemes folders below a game folder, newest product first.

    Accepts the game folder itself, its Products folder, or ControlSchemes.
    """
    if game_dir.name == "ControlSchemes":
        return [game_dir]
    found = sorted(game_dir.glob("Products/*/ControlSchemes")) + sorted(
        game_dir.glob("*/ControlSchemes")
    )
    # elite-dangerous-odyssey-64 (the live game) before elite-dangerous-64 (Legacy).
    return sorted(found, key=lambda p: "odyssey" not in p.parent.name)


# --- reading -------------------------------------------------------------------


def _read_xml(path: Path) -> ET.Element:
    raw = path.read_bytes()
    if len(raw) > MAX_XML_BYTES:
        raise ValueError(f"{path.name} is too large to be a bindings file")
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError(f"{path.name} is not a plain bindings file")
    root = ET.fromstring(raw)
    if root.tag != "Root":
        raise ValueError(f"{path.name} is not a bindings file")
    return root


def active_presets(bindings_dir: Path) -> dict[str, str]:
    """Mode -> preset name, from StartPreset.4.start (or the older StartPreset.start)."""
    for name in ("StartPreset.4.start", "StartPreset.start"):
        selector = bindings_dir / name
        if selector.is_file():
            lines = [line.strip() for line in selector.read_text(encoding="utf-8-sig").splitlines()]
            lines = [line for line in lines if line]
            if len(lines) == 1:
                lines = lines * len(MODES)
            if len(lines) != len(MODES):
                raise ValueError(f"{name} does not name one preset per mode")
            return dict(zip(MODES, lines))
    raise FileNotFoundError(f"No StartPreset file in {bindings_dir}")


def preset_file(name: str, bindings_dir: Path, schemes: list[Path]) -> Path:
    """The user's saved copy of a preset, or the built-in one from the game."""
    if not re.fullmatch(r"[\w .()-]{1,100}", name):
        raise ValueError(f"Unexpected preset name {name!r}")
    saved = []
    for path in bindings_dir.glob("*.binds"):
        match = re.fullmatch(re.escape(name) + r"(?:\.(\d+)\.(\d+))?\.binds", path.name)
        if match:
            version = (int(match.group(1) or 0), int(match.group(2) or 0))
            saved.append((version, path))
    if saved:
        return max(saved)[1]
    for folder in schemes:
        path = folder / f"{name}.binds"
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"The preset {name!r} is built into Elite and the game folder was not found"
    )


def _chord(binding: ET.Element | None) -> list[str] | None:
    """The keys of one Primary/Secondary slot, modifiers first, or None if
    it is not a plain keyboard binding."""
    if binding is None or binding.get("Device") != "Keyboard":
        return None
    key = binding.get("Key", "")
    if key not in SCAN:
        return None
    modifiers = []
    for child in binding:
        if child.tag != "Modifier" or child.get("Device") != "Keyboard":
            return None
        modifier = child.get("Key", "")
        if modifier not in SCAN or modifier in modifiers:
            return None
        modifiers.append(modifier)
    if key in modifiers:
        return None
    return modifiers + [key]


def actions_for(chord: list[str]) -> list[dict]:
    """Hold the modifiers, tap the key, let go of the modifiers."""

    def keyboard(key: str, **extra) -> dict:
        code, extended = SCAN[key]
        return {"keyboard": {"hotkey": key_label(key), "hotkey_codes": [code],
                             "hotkey_extended": extended, **extra}}

    *modifiers, key = chord
    actions = [keyboard(m, press=True) for m in modifiers]
    actions.append(keyboard(key, hold=HOLD_SECONDS))
    actions += [keyboard(m, release=True) for m in reversed(modifiers)]
    return actions


def read_bindings(bindings_dir: Path, schemes: list[Path], blocked: set[str] = frozenset()) -> Bindings:
    """Read the active presets and map every catalog entry to its key.

    `blocked` holds Elite key names Wingman must not press, like its own
    push-to-talk key.
    """
    presets = active_presets(bindings_dir)
    result = Bindings()
    roots: dict[str, ET.Element] = {}
    for mode in CATALOG:
        path = preset_file(presets[mode], bindings_dir, schemes)
        roots[mode] = _read_xml(path)
        result.presets[mode] = str(path)
    for mode, rows in CATALOG.items():
        for tag, name in rows:
            node = roots[mode].find(tag)
            chord = None
            if node is not None:
                toggle = node.find("ToggleOn")
                # "Hold" mode: one tap would switch it on for a blink only.
                if toggle is None or toggle.get("Value", "1") == "1":
                    for slot in ("Primary", "Secondary"):
                        keys = _chord(node.find(slot))
                        if keys and not blocked.intersection(keys):
                            chord = keys
                            break
            if chord is None:
                result.unbound.append(name)
                continue
            result.actions[name] = actions_for(chord)
            result.keys[name] = "+".join(key_label(k) for k in chord)
    return result


def blocked_keys(record_key: str | None, record_key_codes: list[int] | None) -> set[str]:
    """Elite key names that are part of the Wingman's push-to-talk key."""
    blocked = set()
    if record_key_codes:
        blocked |= {key for key, (code, _) in SCAN.items() if code in record_key_codes}
    if record_key:
        tokens = {t.strip().lower() for t in record_key.split("+") if t.strip()}
        for key in SCAN:
            label = key_label(key)
            if label in tokens or label.removeprefix("left ").removeprefix("right ") in tokens:
                blocked.add(key)
    return blocked
