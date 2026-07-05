"""End-to-end tests for the 3.1.3 -> 3.1.4 migration that converts the legacy
prefix-encoded config state ('_' = default, '.' = deleted) to .context.yaml.

Each test builds a fake old 3_1_3 version directory (including the corrupted
states that the legacy bugs produced in the wild), then boots the app the way
main.py does: ConfigManager first (which copies templates), then
migrate_to_latest().
"""

import shutil
from os import listdir, makedirs, path

import yaml

from tests.conftest import REPO_ROOT, VERSION_DIR

OLD_VERSION_DIR = "3_1_3"
TEMPLATES = path.join(REPO_ROOT, "templates", "configs")


def make_old_version(users_dir, config_dirs: dict):
    """Create a fake 3_1_3 config directory.

    config_dirs maps directory name (with legacy prefixes) to a dict of
    filename -> yaml content (or None to copy the real template wingman).
    """
    old_configs = path.join(users_dir, OLD_VERSION_DIR, "configs")
    makedirs(old_configs)

    # top-level files from the real templates (valid current-schema content)
    for filename in ("settings.yaml", "defaults.yaml"):
        shutil.copyfile(
            path.join(TEMPLATES, filename), path.join(old_configs, filename)
        )

    for dir_name, files in config_dirs.items():
        dir_path = path.join(old_configs, dir_name)
        makedirs(dir_path)
        for filename, content in files.items():
            file_path = path.join(dir_path, filename)
            if content is None:
                template_name = filename.lstrip(".").replace(
                    ".yaml", ".template.yaml"
                )
                template_dir = dir_name.lstrip("._") or dir_name
                shutil.copyfile(
                    path.join(TEMPLATES, template_dir, template_name), file_path
                )
            else:
                with open(file_path, "w", encoding="UTF-8") as f:
                    yaml.safe_dump(content, f)

    return old_configs


def boot_and_migrate(boot_config_manager):
    from services.config_migration_service import ConfigMigrationService
    from services.system_manager import SystemManager

    config_manager = boot_config_manager()
    migration_service = ConfigMigrationService(
        config_manager=config_manager,
        system_manager=SystemManager(),
    )
    migration_service.migrate_to_latest()
    return config_manager


def new_config_names(users_dir):
    configs = path.join(users_dir, VERSION_DIR, "configs")
    return sorted(
        d
        for d in listdir(configs)
        if path.isdir(path.join(configs, d)) and not d.startswith(".")
    )


def read_context(users_dir):
    with open(
        path.join(users_dir, VERSION_DIR, "configs", ".context.yaml"),
        "r",
        encoding="UTF-8",
    ) as f:
        return yaml.safe_load(f)


def test_default_switched_user(users_dir, boot_config_manager):
    """User made General the default: old dirs are 'Star Citizen' + '_General'."""
    make_old_version(
        users_dir,
        {
            "Star Citizen": {"Computer.yaml": None, "ATC.yaml": None},
            "_General": {"Clippy.yaml": None},
        },
    )

    cm = boot_and_migrate(boot_config_manager)

    assert new_config_names(users_dir) == ["General", "Star Citizen"]
    assert cm.find_default_config().name == "General"
    assert read_context(users_dir)["default_config"] == "General"


def test_deleted_config_stays_deleted_and_is_archived(
    users_dir, boot_config_manager
):
    """User deleted Star Citizen: old dirs are '.Star Citizen' + '_General'."""
    make_old_version(
        users_dir,
        {
            ".Star Citizen": {"Computer.yaml": None},
            "_General": {"Clippy.yaml": None},
        },
    )

    cm = boot_and_migrate(boot_config_manager)

    assert new_config_names(users_dir) == ["General"]
    context = read_context(users_dir)
    assert context["default_config"] == "General"
    assert "Star Citizen" in context["deleted_template_configs"]

    # content was archived, not destroyed
    archive = path.join(users_dir, "archived_configs", "pre_3_1_4", "Star Citizen")
    assert path.exists(path.join(archive, "Computer.yaml"))

    # a restart does not resurrect it
    boot_config_manager()
    assert new_config_names(users_dir) == ["General"]
    assert cm.find_default_config().name == "General"


def test_duplicated_configs_are_both_kept(users_dir, boot_config_manager):
    """The legacy duplication bug: both 'Star Citizen' and '_Star Citizen'
    exist. Both must survive; the prefixed one becomes 'Star Citizen (2)'."""
    make_old_version(
        users_dir,
        {
            "Star Citizen": {
                "Computer.yaml": {"name": "Computer", "description": "user's own"}
            },
            "_Star Citizen": {"Computer.yaml": None},
            "General": {"Clippy.yaml": None},
        },
    )

    cm = boot_and_migrate(boot_config_manager)

    assert new_config_names(users_dir) == [
        "General",
        "Star Citizen",
        "Star Citizen (2)",
    ]
    # the legacy default flag carries over to the renamed duplicate
    assert cm.find_default_config().name == "Star Citizen (2)"

    # no tombstone: live dirs exist
    assert read_context(users_dir)["deleted_template_configs"] == []

    # a restart neither duplicates nor deletes anything
    boot_config_manager()
    assert new_config_names(users_dir) == [
        "General",
        "Star Citizen",
        "Star Citizen (2)",
    ]


def test_corrupted_underscore_dot_dir(users_dir, boot_config_manager):
    """The legacy resurrection bug produced dirs like '_.Star Citizen'."""
    make_old_version(
        users_dir,
        {
            "_.Star Citizen": {"Computer.yaml": None},
            "General": {"Clippy.yaml": None},
        },
    )

    cm = boot_and_migrate(boot_config_manager)

    assert new_config_names(users_dir) == ["General", "Star Citizen"]
    assert cm.find_default_config().name == "Star Citizen"


def test_deleted_wingman_marker_becomes_tombstone(users_dir, boot_config_manager):
    """User logically deleted a wingman: '.Computer.yaml' marker in the dir."""
    make_old_version(
        users_dir,
        {
            "_Star Citizen": {
                "ATC.yaml": None,
                ".Computer.yaml": {"name": "Computer"},
            },
            "General": {"Clippy.yaml": None},
        },
    )

    cm = boot_and_migrate(boot_config_manager)

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
    old_configs = make_old_version(
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

    cm = boot_and_migrate(boot_config_manager)

    assert new_config_names(users_dir) == ["General"]
    context = read_context(users_dir)
    assert context["default_config"] == "General"
    assert "Star Citizen" in context["deleted_template_configs"]
    assert cm.find_default_config().name == "General"


def test_migration_marker_prevents_rerun(users_dir, boot_config_manager):
    make_old_version(
        users_dir,
        {
            "Star Citizen": {"Computer.yaml": None},
            "_General": {"Clippy.yaml": None},
        },
    )

    boot_and_migrate(boot_config_manager)
    # second full boot incl. migration service: must be a no-op
    boot_and_migrate(boot_config_manager)

    assert new_config_names(users_dir) == ["General", "Star Citizen"]
    assert read_context(users_dir)["default_config"] == "General"
