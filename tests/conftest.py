"""Shared fixtures for config state / migration tests.

All filesystem roots (writable config dir, users dir, custom skills, audio
library) are redirected into pytest tmp directories. The real repo templates
are used, mirroring how main.py boots the app.
"""

import os
from os import path
import sys

import pytest

REPO_ROOT = path.abspath(path.join(path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

from services.module_manager import set_bundled_skills_dir  # noqa: E402
from services.system_manager import LOCAL_VERSION  # noqa: E402

VERSION_DIR = LOCAL_VERSION.replace(".", "_")

set_bundled_skills_dir(path.join(REPO_ROOT, "skills"))


@pytest.fixture
def users_dir(tmp_path, monkeypatch):
    """A fake APPDATA/WingmanAI directory. Patches all path helpers to use it."""
    users = tmp_path / "WingmanAI"
    users.mkdir()

    def fake_get_writable_dir(subdir: str = ""):
        base = str(users / VERSION_DIR)
        full_path = path.join(base, subdir) if subdir else base
        if not path.exists(full_path):
            os.makedirs(full_path)
        return full_path

    def fake_get_users_dir():
        return str(users)

    def fake_get_custom_skills_dir():
        p = users / "custom_skills"
        p.mkdir(exist_ok=True)
        return str(p)

    def fake_get_audio_library_dir():
        p = users / "audio_library"
        p.mkdir(exist_ok=True)
        return str(p)

    import services.config_manager as cm_module
    import services.config_migration_service as mig_module
    import services.migrations.migration_313_to_314 as mig_314_module

    monkeypatch.setattr(cm_module, "get_writable_dir", fake_get_writable_dir)
    monkeypatch.setattr(cm_module, "get_custom_skills_dir", fake_get_custom_skills_dir)
    monkeypatch.setattr(mig_module, "get_users_dir", fake_get_users_dir)
    monkeypatch.setattr(
        mig_module, "get_custom_skills_dir", fake_get_custom_skills_dir
    )
    monkeypatch.setattr(
        mig_module, "get_audio_library_dir", fake_get_audio_library_dir
    )
    monkeypatch.setattr(mig_314_module, "get_users_dir", fake_get_users_dir)

    return str(users)


@pytest.fixture
def boot_config_manager(users_dir):
    """Factory that boots a fresh ConfigManager like main.py does on start."""

    def _boot():
        from services.config_manager import ConfigManager

        return ConfigManager(REPO_ROOT)

    return _boot
