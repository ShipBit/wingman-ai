"""Real startup copying and endpoint selection, isolated from user files and audio."""

from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.config_manager import ConfigManager
from services.config_repair import repair_config_directories
from services.config_service import ConfigService


class DirectoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = self.root / 'app'
        self.templates = self.app / 'templates/configs'
        self.templates.mkdir(parents=True)
        self.live = self.root / 'live'
        self.configs = self.live / 'configs'
        self.configs.mkdir(parents=True)
        shutil.copyfile('templates/configs/defaults.yaml', self.templates / 'defaults.yaml')
        self.write(self.templates / 'Elite Dangerous/Companion.template.yaml', 'name: Companion\n')
        self.write(self.templates / '_Star Citizen/Computer.template.yaml', 'name: Computer\n')
        self.printr = Mock()
        self.printr.print_async = AsyncMock()

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def writable(self, relative=''):
        target = self.live / relative
        target.mkdir(parents=True, exist_ok=True)
        return str(target)

    def startup(self):
        # Exercise the real constructor and template copies, not a mocked manager.
        with patch('services.config_manager.get_writable_dir', side_effect=self.writable), \
             patch('services.config_manager.Printr', return_value=self.printr), \
             patch.object(ConfigManager, 'load_settings_config'), \
             patch.object(ConfigManager, 'load_mcp_config'):
            return ConfigManager(str(self.app))

    def player_config(self):
        self.write(self.configs / '_Elite Dangerous/Copilot.yaml', 'name: Copilot\n')
        self.write(self.configs / '_Elite Dangerous/.Companion.yaml', 'name: Companion\n')
        self.write(self.configs / 'Star Citizen/Computer.yaml', 'name: Customized\n')

    def test_restarts_reuse_default_directory_and_deletion_markers(self):
        self.player_config()
        for _ in range(3):
            manager = self.startup()
            self.assertFalse((self.configs / 'Elite Dangerous').exists())
            self.assertFalse((self.configs / '_Star Citizen').exists())
            self.assertFalse((self.configs / '_Elite Dangerous/Companion.yaml').exists())
            self.assertEqual('_Elite Dangerous', manager.find_default_config().directory)
        self.assertFalse((self.live / 'config-backups').exists())

    def test_recreated_clones_are_backed_up_and_edited_files_survive(self):
        self.player_config()
        self.write(self.configs / 'Elite Dangerous/Companion.yaml', 'name: Companion\n')
        self.write(self.configs / '_Star Citizen/Computer.yaml', 'name: Computer\n')
        manager = self.startup()
        self.assertEqual(['Elite Dangerous', 'Star Citizen'], sorted(c.name for c in manager.get_config_dirs()))
        self.assertEqual(1, sum(c.is_default for c in manager.get_config_dirs()))
        backup = next((self.live / 'config-backups').iterdir())
        self.assertTrue((backup / 'original/Elite Dangerous/Companion.yaml').exists())
        self.assertEqual('name: Customized\n', (self.configs / 'Star Citizen/Computer.yaml').read_text())
        self.startup()
        self.assertEqual(1, len(list((self.live / 'config-backups').iterdir())))

    def test_differing_duplicate_is_recovered_without_overwrite(self):
        self.player_config()
        self.write(self.configs / 'Elite Dangerous/Companion.yaml', 'name: MyOtherCompanion\n')
        manager = self.startup()
        self.assertTrue((self.configs / 'Elite Dangerous Recovered/Companion.yaml').exists())
        self.assertEqual('_Elite Dangerous', manager.get_config_dir('Elite Dangerous').directory)

    def test_deleted_directories_nested_folders_and_migration_snapshots(self):
        self.write(self.configs / '.Elite Dangerous/.Companion.yaml', 'name: Companion\n')
        self.write(self.configs / 'General/_Nested/metadata.txt', 'not a configuration')
        self.write(self.app / 'templates/migration/2_1_1/configs/Elite Dangerous/Companion.template.yaml', 'name: Frozen\n')
        manager = self.startup()
        self.assertFalse((self.configs / 'Elite Dangerous').exists())
        self.assertEqual('_Star Citizen', manager.find_default_config().directory)
        self.assertTrue((self.live / 'migration/2_1_1/configs/Elite Dangerous/Companion.yaml').exists())

    def test_default_switch_keeps_relative_identity_and_survives_restart(self):
        self.player_config()
        manager = self.startup()
        selected = manager.get_config_dir('Star Citizen')
        self.assertTrue(manager.set_default_config(selected))
        self.assertEqual('_Star Citizen', selected.directory)
        self.assertEqual('_Star Citizen', self.startup().find_default_config().directory)
        self.assertFalse((self.configs / '_Elite Dangerous').exists())

    def test_default_collision_refuses_before_any_move(self):
        self.player_config()
        manager = self.startup()
        self.write(self.configs / 'Elite Dangerous/Other.yaml', 'name: Other\n')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            manager.set_default_config(manager.get_config_dir('Star Citizen'))
        self.assertTrue((self.configs / '_Elite Dangerous/Copilot.yaml').exists())
        self.assertFalse((self.configs / 'Elite Dangerous/_Elite Dangerous').exists())

    def test_late_default_failure_rolls_back(self):
        self.player_config()
        manager = self.startup()
        original = Path.rename
        def rename(source, destination):
            if source.name == 'Star Citizen':
                raise OSError('disk failure')
            return original(source, destination)
        with patch.object(Path, 'rename', rename), self.assertRaises(OSError):
            manager.set_default_config(manager.get_config_dir('Star Citizen'))
        self.assertTrue((self.configs / '_Elite Dangerous/Copilot.yaml').exists())
        self.assertTrue((self.configs / 'Star Citizen').exists())

    def test_repair_preserves_default_role_when_edited_copy_has_no_prefix(self):
        self.write(self.configs / 'Star Citizen/Computer.yaml', 'name: Customized\n')
        self.write(self.configs / '_Star Citizen/Computer.yaml', 'name: Computer\n')
        manager = self.startup()
        self.assertEqual('_Star Citizen', manager.find_default_config().directory)
        self.assertEqual('name: Customized\n', (self.configs / '_Star Citizen/Computer.yaml').read_text())

    def test_repair_failure_rolls_back_all_directory_moves(self):
        self.player_config()
        self.write(self.configs / 'Elite Dangerous/Companion.yaml', 'name: Edited\n')
        original = Path.rename
        def rename(source, destination):
            if destination.name == 'Elite Dangerous Recovered':
                raise OSError('disk failure')
            return original(source, destination)
        with patch.object(Path, 'rename', rename), self.assertRaises(OSError):
            repair_config_directories(self.configs, self.templates)
        self.assertTrue((self.configs / '_Elite Dangerous/Copilot.yaml').exists())
        self.assertEqual('name: Edited\n', (self.configs / 'Elite Dangerous/Companion.yaml').read_text())

    def test_real_list_named_read_and_repeated_load_select_personal_profile(self):
        self.player_config()
        self.write(self.configs / 'Elite Dangerous/Companion.yaml', 'name: Companion\n')
        manager = self.startup()
        with patch('services.config_service.Printr', return_value=self.printr):
            service = ConfigService(manager)
        app = FastAPI()
        app.include_router(service.router)
        with TestClient(app) as client:
            configs = client.get('/configs').json()['config_dirs']
            self.assertEqual(1, sum(c['name'] == 'Elite Dangerous' for c in configs))
            for _ in range(2):
                for selected in configs:
                    response = client.post('/config', json=selected)
                    self.assertEqual(200, response.status_code, response.text)
                    self.assertEqual(selected['directory'], response.json()['config_dir']['directory'])
            response = client.get('/config', params={'config_name': 'Elite Dangerous'})
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual(['Copilot'], list(response.json()['config']['wingmen']))


if __name__ == '__main__':
    unittest.main()
