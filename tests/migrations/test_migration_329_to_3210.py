"""3.2.10: the "wingman" pronunciation list is switched on once."""

from unittest.mock import MagicMock

from services.migrations.migration_329_to_3210 import Migration329To3210
from tests.support import template


def migrate(settings):
    return Migration329To3210(MagicMock()).migrate_settings(settings)


def test_the_wingman_list_is_switched_on_next_to_the_users_lists():
    settings = migrate({"pronunciation": {"rules": [], "presets": ["star_citizen"]}})
    assert settings["pronunciation"]["presets"] == ["wingman", "star_citizen"]


def test_a_user_without_lists_gets_it_too_and_once():
    settings = migrate({"pronunciation": {"rules": [], "presets": []}})
    assert migrate(settings)["pronunciation"]["presets"] == ["wingman"]


def wingman_migration(template):
    service = MagicMock()
    service.current_wingman = ("Star Citizen", "Computer.yaml")
    migration = Migration329To3210(service)
    migration.shipped_template = lambda: template
    return migration


def test_an_untouched_computer_gets_the_ai_effect():
    template = {"sound": {"effects": ["AI"]}}
    assert wingman_migration(template).migrate_wingman({"name": "Computer"})["sound"] == {"effects": ["AI"]}


def test_effects_the_user_set_stay():
    template = {"sound": {"effects": ["AI"]}}
    mine = {"name": "Computer", "sound": {"effects": []}}
    assert wingman_migration(template).migrate_wingman(mine)["sound"] == {"effects": []}


def test_the_template_has_computer_speak_with_the_ai_effect():
    assert template("Star Citizen/Computer.template.yaml")["sound"]["effects"] == ["AI"]
