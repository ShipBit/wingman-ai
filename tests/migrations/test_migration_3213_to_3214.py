"""3.2.14: the decision model gets a provider, and `system_one` becomes
`decision_model`. Existing configs keep Wingman Pro and every switch."""

from os import path
from unittest.mock import MagicMock

from api.interface import DecisionModelSettings
from services.migrations.migration_3213_to_3214 import Migration3213To3214
from tests.support import REPO_ROOT, template

SWITCHES = {"enabled": True, "commands": False, "wingman_choice": True, "vocabulary": False, "skills": True}


def _migrate(settings: dict) -> dict:
    service = MagicMock()
    service.templates_dir = path.join(REPO_ROOT, "templates")
    return Migration3213To3214(service).migrate_settings(settings)


def test_the_switches_move_over_and_the_provider_stays_wingman_pro():
    migrated = _migrate({"system_one": dict(SWITCHES)})
    assert "system_one" not in migrated
    block = migrated["decision_model"]
    assert {key: block[key] for key in SWITCHES} == SWITCHES
    assert block["provider"] == "wingman_pro"
    DecisionModelSettings(**block)


def test_the_users_switches_win_over_a_block_the_load_repair_wrote():
    repaired = template("settings.yaml")["decision_model"]
    migrated = _migrate({"system_one": dict(SWITCHES), "decision_model": repaired})
    assert migrated["decision_model"]["commands"] is False
    assert migrated["decision_model"]["vocabulary"] is False


def test_a_provider_already_chosen_is_kept():
    migrated = _migrate({
        "decision_model": {
            **SWITCHES,
            "provider": "server",
            "server": {"endpoint": "http://127.0.0.1:8000/v1"},
        }
    })
    block = migrated["decision_model"]
    assert block["provider"] == "server"
    assert block["server"] == {"endpoint": "http://127.0.0.1:8000/v1", "model": ""}

