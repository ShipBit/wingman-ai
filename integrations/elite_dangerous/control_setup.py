"""Inspect, supplement, install and restore verified Elite controls. Never sends input.

python -m integrations.elite_dangerous.control_setup --help
"""

import argparse
from copy import deepcopy
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import xml.etree.ElementTree as ET
from itertools import product

import yaml

from integrations.elite_dangerous.controls import atomic_write, command_value, read_optional
from services.printr import Printr
from skills.elite_dangerous_controls.runtime import (
    ACTIONS, MODES, BindingResolver, active_chords, chord_of, conflicting_tags, default_bindings, digest, ptt_keys,
)
from skills.elite_dangerous_controls.catalog import CATALOG, BY_MODE_TAG, GENERAL_TAGS, source_mode, exclusion


ROOT = Path(__file__).resolve().parents[2]
PRESET_NAMES = {"general": "Wingman - General", "ship": "Wingman - Ship", "srv": "Wingman - SRV", "on_foot": "Wingman - On Foot"}
PROMPT = ("Use EliteDangerousControls and elite_control for requested game actions. "
          "Natural-language routing authorizes one discrete control per turn; clarify real ambiguity. "
          "On/off wording still presses the binding once. It speaks its own acknowledgment, not a resulting-state claim. "
          "Never claim a telemetry lookup executed a control. Launch/docking automation is unavailable.")


def game_running():
    if platform.system() != "Windows":
        return False
    result = subprocess.run(["tasklist.exe", "/FI", "IMAGENAME eq EliteDangerous64.exe", "/FO", "CSV", "/NH"],
                            capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return any(row and row[0].casefold() == "elitedangerous64.exe" for row in csv.reader(result.stdout.splitlines()))


def profile_path(config_dir, explicit=None):
    if explicit:
        path = Path(explicit).resolve()
        if path.is_file() and path.suffix == ".yaml" and not path.name.startswith("."):
            return path
        raise ValueError("Select an existing enabled profile YAML")
    candidates = []
    for name in ("Elite Dangerous", "_Elite Dangerous"):
        for path in (Path(config_dir) / name).glob("*.yaml"):
            if path.name.startswith(".") or path.name.endswith(".template.yaml"):
                continue
            profile = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
            if isinstance(profile, dict) and not profile.get("disabled") and (
                "EliteDangerous" in (profile.get("discoverable_skills") or []) or
                "elite_status" in profile.get("prompts", {}).get("backstory", "")):
                candidates.append(path.resolve())
    if len(candidates) != 1:
        raise ValueError("Select --profile explicitly; found " + str(len(candidates)) + " enabled Elite profiles")
    return candidates[0]


def migrate_profile(profile, receipts, defaults=None):
    updated = deepcopy(profile)
    commands = updated.get("commands", [])
    if not isinstance(commands, list):
        raise ValueError("Resolve inherited commands before installing controls")
    owned = {}
    for receipt in receipts:
        if receipt.get("version") != 1:
            continue
        for command in receipt.get("commands", []):
            owned.setdefault(command["name"], []).append(command_value(command))
    names = {m.replace("_", " ") + " " + phrase for m, cat in ACTIONS.items() for phrase in cat.values()}
    kept = []
    for command in commands:
        name = command["name"]
        if name in owned and command_value(command) in owned[name]:
            continue
        if name in owned or name in names:
            raise ValueError("Control command was edited or has no matching receipt; review it before migration: " + name)
        kept.append(command)
    updated["commands"] = kept
    ensure_routing_property(updated)
    if updated.get("discoverable_skills") is None:
        updated["discoverable_skills"] = deepcopy((defaults or {}).get("discoverable_skills") or [])
    skills = updated["discoverable_skills"]
    if not isinstance(skills, list):
        raise ValueError("Expected a capability list in discoverable_skills")
    if "EliteDangerousControls" not in skills:
        skills.append("EliteDangerousControls")
    for override in updated.get("skills") or []:
        if override.get("module") == "skills.elite_dangerous_controls.main" and override.get("disabled"):
            raise ValueError("Enable the Elite controls skill before installing")
    prompts = updated.setdefault("prompts", {})
    story = prompts.get("backstory", "")
    for old in ("This profile initially has no game-control commands.",
                "Mode-prefixed controls are configured; use execute_command for requested game actions.",
                "Mode-prefixed controls are configured; use their exact activation phrases.",
                "Only execute controls that actually exist as configured Wingman commands.",
                "Use EliteDangerousControls and elite_control for requested game actions. "
                "Pass state on/off when requested, rather than blindly toggling. "
                "Only its confirmed or already-set result establishes success. It speaks its own result. "
                "Never claim a telemetry lookup executed a control. Launch/docking automation is unavailable.",
                "Use exact activation phrases for mode-prefixed controls as configured.",
                "Only execute controls that exist as configured Wingman commands."):
        story = story.replace(old, "")
    if PROMPT not in story:
        story = story.rstrip() + "\n\n" + PROMPT + "\n"
    prompts["backstory"] = story
    return updated


def ensure_routing_property(profile):
    """Idempotent profile migration; preserve an explicit false and other options."""
    skills = profile.setdefault("skills", [])
    if skills is None:
        skills = profile["skills"] = []
    module = "skills.elite_dangerous_controls.main"
    skill = next((s for s in skills if s.get("module") == module), None)
    if skill is None:
        skill = {"module": module, "custom_properties": []}
        skills.append(skill)
    props = skill.setdefault("custom_properties", [])
    if props is None:
        props = skill["custom_properties"] = []
    if not any(p.get("id") == "semantic_routing" for p in props):
        props.append({"id": "semantic_routing", "value": True})


def report(snapshot):
    rows = []
    for mode, catalog in ACTIONS.items():
        for tag, phrase in catalog.items():
            entry = snapshot["available"].get((mode, tag))
            rows.append({"mode": mode, "action": tag, "phrase": phrase,
                         "status": "configured_not_gameplay_verified" if entry else "needs_setup",
                         **(entry or {"reason": snapshot["unavailable"][(mode, tag)]})})
    inventory = []
    for mode, root in snapshot["roots"].items():
        for index, node in enumerate(root):
            relevant = [a for a in CATALOG if a.tag == node.tag and source_mode(a.vehicle, a.tag) == mode]
            if relevant:
                entries = [(a.vehicle, a.tag) for a in relevant]
                ready = all(key in snapshot["available"] for key in entries)
                status = "supported" if ready else "missing_injectable_binding"
                reason = "One discrete press; context checked at execution" if ready else "; ".join(dict.fromkeys(
                    snapshot["unavailable"][key] for key in entries if key in snapshot["unavailable"]))
            else:
                status, reason = "excluded", exclusion(node.tag)
                if any(a.tag == node.tag for a in CATALOG):
                    reason = "Controlled by another selected vehicle/general preset"
            inventory.append({"preset_mode": mode, "index": index, "tag": node.tag,
                              "status": status, "reason": reason})
    return {"revision": snapshot["revision"], "sources": snapshot["sources"], "actions": rows,
            "distinct_action_ids": len({a.id for a in CATALOG}), "vehicle_action_pairs": len(CATALOG),
            "distinct_executable_bindings": len({(source_mode(m, tag), tag) for m, tag in snapshot["available"]}),
            "inventory": inventory}


def shortcut_candidates():
    """Try ordinary keys before modifiers, retaining physical keypad identities."""
    keys = (["Key_Numpad_" + n for n in ("Divide", "Multiply", "Subtract", "Add", "Decimal", "Enter")] +
            ["Key_F" + str(n) for n in range(1, 13)] +
            ["Key_" + x for x in "1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ"] +
            ["Key_Numpad_" + str(n) for n in range(10)] +
            ["Key_" + n for n in ("Insert", "Home", "PageUp", "PageDown", "End", "Delete",
                                  "Minus", "Equals", "LeftBracket", "RightBracket", "BackSlash",
                                  "Semicolon", "Apostrophe", "Comma", "Period", "Slash")])
    families = [("Key_LeftControl", "Key_RightControl"), ("Key_LeftShift", "Key_RightShift"),
                ("Key_LeftAlt", "Key_RightAlt")]
    modifiers = [()] + [(key,) for family in families for key in family]
    modifiers += [pair for i, family in enumerate(families) for other in families[i+1:]
                  for pair in product(family, other)]
    for mods in modifiers:
        for key in keys:
            # Avoid OS close-window and secure-attention combinations.
            if any("Alt" in m for m in mods) and (key == "Key_F4" or
                    (key == "Key_Delete" and any("Control" in m for m in mods))):
                continue
            yield (*mods, key)


def supplement(snapshot, config, choices=None, owned_slots=()):
    """Keep originals intact. Only free slots or explicit per-action choices change."""
    choices = choices or {}
    roots = deepcopy(snapshot["roots"])
    blocked = ptt_keys(config)
    candidates = list(shortcut_candidates())
    changes, conflicts = [], []

    def vehicles(mode, tag):
        return [m for m in ACTIONS if tag in ACTIONS[m] and source_mode(m, tag) == mode]

    def safe(chord, mode, tag, occupied):
        return (not blocked.intersection(chord) and "Key_Escape" not in chord and
                all(not conflicting_tags(roots, m, tag, chord, occupied[m]) for m in vehicles(mode, tag)))

    # Clear only unchanged, receipt-owned unsafe slots. A working player primary
    # may already make an action available, but its unsafe generated secondary
    # still needs removal. Unowned or edited slots are never silently replaced.
    unsafe = []
    occupied = {m: active_chords(roots, m) for m in ACTIONS}
    for mode, tag, slot in sorted(owned_slots):
        binding = roots[mode].find(f"{tag}/{slot}")
        if binding is not None and not safe(chord_of(binding), mode, tag, occupied):
            unsafe.append((mode, tag, slot, binding))
    for mode, tag, slot, binding in unsafe:
        before = ET.tostring(binding, encoding="unicode")
        binding.clear()
        binding.attrib.update(Device="{NoDevice}", Key="")
        changes.append({"mode": mode, "action": tag, "slot": slot, "chord": [], "previous": before})

    processed = set()
    for (mode, tag), reason in snapshot["unavailable"].items():
        mode = source_mode(mode, tag)
        if (mode, tag) in processed:
            continue
        processed.add((mode, tag))
        node = roots[mode].find(tag)
        if node is None:
            # Some built-in presets predate Odyssey actions; use the known
            # catalogue element with empty slots, not a guessed action name.
            node = ET.SubElement(roots[mode], tag)
            ET.SubElement(node, "Primary", Device="{NoDevice}", Key="")
            ET.SubElement(node, "Secondary", Device="{NoDevice}", Key="")
        toggle = node.find("ToggleOn")
        if toggle is not None and toggle.get("Value", "1") != "1":
            conflicts.append({"mode": mode, "action": tag, "reason": reason})
            continue
        occupied = {m: active_chords(roots, m) for m in vehicles(mode, tag)}
        if not choices.get(mode + "." + tag):
            usable = False
            for candidate_slot in ("Primary", "Secondary"):
                try:
                    usable |= safe(chord_of(node.find(candidate_slot)), mode, tag, occupied)
                except ValueError:
                    pass
            if usable:
                continue  # Removing a conflicting generated slot can restore another binding.
        choice = choices.get(mode + "." + tag)
        if choice is not None and choice not in ("Primary", "Secondary"):
            raise ValueError("Slot choices must be Primary or Secondary")
        free = [slot for slot in ("Secondary", "Primary") if node.find(slot) is None or
                node.find(slot).get("Device") in (None, "{NoDevice}") or not node.find(slot).get("Key")]
        slot = choice or (free[0] if free else None)
        if slot is None:
            conflicts.append({"mode": mode, "action": tag, "reason": "Both slots occupied; choose Primary or Secondary in the choices file"})
            continue
        chord = next((c for c in candidates if safe(c, mode, tag, occupied)), None)
        if chord is None:
            conflicts.append({"mode": mode, "action": tag, "reason": "No conflict-free shortcut; free a key in Elite controls and run repair again"})
            continue
        binding = node.find(slot)
        if binding is None:
            binding = ET.SubElement(node, slot)
        before = ET.tostring(binding, encoding="unicode")
        binding.clear()
        binding.attrib.update(Device="Keyboard", Key=chord[-1])
        for key in chord[:-1]:
            ET.SubElement(binding, "Modifier", Device="Keyboard", Key=key)
        # Collapse removal and replacement into one receipt entry.
        removed = next((c for c in changes if (c['mode'], c['action'], c['slot']) == (mode, tag, slot)), None)
        if removed:
            before = removed['previous']
            changes.remove(removed)
        changes.append({"mode": mode, "action": tag, "slot": slot, "chord": chord, "previous": before})
    return roots, changes, conflicts


def named_preset(root, mode, bindings):
    """Reuse identical copies; never overwrite another preset, including a player's edits."""
    root = deepcopy(root)
    root.set("MajorVersion", "4")
    minor = root.get("MinorVersion", "0")
    if not minor.isdigit():
        raise ValueError("Invalid binding minor version")
    root.set("MinorVersion", minor)
    base = PRESET_NAMES[mode]
    for index in range(1, 1000):
        name = base if index == 1 else f"{base} {index}"
        root.set("PresetName", name)
        data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        target = Path(bindings) / f"{name}.4.{minor}.binds"
        versions = list(Path(bindings).glob(name + ".4.*.binds"))
        if not versions or (versions == [target] and target.read_bytes() == data):
            return name, target, data
    raise ValueError("Too many companion preset copies; review the bindings directory")


def stage_target(output, targets, path, data):
    before = read_optional(path)
    filename = str(len(targets)) + "-" + path.name
    (output / filename).write_bytes(data)
    targets.append({"path": str(path), "staged": filename,
                    "before_sha256": digest(before) if before is not None else None,
                    "after_sha256": digest(data)})


def receipt_owned_slots(snapshot, previous_plans):
    """Prove slot ownership from applied, hash-matching staged preset copies."""
    owned, checks, installations, anchors = set(), [], [], {}
    for previous_path in previous_plans:
        previous_path, previous = load_plan(previous_path)
        applied = previous_path.parent / "applied.json"
        if not applied.is_file():
            raise ValueError("An applied installation receipt is required for binding repair")
        checks += [{"path": str(p), "sha256": digest(p.read_bytes())} for p in (previous_path, applied)]
        staged = {}
        for target in previous["targets"]:
            if Path(target["path"]).suffix != ".binds":
                continue
            path = previous_path.parent / target["staged"]
            raw = path.read_bytes()
            if digest(raw) != target["after_sha256"]:
                raise ValueError("Receipt preset was edited; cannot establish binding ownership")
            root = ET.fromstring(raw)
            staged[root.get("PresetName")] = root
            checks.append({"path": str(path), "sha256": digest(raw)})
        installations.append((previous, staged))
        for mode, source in snapshot["sources"].items():
            if (Path(source["file"]).resolve().parent == Path(previous["bindings"]).resolve() and
                    source["preset"] == previous["select_in_game"].get(mode) and source["preset"] in staged):
                anchors.setdefault(mode, []).append(staged[source["preset"]])

    def same_binding(a, b):
        return (a is not None and b is not None and a.attrib == b.attrib and
                [(c.tag, c.attrib) for c in a] == [(c.tag, c.attrib) for c in b])

    for previous, staged in installations:
        for change in previous["changes"]:
            mode, tag, slot = change["mode"], change["action"], change["slot"]
            if mode not in snapshot["sources"] or slot not in ("Primary", "Secondary"):
                continue
            source = snapshot["sources"][mode]
            if Path(source["file"]).resolve().parent != Path(previous["bindings"]).resolve():
                continue
            original = staged.get(previous["select_in_game"].get(mode))
            if original is None:
                continue
            saved, current = original.find(f"{tag}/{slot}"), snapshot["roots"][mode].find(f"{tag}/{slot}")
            try:
                # Comparing the parsed binding also tolerates Elite reformatting XML.
                if (same_binding(saved, current) and
                        any(same_binding(anchor.find(f"{tag}/{slot}"), current) for anchor in anchors.get(mode, [])) and
                        chord_of(current) == tuple(change["chord"])):
                    owned.add((mode, tag, slot))
            except ValueError:
                pass
    return owned, checks


def prepare(profile, bindings, presets, output, choices=None, select_presets=False, repair_from=()):
    profile, bindings, presets, output = (Path(p).resolve() for p in (profile, bindings, presets, output))
    raw = profile.read_bytes()
    config = yaml.safe_load(raw.decode("utf-8-sig"))
    if not isinstance(config, dict) or config.get("disabled"):
        raise ValueError("Select an enabled profile")
    defaults_path = profile.parent.parent / "defaults.yaml"
    defaults_raw = read_optional(defaults_path)
    defaults = yaml.safe_load(defaults_raw.decode("utf-8-sig")) if defaults_raw else {}
    if not isinstance(defaults, dict):
        raise ValueError("Expected Core defaults mapping")
    resolver = BindingResolver(bindings, presets, config)
    snapshot = resolver.read()
    receipts = []
    receipt_sources = []
    for path in profile.parent.glob("*.elite-controls.json"):
        receipt_raw = path.read_bytes()
        receipts.append(json.loads(receipt_raw))
        receipt_sources.append({"path": str(path), "sha256": digest(receipt_raw)})
    migrated = migrate_profile(config, receipts, defaults)
    owned, ownership_checks = receipt_owned_slots(snapshot, repair_from)
    roots, changes, conflicts = supplement(snapshot, config, choices, owned)
    output.mkdir(parents=True, exist_ok=False)
    targets = []
    def target(path, data):
        stage_target(output, targets, path, data)
    # A binding-only repair must preserve the player's profile byte for byte.
    target(profile, raw if repair_from else yaml.safe_dump(migrated, sort_keys=False, allow_unicode=True).encode())
    selections = {}
    for mode in MODES:
        if not any(c["mode"] == mode for c in changes):
            continue
        name, path, data = named_preset(roots[mode], mode, bindings)
        target(path, data)
        selections[mode] = name
    if select_presets and selections:
        selected = [selections.get(mode, snapshot["sources"][mode]["preset"]) for mode in MODES]
        target(bindings / "StartPreset.4.start", ("\n".join(selected) + "\n").encode())
    checks = [{"path": str(bindings / "StartPreset.4.start"), "sha256": snapshot["selector_sha256"]}]
    checks += [{"path": s["file"], "sha256": s["sha256"]} for s in snapshot["sources"].values()]
    checks += receipt_sources
    checks += ownership_checks
    if defaults_raw is not None:
        checks.append({"path": str(defaults_path), "sha256": digest(defaults_raw)})
    plan = {"kind": "elite-verified-controls", "version": 3 if select_presets else 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "profile": str(profile), "bindings": str(bindings), "presets": str(presets), "targets": targets,
            "inputs": checks, "select_in_game": selections, "changes": changes, "conflicts": conflicts,
            "gameplay_verified": False}
    (output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    (output / "readiness.json").write_text(json.dumps(report(snapshot), indent=2), encoding="utf-8")
    lines = ["# Elite controls setup", "", "Apply while Elite is closed. Then reload the Wingman profile.",
             "Select these presets in Elite's corresponding Controls sections (other sections stay as selected):", ""]
    lines += [f"- {mode}: {name}" for mode, name in selections.items()]
    lines += ["", "| Mode | Action | Companion shortcut |", "| --- | --- | --- |"]
    lines += [f"| {c['mode']} | {c['action']} | {' + '.join(c['chord']) or 'Unsafe generated slot cleared'} |" for c in changes]
    lines += ["", "## Choices still needed", ""]
    lines += [f"- {c['mode']}.{c['action']}: {c['reason']}" for c in conflicts]
    lines += ["", "Configured bindings are not evidence of live gameplay delivery. No input was sent during setup.",
              "A changed/unsupported binding is blocked instead of being guessed. Ask for controls status."]
    (output / "REVIEW.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return plan


def prepare_preset_names(previous_plan, output):
    """Rename selected receipt-owned copies, preserving game edits and original files."""
    previous_path, previous = load_plan(previous_plan)
    if not (previous_path.parent / "applied.json").is_file():
        raise ValueError("An applied installation receipt is required")
    bindings, presets, profile = (Path(previous[k]).resolve() for k in ("bindings", "presets", "profile"))
    profile_raw = profile.read_bytes()
    snapshot = BindingResolver(bindings, presets, yaml.safe_load(profile_raw)).read()
    selector = bindings / "StartPreset.4.start"
    selected = selector.read_text(encoding="utf-8-sig").splitlines()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    targets, selections = [], {}
    stage_target(output, targets, profile, profile_raw)
    owned = {Path(t["path"]).resolve() for t in previous["targets"] if Path(t["path"]).suffix == ".binds"}
    for mode in ACTIONS:
        source = snapshot["sources"][mode]
        # Elite may save a newer minor-version file for the same installed
        # preset. Read that active file, rather than restoring stale staged XML.
        owned_series = any(p.parent == bindings and re.fullmatch(
            re.escape(source["preset"]) + r"\.4\.\d+\.binds", p.name) for p in owned)
        if (source["preset"] != previous["select_in_game"].get(mode)
                or Path(source["file"]).resolve().parent != bindings or not owned_series):
            continue
        if source["preset"] == PRESET_NAMES[mode] or source["preset"].startswith(PRESET_NAMES[mode] + " "):
            continue
        name, target, data = named_preset(snapshot["roots"][mode], mode, bindings)
        stage_target(output, targets, target, data)
        selected[MODES.index(mode)] = name
        selections[mode] = name
    if selections:
        stage_target(output, targets, selector, ("\n".join(selected) + "\n").encode("utf-8"))
    checks = [{"path": str(selector), "sha256": snapshot["selector_sha256"]},
              {"path": str(previous_path), "sha256": digest(previous_path.read_bytes())}]
    checks += [{"path": s["file"], "sha256": s["sha256"]} for s in snapshot["sources"].values()]
    plan = {"kind": "elite-verified-controls", "version": 2,
            "created_at": datetime.now(timezone.utc).isoformat(), "profile": str(profile),
            "bindings": str(bindings), "presets": str(presets), "targets": targets,
            "inputs": checks, "select_in_game": selections, "changes": [], "conflicts": [],
            "gameplay_verified": False}
    (output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    lines = ["# Friendly preset names", "", "Apply with Elite closed. Matching selections are updated automatically.",
             "Current game edits and all original preset files are preserved. Restore uses the backed-up selector.", ""]
    lines += [f"- {mode}: {name}" for mode, name in selections.items()]
    (output / "REVIEW.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return plan


def load_plan(path):
    path = Path(path).resolve()
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("kind") != "elite-verified-controls" or plan.get("version") not in (1, 2, 3):
        raise ValueError("Unsupported controls plan")
    targets = plan["targets"]
    if not targets or len(targets) > (6 if plan["version"] in (2, 3) else 5) or len({Path(t["path"]).resolve() for t in targets}) != len(targets):
        raise ValueError("Invalid controls targets")
    for index, entry in enumerate(targets):
        target, staged = Path(entry["path"]).resolve(), (path.parent / entry["staged"]).resolve()
        if staged.parent != path.parent or staged == target:
            raise ValueError("Invalid staged path")
        if index == 0:
            if target != Path(plan["profile"]).resolve() or target.suffix != ".yaml":
                raise ValueError("Invalid profile target")
        elif plan["version"] in (2, 3) and index == len(targets) - 1 and target == Path(plan["bindings"]).resolve() / "StartPreset.4.start":
            pass
        elif target.parent != Path(plan["bindings"]).resolve() or not target.name.startswith("Wingman ") or target.suffix != ".binds":
            raise ValueError("Invalid preset target")
    return path, plan


def apply_plan(path):
    path, plan = load_plan(path)
    if game_running():
        raise ValueError("Close Elite before installing preset copies; the game can overwrite controls while running")
    if (path.parent / "applied.json").exists():
        raise ValueError("Already applied; prepare a new repair plan")
    for entry in plan["inputs"]:
        if digest(Path(entry["path"]).read_bytes()) != entry["sha256"]:
            raise ValueError("Source bindings or receipts changed; prepare again")
    writes = []
    for entry in plan["targets"]:
        target = Path(entry["path"]).resolve()
        before, after = read_optional(target), (path.parent / entry["staged"]).read_bytes()
        if (digest(before) if before is not None else None) != entry["before_sha256"] or digest(after) != entry["after_sha256"]:
            raise ValueError("Profile, preset or staged data changed; prepare again")
        writes.append((target, before, after))
    backup = path.parent / "backup"
    backup.mkdir(exist_ok=False)
    changed = []
    for i, (_, before, _) in enumerate(writes):
        if before is not None:
            (backup / str(i)).write_bytes(before)
    try:
        for target, before, after in writes:
            if read_optional(target) != before:
                raise ValueError("Configuration changed during apply")
            if before != after:
                atomic_write(target, after)
                changed.append((target, before, after))
    except Exception:
        for target, before, after in reversed(changed):
            if read_optional(target) == after:
                if before is None:
                    target.unlink()
                else:
                    atomic_write(target, before)
        raise
    result = {"changed_files": len(changed), "gameplay_verified": False, "core_restarted": False,
              "select_in_game": plan["select_in_game"], "conflicts": plan["conflicts"]}
    (path.parent / "applied.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def restore(path):
    path, plan = load_plan(path)
    if game_running():
        raise ValueError("Close Elite before restoring")
    if not (path.parent / "applied.json").exists():
        raise ValueError("Plan was not applied")
    names = (Path(plan["bindings"]) / "StartPreset.4.start").read_text(encoding="utf-8-sig").splitlines()
    if plan["version"] == 1 and set(names) & set(plan["select_in_game"].values()):
        raise ValueError("Select your original presets in Elite, exit the game, then restore")
    if plan["version"] in (2, 3):
        # The restored selector must still refer to the same saved source presets.
        for entry in plan["inputs"]:
            if Path(entry["path"]).suffix == ".binds" and digest(Path(entry["path"]).read_bytes()) != entry["sha256"]:
                raise ValueError("Original preset changed; review it before restoring the old selection")
    writes = []
    for i, entry in enumerate(plan["targets"]):
        target = Path(entry["path"]).resolve()
        current = read_optional(target)
        if current is None or digest(current) != entry["after_sha256"]:
            raise ValueError("User edits detected; automatic restore stopped without changing files")
        before = read_optional(path.parent / "backup" / str(i))
        if (digest(before) if before is not None else None) != entry["before_sha256"]:
            raise ValueError("Backup does not match original")
        writes.append((target, before, current))
    changed = []
    try:
        for target, before, current in reversed(writes):
            if read_optional(target) != current:
                raise ValueError("Configuration changed during restore")
            if before is None:
                target.unlink()
            else:
                atomic_write(target, before)
            changed.append((target, before, current))
    except Exception:
        for target, before, current in reversed(changed):
            if read_optional(target) == before:
                atomic_write(target, current)
        raise
    return {"restored_files": len(writes)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    for name in ("inspect", "prepare", "repair"):
        sub = subs.add_parser(name)
        sub.add_argument("--profile", type=Path)
        sub.add_argument("--config-dir", type=Path, default=Path(os.environ.get("APPDATA", Path.home())) / "ShipBit/WingmanAI/2_1_1/configs")
        sub.add_argument("--bindings", type=Path, default=default_bindings())
        sub.add_argument("--presets", type=Path, required=True)
        sub.add_argument("--output", type=Path, required=True)
        if name != "inspect":
            sub.add_argument("--choices", type=Path, help='JSON mapping, e.g. {"ship.NightVisionToggle":"Secondary"}')
            sub.add_argument("--select-presets", action="store_true", help="Stage selector changes too; apply only with Elite closed")
            sub.add_argument("--repair-from", type=Path, action="append", default=[],
                             help="Applied plan proving ownership of generated slots; repeat for multiple installations")
    for name in ("apply", "restore"):
        subs.add_parser(name).add_argument("--plan", required=True, type=Path)
    names = subs.add_parser("rename-presets", help="Stage friendly names for selected receipt-owned presets")
    names.add_argument("--plan", required=True, type=Path)
    names.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.action == "rename-presets":
            result = prepare_preset_names(args.plan, args.output)
        elif args.action in ("apply", "restore"):
            result = apply_plan(args.plan) if args.action == "apply" else restore(args.plan)
        else:
            profile = profile_path(args.config_dir, args.profile)
            if args.action == "inspect":
                config = yaml.safe_load(profile.read_text(encoding="utf-8-sig"))
                result = report(BindingResolver(args.bindings, args.presets, config).read())
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            else:
                choices = json.loads(args.choices.read_text(encoding="utf-8")) if args.choices else None
                result = prepare(profile, args.bindings, args.presets, args.output, choices, args.select_presets, args.repair_from)
        Printr().print(json.dumps(result, indent=2), server_only=True)
    except (OSError, ValueError, ET.ParseError, subprocess.SubprocessError) as exc:
        Printr().print("Elite controls setup failed: " + str(exc), server_only=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
