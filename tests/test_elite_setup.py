"""Install native source configuration without accounts, dependencies or Core startup."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import yaml

from integrations.elite_dangerous import setup


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.checkout = self.root / "fork with spaces"
        original = setup.ROOT
        paths = list((original / "integrations/elite_dangerous").glob("*.py"))
        paths.extend(original / "integrations/elite_dangerous" / name for name in ("requirements.txt", "mcp.example.yaml"))
        paths.extend(original / "skills/elite_dangerous" / name for name in ("main.py", "telemetry.py", "default_config.yaml", "logo.png"))
        paths.extend(original / "skills/elite_dangerous_controls" / name for name in
                     ("__init__.py", "main.py", "input.py", "runtime.py", "bindings.py", "result.py", "observation.py", "speech.py", "workflows.py", "default_config.yaml", "logo.png"))
        paths.append(original / "templates/configs/Elite Dangerous/Companion.template.yaml")
        for source in paths:
            target = self.checkout / source.relative_to(original)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        self.root_patch = patch.object(setup, "ROOT", self.checkout)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.config = self.root / "configs"
        self.config.mkdir()
        self.defaults = {"prompts": {"backstory": "User defaults"}, "discoverable_mcps": ["inherited"]}
        self.save(self.config / "defaults.yaml", self.defaults)
        self.python = self.root / "python.exe"
        self.python.write_bytes(b"test interpreter, never executed")
        self.output = self.root / "review"
        self.cache = self.root / "cache"
        self.profile = self.config / "Elite Dangerous/Companion.yaml"
        self.mcp = self.config / "mcp.yaml"

    @staticmethod
    def save(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def prepare(self, output=None):
        return setup.prepare(self.config, self.python, self.cache, output or self.output)

    def apply(self):
        return setup.apply_plan(self.output / "plan.json")

    def test_prepare_is_read_only_then_creates_profile_and_merges_other_servers(self):
        other = {"name": "existing", "display_name": "Existing", "type": "http", "url": "https://example.invalid",
                 "headers": {"Authorization": "test-secret"}}
        self.save(self.mcp, {"servers": [other], "unrelated": True})
        original = self.mcp.read_bytes()
        plan = self.prepare()
        self.assertEqual(original, self.mcp.read_bytes())
        self.assertFalse(self.profile.exists())
        self.assertFalse(self.cache.exists())
        self.assertEqual(2, plan["changed_files"])
        self.assertNotIn("test-secret", json.dumps(plan))
        report = self.apply()
        self.assertEqual(2, report["changed_files"])
        self.assertFalse(report["core_restarted"])
        config = yaml.safe_load(self.mcp.read_text())
        self.assertEqual(other, config["servers"][0])
        self.assertTrue(config["unrelated"])
        server = config["servers"][1]
        self.assertEqual(str(self.python), server["command"])
        self.assertEqual(str(self.checkout / "integrations/elite_dangerous/server.py"), server["args"][0])
        self.assertEqual(original, (self.output / "backup/1-mcp.yaml").read_bytes())
        self.assertEqual([], yaml.safe_load(self.profile.read_text())["commands"])

    def test_existing_profile_and_inherited_capabilities_are_preserved(self):
        original = {"name": "Companion", "prompts": {"backstory": "My custom voice"},
                    "commands": [{"name": "my command", "actions": [{"wait": 0.1}]}],
                    "record_key": "home", "features": {"tts_provider": "edge_tts"},
                    "skills": [{"module": "skills.elite_dangerous.main", "name": "EliteDangerous",
                                "custom_properties": [{"id": "announce_events", "value": False}]}]}
        self.save(self.profile, original)
        self.prepare()
        self.apply()
        loaded = yaml.safe_load(self.profile.read_text())
        for key, value in original.items():
            self.assertEqual(value, loaded[key])
        self.assertIn("inherited", loaded["discoverable_mcps"])
        self.assertIn("elite_public_data", loaded["discoverable_mcps"])
        self.assertIn("EliteDangerous", loaded["discoverable_skills"])

    def test_default_profile_directory_is_reused_without_changing_default(self):
        default = self.config / "_Elite Dangerous/Companion.yaml"
        self.save(default, {"name": "Companion", "commands": []})
        plan = self.prepare()
        self.apply()
        self.assertTrue(default.exists())
        self.assertFalse(self.profile.parent.exists())
        self.assertIn("_Elite Dangerous", plan["targets"][0]["relative_path"])

    def test_second_run_preserves_identical_bytes_and_is_a_noop(self):
        self.prepare()
        self.apply()
        before = [self.profile.read_bytes(), self.mcp.read_bytes()]
        second = self.root / "second"
        plan = self.prepare(second)
        self.assertEqual(0, plan["changed_files"])
        self.assertEqual(0, setup.apply_plan(second / "plan.json")["changed_files"])
        self.assertEqual(before, [self.profile.read_bytes(), self.mcp.read_bytes()])

    def test_existing_elite_server_env_timeout_and_other_values_are_preserved(self):
        self.prepare()
        self.apply()
        config = yaml.safe_load(self.mcp.read_text())
        server = config["servers"][0]
        server.update(env={"CUSTOM": "retain"}, timeout=90, discoverable_by_default=True)
        self.save(self.mcp, config)
        second = self.root / "second"
        self.prepare(second)
        setup.apply_plan(second / "plan.json")
        result = yaml.safe_load(self.mcp.read_text())["servers"][0]
        self.assertEqual(server, result)

    def test_equivalent_path_spelling_does_not_rewrite_mcp(self):
        self.prepare()
        self.apply()
        config = yaml.safe_load(self.mcp.read_text())
        server = config["servers"][0]
        server["command"] = self.python.as_posix()
        server["args"] = [(self.checkout / "integrations/elite_dangerous/server.py").as_posix(), "--cache-dir", self.cache.as_posix()]
        self.save(self.mcp, config)
        second = self.root / "second"
        self.assertEqual(0, self.prepare(second)["changed_files"])

    def test_conflicting_or_duplicate_mcp_server_is_rejected_before_staging(self):
        server = {"name": "elite_public_data", "display_name": "Different", "type": "http", "url": "https://example.invalid"}
        self.save(self.mcp, {"servers": [server]})
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.output.exists())
        self.save(self.mcp, {"servers": [server, server]})
        with self.assertRaises(ValueError):
            self.prepare()

    def test_disabled_deleted_and_ambiguous_profiles_are_not_revived(self):
        self.save(self.profile, {"name": "Companion", "disabled": True})
        with self.assertRaises(ValueError):
            self.prepare()
        self.save(self.profile, {"name": "Companion"})
        deleted = self.profile.with_name(".Companion.yaml")
        deleted.write_text("name: Companion")
        with self.assertRaises(ValueError):
            self.prepare()
        deleted.unlink()
        (self.config / "_Elite Dangerous").mkdir()
        with self.assertRaises(ValueError):
            self.prepare()

    def test_changed_config_and_staged_files_refuse_apply_without_writes(self):
        self.prepare()
        self.mcp.write_text("servers: []\n")
        with self.assertRaises(ValueError):
            self.apply()
        self.assertFalse(self.profile.exists())
        self.mcp.unlink()
        staged = self.output / "Companion.staged.yaml"
        staged.write_text(staged.read_text() + "# edited\n")
        with self.assertRaises(ValueError):
            self.apply()
        self.assertFalse(self.profile.exists())

    def test_changed_source_or_defaults_refuse_apply(self):
        self.prepare()
        source = self.checkout / "skills/elite_dangerous/telemetry.py"
        original = source.read_bytes()
        source.write_bytes(original + b"\n# changed\n")
        with self.assertRaises(ValueError):
            self.apply()
        source.write_bytes(original)
        self.save(self.config / "defaults.yaml", {"prompts": {"backstory": "changed"}})
        with self.assertRaises(ValueError):
            self.apply()
        self.assertFalse(self.profile.exists())

    def test_input_change_during_prepare_is_not_attested_as_reviewed(self):
        real_inputs = setup.source_inputs
        count = 0
        def changed(*args):
            nonlocal count
            count += 1
            if count == 2:
                self.save(self.config / "defaults.yaml", {"prompts": {"backstory": "edited mid-prepare"}})
            return real_inputs(*args)
        with patch.object(setup, "source_inputs", side_effect=changed):
            with self.assertRaises(ValueError):
                self.prepare()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.profile.exists())

    def test_redirected_target_and_staging_inside_config_are_rejected(self):
        with self.assertRaises(ValueError):
            self.prepare(self.config / "review")
        self.prepare()
        plan_path = self.output / "plan.json"
        plan = json.loads(plan_path.read_text())
        plan["targets"][0]["relative_path"] = "../outside.yaml"
        plan_path.write_text(json.dumps(plan))
        with self.assertRaises(ValueError):
            self.apply()
        self.assertFalse((self.root / "outside.yaml").exists())

    def test_failed_second_write_rolls_back_created_profile(self):
        self.prepare()
        real_write = setup.atomic_write
        def fail_second(path, raw):
            if path == self.mcp:
                raise OSError("synthetic write failure")
            real_write(path, raw)
        with patch.object(setup, "atomic_write", side_effect=fail_second):
            with self.assertRaises(OSError):
                self.apply()
        self.assertFalse(self.profile.exists())
        self.assertFalse(self.mcp.exists())

    def test_rollback_preserves_intervening_user_edit(self):
        self.prepare()
        real_write = setup.atomic_write
        def fail_second(path, raw):
            if path == self.mcp:
                self.profile.write_text("name: user-edited\n")
                raise OSError("synthetic write failure")
            real_write(path, raw)
        with patch.object(setup, "atomic_write", side_effect=fail_second):
            with self.assertRaises(OSError):
                self.apply()
        self.assertEqual("name: user-edited\n", self.profile.read_text())
