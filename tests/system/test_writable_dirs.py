"""Two threads asking for the same folder at once: the one that checks second
finds it created by the first between its check and its makedirs."""

import os
from types import SimpleNamespace

import services.file as file_module


def test_a_folder_created_meanwhile_is_no_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        file_module, "PlatformDirs", lambda **kwargs: SimpleNamespace(user_data_dir=str(tmp_path))
    )
    (tmp_path / "logs").mkdir()
    (tmp_path / "custom_skills").mkdir()
    # Not there yet when checked, created by the other thread right after.
    monkeypatch.setattr(
        file_module, "path", SimpleNamespace(join=os.path.join, exists=lambda p: False)
    )

    assert file_module.get_writable_dir("logs") == str(tmp_path / "logs")
    assert file_module.get_custom_skills_dir() == str(tmp_path / "custom_skills")
