"""3.2.8: the Star Citizen folder moves from the log reader to its own
`star_citizen` block, and every user is asked once whether they play.
System One (Jev) is off for everyone and has to be switched on.

The Computer called the user "Pilot" or "Commander" in nearly every reply and
made up ship status. 3.2.8 ships a new Computer backstory and a system prompt
line against it. The backstory reaches users who never edited theirs; an
edited one is kept.
"""

from os import path
from unittest.mock import MagicMock

from services.migrations.migration_327_to_328 import (
    OLD_COMPUTER_BACKSTORY,
    Migration327To328,
)
from services.star_citizen.game_folder import DEFAULT_GAME_PATH
from tests.support import TEMPLATES, read_yaml, template

COMPUTER = path.join("Star Citizen", "Computer.template.yaml")


def migrate(settings: dict) -> dict:
    return Migration327To328(MagicMock()).migrate_settings(settings)


def _migration() -> Migration327To328:
    service = MagicMock()
    service.current_wingman = None
    service.templates_dir = path.dirname(TEMPLATES)
    service.config_manager.read_config = read_yaml
    return Migration327To328(service)


def _computer(backstory: str) -> dict:
    wingman = template(COMPUTER)
    wingman["prompts"]["backstory"] = backstory
    return wingman


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


def test_the_shipped_old_backstory_is_replaced():
    out = _migration().migrate_wingman(_computer(OLD_COMPUTER_BACKSTORY))
    assert out["prompts"]["backstory"] == template(COMPUTER)["prompts"]["backstory"]


def test_a_reflowed_old_backstory_is_still_recognised():
    # The client saves it back as a folded single-quoted YAML string.
    reflowed = OLD_COMPUTER_BACKSTORY.replace("\n", "\n\n").strip()
    out = _migration().migrate_wingman(_computer(reflowed))
    assert out["prompts"]["backstory"] == template(COMPUTER)["prompts"]["backstory"]


def test_an_edited_backstory_is_kept():
    edited = OLD_COMPUTER_BACKSTORY + "- Call me Captain\n"
    out = _migration().migrate_wingman(_computer(edited))
    assert out["prompts"]["backstory"] == edited


def test_a_wingman_system_prompt_override_is_dropped():
    wingman = _computer("Your name is Bob.")
    wingman["prompts"]["system_prompt"] = "old contract"
    out = _migration().migrate_wingman(wingman)
    assert "system_prompt" not in out["prompts"]
    assert out["prompts"]["backstory"] == "Your name is Bob."


def test_defaults_get_the_shipped_system_prompt():
    defaults = template("defaults.yaml")
    defaults["prompts"]["system_prompt"] = "old contract"
    out = _migration().migrate_defaults(defaults)
    assert out["prompts"]["system_prompt"] == template("defaults.yaml")["prompts"]["system_prompt"]
