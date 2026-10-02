"""3.2.2 cut an utterance after 12 seconds, mid-word, which cost a second LLM
call and garbled numbers. 3.2.3 moves that emergency stop to 160 s and the
end-of-sentence pause from 700 ms to 500 ms - but only for users who never
touched the values.
"""

import shutil
from os import makedirs, path
from unittest.mock import MagicMock

from api.interface import SettingsConfig
from services.migrations.migration_322_to_323 import (
    NEW_END_PAUSE_MS,
    NEW_MAX_UTTERANCE_S,
    Migration322To323,
)
from tests.support import TEMPLATES, VERSION_DIR, boot_and_migrate, read_yaml, template, write_yaml


def _migration() -> Migration322To323:
    return Migration322To323(MagicMock())


def _settings(**voice_activation) -> dict:
    settings = template("settings.yaml")
    settings["voice_activation"].update(voice_activation)
    return settings


def test_old_defaults_are_replaced():
    out = _migration().migrate_settings(
        _settings(max_utterance_s=12, end_pause_ms=700)
    )
    assert out["voice_activation"]["max_utterance_s"] == NEW_MAX_UTTERANCE_S
    assert out["voice_activation"]["end_pause_ms"] == NEW_END_PAUSE_MS
    SettingsConfig(**out)


def test_tuned_values_are_kept():
    out = _migration().migrate_settings(
        _settings(max_utterance_s=30, end_pause_ms=900)
    )
    assert out["voice_activation"]["max_utterance_s"] == 30
    assert out["voice_activation"]["end_pause_ms"] == 900


def test_each_value_is_judged_on_its_own():
    out = _migration().migrate_settings(
        _settings(max_utterance_s=12, end_pause_ms=900)
    )
    assert out["voice_activation"]["max_utterance_s"] == NEW_MAX_UTTERANCE_S
    assert out["voice_activation"]["end_pause_ms"] == 900


def test_missing_block_is_left_alone():
    assert _migration().migrate_settings({"debug_mode": False}) == {
        "debug_mode": False
    }


def test_the_template_ships_what_the_migration_writes():
    template_settings = template("settings.yaml")
    assert template_settings["voice_activation"]["max_utterance_s"] == NEW_MAX_UTTERANCE_S
    assert template_settings["voice_activation"]["end_pause_ms"] == NEW_END_PAUSE_MS


# ── the chain a 3.2.2 user walks ───────────────────────────────────────
#
# The tests above call the hook directly. These boot the real migration
# service over a 3.2.2 config folder, because the values only reach a user if
# the hook runs AND survives the final backfill against the current template.

OLD_VERSION_DIR = "3_2_2"


def _make_322_configs(users_dir, max_utterance_s, end_pause_ms) -> None:
    """3.2.3 added no settings fields, so a 3.2.2 settings.yaml is the current
    template with the two old voice activation values."""
    settings = _settings(max_utterance_s=max_utterance_s, end_pause_ms=end_pause_ms)
    old_configs = path.join(users_dir, OLD_VERSION_DIR, "configs")
    makedirs(old_configs)
    write_yaml(path.join(old_configs, "settings.yaml"), settings)
    shutil.copyfile(path.join(TEMPLATES, "defaults.yaml"), path.join(old_configs, "defaults.yaml"))
    # without the marker the dir counts as an interrupted migration
    with open(path.join(old_configs, ".migration"), "w", encoding="UTF-8") as f:
        f.write(f"Version {OLD_VERSION_DIR} - test fixture\n")


def _migrated_settings(users_dir) -> dict:
    return read_yaml(path.join(users_dir, VERSION_DIR, "configs", "settings.yaml"))


def test_a_322_user_gets_the_new_values(users_dir, boot_config_manager):
    _make_322_configs(users_dir, max_utterance_s=12, end_pause_ms=700)
    config_manager, service = boot_and_migrate(boot_config_manager)

    assert "Unable to migrate settings.yaml" not in service.log_message

    on_disk = _migrated_settings(users_dir)
    assert on_disk["voice_activation"]["max_utterance_s"] == NEW_MAX_UTTERANCE_S
    assert on_disk["voice_activation"]["end_pause_ms"] == NEW_END_PAUSE_MS

    va = config_manager.settings_config.voice_activation
    assert va.max_utterance_s == NEW_MAX_UTTERANCE_S
    assert va.end_pause_ms == NEW_END_PAUSE_MS


def test_a_322_user_keeps_what_they_tuned(users_dir, boot_config_manager):
    _make_322_configs(users_dir, max_utterance_s=30, end_pause_ms=900)
    config_manager, _ = boot_and_migrate(boot_config_manager)

    va = config_manager.settings_config.voice_activation
    assert va.max_utterance_s == 30
    assert va.end_pause_ms == 900
