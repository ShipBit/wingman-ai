"""Stage ordinary Wingman commands from Elite's active Odyssey bindings.

No input is sent and no game or Wingman configuration is modified. Run from
the repository with ``python -m integrations.elite_dangerous.bindings``.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import yaml


MODES = ("general", "ship", "srv", "on_foot")
from .catalog import ACTIONS

KEYS = {
    "Space": "space", "Return": "enter", "Tab": "tab", "Escape": "esc",
    "Backspace": "backspace", "UpArrow": "up", "DownArrow": "down",
    "LeftArrow": "left", "RightArrow": "right", "Home": "home", "End": "end",
    "Insert": "insert", "Delete": "delete", "PageUp": "page up", "PageDown": "page down",
    "LeftShift": "left shift", "RightShift": "right shift",
    "LeftControl": "left ctrl", "RightControl": "right ctrl",
    "LeftAlt": "left alt", "RightAlt": "right alt",
    "Minus": "-", "Equals": "=", "Comma": ",", "Period": ".",
    "Numpad_Subtract": "num -", "Numpad_Add": "num +",
    "Numpad_Multiply": "num *", "Numpad_Divide": "num /",
}
MODIFIERS = {"left shift", "right shift", "left ctrl", "right ctrl", "left alt", "right alt"}
MOUSE = {"Mouse_1": "left", "Mouse_2": "right", "Mouse_3": "middle"}


def key_name(value):
    if not value.startswith("Key_"):
        raise ValueError(f"Unsupported key: {value}")
    key = value[4:]
    if re.fullmatch(r"[A-Z0-9]|F(?:[1-9]|1[0-2])", key):
        return key.lower()
    if re.fullmatch(r"Numpad_[0-9]", key):
        return "num " + key[-1]
    if key in KEYS:
        return KEYS[key]
    raise ValueError(f"Unsupported key: {value}")


def read_xml(path):
    raw = path.read_bytes()
    if len(raw) > 512 * 1024 or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError(f"Unsupported or oversized XML: {path.name}")
    root = ET.fromstring(raw)
    if root.tag != "Root":
        raise ValueError(f"Invalid bindings root: {path.name}")
    return root, hashlib.sha256(raw).hexdigest()


def resolve_preset(name, user_dir, game_dir):
    if not re.fullmatch(r"[\w -]{1,100}", name):
        raise ValueError("Invalid active preset name")
    candidates = []
    for path in user_dir.glob("*.binds"):
        match = re.fullmatch(re.escape(name) + r"\.4\.(\d+)\.binds", path.name)
        if match:
            candidates.append((int(match[1]), path))
    if candidates:
        path = max(candidates)[1]
    else:
        path = game_dir / (name + ".binds")
    root, digest = read_xml(path)
    if root.get("PresetName") != name:
        raise ValueError(f"Preset identity mismatch: {path.name}")
    if candidates and (root.get("MajorVersion") != "4" or root.get("MinorVersion") != str(max(candidates)[0])):
        raise ValueError(f"Preset version mismatch: {path.name}")
    return root, {"preset": name, "file": str(path.resolve()), "sha256": digest}


def binding_actions(binding):
    """Convert one supported chord; reject hold/toggle semantics we cannot preserve."""
    modifiers = []
    for child in binding:
        if child.tag != "Modifier" or child.get("Device") != "Keyboard" or len(child):
            raise ValueError("Unsupported hold or non-keyboard modifier")
        key = key_name(child.get("Key", ""))
        if key not in MODIFIERS or key in modifiers:
            raise ValueError("Unsupported modifier")
        modifiers.append(key)
    device, key = binding.get("Device"), binding.get("Key", "")
    if device == "Keyboard":
        key = key_name(key)
        if key in modifiers:
            raise ValueError("Key duplicates modifier")
        action = {"keyboard": {"hotkey": key, "hold": 0.1}}
        chord = "+".join(modifiers + [key])
    elif device == "Mouse" and key in MOUSE:
        action = {"mouse": {"button": MOUSE[key], "hold": 0.1}}
        chord = "+".join(modifiers + ["mouse " + MOUSE[key]])
    else:
        raise ValueError("Unbound or unsupported device")
    # Separate modifiers avoid '+' parser ambiguity for the numpad plus key.
    actions = [{"keyboard": {"hotkey": key, "press": True}} for key in modifiers]
    actions.append(action)
    actions.extend({"keyboard": {"hotkey": key, "release": True}} for key in reversed(modifiers))
    return actions, chord


def generate(user_dir, game_dir, record_key="end"):
    user_dir, game_dir = Path(user_dir), Path(game_dir)
    ptt = record_key.strip().casefold()
    ptt_keys = {
        "ctrl": {"left ctrl", "right ctrl"}, "control": {"left ctrl", "right ctrl"},
        "shift": {"left shift", "right shift"}, "alt": {"left alt", "right alt"},
        "escape": {"esc"}, "return": {"enter"},
    }.get(ptt, {ptt})
    selector = user_dir / "StartPreset.4.start"
    raw = selector.read_bytes()
    names = raw.decode("utf-8-sig").splitlines()
    if len(names) != 4 or any(not name.strip() for name in names):
        raise ValueError("Expected four Odyssey selectors: general, ship, SRV, on-foot")
    roots, sources = {}, {}
    for mode, name in zip(MODES, names):
        roots[mode], sources[mode] = resolve_preset(name.strip(), user_dir, game_dir)
    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "sources": sources,
              "selector_sha256": hashlib.sha256(raw).hexdigest(), "controls": "keyboard_and_mouse",
              "status": "staged_not_gameplay_verified", "commands": [], "skipped": [],
              "limitations": ["Requires game focus and matching vehicle mode; ordinary commands have no mode/focus guard.",
                              "Names use Wingman's current OS keyboard layout; verify in-game before enabling.",
                              "Regenerate after any binding or push-to-talk change.",
                              "Toggle requests do not guarantee a resulting state."]}
    rows = []
    for mode, mappings in ACTIONS.items():
        for tag, phrase in mappings.items():
            nodes = roots[mode].findall(tag)
            reason = "No usable primary or secondary binding"
            if len(nodes) == 1:
                node = nodes[0]
                toggle = node.find("ToggleOn")
                if toggle is not None and toggle.get("Value", "1") != "1":
                    reason = "Action configured as hold instead of toggle"
                else:
                    for slot in ("Primary", "Secondary"):
                        binding = node.find(slot)
                        if binding is None:
                            continue
                        try:
                            actions, chord = binding_actions(binding)
                            keys = [a["keyboard"]["hotkey"] for a in actions if "keyboard" in a]
                            if ptt_keys.intersection(keys):
                                raise ValueError("Conflicts with Companion push-to-talk key")
                        except ValueError as exc:
                            reason = str(exc)
                            continue
                        name = mode.replace("_", " ") + " " + phrase
                        # Speech-to-text commonly adds sentence punctuation. Keep
                        # exact shortcuts and expose the same action to native tools.
                        command = {"name": name, "instant_activation": [name, name + ".", name + "!"], "force_instant_activation": False,
                                   "actions": actions, "additional_context":
                                   f"Sent {tag} input for {mode}; resulting game state is unverified."}
                        result["commands"].append(command)
                        rows.append({"mode": mode, "action": tag, "phrase": name, "key": chord, "slot": slot})
                        break
                    else:
                        result["skipped"].append({"mode": mode, "action": tag, "reason": reason})
                    continue
            result["skipped"].append({"mode": mode, "action": tag, "reason": reason})
    # Detect edits during generation instead of producing a mixed snapshot.
    if selector.read_bytes() != raw or any(hashlib.sha256(Path(s["file"]).read_bytes()).hexdigest() != s["sha256"] for s in sources.values()):
        raise ValueError("Bindings changed during generation; retry")
    result["mappings"] = rows
    return result


def stage(result, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for mode in ACTIONS:
        names = {row["phrase"] for row in result["mappings"] if row["mode"] == mode}
        commands = [command for command in result["commands"] if command["name"] in names]
        (output / f"{mode}.commands.yaml").write_text(yaml.safe_dump({"commands": commands}, sort_keys=False), encoding="utf-8")
    (output / "bindings-report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = ["# Generated Elite command reference", "", "Staged only; verify game focus, vehicle mode, and keyboard layout before use.", "",
             "| Mode | Exact spoken phrase | Key |", "| --- | --- | --- |"]
    lines.extend(f"| {row['mode']} | {row['phrase']} | {row['key']} |" for row in result["mappings"])
    lines.extend(["", "## Unavailable commands", ""])
    lines.extend(f"- {row['mode']}: {row['action']} — {row['reason']}" for row in result["skipped"])
    (output / "COMMANDS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bindings", required=True, type=Path)
    parser.add_argument("--presets", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--record-key", default="end")
    args = parser.parse_args()
    stage(generate(args.bindings, args.presets, args.record_key), args.output)
