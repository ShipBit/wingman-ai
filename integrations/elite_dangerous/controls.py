"""Stage/apply verified bindings to a native Wingman profile, without sending input.

Run from the checkout with python -m integrations.elite_dangerous.controls.
Generated profiles, backups and reports are private local artifacts.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

import yaml

from api.interface import CommandConfig
from integrations.elite_dangerous.bindings import generate, stage


def digest(raw):
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def read_optional(path):
    return path.read_bytes() if path.exists() else None


def command_value(command):
    # Core/client saves may materialize defaults without changing a command.
    return CommandConfig.model_validate(command).model_dump(mode="json")


def tokens(command):
    return {value.strip().casefold() for value in
            [command["name"], *(command.get("instant_activation") or [])]}


def merge_commands(profile, generated, previous):
    merged = deepcopy(profile)
    commands = merged.get("commands")
    if not isinstance(commands, list):
        raise ValueError("Profile must declare an explicit commands list; inherited commands need review")
    old = {command["name"]: command for command in previous}
    if len(old) != len(previous):
        raise ValueError("Duplicate commands in installation receipt")
    kept, managed, reused = [], [], []
    for command in commands:
        command_value(command)
        if command["name"] in old:
            if command_value(command) != command_value(old[command["name"]]):
                raise ValueError(f"Previously installed command was edited: {command['name']}")
        else:
            kept.append(command)
    for command in generated:
        command_value(command)
        overlaps = [existing for existing in kept if tokens(command) & tokens(existing)]
        if overlaps:
            if len(overlaps) == 1 and command_value(overlaps[0]) == command_value(command):
                reused.append(command["name"])
                continue
            # A client rename/copy can leave the old installation receipt behind.
            # Adopt only an exact match to our previous generated representation;
            # preserve the usual conflict check for any edited actions or context.
            legacy = {**command, "force_instant_activation": True,
                      "instant_activation": [command["name"]]}
            if len(overlaps) == 1 and command_value(overlaps[0]) == command_value(legacy):
                kept.remove(overlaps[0])
            else:
                raise ValueError(f"Command name or activation phrase conflicts: {command['name']}")
        kept.append(command)
        managed.append(command)
    merged["commands"] = kept
    prompts = merged.get("prompts", {})
    if isinstance(prompts.get("backstory"), str) and generated:
        for old in ("This profile initially has no game-control commands.",
                    "Mode-prefixed controls are configured; use their exact activation phrases."):
            prompts["backstory"] = prompts["backstory"].replace(
                old, "Mode-prefixed controls are configured; use execute_command for requested game actions.")
    return merged, managed, reused


def prepare(profile_path, bindings, presets, output):
    profile_path, output = Path(profile_path).resolve(), Path(output).resolve()
    receipt_path = profile_path.with_suffix(".elite-controls.json")
    original = profile_path.read_bytes()
    profile = yaml.safe_load(original.decode("utf-8-sig"))
    if not isinstance(profile, dict):
        raise ValueError("Expected a Wingman profile mapping")
    # Numeric scan codes take precedence over record_key in Wingman. Do not
    # pretend its display text establishes the effective OS-specific chord.
    if profile.get("record_key_codes"):
        raise ValueError("Scan-code push-to-talk needs conflict verification; use the manual command review path")
    key = profile.get("record_key") or ""
    if not isinstance(key, str) or "+" in key or "," in key:
        raise ValueError("Only a single named keyboard push-to-talk key can be checked automatically")
    result = generate(bindings, presets, record_key=key)
    mouse = profile.get("record_mouse_button")
    if mouse:
        blocked = {c["name"] for c in result["commands"] if any(
            a.get("mouse", {}).get("button") == mouse for a in c["actions"])}
        for row in result["mappings"]:
            if row["phrase"] in blocked:
                result["skipped"].append({"mode": row["mode"], "action": row["action"],
                                          "reason": "Conflicts with Companion mouse push-to-talk"})
        result["commands"] = [c for c in result["commands"] if c["name"] not in blocked]
        result["mappings"] = [r for r in result["mappings"] if r["phrase"] not in blocked]
    receipt_raw = read_optional(receipt_path)
    previous = json.loads(receipt_raw) if receipt_raw else {"version": 1, "commands": []}
    if previous.get("version") != 1:
        raise ValueError("Unsupported controls receipt version")
    merged, managed, reused = merge_commands(profile, result["commands"], previous["commands"])
    receipt = {"version": 1, "commands": managed, "sources": result["sources"],
               "selector_sha256": result["selector_sha256"], "status": "installed_not_gameplay_verified"}
    inputs = [{"path": str(Path(bindings).resolve() / "StartPreset.4.start"), "sha256": result["selector_sha256"]}]
    inputs.extend({"path": source["file"], "sha256": source["sha256"]} for source in result["sources"].values())
    # Refuse reuse: a second preparation gets its own review/backup directory.
    output.mkdir(parents=True, exist_ok=False)
    stage(result, output)
    targets = []
    for target, before, name, data in (
        (profile_path, original, "Companion.staged.yaml", yaml.safe_dump(merged, sort_keys=False, allow_unicode=True).encode("utf-8")),
        (receipt_path, receipt_raw, "controls-receipt.json", json.dumps(receipt, indent=2).encode("utf-8")),
    ):
        staged = output / name
        staged.write_bytes(data)
        targets.append({"path": str(target), "before_sha256": digest(before), "staged": name, "after_sha256": digest(data)})
    plan = {"version": 1, "created_at": datetime.now(timezone.utc).isoformat(), "targets": targets,
            "binding_directories": {"bindings": str(Path(bindings).resolve()), "presets": str(Path(presets).resolve())},
            "inputs": inputs, "commands": len(result["commands"]), "unavailable": len(result["skipped"]),
            "reused_existing": reused, "core_restarted": False, "gameplay_verified": False}
    (output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return plan


def atomic_write(path, data):
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def apply_plan(plan_path):
    plan_path = Path(plan_path).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("version") != 1 or len(plan.get("targets", [])) != 2:
        raise ValueError("Unsupported controls installation plan")
    if (plan_path.parent / "applied.json").exists():
        raise ValueError("This plan was already applied; prepare a new plan to update controls")
    directories = plan["binding_directories"]
    active = generate(directories["bindings"], directories["presets"])
    selected = {(source["file"], source["sha256"]) for source in active["sources"].values()}
    expected = {(source["path"], source["sha256"]) for source in plan["inputs"][1:]}
    if selected != expected:
        raise ValueError("Active bindings changed after staging; prepare a new plan")
    for source in plan["inputs"]:
        if digest(Path(source["path"]).read_bytes()) != source["sha256"]:
            raise ValueError("Active bindings changed after staging; prepare a new plan")
    writes = []
    for entry in plan["targets"]:
        path = Path(entry["path"]).resolve()
        staged = (plan_path.parent / entry["staged"]).resolve()
        if staged.parent != plan_path.parent or staged == path:
            raise ValueError("Invalid staging path")
        before, after = read_optional(path), staged.read_bytes()
        if digest(before) != entry["before_sha256"]:
            raise ValueError("Profile or installation receipt changed after staging; prepare a new plan")
        if digest(after) != entry["after_sha256"]:
            raise ValueError("Staged files changed; prepare a new plan")
        writes.append((path, before, after))
    if writes[0][0] == writes[1][0]:
        raise ValueError("Installation targets must be distinct")
    backup = plan_path.parent / "backup"
    backup.mkdir(exist_ok=False)
    for index, (path, before, _) in enumerate(writes):
        if before is not None:
            (backup / f"{index}-{path.name}").write_bytes(before)
    changed = []
    try:
        for path, before, after in writes:
            if read_optional(path) != before:
                raise ValueError("Configuration changed during apply")
            if before != after:
                atomic_write(path, after)
                changed.append((path, before, after))
    except Exception:
        # Roll back only bytes still owned by this operation; preserve later edits.
        for path, before, after in reversed(changed):
            if read_optional(path) == after:
                if before is None:
                    path.unlink()
                else:
                    atomic_write(path, before)
        raise
    report = {"applied_at": datetime.now(timezone.utc).isoformat(), "commands": plan["commands"],
              "backup": str(backup), "core_restarted": False, "gameplay_verified": False,
              "next_step": "Reload the Elite Dangerous profile in the client, then verify commands in-game."}
    (plan_path.parent / "applied.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    preparing = actions.add_parser("prepare")
    for name in ("profile", "bindings", "presets", "output"):
        preparing.add_argument("--" + name, required=True, type=Path)
    applying = actions.add_parser("apply")
    applying.add_argument("--plan", required=True, type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.profile, args.bindings, args.presets, args.output)
    else:
        apply_plan(args.plan)


if __name__ == "__main__":
    main()
