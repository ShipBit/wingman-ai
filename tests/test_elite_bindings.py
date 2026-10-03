"""Verify mode-specific bindings become faithful ordinary Wingman commands."""

import json
from pathlib import Path
import tempfile
import unittest

import yaml
from api.interface import CommandConfig
from integrations.elite_dangerous.bindings import generate, stage


class BindingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.user, self.game = self.root / "user", self.root / "game"
        self.user.mkdir()
        self.game.mkdir()
        (self.user / "StartPreset.4.start").write_text("Default\nCustom\nDefault\nDefault\n")
        self.custom = self.user / "Custom.4.2.binds"
        self.custom.write_text('<Root PresetName="Custom" MajorVersion="4" MinorVersion="2">'
                              '<LandingGearToggle><Primary Device="Keyboard" Key="Key_L"/></LandingGearToggle>'
                              '<ToggleCargoScoop><Primary Device="Keyboard" Key="Key_Home"/><ToggleOn Value="1"/></ToggleCargoScoop>'
                              '</Root>')
        self.default = self.game / "Default.binds"
        self.default.write_text('<Root PresetName="Default">'
                                '<LandingGearToggle><Primary Device="Keyboard" Key="Key_Z"/></LandingGearToggle>'
                                '<HeadlightsBuggyButton><Primary Device="Keyboard" Key="Key_V"/></HeadlightsBuggyButton>'
                                '<HumanoidToggleFlashlightButton><Primary Device="Keyboard" Key="Key_T"/></HumanoidToggleFlashlightButton>'
                                '</Root>')

    def result(self):
        return generate(self.user, self.game)

    def test_uses_correct_mode_and_newest_version(self):
        (self.user / "Custom.4.0.binds").write_text('<Root PresetName="Custom" MajorVersion="4" MinorVersion="0"/>')
        result = self.result()
        mappings = {row["phrase"]: row["key"] for row in result["mappings"]}
        self.assertEqual("l", mappings["ship toggle landing gear"])
        self.assertEqual("v", mappings["srv toggle lights"])
        self.assertEqual("t", mappings["on foot toggle flashlight"])
        self.assertTrue(result["sources"]["ship"]["file"].endswith("Custom.4.2.binds"))
        self.assertTrue(any(row["action"] == "GalaxyMapOpen" for row in result["skipped"]))
        for command in result["commands"]:
            parsed = CommandConfig.model_validate(command)
            self.assertFalse(parsed.force_instant_activation)
            self.assertEqual([parsed.name, parsed.name + ".", parsed.name + "!"], parsed.instant_activation)

    def test_modifier_order_secondary_mouse_and_hold_rejection(self):
        self.custom.write_text('<Root PresetName="Custom" MajorVersion="4" MinorVersion="2">'
                              '<LandingGearToggle><Primary Device="Joystick" Key="Joy_1"/>'
                              '<Secondary Device="Keyboard" Key="Key_L">'
                              '<Modifier Device="Keyboard" Key="Key_LeftControl"/>'
                              '<Modifier Device="Keyboard" Key="Key_LeftShift"/>'
                              '</Secondary></LandingGearToggle>'
                              '<SelectTarget><Primary Device="Mouse" Key="Mouse_2"/></SelectTarget>'
                              '<ToggleCargoScoop><Primary Device="Keyboard" Key="Key_Home"/><ToggleOn Value="0"/></ToggleCargoScoop>'
                              '<SetSpeedZero><Primary Device="Keyboard" Key="Key_X"><Hold Value="1"/></Primary></SetSpeedZero>'
                              '</Root>')
        result = self.result()
        commands = {c["name"]: c for c in result["commands"]}
        actions = commands["ship toggle landing gear"]["actions"]
        self.assertEqual(["left ctrl", "left shift", "l", "left shift", "left ctrl"],
                         [a["keyboard"]["hotkey"] for a in actions])
        self.assertTrue(actions[0]["keyboard"]["press"])
        self.assertTrue(actions[-1]["keyboard"]["release"])
        self.assertEqual("right", commands["ship target ahead"]["actions"][0]["mouse"]["button"])
        self.assertNotIn("ship toggle cargo scoop", commands)
        self.assertNotIn("ship zero throttle", commands)

    def test_ptt_conflict_and_unknown_keys_never_guessed(self):
        self.custom.write_text('<Root PresetName="Custom" MajorVersion="4" MinorVersion="2">'
                              '<LandingGearToggle><Primary Device="Keyboard" Key="Key_End"/></LandingGearToggle>'
                              '<SetSpeedZero><Primary Device="Keyboard" Key="Key_NotARealKey"/></SetSpeedZero>'
                              '</Root>')
        self.assertFalse(any(row["mode"] == "ship" for row in self.result()["mappings"]))

    def test_missing_selector_no_default_assumption(self):
        (self.user / "StartPreset.4.start").unlink()
        with self.assertRaises(FileNotFoundError):
            self.result()

    def test_bad_selectors_identity_and_xml_rejected(self):
        for selector in ("Default\n", "../Default\nCustom\nDefault\nDefault\n"):
            (self.user / "StartPreset.4.start").write_text(selector)
            with self.assertRaises(ValueError):
                self.result()
        (self.user / "StartPreset.4.start").write_text("Default\nCustom\nDefault\nDefault\n")
        for xml in ('<Root PresetName="Wrong"/>', '<!DOCTYPE Root><Root PresetName="Custom"/>'):
            self.custom.write_text(xml)
            with self.assertRaises(ValueError):
                self.result()

    def test_staging_preserves_source_and_has_valid_mode_files(self):
        before = self.custom.read_bytes()
        result = self.result()
        out = self.root / "staged"
        stage(result, out)
        self.assertEqual(before, self.custom.read_bytes())
        for mode in ("ship", "srv", "on_foot"):
            for c in yaml.safe_load((out / f"{mode}.commands.yaml").read_text())["commands"]:
                CommandConfig.model_validate(c)
        self.assertEqual("staged_not_gameplay_verified", json.loads((out / "bindings-report.json").read_text())["status"])


if __name__ == "__main__":
    unittest.main()
