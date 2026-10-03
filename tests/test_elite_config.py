from pathlib import Path
import struct
import unittest

import yaml
from api.interface import McpConfig, WingmanConfig


class ConfigTests(unittest.TestCase):
    def test_additive_profile_and_snapshot(self):
        path = Path("templates/configs/Elite Dangerous/Companion.template.yaml")
        profile = yaml.safe_load(path.read_text(encoding="utf-8"))
        defaults = yaml.safe_load(Path("templates/configs/defaults.yaml").read_text(encoding="utf-8"))
        # Profile uses only existing fields. Match nested provider/prompt defaults.
        defaults["prompts"].update(profile.pop("prompts"))
        defaults.update(profile)
        # Core expands skill/property metadata from the skill's default config.
        from services.config_manager import ConfigManager
        manager = object.__new__(ConfigManager)
        defaults['skills'] = [manager._ConfigManager__deep_merge(
            yaml.safe_load(Path(s['module'].replace('.main', '').replace('.', '/') + '/default_config.yaml').read_text()), s)
            for s in defaults.get('skills', [])]
        wingman = WingmanConfig.model_validate(defaults)
        self.assertIn("EliteDangerous", wingman.discoverable_skills)
        snapshot = Path("templates/migration/2_1_1/configs/Elite Dangerous/Companion.template.yaml")
        self.assertEqual(path.read_bytes(), snapshot.read_bytes())
        config = McpConfig.model_validate(yaml.safe_load(Path(
            "integrations/elite_dangerous/mcp.example.yaml").read_text(encoding="utf-8")))
        self.assertIn(config.servers[0].name, wingman.discoverable_mcps)

    def test_icon_is_png(self):
        data = Path("skills/elite_dangerous/logo.png").read_bytes()
        self.assertEqual(b"\x89PNG\r\n\x1a\n", data[:8])
        width, height = struct.unpack(">II", data[16:24])
        self.assertGreaterEqual(width, 256)
        self.assertEqual(width, height)


if __name__ == "__main__":
    unittest.main()
