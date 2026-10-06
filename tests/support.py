"""Paths and helpers shared by more than one test module.

Fixtures live in conftest.py. This module holds plain functions and constants,
so test modules import them explicitly instead of from conftest.
"""

import os
import shutil
from os import path
from types import SimpleNamespace

import yaml

from services.system_manager import LOCAL_VERSION

REPO_ROOT = path.dirname(path.dirname(path.abspath(__file__)))
TEMPLATES = path.join(REPO_ROOT, "templates", "configs")
FIXTURES = path.join(REPO_ROOT, "tests", "fixtures")
# The config folders a fresh install gets: General, Star Citizen and so on.
SHIPPED_CONFIGS = sorted(
    d for d in os.listdir(TEMPLATES) if path.isdir(path.join(TEMPLATES, d))
)
# The config folder name of the version under test, e.g. "3_2_5".
VERSION_DIR = LOCAL_VERSION.replace(".", "_")


def read_yaml(file_path: str):
    with open(file_path, "r", encoding="UTF-8") as f:
        return yaml.safe_load(f)


def write_yaml(file_path: str, content) -> None:
    with open(file_path, "w", encoding="UTF-8") as f:
        yaml.safe_dump(content, f)


def template(name: str):
    """A file from templates/configs, parsed."""
    return read_yaml(path.join(TEMPLATES, name))


def shipped_configs(without=(), plus=()) -> list[str]:
    """The shipped config folders, minus the ones the user deleted, plus their own."""
    return sorted((set(SHIPPED_CONFIGS) - set(without)) | set(plus))


def config_names(users_dir: str, version_dir: str = VERSION_DIR) -> list[str]:
    """The visible config folders of one version, sorted."""
    configs = path.join(users_dir, version_dir, "configs")
    return sorted(
        d
        for d in os.listdir(configs)
        if path.isdir(path.join(configs, d)) and not d.startswith(".")
    )


# ── an older install on disk ───────────────────────────────────────────


def make_old_version(users_dir: str, version_dir: str, config_dirs: dict) -> str:
    """Create the config folder an older Wingman left behind.

    `config_dirs` maps a folder name (legacy prefixes allowed) to its files:
    filename -> YAML content, or None to copy the shipped template wingman.
    settings.yaml and defaults.yaml are copied from the current templates.
    """
    old_configs = path.join(users_dir, version_dir, "configs")
    os.makedirs(old_configs)

    for filename in ("settings.yaml", "defaults.yaml"):
        shutil.copyfile(path.join(TEMPLATES, filename), path.join(old_configs, filename))

    # Every completed version has this marker. Without it the folder counts as
    # an interrupted migration.
    with open(path.join(old_configs, ".migration"), "w", encoding="UTF-8") as f:
        f.write(f"Version {version_dir} - test fixture\n")

    for dir_name, files in config_dirs.items():
        dir_path = path.join(old_configs, dir_name)
        os.makedirs(dir_path)
        for filename, content in files.items():
            file_path = path.join(dir_path, filename)
            if content is None:
                template_name = filename.lstrip(".").replace(".yaml", ".template.yaml")
                template_dir = dir_name.lstrip("._") or dir_name
                shutil.copyfile(path.join(TEMPLATES, template_dir, template_name), file_path)
            else:
                write_yaml(file_path, content)

    return old_configs


def migration_service(config_manager):
    from services.config_migration_service import ConfigMigrationService
    from services.system_manager import SystemManager

    return ConfigMigrationService(config_manager=config_manager, system_manager=SystemManager())


def boot_and_migrate(boot_config_manager):
    """Start the way main.py does: ConfigManager first, then the migrations."""
    config_manager = boot_config_manager()
    service = migration_service(config_manager)
    service.migrate_to_latest()
    return config_manager, service


# ── a ConfigManager over a plain folder ────────────────────────────────


class FakeConfigManager:
    """The few ConfigManager methods the voice and language helpers call,
    over `root/configs/<config>/<wingman>.yaml`."""

    def __init__(self, root):
        self.config_dir = str(root / "configs")

    def get_config_dirs(self):
        return [
            SimpleNamespace(name=d, directory=d)
            for d in sorted(os.listdir(self.config_dir))
            if path.isdir(path.join(self.config_dir, d))
        ]

    def get_wingmen_configs(self, config_dir):
        folder = path.join(self.config_dir, config_dir.directory)
        return [
            SimpleNamespace(name=f[:-5], file=f)
            for f in sorted(os.listdir(folder))
            if f.endswith(".yaml")
        ]

    def read_config(self, file_path):
        return read_yaml(file_path)

    def write_config(self, file_path, content):
        write_yaml(file_path, content)
        return True
