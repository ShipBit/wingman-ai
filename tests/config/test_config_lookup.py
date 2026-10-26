"""Looking up configs and their Wingmen.

A folder inside a config folder (a backup, a copy of another config) is no
part of it: its Wingmen showed up twice with the same name. A config name the
client still shows after a rename, or none at all, must not end in a crash.
"""

import asyncio
import os
import shutil
from os import path
from unittest.mock import AsyncMock, MagicMock

from services.config_service import ConfigService


def service_on(config_manager) -> ConfigService:
    service = ConfigService.__new__(ConfigService)
    service.config_manager = config_manager
    service.tower = None
    service.current_config_dir = None
    service.printr = MagicMock()
    service.config_events = MagicMock(publish=AsyncMock())
    return service


def copy_into_subfolder(config_manager, config_dir) -> None:
    folder = path.join(config_manager.config_dir, config_dir.directory)
    backup = path.join(folder, "backup")
    shutil.copytree(folder, backup)


def test_a_subfolder_adds_no_wingmen(boot_config_manager):
    config_manager = boot_config_manager()
    config_dir = config_manager.get_config_dir("Star Citizen")
    before = [w.name for w in config_manager.get_wingmen_configs(config_dir)]

    copy_into_subfolder(config_manager, config_dir)

    after = [w.name for w in config_manager.get_wingmen_configs(config_dir)]
    assert sorted(after) == sorted(before)
    assert len(after) == len(set(after))
    _dir, config = config_manager.parse_config(config_dir)
    assert sorted(config.wingmen) == sorted(before)


def test_a_wingman_only_in_a_subfolder_is_no_name_clash(boot_config_manager):
    config_manager = boot_config_manager()
    config_dir = config_manager.get_config_dir("Star Citizen")
    folder = path.join(config_manager.config_dir, config_dir.directory, "backup")
    os.makedirs(folder)
    with open(path.join(folder, "Old Friend.yaml"), "w", encoding="UTF-8") as f:
        f.write("name: Old Friend\n")

    assert not config_manager._wingman_name_exists_in_config_dir(config_dir, "Old Friend")
    assert config_manager._wingman_name_exists_in_config_dir(config_dir, "computer")


def test_wingmen_of_an_unknown_config_are_none(boot_config_manager):
    service = service_on(boot_config_manager())

    assert asyncio.run(service.get_wingmen_config_files("Renamed meanwhile")) == []


def test_no_config_name_loads_the_default_config(boot_config_manager):
    config_manager = boot_config_manager()
    service = service_on(config_manager)

    loaded = asyncio.run(service.get_config(""))

    assert loaded.config_dir == config_manager.find_default_config()
