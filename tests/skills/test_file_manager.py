"""File Manager paths: the model picks any folder the user asks for, but it
cannot climb out of a folder by file name, read key files, drop scripts
outside the default directory or write into Wingman's own folders."""

import asyncio
import os
import zipfile
from pathlib import Path

import pytest

from skills.file_manager import main as file_manager


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def skill(tmp_path, monkeypatch):
    home = tmp_path / "home"
    wingman_dir = home / "WingmanAI"
    default_dir = wingman_dir / "generated_files" / "FileManager"
    default_dir.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)

    skill = file_manager.FileManager.__new__(file_manager.FileManager)
    skill.get_generated_files_dir = lambda: str(default_dir)
    skill.allowed_file_extensions = file_manager.SUPPORTED_FILE_EXTENSIONS
    skill.default_file_extension = "txt"
    skill.max_text_size = file_manager.DEFAULT_MAX_TEXT_SIZE
    skill._get_default_directory = lambda: str(default_dir)
    skill._get_allow_overwrite_existing = lambda: False
    skill.home = home
    skill.wingman_dir = wingman_dir
    skill.default_dir = default_dir
    return skill


def test_a_file_anywhere_the_user_names_can_still_be_read_and_saved(skill, tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    (documents / "notes.txt").write_text("fuel at 40 percent")

    assert "fuel at 40 percent" in _run(skill.load_text_from_file("notes.txt", str(documents)))
    assert "saved" in _run(skill.save_text_to_file("log.md", "landed", str(documents)))
    assert (documents / "log.md").read_text() == "landed"


@pytest.mark.parametrize("name", ["../secret.txt", "a/../../secret.txt", "/etc/hosts.txt"])
def test_a_file_name_cannot_leave_its_directory(skill, tmp_path, name):
    (tmp_path / "secret.txt").write_text("do not read")

    assert "must not contain a path" in _run(skill.load_text_from_file(name, str(skill.default_dir)))
    assert "must not contain a path" in _run(skill.save_text_to_file(name, "x", str(skill.default_dir)))


def test_key_files_are_never_loaded(skill, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text("API_KEY=abc")
    (project / "readme.md").write_text("hello")
    config_dir = skill.wingman_dir / "3_2_9"
    config_dir.mkdir()
    (config_dir / "secrets.yaml").write_text("openai: sk-123")

    assert "cannot be loaded" in _run(skill.load_text_from_file(".env", str(project)))
    assert "cannot be loaded" in _run(skill.load_text_from_file("secrets.yaml", str(config_dir)))

    folder = _run(skill.load_folder_contents(str(project)))
    assert "hello" in folder
    assert "API_KEY" not in folder


def test_scripts_are_saved_only_in_the_default_directory(skill, tmp_path):
    desktop = tmp_path / "Desktop"

    assert "Script files" in _run(skill.save_text_to_file("run.bat", "del *", str(desktop)))
    assert not desktop.exists()
    assert "saved" in _run(skill.save_text_to_file("run.bat", "echo hi", None))
    assert (skill.default_dir / "run.bat").exists()


def test_wingmans_own_folders_are_protected_except_generated_files(skill):
    configs = skill.wingman_dir / "3_2_9" / "configs"

    assert "not allowed" in _run(skill.save_text_to_file("evil.yaml", "a: 1", str(configs)))
    assert "not allowed" in _run(skill.create_folder("x", str(configs)))
    assert not configs.exists()

    other_skill = skill.wingman_dir / "generated_files" / "Other"
    assert "saved" in _run(skill.save_text_to_file("ok.txt", "fine", str(other_skill)))


def test_a_zip_cannot_carry_a_script_out_of_the_default_directory(skill, tmp_path):
    archive = skill.default_dir / "pack.zip"
    with zipfile.ZipFile(archive, "w") as zip_ref:
        zip_ref.writestr("readme.txt", "hi")
        zip_ref.writestr("start.ps1", "evil")
    target = tmp_path / "Desktop"

    assert "Extraction cancelled" in _run(skill.extract_zip(str(archive), str(target)))
    assert not (target / "start.ps1").exists()

    inside = skill.default_dir / "unpacked"
    assert "Extracted" in _run(skill.extract_zip(str(archive), str(inside)))
    assert os.path.isfile(inside / "start.ps1")
