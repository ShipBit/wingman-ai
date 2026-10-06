"""End-to-end tests for the 3.1.3 -> 3.1.4 migration that converts the legacy
prefix-encoded config state ('_' = default, '.' = deleted) to context.yaml.

Each test builds a fake old 3_1_3 version directory (including the corrupted
states that the legacy bugs produced in the wild), then boots the app the way
main.py does: ConfigManager first (which copies templates), then
migrate_to_latest().
"""

import shutil
from os import listdir, path

from tests.support import (
    VERSION_DIR,
    boot_and_migrate,
    config_names,
    make_old_version,
    read_yaml,
    shipped_configs,
)

OLD_VERSION_DIR = "3_1_3"


def make_313(users_dir, config_dirs):
    return make_old_version(users_dir, OLD_VERSION_DIR, config_dirs)


def migrate(boot_config_manager):
    config_manager, _ = boot_and_migrate(boot_config_manager)
    return config_manager


def read_context(users_dir):
    return read_yaml(path.join(users_dir, VERSION_DIR, "configs", "context.yaml"))


def test_default_switched_user(users_dir, boot_config_manager):
    """User made General the default: old dirs are 'Star Citizen' + '_General'."""
    make_313(
        users_dir,
        {
            "Star Citizen": {"Computer.yaml": None, "ATC.yaml": None},
            "_General": {"Clippy.yaml": None},
        },
    )

    cm = migrate(boot_config_manager)

    assert config_names(users_dir) == shipped_configs()
    assert cm.find_default_config().name == "General"
    assert read_context(users_dir)["default_config"] == "General"


def test_deleted_config_stays_deleted_and_is_archived(
    users_dir, boot_config_manager
):
    """User deleted Star Citizen: old dirs are '.Star Citizen' + '_General'."""
    make_313(
        users_dir,
        {
            ".Star Citizen": {"Computer.yaml": None},
            "_General": {"Clippy.yaml": None},
        },
    )

    cm = migrate(boot_config_manager)

    assert config_names(users_dir) == shipped_configs(without=["Star Citizen"])
    context = read_context(users_dir)
    assert context["default_config"] == "General"
    assert "Star Citizen" in context["deleted_template_configs"]

    # content was archived, not destroyed
    archive = path.join(users_dir, "archived_configs", "pre_3_1_4", "Star Citizen")
    assert path.exists(path.join(archive, "Computer.yaml"))

    # a restart does not resurrect it
    boot_config_manager()
    assert config_names(users_dir) == shipped_configs(without=["Star Citizen"])
    assert cm.find_default_config().name == "General"


def test_duplicated_configs_are_both_kept(users_dir, boot_config_manager):
    """The legacy duplication bug: both 'Star Citizen' and '_Star Citizen'
    exist. Both must survive; the prefixed one becomes 'Star Citizen (2)'."""
    make_313(
        users_dir,
        {
            "Star Citizen": {
                "Computer.yaml": {"name": "Computer", "description": "user's own"}
            },
            "_Star Citizen": {"Computer.yaml": None},
            "General": {"Clippy.yaml": None},
        },
    )

    cm = migrate(boot_config_manager)

    assert config_names(users_dir) == shipped_configs(plus=["Star Citizen (2)"])
    # the legacy default flag carries over to the renamed duplicate
    assert cm.find_default_config().name == "Star Citizen (2)"

    # no tombstone: live dirs exist
    assert read_context(users_dir)["deleted_template_configs"] == []

    # a restart neither duplicates nor deletes anything
    boot_config_manager()
    assert config_names(users_dir) == shipped_configs(plus=["Star Citizen (2)"])


def test_corrupted_underscore_dot_dir(users_dir, boot_config_manager):
    """The legacy resurrection bug produced dirs like '_.Star Citizen'."""
    make_313(
        users_dir,
        {
            "_.Star Citizen": {"Computer.yaml": None},
            "General": {"Clippy.yaml": None},
        },
    )

    cm = migrate(boot_config_manager)

    assert config_names(users_dir) == shipped_configs()
    assert cm.find_default_config().name == "Star Citizen"


def test_deleted_wingman_marker_becomes_tombstone(users_dir, boot_config_manager):
    """User logically deleted a wingman: '.Computer.yaml' marker in the dir."""
    make_313(
        users_dir,
        {
            "_Star Citizen": {
                "ATC.yaml": None,
                ".Computer.yaml": {"name": "Computer"},
            },
            "General": {"Clippy.yaml": None},
        },
    )

    cm = migrate(boot_config_manager)

    star_citizen_dir = path.join(users_dir, VERSION_DIR, "configs", "Star Citizen")
    files = sorted(f for f in listdir(star_citizen_dir) if f.endswith(".yaml"))
    assert "Computer.yaml" not in files
    assert ".Computer.yaml" not in files
    assert "ATC.yaml" in files

    context = read_context(users_dir)
    assert context["deleted_template_wingmen"] == {"Star Citizen": ["Computer"]}

    # a restart does not resurrect the wingman
    boot_config_manager()
    files = sorted(f for f in listdir(star_citizen_dir) if f.endswith(".yaml"))
    assert "Computer.yaml" not in files

    assert cm.find_default_config().name == "Star Citizen"


def test_multi_step_migration_from_3_1_2(users_dir, boot_config_manager):
    """A user jumping 3.1.2 -> 3.1.4 goes through the intermediate 3.1.3 step.
    Legacy state must convert exactly like in the single-step case."""
    old_configs = make_313(
        users_dir,
        {
            ".Star Citizen": {"Computer.yaml": None},
            "_General": {"Clippy.yaml": None},
        },
    )
    # relocate the fake old version from 3_1_3 to 3_1_2
    shutil.move(
        path.join(users_dir, OLD_VERSION_DIR),
        path.join(users_dir, "3_1_2"),
    )
    assert not path.exists(old_configs)

    cm = migrate(boot_config_manager)

    assert config_names(users_dir) == shipped_configs(without=["Star Citizen"])
    context = read_context(users_dir)
    assert context["default_config"] == "General"
    assert "Star Citizen" in context["deleted_template_configs"]
    assert cm.find_default_config().name == "General"


def test_migration_marker_prevents_rerun(users_dir, boot_config_manager):
    make_313(
        users_dir,
        {
            "Star Citizen": {"Computer.yaml": None},
            "_General": {"Clippy.yaml": None},
        },
    )

    migrate(boot_config_manager)
    # second full boot incl. migration service: must be a no-op
    migrate(boot_config_manager)

    assert config_names(users_dir) == shipped_configs()
    assert read_context(users_dir)["default_config"] == "General"
