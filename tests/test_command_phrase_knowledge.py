import json
from pathlib import Path
import tempfile
import unittest

from star_citizen_data.keybindings.export_command_phrase_knowledge import (
    export_command_phrase_knowledge,
)
from star_citizen_data.keybindings.version_utils import (
    available_versions,
    resolve_version,
)


class CommandPhraseKnowledgeTests(unittest.TestCase):
    def test_export_keeps_prior_knowledge_and_adds_current_phrases(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source_dir = root / "R4_100"
            source_dir.mkdir()
            source = source_dir / "sc_all_keybindings.json"
            source.write_text(
                json.dumps(
                    {
                        "new_action": {"command-phrases": {"en": ["new phrase"]}},
                        "without_phrases": {},
                    }
                ),
                encoding="utf-8",
            )
            destination = root / "command_phrase_knowledge.json"
            destination.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source_version": "R4_90",
                        "commands": {"old_action": {"en": ["old phrase"]}},
                    }
                ),
                encoding="utf-8",
            )

            count = export_command_phrase_knowledge(source, destination)
            exported = json.loads(destination.read_text(encoding="utf-8"))

            self.assertEqual(2, count)
            self.assertEqual("R4_100", exported["source_version"])
            self.assertEqual(
                {"old_action", "new_action"}, set(exported["commands"])
            )

    def test_latest_generated_version_is_selected_numerically(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            for version in ("R4_90", "R4_100", "not-a-version"):
                version_dir = root / version
                version_dir.mkdir()
                (version_dir / "sc_all_keybindings.json").write_text(
                    "{}", encoding="utf-8"
                )

            self.assertEqual(["R4_90", "R4_100"], available_versions(root))
            self.assertEqual("R4_100", resolve_version(root))


if __name__ == "__main__":
    unittest.main()
