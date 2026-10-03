"""Preflight must separate configuration evidence from runtime acceptance."""

import json
from pathlib import Path
import tempfile
import unittest

import yaml

from integrations.elite_dangerous.bindings import generate
from integrations.elite_dangerous.diagnostics import collect


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.bindings, self.presets, self.journal = [root / n for n in ("bindings", "presets", "journal")]
        for directory in (self.bindings, self.presets, self.journal):
            directory.mkdir()
        (self.bindings / "StartPreset.4.start").write_text("Default\n" * 4)
        (self.presets / "Default.binds").write_text('<Root PresetName="Default"><LandingGearToggle>'
            '<Primary Device="Keyboard" Key="Key_L"/></LandingGearToggle></Root>')
        self.profile = root / "Elite Dangerous" / "Companion.yaml"
        self.profile.parent.mkdir()
        self.profile.write_text(yaml.safe_dump({"name": "Companion", "record_key": "end",
            "commands": generate(self.bindings, self.presets)["commands"], "private_config": "secret-sentinel"}))
        events = [{"timestamp": "2026-09-27T12:00:00Z", "event": "Fileheader", "gameversion": "4.4.1.1"},
                  {"timestamp": "2026-09-27T12:00:01Z", "event": "Commander", "Name": "private-pilot", "FID": "private-id"},
                  {"timestamp": "2026-09-27T12:00:02Z", "event": "Shutdown"}]
        (self.journal / "Journal.2026-09-27T120000.01.log").write_text("\n".join(json.dumps(e) for e in events) + "\n")
        self.responses = {"/ping": {"state": "ready"}, "/configs": {"current_config_dir": {"name": "Elite Dangerous"}},
                          "/client/account-name": "private-account", "/startup-errors": [],
                          "/wingman-skills": [{"skill": {"name": "EliteDangerous"}, "is_enabled": True}],
                          "/wingman-mcps": [{"config": {"name": "elite_public_data", "secret": "secret-sentinel"},
                                             "is_enabled": True, "is_connected": False, "error": None}]}
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        return self.responses[path.split("?")[0]]

    def report(self, get=None):
        return collect(self.profile, self.bindings, self.presets, self.journal, get or self.get)

    def test_metadata_privacy_and_no_false_gameplay_pass(self):
        result = self.report()
        self.assertTrue(result["checks"]["binding_commands_present_on_disk"])
        self.assertTrue(result["checks"]["runtime_skill_available_and_enabled"])
        self.assertTrue(result["checks"]["public_data_registered_and_enabled"])
        self.assertFalse(result["checks"]["public_data_connected"])
        self.assertEqual("offline", result["journal"]["session"])
        self.assertTrue(result["manual_acceptance"])
        encoded = json.dumps(result)
        for private in ("private-account", "private-pilot", "private-id", "secret-sentinel"):
            self.assertNotIn(private, encoded)
        self.assertFalse(any("connect" in path for path in self.paths))

    def test_offline_core_preserves_independent_local_findings(self):
        def unavailable(path):
            raise OSError("private connection detail")
        result = self.report(unavailable)
        self.assertFalse(result["checks"]["core_ready"])
        self.assertTrue(result["checks"]["binding_commands_present_on_disk"])
        self.assertNotIn("private connection detail", json.dumps(result))
        self.assertEqual(1, len(result["issues"]))

    def test_verified_runtime_does_not_require_legacy_hotkey_commands(self):
        config = yaml.safe_load(self.profile.read_text())
        config['commands'] = []
        config['discoverable_skills'] = ['EliteDangerous', 'EliteDangerousControls']
        self.profile.write_text(yaml.safe_dump(config))
        result = self.report()
        self.assertEqual('verified_runtime', result['checks']['control_path'])
        self.assertEqual(0, result['checks']['legacy_control_commands_remaining'])
        self.assertNotIn('binding_commands_present_on_disk', result['checks'])

    def test_missing_account_and_changed_bindings_are_distinct(self):
        self.responses["/client/account-name"] = ""
        source = self.presets / "Default.binds"
        source.write_text(source.read_text().replace("Key_L", "Key_K"))
        result = self.report()
        self.assertFalse(result["checks"]["core_reports_account"])
        self.assertFalse(result["checks"]["binding_commands_present_on_disk"])
        self.assertTrue(result["checks"]["core_ready"])

    def test_malformed_or_unavailable_services_are_unknown_not_empty_success(self):
        self.responses["/startup-errors"] = None
        self.responses["/client/account-name"] = {"wrong": True}
        self.responses["/wingman-mcps"] = None
        result = self.report()
        self.assertIsNone(result["checks"]["startup_error_count"])
        self.assertIsNone(result["checks"]["core_reports_account"])
        self.assertNotIn("public_data_registered_and_enabled", result["checks"])
