"""Seeding the vocabulary must land in the settings object that gets saved,
also when a migration at start has replaced that object."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from services.settings_service import SettingsService


def _settings(user_name=None):
    return SimpleNamespace(stt=SimpleNamespace(vocabulary=[]), user_name=user_name, audio=None)


def _service():
    manager = MagicMock()
    manager.settings_config = _settings()
    manager.config_dir = "/configs"
    manager.get_config_dirs.return_value = [SimpleNamespace(directory="c1", is_deleted=False)]
    manager.get_wingmen_configs.return_value = [
        SimpleNamespace(file="computer.yaml", name="Computer", is_deleted=False)
    ]
    manager.read_config.return_value = {"name": "Computer"}
    service = SettingsService.__new__(SettingsService)
    service.config_manager = manager
    service.printr = MagicMock()
    # Wired by WingmanCore; the broadcast is not what these tests are about.
    service.vocabulary_changed_callback = None
    return service, manager


def test_seed_writes_into_the_settings_that_are_saved():
    service, manager = _service()
    # what the migration does after the service was created
    manager.settings_config = _settings(user_name="Sam")
    assert service.seed_vocabulary() == ["Computer", "Sam"]
    assert manager.settings_config.stt.vocabulary == ["Computer", "Sam"]
    manager.save_settings_config.assert_called_once()
    # a second run adds nothing
    assert service.seed_vocabulary() == []
