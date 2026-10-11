"""A Wingman switched off in the client kept answering.

The client saves the config with `disabled: true`. The save only wrote the flag
into the running Wingman's config, but the Tower routes by its list of Wingmen
and never looks at the flag, so the Wingman stayed in the list and kept
listening and speaking until the next restart.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from api.interface import WingmanConfig
from services.config_manager import deep_merge_configs
from services.config_service import ConfigService
from services.tower import Tower
from tests.support import template

WINGMAN = {"name": "Computer", "description": "test", "record_key": "end"}


def config(**fields) -> WingmanConfig:
    return WingmanConfig(**deep_merge_configs(template("defaults.yaml"), {**WINGMAN, **fields}))


def running_wingman(wingman_config: WingmanConfig):
    return SimpleNamespace(
        name="Computer",
        config=wingman_config,
        unload=AsyncMock(),
        unload_mcps=AsyncMock(),
        update_config=AsyncMock(return_value=True),
    )


def service_with(tower: Tower, on_disk: WingmanConfig) -> ConfigService:
    service = ConfigService.__new__(ConfigService)
    service.config_manager = MagicMock()
    service.config_manager.load_wingman_config.return_value = on_disk
    service.tower = tower
    service.printr = MagicMock()
    service.config_events = MagicMock(publish=AsyncMock())
    return service


def tower_with(*wingmen) -> Tower:
    tower = Tower.__new__(Tower)
    tower.wingmen = list(wingmen)
    tower.disabled_wingmen = []
    tower.log_source_name = "Tower"
    return tower


def save(service: ConfigService, wingman_config: WingmanConfig):
    asyncio.run(
        service.save_wingman_config(
            SimpleNamespace(directory="c"),
            SimpleNamespace(name="Computer", file="Computer.yaml"),
            wingman_config,
        )
    )


def test_switching_off_takes_the_wingman_out_of_the_tower():
    wingman = running_wingman(config())
    tower = tower_with(wingman)
    service = service_with(tower, config())

    save(service, config(disabled=True))

    assert tower.get_wingman_by_name("Computer") is None
    assert tower.get_wingman_from_text("Computer, open the map") is None
    assert tower.get_disabled_wingman_by_name("Computer") is wingman.config
    wingman.unload.assert_awaited_once()
    wingman.unload_mcps.assert_awaited_once()
    assert service.config_manager.save_wingman_config.call_args.kwargs["wingman_config"].disabled


def test_editing_a_switched_off_wingman_is_saved():
    tower = tower_with()
    tower.disabled_wingmen.append(config(disabled=True))
    service = service_with(tower, config(disabled=True))

    save(service, config(disabled=True, description="changed"))

    service.printr.toast_error.assert_not_called()
    saved = service.config_manager.save_wingman_config.call_args.kwargs["wingman_config"]
    assert saved.description == "changed"
    assert tower.wingmen == []
