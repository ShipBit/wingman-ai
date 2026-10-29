"""3.2.13: Jev gets a switch per place it decides. The new ones start on, so
whoever had Jev on keeps every decision it took before."""

from unittest.mock import MagicMock

from services.migrations.migration_3212_to_3213 import Migration3212To3213


def migrate(settings: dict) -> dict:
    return Migration3212To3213(MagicMock()).migrate_settings(settings)


def test_the_new_switches_start_on():
    out = migrate({"system_one": {"enabled": True, "commands": False}})
    assert out["system_one"] == {
        "enabled": True,
        "commands": False,
        "wingman_choice": True,
        "vocabulary": True,
        "skills": True,
    }


def test_a_switch_that_is_there_is_kept():
    out = migrate({"system_one": {"enabled": False, "commands": True, "skills": False}})
    assert out["system_one"]["skills"] is False
