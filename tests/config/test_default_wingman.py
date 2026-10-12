"""The ⭐ Wingman could not be set again once it was switched off.

The star only updates one copy of the config in the client. The chat input and
the edit page save their own, older copies, which still held the previous
value, so the next volume or model change put the old default back.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from api.interface import WingmanConfig
from services.config_service import ConfigService


def service_on(config_manager) -> ConfigService:
    service = ConfigService.__new__(ConfigService)
    service.config_manager = config_manager
    service.tower = None
    service.current_config_dir = None
    service.printr = MagicMock()
    service.config_events = MagicMock(publish=AsyncMock())
    return service


def defaults(config_manager, config_dir) -> dict:
    _dir, config = config_manager.parse_config(config_dir)
    return {
        name: bool(wingman.is_voice_activation_default)
        for name, wingman in config.wingmen.items()
    }


def click_star(service, config_dir, name):
    asyncio.run(service.set_default_wingman(config_dir, name))


def test_star_switches_the_default_off_and_on_again(boot_config_manager):
    config_manager = boot_config_manager()
    service = service_on(config_manager)
    config_dir = config_manager.get_config_dir("Star Citizen")

    click_star(service, config_dir, "Computer")
    click_star(service, config_dir, "Computer")
    assert defaults(config_manager, config_dir) == {"ATC": False, "Computer": False}

    click_star(service, config_dir, "Computer")
    assert defaults(config_manager, config_dir) == {"ATC": False, "Computer": True}

    click_star(service, config_dir, "ATC")
    assert defaults(config_manager, config_dir) == {"ATC": True, "Computer": False}


def test_saving_an_older_copy_keeps_the_star(boot_config_manager):
    config_manager = boot_config_manager()
    service = service_on(config_manager)
    config_dir = config_manager.get_config_dir("Star Citizen")
    _dir, config = config_manager.parse_config(config_dir)
    # What the client sends back: every field, the old default included.
    older_copy = WingmanConfig.model_validate(
        config.wingmen["Computer"].model_dump(mode="json")
    )
    wingman_file = next(
        f for f in config_manager.get_wingmen_configs(config_dir) if f.name == "Computer"
    )

    click_star(service, config_dir, "Computer")
    older_copy.sound.volume = 0.5
    asyncio.run(
        service.save_wingman_config(
            config_dir=config_dir, wingman_file=wingman_file, wingman_config=older_copy
        )
    )

    _dir, config = config_manager.parse_config(config_dir)
    assert config.wingmen["Computer"].is_voice_activation_default
    assert config.wingmen["Computer"].sound.volume == 0.5
