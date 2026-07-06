"""Tests for the .context.yaml based config state (default + deletion tombstones).

These cover the historic bug class where changing the default config or
deleting a template config resurrected or duplicated configs on restart.
"""

from os import listdir, path

from tests.conftest import VERSION_DIR


def config_names(users_dir):
    configs = path.join(users_dir, VERSION_DIR, "configs")
    return sorted(
        d
        for d in listdir(configs)
        if path.isdir(path.join(configs, d)) and not d.startswith(".")
    )


def test_fresh_install_creates_templates_and_context(users_dir, boot_config_manager):
    cm = boot_config_manager()

    assert config_names(users_dir) == ["General", "Star Citizen"]
    assert path.exists(path.join(cm.config_dir, ".context.yaml"))

    default = cm.find_default_config()
    assert default.name == "Star Citizen"
    assert default.directory == "Star Citizen"
    assert default.is_default


def test_restart_is_idempotent(users_dir, boot_config_manager):
    boot_config_manager()
    boot_config_manager()

    assert config_names(users_dir) == ["General", "Star Citizen"]


def test_change_default_survives_restart_without_duplicates(
    users_dir, boot_config_manager
):
    """THE historic bug: changing the default config resurrected both shipped
    configs (as '_Star Citizen' + 'Star Citizen' and 'General' + '_General')
    on the next restart."""
    cm = boot_config_manager()
    general = cm.get_config_dir("General")
    assert cm.set_default_config(general)

    cm2 = boot_config_manager()

    assert config_names(users_dir) == ["General", "Star Citizen"]
    assert cm2.find_default_config().name == "General"

    star_citizen = cm2.get_config_dir("Star Citizen")
    assert star_citizen and not star_citizen.is_default


def test_deleted_template_config_stays_deleted(users_dir, boot_config_manager):
    cm = boot_config_manager()
    star_citizen = cm.get_config_dir("Star Citizen")
    assert cm.delete_config(star_citizen)

    assert config_names(users_dir) == ["General"]
    # deleting the default promotes the remaining config
    assert cm.find_default_config().name == "General"

    cm2 = boot_config_manager()
    assert config_names(users_dir) == ["General"]
    assert cm2.find_default_config().name == "General"


def test_renamed_template_config_is_not_recreated(users_dir, boot_config_manager):
    cm = boot_config_manager()
    star_citizen = cm.get_config_dir("Star Citizen")
    renamed = cm.rename_config(star_citizen, "My Universe")

    assert renamed and renamed.directory == "My Universe"
    # rename of the default config keeps it default
    assert cm.find_default_config().name == "My Universe"

    boot_config_manager()
    assert config_names(users_dir) == ["General", "My Universe"]


def test_deleted_template_wingman_stays_deleted(users_dir, boot_config_manager):
    cm = boot_config_manager()
    star_citizen = cm.get_config_dir("Star Citizen")
    wingmen = cm.get_wingmen_configs(star_citizen)
    assert wingmen, "Star Citizen template should ship wingmen"
    victim = wingmen[0]

    assert cm.delete_wingman_config(star_citizen, victim)
    assert not path.exists(path.join(cm.config_dir, "Star Citizen", victim.file))

    cm2 = boot_config_manager()
    remaining = [w.name for w in cm2.get_wingmen_configs(star_citizen)]
    assert victim.name not in remaining
    # the others are still there
    assert len(remaining) == len(wingmen) - 1


def test_recreating_deleted_config_clears_tombstone(users_dir, boot_config_manager):
    cm = boot_config_manager()
    cm.delete_config(cm.get_config_dir("Star Citizen"))
    assert cm.is_template_config_deleted("Star Citizen")

    template = next(
        t for t in cm.get_config_template_dirs() if t.name == "Star Citizen"
    )
    cm.create_config("Star Citizen", template=template)

    assert not cm.is_template_config_deleted("Star Citizen")
    assert config_names(users_dir) == ["General", "Star Citizen"]
    # the recreated config has the template wingmen
    wingmen = cm.get_wingmen_configs(cm.get_config_dir("Star Citizen"))
    assert wingmen


def test_manually_deleted_default_dir_falls_back_to_first(
    users_dir, boot_config_manager
):
    """User deletes the default config dir in the file system (not via API):
    the first existing config becomes the default and the state self-heals."""
    import shutil

    cm = boot_config_manager()
    shutil.rmtree(path.join(cm.config_dir, "Star Citizen"))

    default = cm.find_default_config()
    assert default.name == "General"
    assert cm.context_state.default_config == "General"

    # No tombstone was set (the app didn't delete it), so a restart restores
    # the template - the documented self-heal story for broken configs.
    boot_config_manager()
    assert config_names(users_dir) == ["General", "Star Citizen"]


def test_manually_edited_default_to_unknown_name(boot_config_manager):
    """User edits .context.yaml and sets default_config to a nonexistent name."""
    cm = boot_config_manager()
    cm.context_state.default_config = "Does Not Exist"
    cm.save_context_state()

    cm2 = boot_config_manager()
    default = cm2.find_default_config()
    assert default.name == "General"  # first existing dir (sorted)
    assert cm2.context_state.default_config == "General"


def test_manually_removed_tombstone_resurrects_template(
    users_dir, boot_config_manager
):
    """User removes an entry from deleted_template_configs in .context.yaml:
    the template is recreated on next start (= manual un-delete)."""
    cm = boot_config_manager()
    cm.delete_config(cm.get_config_dir("Star Citizen"))
    assert config_names(users_dir) == ["General"]

    cm.context_state.deleted_template_configs = []
    cm.save_context_state()

    boot_config_manager()
    assert config_names(users_dir) == ["General", "Star Citizen"]


def test_corrupt_context_file_does_not_crash(users_dir, boot_config_manager):
    """A broken .context.yaml must not crash the app - it falls back to
    defaults in memory without overwriting the file."""
    cm = boot_config_manager()
    with open(cm.context_state_path, "w", encoding="UTF-8") as f:
        f.write("default_config: [this, is, not, a, string]\n")

    cm2 = boot_config_manager()
    assert cm2.context_state.default_config == "Star Citizen"
    assert cm2.find_default_config().name == "Star Citizen"

    # the broken file was preserved for the user to inspect/fix
    with open(cm2.context_state_path, "r", encoding="UTF-8") as f:
        assert "[this, is, not, a, string]" in f.read()


def test_deleting_everything_self_heals(users_dir, boot_config_manager):
    cm = boot_config_manager()
    cm.delete_config(cm.get_config_dir("Star Citizen"))
    cm.delete_config(cm.get_config_dir("General"))
    assert config_names(users_dir) == []

    default = cm.find_default_config()
    assert default is not None
    assert config_names(users_dir) == ["General", "Star Citizen"]
