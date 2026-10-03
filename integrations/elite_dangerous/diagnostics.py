"""Read-only Elite preflight. Writes a metadata report, never sends game input.

No sign-in simulation, model calls, credential dumps or Core restarts. Run from
the checkout with python -m integrations.elite_dangerous.diagnostics.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlencode

import requests
import yaml

from integrations.elite_dangerous.bindings import generate
from integrations.elite_dangerous.controls import command_value
from skills.elite_dangerous.telemetry import JournalReader, default_journal_dir
from skills.elite_dangerous_controls.runtime import ACTIONS, BindingResolver


class LocalCore:
    def __init__(self, port=49111):
        if not 1 <= port <= 65535:
            raise ValueError("Invalid local Core port")
        self.base = f"http://127.0.0.1:{port}"
        self.session = requests.Session()
        self.session.trust_env = False

    def get(self, path):
        with self.session.get(self.base + path, timeout=5, stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                raise ValueError("Core endpoint unavailable")
            raw = bytearray()
            for chunk in response.iter_content(65536):
                raw.extend(chunk)
                # Skill listings embed all base64 icons (currently about 4.7 MB).
                # The report retains only availability flags, never these assets.
                if len(raw) > 16 * 1024 * 1024:
                    raise ValueError("Core response exceeds diagnostic limit")
            return json.loads(raw)

    def close(self):
        self.session.close()


def collect(profile_path, bindings, presets, journal, get):
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Configuration and observation checks only; no voice, provider conversation or input execution test.",
        "checks": {}, "issues": [],
        "manual_acceptance": ["Client connected to source Core", "Subscriber/provider authentication",
                              "Fresh-context skill and MCP discovery", "Microphone transcription and audible response",
                              "Fresh journal narration during gameplay", "Input delivery in each vehicle mode"],
    }
    checks = report["checks"]

    def query(path):
        try:
            return get(path)
        except (OSError, ValueError, requests.RequestException):
            # Exception text and endpoint payloads can contain private config.
            report["issues"].append("Core read failed: " + path.split("?")[0])
            return None

    profile_path = Path(profile_path)
    try:
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8-sig"))
        if not isinstance(profile, dict):
            raise ValueError("Expected profile mapping")
        checks["profile_readable"] = True
        commands = profile.get("commands")
        if not isinstance(commands, list):
            raise ValueError("Expected explicit command list")
        configured = [command_value(c) for c in commands]
        checks["configured_command_count"] = len(configured)
        verified = "EliteDangerousControls" in (profile.get("discoverable_skills") or [])
        if not verified and (profile.get("record_key_codes") or not isinstance(profile.get("record_key", ""), (str, type(None)))):
            raise ValueError("Push-to-talk needs manual conflict review")
        key = profile.get("record_key") or ""
        if not verified and ("+" in key or "," in key):
            raise ValueError("Push-to-talk needs manual conflict review")
        generated = generate(bindings, presets, record_key=key)
        mouse = profile.get("record_mouse_button")
        expected = [command_value(c) for c in generated["commands"] if not mouse or not any(
            a.get("mouse", {}).get("button") == mouse for a in c["actions"])]
        checks["supported_binding_count"] = len(expected)
        checks["unavailable_binding_count"] = len(generated["skipped"]) + len(generated["commands"]) - len(expected)
        if verified:
            resolved = BindingResolver(bindings, presets, profile).read()
            checks["control_path"] = "verified_runtime"
            checks["supported_binding_count"] = len(resolved["available"])
            checks["unavailable_binding_count"] = len(resolved["unavailable"])
            legacy_names = {mode.replace("_", " ") + " " + phrase for mode, catalog in ACTIONS.items() for phrase in catalog.values()}
            checks["legacy_control_commands_remaining"] = sum(c["name"] in legacy_names for c in configured)
            if checks["legacy_control_commands_remaining"]:
                report["issues"].append("Legacy control commands remain; run control_setup repair to migrate receipt-owned commands")
            if resolved["unavailable"]:
                report["issues"].append("Some active bindings need supplementation; run control_setup inspect")
        else:
            checks["control_path"] = "legacy_hotkeys"
            checks["binding_commands_present_on_disk"] = bool(expected) and all(c in configured for c in expected)
            if not checks["binding_commands_present_on_disk"]:
                report["issues"].append("Supported bindings do not all match the on-disk profile; regenerate/review controls")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, yaml.YAMLError):
        report["issues"].append("Profile/bindings could not be verified; inspect paths, schema and push-to-talk settings")

    reader = JournalReader(journal)
    reader.refresh()
    observation = reader.snapshot()
    report["journal"] = {key: observation.get(key) for key in
                         ("session", "galaxy", "game_version", "odyssey", "age_seconds", "catching_up")}
    report["journal"]["warning_count"] = len(observation.get("warnings", []))
    report["journal"]["has_location_observation"] = "location" in observation

    ping = query("/ping")
    checks["core_ready"] = isinstance(ping, dict) and ping.get("state") == "ready"
    if isinstance(ping, dict):
        config_name = profile_path.parent.name.lstrip("_")
        wingman_name = profile_path.stem
        configs = query("/configs")
        current = configs.get("current_config_dir") if isinstance(configs, dict) else None
        checks["profile_selected"] = current.get("name") == config_name if isinstance(current, dict) else None
        account = query("/client/account-name")
        checks["core_reports_account"] = bool(account.strip()) if isinstance(account, str) else None
        errors = query("/startup-errors")
        checks["startup_error_count"] = len(errors) if isinstance(errors, list) else None
        params = "?" + urlencode({"config_name": config_name, "wingman_name": wingman_name})
        skills = query("/wingman-skills" + params)
        if isinstance(skills, list):
            checks["runtime_skill_available_and_enabled"] = any(
                isinstance(s, dict) and isinstance(s.get("skill"), dict) and
                s["skill"].get("name") == "EliteDangerous" and s.get("is_enabled") is True for s in skills)
        mcps = query("/wingman-mcps" + params)
        if isinstance(mcps, list):
            elite = next((m for m in mcps if isinstance(m, dict) and isinstance(m.get("config"), dict)
                          and m["config"].get("name") == "elite_public_data"), None)
            checks["public_data_registered_and_enabled"] = bool(elite and elite.get("is_enabled") is True)
            checks["public_data_connected"] = elite.get("is_connected") if elite else None
            checks["public_data_reported_error"] = bool(elite.get("error")) if elite else None
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("profile", "bindings", "presets", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--journal", type=Path, default=default_journal_dir())
    parser.add_argument("--port", type=int, default=49111)
    args = parser.parse_args()
    core = LocalCore(args.port)
    try:
        report = collect(args.profile, args.bindings, args.presets, args.journal, core.get)
    finally:
        core.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
