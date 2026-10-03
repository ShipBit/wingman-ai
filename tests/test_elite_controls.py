"""Exercise native profile installation without game input or account services."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from integrations.elite_dangerous import controls


class ControlsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bindings, self.presets = self.root / "bindings", self.root / "presets"
        self.bindings.mkdir()
        self.presets.mkdir()
        (self.bindings / "StartPreset.4.start").write_text("Default\nDefault\nDefault\nDefault\n")
        self.xml = self.presets / "Default.binds"
        self.xml.write_text('<Root PresetName="Default">'
                            '<LandingGearToggle><Primary Device="Keyboard" Key="Key_L"/></LandingGearToggle>'
                            '<SelectTarget><Primary Device="Mouse" Key="Mouse_2"/></SelectTarget>'
                            '<HeadlightsBuggyButton><Primary Device="Keyboard" Key="Key_V"/></HeadlightsBuggyButton>'
                            '</Root>')
        self.profile = self.root / "Companion.yaml"
        self.existing = {"name": "my command", "instant_activation": ["my phrase"], "actions": [{"wait": 0.1}]}
        self.config = {"name": "Companion", "record_key": "end", "commands": [self.existing],
                       "prompts": {"backstory": "Custom voice. This profile initially has no game-control commands."},
                       "discoverable_mcps": ["custom_provider"], "custom_setting": {"retained": 42}}
        self.save()
        self.output = self.root / "setup"

    def save(self):
        self.profile.write_text(yaml.safe_dump(self.config), encoding="utf-8")

    def prepare(self, output=None):
        return controls.prepare(self.profile, self.bindings, self.presets, output or self.output)

    def apply(self, output=None):
        return controls.apply_plan((output or self.output) / "plan.json")

    def read(self):
        return yaml.safe_load(self.profile.read_text(encoding="utf-8"))

    def test_prepare_is_read_only_then_apply_preserves_settings_and_backup(self):
        before = self.profile.read_bytes()
        plan = self.prepare()
        self.assertEqual(before, self.profile.read_bytes())
        self.assertEqual(3, plan["commands"])
        report = self.apply()
        installed = self.read()
        self.assertEqual(4, len(installed["commands"]))
        self.assertEqual(self.existing, installed["commands"][0])
        self.assertEqual(self.config["custom_setting"], installed["custom_setting"])
        self.assertEqual(self.config["discoverable_mcps"], installed["discoverable_mcps"])
        self.assertTrue(installed["prompts"]["backstory"].startswith("Custom voice."))
        self.assertNotIn("no game-control commands", installed["prompts"]["backstory"])
        self.assertEqual(before, (Path(report["backup"]) / "0-Companion.yaml").read_bytes())
        self.assertFalse(report["gameplay_verified"])
        self.assertFalse(report["core_restarted"])
        with self.assertRaisesRegex(ValueError, "already applied"):
            self.apply()

    def test_binding_or_profile_change_after_stage_refuses_all_writes(self):
        before = self.profile.read_bytes()
        self.prepare()
        xml = self.xml.read_text()
        self.xml.write_text(xml.replace("Key_L", "Key_K"))
        with self.assertRaisesRegex(ValueError, "bindings changed"):
            self.apply()
        self.assertEqual(before, self.profile.read_bytes())
        self.xml.write_text(xml)
        self.config["record_key"] = "l"
        self.save()
        edited = self.profile.read_bytes()
        with self.assertRaisesRegex(ValueError, "changed after staging"):
            self.apply()
        self.assertEqual(edited, self.profile.read_bytes())

    def test_copied_legacy_controls_without_receipt_become_tool_accessible(self):
        generated = controls.generate(self.bindings, self.presets)["commands"]
        legacy = [{**command, "force_instant_activation": True,
                   "instant_activation": [command["name"]]} for command in generated]
        self.config["commands"].extend(legacy)
        self.save()
        self.prepare()
        self.apply()
        installed = self.read()
        self.assertEqual(self.existing, installed["commands"][0])
        self.assertEqual(generated, installed["commands"][1:])
        receipt = json.loads(self.profile.with_suffix(".elite-controls.json").read_text())
        self.assertEqual(generated, receipt["commands"])

    def test_copied_legacy_control_with_changed_action_is_not_adopted(self):
        generated = controls.generate(self.bindings, self.presets)["commands"][0]
        edited = {**generated, "force_instant_activation": True,
                  "instant_activation": [generated["name"]], "actions": [{"wait": 1}]}
        self.config["commands"].append(edited)
        self.save()
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.prepare()

    def test_updates_owned_commands_and_removes_now_unbound(self):
        self.prepare()
        self.apply()
        self.xml.write_text(self.xml.read_text().replace("Key_L", "Key_K").replace("Key_V", "Key_Unknown"))
        next_output = self.root / "updated"
        self.prepare(next_output)
        self.apply(next_output)
        commands = {c["name"]: c for c in self.read()["commands"]}
        self.assertEqual("k", commands["ship toggle landing gear"]["actions"][0]["keyboard"]["hotkey"])
        self.assertNotIn("srv toggle lights", commands)
        self.assertEqual(self.existing, commands["my command"])

    def test_new_active_preset_version_after_staging_is_detected(self):
        self.prepare()
        before = self.profile.read_bytes()
        (self.bindings / "Default.4.2.binds").write_text(
            '<Root PresetName="Default" MajorVersion="4" MinorVersion="2"/>')
        with self.assertRaisesRegex(ValueError, "bindings changed"):
            self.apply()
        self.assertEqual(before, self.profile.read_bytes())

    def test_manually_edited_managed_command_is_not_overwritten(self):
        self.prepare()
        self.apply()
        self.config = self.read()
        self.config["commands"][1]["responses"] = ["Custom acknowledgement"]
        self.save()
        before = self.profile.read_bytes()
        with self.assertRaisesRegex(ValueError, "was edited"):
            self.prepare(self.root / "edited")
        self.assertEqual(before, self.profile.read_bytes())

    def test_alias_conflict_fails_without_mutation(self):
        self.config["commands"][0]["instant_activation"].append("SHIP TOGGLE LANDING GEAR")
        self.save()
        before = self.profile.read_bytes()
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.prepare()
        self.assertEqual(before, self.profile.read_bytes())
        self.assertFalse(self.output.exists())

    def test_push_to_talk_keyboard_mouse_and_scan_codes(self):
        self.config["record_key"] = "l"
        self.config["record_mouse_button"] = "right"
        self.save()
        self.assertEqual(1, self.prepare()["commands"])
        self.config["record_key_codes"] = [38]
        self.save()
        with self.assertRaisesRegex(ValueError, "Scan-code"):
            self.prepare(self.root / "codes")
        self.config.pop("record_key_codes")
        self.config["record_key"] = "CTRL"
        self.save()
        self.xml.write_text(self.xml.read_text().replace(
            'Device="Keyboard" Key="Key_L"/>',
            'Device="Keyboard" Key="Key_L"><Modifier Device="Keyboard" Key="Key_LeftControl"/></Primary>'))
        self.assertEqual(1, self.prepare(self.root / "modifier")["commands"])

    def test_second_file_failure_rolls_back_first(self):
        before = self.profile.read_bytes()
        self.prepare()
        real_write = controls.atomic_write

        def fail_receipt(path, data):
            if path.suffix == ".json":
                raise OSError("Synthetic disk failure")
            real_write(path, data)

        with patch.object(controls, "atomic_write", side_effect=fail_receipt):
            with self.assertRaisesRegex(OSError, "Synthetic disk"):
                self.apply()
        self.assertEqual(before, self.profile.read_bytes())
        self.assertFalse(self.profile.with_suffix(".elite-controls.json").exists())
        self.assertFalse((self.output / "applied.json").exists())

    def test_staged_tamper_and_ambiguous_inheritance_rejected(self):
        before = self.profile.read_bytes()
        self.prepare()
        (self.output / "Companion.staged.yaml").write_text("name: changed\n")
        with self.assertRaisesRegex(ValueError, "Staged files changed"):
            self.apply()
        self.assertEqual(before, self.profile.read_bytes())
        del self.config["commands"]
        self.save()
        with self.assertRaisesRegex(ValueError, "explicit commands list"):
            self.prepare(self.root / "inherited")

    def test_client_materialized_defaults_are_semantically_unchanged(self):
        self.prepare()
        self.apply()
        self.config = self.read()
        self.config["commands"] = [controls.command_value(c) for c in self.config["commands"]]
        self.save()
        before = deepcopy(self.config)
        self.prepare(self.root / "defaults")
        self.apply(self.root / "defaults")
        self.assertEqual([controls.command_value(c) for c in before["commands"]],
                         [controls.command_value(c) for c in self.read()["commands"]])
