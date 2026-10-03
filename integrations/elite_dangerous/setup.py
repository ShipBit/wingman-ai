"""Prepare/apply native profile and MCP settings for this source checkout.

Does not start Core, install dependencies, sign in, or send game input.
Run with python -m integrations.elite_dangerous.setup.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

import yaml

from api.interface import McpConfig
from integrations.elite_dangerous.controls import atomic_write, digest, read_optional


ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIRS = ("Elite Dangerous", "_Elite Dangerous")


def mapping(raw, label):
    value = yaml.safe_load(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a YAML mapping in {label}")
    return value


def profile_directory(config_dir):
    found = [config_dir / name for name in PROFILE_DIRS if (config_dir / name).exists()]
    if len(found) > 1:
        raise ValueError("Both normal and default Elite configuration directories exist; resolve the duplicate first")
    if not found and (config_dir / ".Elite Dangerous").exists():
        raise ValueError("Elite configuration is logically deleted; restore it in the client first")
    directory = found[0] if found else config_dir / PROFILE_DIRS[0]
    if not directory.resolve().is_relative_to(config_dir):
        raise ValueError("Elite configuration directory resolves outside the specified config root")
    if (directory / ".Companion.yaml").exists() and selected_profile_path(directory) == directory / "Companion.yaml":
        raise ValueError("Companion is logically deleted; restore or resolve it in the client first")
    return directory


def append_unique(config, field, additions):
    values = config.get(field, [])
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError(f"Expected a list of capability names in {field}")
    config[field] = values + [value for value in additions if value not in values]


def selected_profile_path(directory):
    conventional = directory / "Companion.yaml"
    if conventional.exists():
        return conventional
    candidates = []
    for path in directory.glob("*.yaml"):
        if path.name.startswith(".") or path.name.endswith(".template.yaml"):
            continue
        config = mapping(path.read_bytes(), path.name)
        if "EliteDangerous" in (config.get("discoverable_skills") or []) or "elite_status" in config.get("prompts", {}).get("backstory", ""):
            candidates.append(path)
    if len(candidates) > 1:
        raise ValueError("Multiple Elite profiles found; use explicit-profile controls setup and resolve source setup selection")
    return candidates[0] if candidates else conventional


def merge_profile(original, template, defaults, allow_renamed=False):
    profile = deepcopy(original if original is not None else template)
    if profile.get("name", "Companion") != "Companion" and not allow_renamed:
        raise ValueError("Companion.yaml belongs to a differently named Wingman")
    if profile.get("disabled") is True:
        raise ValueError("Companion is disabled; enable it in the client before setup")
    profile.setdefault("name", "Companion")
    if original is not None and "discoverable_mcps" not in original:
        profile["discoverable_mcps"] = deepcopy(defaults.get("discoverable_mcps", []))
    append_unique(profile, "discoverable_skills", ["EliteDangerous", "EliteDangerousControls"])
    append_unique(profile, "discoverable_mcps", template["discoverable_mcps"])
    # Existing prompts, commands, skill overrides and providers belong to the user.
    return profile


def merge_mcp(original, example, interpreter, cache_dir):
    config = deepcopy(original)
    servers = config.get("servers", [])
    if not isinstance(servers, list) or not all(isinstance(server, dict) for server in servers):
        raise ValueError("Expected MCP servers list")
    names = [server.get("name") for server in servers]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate MCP server names must be resolved before setup")
    matches = [server for server in servers if server.get("name") == "elite_public_data"]
    server = matches[0] if matches else deepcopy(example)
    if matches and (server.get("type") != "stdio" or server.get("url")):
        raise ValueError("elite_public_data is configured as a remote server; resolve the name conflict first")
    if matches:
        args = server.get("args") or []
        # A shared name alone is insufficient to replace a different executable.
        if not isinstance(args, list) or not args or Path(args[0]).name != "server.py" or "elite_dangerous" not in Path(args[0]).parts:
            raise ValueError("elite_public_data is not recognisable as this integration; resolve the name conflict first")
    for key in ("display_name", "description", "discovery_keywords"):
        server[key] = deepcopy(example[key])
    def path_value(previous, desired):
        if isinstance(previous, str) and os.path.normcase(os.path.abspath(previous)) == os.path.normcase(os.path.abspath(desired)):
            return previous  # Equivalent slash/case spelling does not need a rewrite.
        return str(desired)

    old_args = server.get("args") or []
    script = ROOT / "integrations/elite_dangerous/server.py"
    args = [str(script), "--cache-dir", str(cache_dir)]
    if len(old_args) == 3 and old_args[1] == "--cache-dir":
        args = [path_value(old_args[0], script), "--cache-dir", path_value(old_args[2], cache_dir)]
    server.update(type="stdio", command=path_value(server.get("command"), interpreter), args=args)
    # Keep explicit user timeout/discovery/env/header settings. Defaults apply to new servers.
    if not matches:
        servers.append(server)
    config["servers"] = servers
    McpConfig.model_validate(config)
    return config


def source_inputs(config_dir, interpreter):
    paths = [config_dir / "defaults.yaml", interpreter,
             ROOT / "templates/configs/Elite Dangerous/Companion.template.yaml",
             ROOT / "integrations/elite_dangerous/mcp.example.yaml",
             ROOT / "integrations/elite_dangerous/requirements.txt"]
    paths.extend(sorted((ROOT / "integrations/elite_dangerous").glob("*.py")))
    paths.extend(ROOT / "skills/elite_dangerous" / name for name in
                 ("main.py", "telemetry.py", "default_config.yaml", "logo.png"))
    paths.extend(ROOT / "skills/elite_dangerous_controls" / name for name in
                 ("__init__.py", "main.py", "input.py", "runtime.py", "bindings.py", "result.py", "observation.py", "speech.py", "workflows.py", "default_config.yaml", "logo.png"))
    return [{"path": str(path.resolve()), "sha256": digest(path.read_bytes())} for path in paths]


def prepare(config_dir, interpreter, cache_dir, output):
    config_dir, cache_dir, output = (Path(p).resolve() for p in (config_dir, cache_dir, output))
    # Unix virtualenv Python is often a symlink; resolving it would bypass the venv.
    interpreter = Path(os.path.abspath(Path(interpreter).expanduser()))
    if not config_dir.is_dir() or not interpreter.is_file():
        raise ValueError("Supply an existing Core config directory and MCP Python interpreter")
    if output.is_relative_to(config_dir):
        raise ValueError("Keep staged setup files outside Core's configuration directory")
    inputs = source_inputs(config_dir, interpreter)
    defaults = mapping((config_dir / "defaults.yaml").read_bytes(), "defaults.yaml")
    if not isinstance(defaults.get("prompts"), dict):
        raise ValueError("Core defaults must already be initialized")
    directory = profile_directory(config_dir)
    profile_path, mcp_path = selected_profile_path(directory), config_dir / "mcp.yaml"
    for target in (profile_path, mcp_path):
        if not target.resolve().is_relative_to(config_dir):
            raise ValueError("Configuration target resolves outside the specified config root")
    profile_raw, mcp_raw = read_optional(profile_path), read_optional(mcp_path)
    template = mapping((ROOT / "templates/configs/Elite Dangerous/Companion.template.yaml").read_bytes(), "profile template")
    example = mapping((ROOT / "integrations/elite_dangerous/mcp.example.yaml").read_bytes(), "MCP example")["servers"][0]
    original_profile = mapping(profile_raw, "Companion.yaml") if profile_raw is not None else None
    original_mcp = mapping(mcp_raw, "mcp.yaml") if mcp_raw is not None else {"servers": []}
    profile = merge_profile(original_profile, template, defaults, allow_renamed=profile_path.name != "Companion.yaml")
    mcp = merge_mcp(original_mcp, example, interpreter, cache_dir)
    if source_inputs(config_dir, interpreter) != inputs:
        raise ValueError("Source or defaults changed during preparation; retry with stable inputs")
    output.mkdir(parents=True, exist_ok=False)
    targets = []
    for target, before, old_value, value, filename in (
        (profile_path, profile_raw, original_profile, profile, "Companion.staged.yaml"),
        (mcp_path, mcp_raw, original_mcp, mcp, "mcp.staged.yaml"),
    ):
        # Preserve original formatting and bytes when no semantic change is needed.
        after = before if before is not None and old_value == value else yaml.safe_dump(value, sort_keys=False, allow_unicode=True).encode("utf-8")
        (output / filename).write_bytes(after)
        targets.append({"relative_path": str(target.relative_to(config_dir)), "staged": filename,
                        "before_sha256": digest(before), "after_sha256": digest(after)})
    plan = {"kind": "elite-source-setup", "version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "config_dir": str(config_dir), "checkout": str(ROOT.resolve()), "python": str(interpreter),
            "cache_dir": str(cache_dir), "inputs": inputs, "targets": targets,
            "changed_files": sum(t["before_sha256"] != t["after_sha256"] for t in targets),
            "existing_profile_preserved": original_profile is not None,
            "core_restarted": False, "dependencies_verified": False, "gameplay_verified": False}
    (output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    (output / "REVIEW.md").write_text(
        "# Elite source setup\n\nReview Companion.staged.yaml and mcp.staged.yaml. "
        "Existing profile prompts, controls and provider settings are preserved; new profiles inherit Core defaults. "
        "The Elite MCP command and reference metadata point to this checkout. Other servers are preserved.\n\n"
        "Apply with python -m integrations.elite_dangerous.setup apply --plan <this-directory>/plan.json. "
        "Load changed files at your next user-initiated Core startup, then select the Elite profile in the client. "
        "This operation does not start/restart Core, install dependencies, copy release skills, sign in or verify gameplay.\n",
        encoding="utf-8")
    return plan


def apply_plan(plan_path):
    plan_path = Path(plan_path).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("kind") != "elite-source-setup" or plan.get("version") != 1:
        raise ValueError("Unsupported Elite setup plan")
    if (plan_path.parent / "applied.json").exists():
        raise ValueError("Setup plan already applied; prepare a new plan")
    if Path(plan["checkout"]).resolve() != ROOT.resolve():
        raise ValueError("Checkout moved after preparation; prepare a new plan")
    config_dir = Path(plan["config_dir"]).resolve()
    directory = profile_directory(config_dir)
    expected = [selected_profile_path(directory), config_dir / "mcp.yaml"]
    if source_inputs(config_dir, Path(plan["python"])) != plan["inputs"]:
        raise ValueError("Source, defaults or interpreter changed after preparation; prepare a new plan")
    targets = plan.get("targets", [])
    if len(targets) != len(expected):
        raise ValueError("Unexpected setup targets")
    writes = []
    for entry, target in zip(targets, expected):
        path = (config_dir / entry["relative_path"]).resolve()
        staged = (plan_path.parent / entry["staged"]).resolve()
        if path != target.resolve() or not path.is_relative_to(config_dir) or staged.parent != plan_path.parent or staged == path:
            raise ValueError("Setup target or staging path changed")
        before, after = read_optional(path), staged.read_bytes()
        if digest(before) != entry["before_sha256"] or digest(after) != entry["after_sha256"]:
            raise ValueError("Configuration or staged bytes changed; prepare a new plan")
        writes.append((path, before, after))
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
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(path, after)
                changed.append((path, before, after))
    except Exception:
        for path, before, after in reversed(changed):
            if read_optional(path) == after:
                if before is None:
                    path.unlink()
                else:
                    atomic_write(path, before)
        raise
    report = {"applied_at": datetime.now(timezone.utc).isoformat(), "changed_files": len(changed),
              "backup": str(backup), "core_restarted": False, "gameplay_verified": False,
              "next_step": "Load changed files at your next user-initiated Core startup, then select the Elite profile."}
    (plan_path.parent / "applied.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    staging = actions.add_parser("prepare")
    for name in ("config-dir", "cache-dir", "output"):
        staging.add_argument("--" + name, required=True, type=Path)
    staging.add_argument("--python", type=Path, default=Path(sys.executable))
    applying = actions.add_parser("apply")
    applying.add_argument("--plan", required=True, type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.config_dir, args.python, args.cache_dir, args.output)
    else:
        apply_plan(args.plan)


if __name__ == "__main__":
    main()
