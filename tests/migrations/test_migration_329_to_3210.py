"""3.2.10: the "wingman" pronunciation list is switched on once."""

from unittest.mock import MagicMock

from services.migrations.migration_329_to_3210 import Migration329To3210


def migrate(settings):
    return Migration329To3210(MagicMock()).migrate_settings(settings)


def test_the_wingman_list_is_switched_on_next_to_the_users_lists():
    settings = migrate({"pronunciation": {"rules": [], "presets": ["star_citizen"]}})
    assert settings["pronunciation"]["presets"] == ["wingman", "star_citizen"]


def test_a_user_without_lists_gets_it_too_and_once():
    settings = migrate({"pronunciation": {"rules": [], "presets": []}})
    assert migrate(settings)["pronunciation"]["presets"] == ["wingman"]
