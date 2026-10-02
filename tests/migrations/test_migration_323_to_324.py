"""3.2.4 puts a System One model in front of the main model. A config written
by 3.2.3 has no `system_one` block, and the field is required, so the chain
has to add one — switched on, because every decision it takes falls back to
3.2.3's path when the model is unavailable.
"""

import glob
import shutil
from os import makedirs, path
from unittest.mock import MagicMock

from api.interface import CommandConfig, SettingsConfig
from services.migrations.migration_323_to_324 import Migration323To324
from tests.support import REPO_ROOT, TEMPLATES, VERSION_DIR, boot_and_migrate, read_yaml, template, write_yaml


def _migration() -> Migration323To324:
    """The real migration, pointed at the repo's own templates.

    `templates_dir` comes off the service, and a MagicMock for it makes
    `_shipped_descriptions` walk nothing and quietly fill nothing in — which
    is exactly the failure this file is meant to catch, so it has to be real.
    """
    service = MagicMock()
    service.templates_dir = path.join(REPO_ROOT, "templates")
    return Migration323To324(service)


def _settings_323() -> dict:
    """The shipped settings.yaml as 3.2.3 wrote it: everything but the blocks
    3.2.4 introduces."""
    settings = template("settings.yaml")
    settings.pop("system_one", None)
    settings.pop("show_token_count", None)
    settings.pop("filler_responses", None)
    return settings


def test_the_block_is_added_and_switched_on():
    migrated = _migration().migrate_settings(_settings_323())
    assert migrated["system_one"] == {"enabled": True, "commands": True}


def test_a_user_who_switched_it_off_keeps_it_off():
    """The load-time repair may have written the block before the chain ran.
    Whatever it says is the user's, and running the migration must not switch
    the feature back on behind their back."""
    settings = _settings_323()
    settings["system_one"] = {"enabled": False, "commands": False}
    assert _migration().migrate_settings(settings)["system_one"] == {
        "enabled": False, "commands": False
    }


def test_a_half_written_block_is_completed_not_replaced():
    """Both fields are required, so a block missing one would not load — but
    the switch the user did set has to survive being completed."""
    settings = _settings_323()
    settings["system_one"] = {"enabled": False}
    assert _migration().migrate_settings(settings)["system_one"] == {
        "enabled": False, "commands": True
    }


def test_nothing_else_is_touched():
    before = _settings_323()
    after = _migration().migrate_settings(dict(before))
    after.pop("system_one")
    after.pop("show_token_count")
    after.pop("filler_responses")
    assert after == before


def test_the_result_still_loads():
    """The whole point of the step: a 3.2.3 settings.yaml that has been through
    it must satisfy the model 3.2.4 validates against."""
    SettingsConfig(**_migration().migrate_settings(_settings_323()))


def test_token_counts_are_added_and_switched_off():
    assert _migration().migrate_settings(_settings_323())["show_token_count"] is False


def test_a_user_who_switched_token_counts_on_keeps_them_on():
    settings = _settings_323()
    settings["show_token_count"] = True
    assert _migration().migrate_settings(settings)["show_token_count"] is True


def test_filler_responses_are_added_and_switched_on():
    assert _migration().migrate_settings(_settings_323())["filler_responses"] is True


def test_a_user_who_switched_filler_responses_off_keeps_them_off():
    settings = _settings_323()
    settings["filler_responses"] = False
    assert _migration().migrate_settings(settings)["filler_responses"] is False


def test_the_old_per_wingman_switch_is_removed():
    wingman = {"name": "Clippy", "features": {"use_generic_instant_responses": True, "tts_provider": "openai"}}
    migrated = _migration().migrate_wingman(wingman)
    assert migrated["features"] == {"tts_provider": "openai"}
    defaults = {"features": {"use_generic_instant_responses": False}}
    assert _migration().migrate_defaults(defaults)["features"] == {}


def test_a_323_install_comes_out_with_system_one_on(users_dir, boot_config_manager):
    """The whole chain, as a 3.2.3 user runs it: the block is added and the
    user's own values are kept."""
    old_configs = path.join(users_dir, "3_2_3", "configs")
    makedirs(path.join(old_configs, "General"))
    settings = _settings_323()
    settings["debug_mode"] = True  # something of the user's, to check it survives
    write_yaml(path.join(old_configs, "settings.yaml"), settings)
    shutil.copyfile(path.join(TEMPLATES, "defaults.yaml"), path.join(old_configs, "defaults.yaml"))
    with open(path.join(old_configs, ".migration"), "w", encoding="UTF-8") as f:
        f.write("Version 3_2_3 - test fixture\n")
    shutil.copyfile(
        path.join(TEMPLATES, "General", "Clippy.template.yaml"),
        path.join(old_configs, "General", "Clippy.yaml"),
    )

    _, service = boot_and_migrate(boot_config_manager)

    assert "Unable to migrate settings.yaml" not in service.log_message
    migrated = read_yaml(path.join(users_dir, VERSION_DIR, "configs", "settings.yaml"))
    assert migrated["system_one"] == {"enabled": True, "commands": True}
    assert migrated["debug_mode"] is True
    assert migrated["filler_responses"] is True
    SettingsConfig(**migrated)


# ── command descriptions ────────────────────────────────────────────


def _wingman_323() -> dict:
    """A Wingman config as 3.2.3 wrote it: template commands, no descriptions."""
    commands = []
    for command in template(path.join("Star Citizen", "Computer.template.yaml"))["commands"]:
        stripped = dict(command)
        stripped.pop("description", None)
        commands.append(stripped)
    return {"name": "Computer", "commands": commands}


def test_template_commands_get_the_shipped_description():
    migrated = _migration().migrate_wingman(_wingman_323())
    described = [c for c in migrated["commands"] if c.get("description")]
    assert len(described) == len(migrated["commands"])
    landing = next(c for c in migrated["commands"] if c["name"] == "Toggle Landing System")
    assert "gear" in landing["description"].lower()


def test_a_description_the_user_wrote_is_never_overwritten():
    config = _wingman_323()
    config["commands"][0]["description"] = "mine, hands off"
    migrated = _migration().migrate_wingman(config)
    assert migrated["commands"][0]["description"] == "mine, hands off"


def test_a_command_the_user_invented_is_left_without_one():
    """Empty is normal and must stay valid — this is the custom-command case."""
    config = {"name": "W", "commands": [{"name": "My Own Macro", "actions": []}]}
    migrated = _migration().migrate_wingman(config)
    assert "description" not in migrated["commands"][0]
    assert CommandConfig(**migrated["commands"][0]).description is None


def test_a_config_without_commands_survives():
    migrated = _migration().migrate_wingman({"name": "W"})
    assert migrated == {"name": "W"}
    assert _migration().migrate_wingman({"name": "W", "commands": None})["commands"] is None


def test_every_shipped_template_command_has_a_description():
    """The templates are where the descriptions come from; a command added to
    one without a line makes the migration silently skip it."""
    missing = []
    for template_path in glob.glob(path.join(TEMPLATES, "**", "*.template.yaml"), recursive=True):
        for command in (read_yaml(template_path) or {}).get("commands") or []:
            if not (command.get("description") or "").strip():
                missing.append(f"{path.basename(template_path)}: {command.get('name')}")
    assert not missing, f"shipped commands without a description: {missing}"
