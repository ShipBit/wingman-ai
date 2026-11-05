"""A renamed Wingman answered to its new name at once, but the chat and the
HUD showed the old one until a restart: the running Wingman keeps the name it
was built with. A rename builds the config again."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from api.interface import WingmanConfig
from services.config_manager import deep_merge_configs
from services.config_service import ConfigService
from tests.support import template

CONFIG_DIR = SimpleNamespace(name="c", directory="c")


def config(**fields) -> WingmanConfig:
    base = {"name": "ATC", "description": "test", "record_bindings": []}
    return WingmanConfig(**deep_merge_configs(template("defaults.yaml"), {**base, **fields}))


def service_with_running(wingman_config: WingmanConfig) -> tuple[ConfigService, SimpleNamespace]:
    wingman = SimpleNamespace(
        name=wingman_config.name,
        config=wingman_config,
        update_config=AsyncMock(return_value=True),
    )
    service = ConfigService.__new__(ConfigService)
    service.config_manager = MagicMock()
    service.config_manager.load_wingman_config.return_value = wingman_config
    service.tower = SimpleNamespace(
        get_wingman_by_name=lambda name: wingman if wingman.config.name == name else None
    )
    service.current_config_dir = CONFIG_DIR
    service.printr = MagicMock()
    service.config_events = MagicMock(publish=AsyncMock())
    service.load_config = AsyncMock()
    return service, wingman


def save(service: ConfigService, wingman_config: WingmanConfig):
    asyncio.run(
        service.save_wingman_config(
            CONFIG_DIR, SimpleNamespace(name="ATC", file="ATC.yaml"), wingman_config
        )
    )


def test_a_rename_builds_the_wingmen_again():
    service, wingman = service_with_running(config())

    save(service, config(name="Tower"))

    saved = service.config_manager.save_wingman_config.call_args.kwargs["wingman_config"]
    assert saved.name == "Tower"
    service.load_config.assert_awaited_once_with(CONFIG_DIR)
    wingman.update_config.assert_not_called()


def test_an_edit_without_rename_updates_the_running_wingman():
    service, wingman = service_with_running(config())

    save(service, config(description="changed"))

    service.load_config.assert_not_called()
    wingman.update_config.assert_awaited_once()
