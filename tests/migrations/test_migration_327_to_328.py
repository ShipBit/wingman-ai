"""3.2.8: the Star Citizen folder moves from the log reader to its own
`star_citizen` block, and every user is asked once whether they play."""

from unittest.mock import MagicMock

from services.migrations.migration_327_to_328 import Migration327To328
from services.star_citizen.game_folder import DEFAULT_GAME_PATH
from tests.support import template


def migrate(settings: dict) -> dict:
    return Migration327To328(MagicMock()).migrate_settings(settings)


def test_the_folder_moves_out_of_the_log_reader():
    out = migrate({"sc_gamelog": {"enabled": False, "game_path": "D:\\StarCitizen"}})
    assert out["sc_gamelog"] == {"enabled": False}
    assert out["star_citizen"] == {"plays": None, "game_path": "D:\\StarCitizen"}


def test_without_a_folder_the_default_is_used():
    assert migrate({})["star_citizen"]["game_path"] == DEFAULT_GAME_PATH


def test_a_star_citizen_block_that_is_there_is_kept():
    mine = {"plays": False, "game_path": "E:\\SC"}
    assert migrate({"star_citizen": dict(mine)})["star_citizen"] == mine


def test_the_template_asks_and_keeps_the_folder_in_one_place():
    settings = template("settings.yaml")
    assert settings["star_citizen"]["plays"] is None
    assert "game_path" not in settings["sc_gamelog"]
