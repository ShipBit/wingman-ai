import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wingmen.star_citizen_services.sc_game_files import (
    SCBuild,
    SCGameFileError,
    SCGameFileExtractor,
    detect_installed_build,
    version_directory_from_branch,
)


class VersionDetectionTests(unittest.TestCase):
    def test_version_directory_uses_all_release_components(self):
        self.assertEqual(
            "R4_100", version_directory_from_branch("sc-alpha-4.10.0-hotfix")
        )
        self.assertEqual("R4_91", version_directory_from_branch("sc-alpha-4.9.1"))

    def test_invalid_branch_is_rejected(self):
        with self.assertRaises(SCGameFileError):
            version_directory_from_branch("unknown-build")

    def test_reads_installed_channel_manifest(self):
        with tempfile.TemporaryDirectory() as temp_name:
            installation = Path(temp_name)
            channel_dir = installation / "LIVE"
            channel_dir.mkdir()
            (channel_dir / "build_manifest.id").write_text(
                json.dumps(
                    {
                        "Data": {
                            "Branch": "sc-alpha-4.10.0-hotfix",
                            "BuildId": "build-123",
                            "Version": "1.0.0",
                        }
                    }
                ),
                encoding="utf-8",
            )

            build = detect_installed_build(installation, "LIVE")

            self.assertIsNotNone(build)
            self.assertEqual("R4_100", build.version_directory)
            self.assertEqual("build-123", build.build_id)


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.installation = self.root / "StarCitizen"
        channel_dir = self.installation / "LIVE"
        channel_dir.mkdir(parents=True)
        (channel_dir / "Data.p4k").write_bytes(b"archive")

        self.tool_dir = self.root / "unp4k-suite"
        self.tool_dir.mkdir()
        (self.tool_dir / "unp4k.exe").write_bytes(b"tool")
        (self.tool_dir / "unforge.exe").write_bytes(b"tool")

        self.mapping = {
            "sc_unp4k_install_dir": str(self.tool_dir),
            "sc_unp4k_file_default_keybindings_filter": "defaultProfile.xml",
            "sc_unp4k_file_keybinding_localization_filter": "keybinding_localization.xml",
            "sc_unp4k_translations_filter": "global.ini",
            "en_translation_file": "global_en_GB.ini",
        }
        self.extractor = SCGameFileExtractor(
            self.mapping, self.installation, ["de_DE"]
        )
        self.build = SCBuild(
            channel="LIVE",
            branch="sc-alpha-4.10.0-hotfix",
            build_id="build-123",
            build_version="1.0.0",
            version_directory="R4_100",
        )
        self.version_dir = self.root / "keybindings" / "R4_100"

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def _fake_tool_run(_executable, args, cwd):
        file_filter = str(tuple(args)[-1])
        if file_filter == "defaultProfile.xml":
            target = cwd / "Data" / "Libs" / "Config" / file_filter
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("<profile />", encoding="utf-8")
        elif file_filter == "keybinding_localization.xml":
            target = cwd / "Data" / "Libs" / "Config" / file_filter
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("<LocalizedKeys />", encoding="utf-8")
        elif file_filter == "global.ini":
            for directory, contents in (
                ("english", "hello=Hello"),
                ("german_(germany)", "hello=Hallo"),
            ):
                target = cwd / "Data" / "Localization" / directory / "global.ini"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(contents, encoding="utf-8")

    def test_extracts_normalizes_and_skips_unchanged_build(self):
        with patch.object(
            self.extractor, "_run_tool", side_effect=self._fake_tool_run
        ) as run_tool:
            changed = self.extractor.ensure_extracted(self.build, self.version_dir)
            unchanged = self.extractor.ensure_extracted(self.build, self.version_dir)

        self.assertTrue(changed)
        self.assertFalse(unchanged)
        self.assertEqual(3, run_tool.call_count)
        self.assertEqual(
            "hello=Hello",
            (self.version_dir / "global_en_GB.ini").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            "hello=Hallo",
            (self.version_dir / "global_de_DE.ini").read_text(encoding="utf-8"),
        )
        state = json.loads(
            (self.version_dir / ".sc-extraction.json").read_text(encoding="utf-8")
        )
        self.assertEqual("build-123", state["build_id"])

    def test_changed_build_id_triggers_extraction(self):
        with patch.object(
            self.extractor, "_run_tool", side_effect=self._fake_tool_run
        ):
            self.extractor.ensure_extracted(self.build, self.version_dir)

        changed_build = SCBuild(
            **{**self.build.__dict__, "build_id": "build-456"}
        )
        with patch.object(
            self.extractor, "_run_tool", side_effect=self._fake_tool_run
        ) as run_tool:
            self.assertTrue(
                self.extractor.ensure_extracted(changed_build, self.version_dir)
            )
        self.assertEqual(3, run_tool.call_count)


if __name__ == "__main__":
    unittest.main()
