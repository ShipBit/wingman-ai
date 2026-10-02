"""A skill switched on in the menu ran, but the menu showed it off again after
leaving and re-entering.

`save_wingman_config` merges a partial payload over what is on disk and keeps
the disk value for any field the caller did not set. Pydantic counts a field
as set only when it is assigned or was present in the parsed YAML, so
`discoverable_skills.append(...)` marked nothing: for a Wingman whose file
never had the key, the toggle reached memory only.

The toggles therefore assign the whole list. These tests run the real toggle
methods and check that what reaches the save is marked as set.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api.interface import WingmanConfig
from services.config_manager import deep_merge_configs
from services.config_service import ConfigService
from tests.support import template

# A Wingman file without `discoverable_skills` or `discoverable_mcps`.
WINGMAN = {"name": "Computer", "description": "test", "record_key": "end"}


def toggled(method: str, name: str, enabled: bool, on_disk: dict) -> WingmanConfig:
    """Run one toggle and return the config it handed to the save."""
    service = ConfigService.__new__(ConfigService)
    service.config_manager = MagicMock()
    service.config_manager.load_wingman_config.return_value = WingmanConfig(
        **deep_merge_configs(template("defaults.yaml"), on_disk)
    )
    service.tower = None
    service.printr = MagicMock()
    saved = []

    async def save_wingman_config(config_dir, wingman_file, wingman_config, silent=False):
        saved.append(wingman_config)

    service.save_wingman_config = save_wingman_config
    asyncio.run(
        getattr(service, method)(
            SimpleNamespace(directory="c"), SimpleNamespace(name="Computer", file="Computer.yaml"), name, enabled
        )
    )
    return saved[0]


@pytest.mark.parametrize(
    "method, field",
    [("toggle_wingman_skill", "discoverable_skills"), ("toggle_wingman_mcp", "discoverable_mcps")],
)
def test_switching_on_survives_the_save_merge(method, field):
    config = toggled(method, "HUD", True, WINGMAN)
    assert config.model_dump(exclude_unset=True)[field] == ["HUD"]


def test_switching_off_the_last_one_saves_an_empty_list():
    config = toggled("toggle_wingman_skill", "Timer", False, {**WINGMAN, "discoverable_skills": ["Timer"]})
    assert config.model_dump(exclude_unset=True)["discoverable_skills"] == []


def test_switching_on_twice_adds_it_once():
    config = toggled("toggle_wingman_skill", "Timer", True, {**WINGMAN, "discoverable_skills": ["Timer"]})
    assert config.discoverable_skills == ["Timer"]
