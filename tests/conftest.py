"""Fixtures for tests that boot the config system.

Every place Core writes to (the version's config folder, custom skills, the
audio and lore libraries) is redirected into a pytest tmp folder. The real
templates from the repository are used, the same way main.py boots the app.
"""

import os
from os import path

import pytest

from services.module_manager import set_bundled_skills_dir
from tests.support import REPO_ROOT, VERSION_DIR

set_bundled_skills_dir(path.join(REPO_ROOT, "skills"))


@pytest.fixture
def users_dir(tmp_path, monkeypatch):
    """A fake APPDATA/WingmanAI folder. All path helpers point into it."""
    users = tmp_path / "WingmanAI"
    users.mkdir()

    def fake_get_writable_dir(subdir: str = ""):
        base = str(users / VERSION_DIR)
        full_path = path.join(base, subdir) if subdir else base
        os.makedirs(full_path, exist_ok=True)
        return full_path

    def fake_get_users_dir():
        return str(users)

    def subfolder(name):
        def get():
            folder = users / name
            folder.mkdir(exist_ok=True)
            return str(folder)

        return get

    import services.config_manager as cm_module
    import services.config_migration_service as mig_module
    import services.file as file_module
    import services.migrations.migration_313_to_314 as mig_314_module

    monkeypatch.setattr(cm_module, "get_writable_dir", fake_get_writable_dir)
    monkeypatch.setattr(cm_module, "get_custom_skills_dir", subfolder("custom_skills"))
    monkeypatch.setattr(mig_module, "get_users_dir", fake_get_users_dir)
    monkeypatch.setattr(mig_module, "get_custom_skills_dir", subfolder("custom_skills"))
    monkeypatch.setattr(mig_module, "get_audio_library_dir", subfolder("audio_library"))
    monkeypatch.setattr(mig_314_module, "get_users_dir", fake_get_users_dir)
    monkeypatch.setattr(
        file_module, "get_lore_library_dir", subfolder("lore_library"), raising=False
    )

    return str(users)


@pytest.fixture
def boot_config_manager(users_dir):
    """Factory that boots a fresh ConfigManager like main.py does on start."""

    def _boot():
        from services.config_manager import ConfigManager

        return ConfigManager(REPO_ROOT)

    return _boot
