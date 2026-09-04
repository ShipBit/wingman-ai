import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from wingmen.star_citizen_services.keybindings import SCKeybindings


class KeybindingVersionIntegrationTests(unittest.TestCase):
    def test_detected_version_updates_runtime_config_and_paths(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            channel_dir = root / "StarCitizen" / "LIVE"
            channel_dir.mkdir(parents=True)
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
            config = self._config(root)
            secret_keeper = Mock()
            secret_keeper.retrieve.return_value = None

            manager = SCKeybindings(config, secret_keeper)

            self.assertEqual("R4_100", manager.sc_channel_version)
            self.assertEqual(
                "R4_100", config["sc-keybind-mappings"]["sc_channel_version"]
            )
            self.assertEqual("R4_100", manager.version_dir.name)
            self.assertIn("R4_100", manager.user_keybinding_file.name)

    def test_invalid_manifest_keeps_configured_fallback(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            channel_dir = root / "StarCitizen" / "LIVE"
            channel_dir.mkdir(parents=True)
            (channel_dir / "build_manifest.id").write_text(
                "not json", encoding="utf-8"
            )
            config = self._config(root)
            secret_keeper = Mock()
            secret_keeper.retrieve.return_value = None

            manager = SCKeybindings(config, secret_keeper)

            self.assertEqual("R4_90", manager.sc_channel_version)
            self.assertEqual(
                "R4_90", config["sc-keybind-mappings"]["sc_channel_version"]
            )

    def test_merge_refreshes_sc_data_but_preserves_existing_phrases(self):
        manager = object.__new__(SCKeybindings)
        manager._build_sc_keybinding_default_actions = Mock(
            return_value={
                "shared": {"actionname": "shared", "action-label-en": "New label"},
                "new": {"actionname": "new", "action-label-en": "New action"},
            }
        )
        previous = {
            "shared": {
                "actionname": "shared",
                "action-label-en": "Old label",
                "command-phrases": {"en": ["existing phrase"]},
            },
            "removed": {"actionname": "removed"},
        }

        merged = manager._merge_missing_default_actions(previous)

        self.assertEqual({"shared", "new"}, set(merged))
        self.assertEqual("New label", merged["shared"]["action-label-en"])
        self.assertEqual(
            {"en": ["existing phrase"]}, merged["shared"]["command-phrases"]
        )
        self.assertNotIn("command-phrases", merged["new"])

    @staticmethod
    def _config(root: Path):
        return {
            "data-root-directory": f"{root / 'data'}/",
            "openai": {"player_language": "en"},
            "command_languages": ["de_DE"],
            "commands": [],
            "sc-keybind-mappings": {
                "keybindings-directory": "keybindings/",
                "sc_installation_dir": str(root / "StarCitizen"),
                "sc_active_channel": "LIVE",
                "sc_channel_version": "R4_90",
                "auto_detect_version": True,
                "auto_extract_game_files": False,
                "user_keybinding_file_name": "layout_{sc_channel_version}.xml",
                "sc_unp4k_file_default_keybindings_filter": "defaultProfile.xml",
                "sc_unp4k_file_keybinding_localization_filter": "keybinding_localization.xml",
                "sc_unp4k_translations_filter": "global.ini",
                "en_translation_file": "global_en_GB.ini",
            },
        }


if __name__ == "__main__":
    unittest.main()
