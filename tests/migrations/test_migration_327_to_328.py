"""3.2.8: the Star Citizen folder moves from the log reader to its own
`star_citizen` block, and every user is asked once whether they play.
System One (Jev) is off for everyone and has to be switched on."""

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


def test_system_one_is_switched_off():
    out = migrate({"system_one": {"enabled": True, "commands": True}})
    assert out["system_one"]["enabled"] is False


def test_the_command_switch_keeps_the_users_choice():
    out = migrate({"system_one": {"enabled": True, "commands": False}})
    assert out["system_one"] == {"enabled": False, "commands": False}


def test_a_missing_system_one_block_is_written_switched_off():
    assert migrate({})["system_one"] == {"enabled": False, "commands": True}


def test_the_template_starts_with_system_one_off():
    assert template("settings.yaml")["system_one"]["enabled"] is False
