"""The migration chain as a whole: an old config folder goes in, the current
version comes out, and nothing of the user's is lost on the way.

Bugs these tests pin:

* A packaged 3.1.5 build lacked a module one step needed. The broken chain was
  noticed only mid-migration, after configs in the new version had already
  been deleted, and the run still logged "Migration completed successfully".
* Multi-step chains discarded every intermediate step's settings.yaml: the
  final step validated the original old file against the current schema,
  failed, and reset the user's settings to the templates.
* The `.migration` marker was written before the 3.1.4 conversion finished, so
  a crash in between stranded the legacy folders for good.
"""

import os
import shutil
from os import listdir, makedirs, path

import pytest
import yaml

from tests.support import (
    TEMPLATES,
    VERSION_DIR,
    boot_and_migrate,
    config_names,
    make_old_version,
    migration_service,
    read_yaml,
    write_yaml,
)

OLD_VERSION_DIR = "3_1_3"


def break_chain(service):
    """What a packaged build without migration_313_to_314 looks like."""
    service.migrations = [m for m in service.migrations if m[0] != "3_1_3"]


# ── the chain is checked before anything is touched ────────────────────


def test_a_complete_chain_reaches_the_current_version(users_dir, boot_config_manager):
    make_old_version(users_dir, OLD_VERSION_DIR, {"Star Citizen": {"Computer.yaml": None}})
    service = migration_service(boot_config_manager())

    chain = service.build_migration_chain(OLD_VERSION_DIR)

    assert chain[0] == OLD_VERSION_DIR
    assert chain[-1] == VERSION_DIR


def test_a_missing_link_is_no_chain(users_dir, boot_config_manager):
    make_old_version(users_dir, OLD_VERSION_DIR, {"Star Citizen": {"Computer.yaml": None}})
    service = migration_service(boot_config_manager())
    break_chain(service)

    assert service.build_migration_chain(OLD_VERSION_DIR) is None


def test_a_broken_chain_aborts_before_deleting_anything(users_dir, boot_config_manager):
    make_old_version(
        users_dir,
        OLD_VERSION_DIR,
        {
            "_Star Citizen": {"Computer.yaml": None, "ATC.yaml": None},
            "General": {"Clippy.yaml": None},
        },
    )
    service = migration_service(boot_config_manager())
    before = config_names(users_dir)
    assert "Star Citizen" in before  # templates restored on boot

    break_chain(service)
    service.migrate_to_latest()

    assert config_names(users_dir) == before
    assert not path.exists(path.join(users_dir, VERSION_DIR, "configs", ".migration"))
    assert "Migration completed successfully" not in service.log_message
    assert "No complete migration path" in service.log_message
    old_configs = path.join(users_dir, OLD_VERSION_DIR, "configs")
    assert {"_Star Citizen", "General"} <= set(listdir(old_configs))


def test_the_next_start_with_a_complete_chain_recovers(users_dir, boot_config_manager):
    make_old_version(
        users_dir,
        OLD_VERSION_DIR,
        {
            "_Star Citizen": {"Computer.yaml": None, "ATC.yaml": None},
            "My Game": {"Computer.yaml": read_yaml(path.join(TEMPLATES, "Star Citizen", "Computer.template.yaml"))},
        },
    )
    broken = migration_service(boot_config_manager())
    break_chain(broken)
    broken.migrate_to_latest()

    _, fixed = boot_and_migrate(boot_config_manager)

    assert {"My Game", "Star Citizen"} <= set(config_names(users_dir))
    assert path.exists(path.join(users_dir, VERSION_DIR, "configs", ".migration"))
    assert "Migration completed successfully" in fixed.log_message


# ── which old version is the source ────────────────────────────────────


def test_an_interrupted_folder_does_not_hide_a_completed_one(users_dir, boot_config_manager):
    """A version folder without the marker is what a broken update left
    behind. It must not shadow an older, completed version."""
    make_old_version(users_dir, OLD_VERSION_DIR, {"Star Citizen": {"Computer.yaml": None}})
    makedirs(path.join(users_dir, "3_1_4", "configs"))

    service = migration_service(boot_config_manager())

    assert service.find_latest_migratable_version(users_dir) == OLD_VERSION_DIR


def test_an_interrupted_folder_is_used_when_it_is_all_there_is(users_dir, boot_config_manager):
    makedirs(path.join(users_dir, "3_1_4", "configs"))

    service = migration_service(boot_config_manager())

    assert service.find_latest_migratable_version(users_dir) == "3_1_4"


# ── a crash in the middle ──────────────────────────────────────────────


def test_a_crash_in_a_step_reruns_it_on_the_next_start(users_dir, boot_config_manager, monkeypatch):
    make_old_version(
        users_dir,
        OLD_VERSION_DIR,
        {".Star Citizen": {"Computer.yaml": None}, "_General": {"Clippy.yaml": None}},
    )
    from services.migrations.migration_313_to_314 import Migration313To314

    original = Migration313To314.convert_to_context_state

    def crash(self):
        raise OSError("simulated crash during conversion")

    monkeypatch.setattr(Migration313To314, "convert_to_context_state", crash)
    with pytest.raises(OSError):
        boot_and_migrate(boot_config_manager)

    marker = path.join(users_dir, VERSION_DIR, "configs", ".migration")
    assert not path.exists(marker)

    monkeypatch.setattr(Migration313To314, "convert_to_context_state", original)
    config_manager, _ = boot_and_migrate(boot_config_manager)

    assert path.exists(marker)
    assert config_names(users_dir) == ["General"]
    assert config_manager.find_default_config().name == "General"


def test_a_rerun_over_a_finished_migration_makes_no_duplicates(users_dir, boot_config_manager):
    make_old_version(
        users_dir,
        OLD_VERSION_DIR,
        {"Star Citizen": {"Computer.yaml": None}, "_General": {"Clippy.yaml": None}},
    )
    boot_and_migrate(boot_config_manager)
    os.remove(path.join(users_dir, VERSION_DIR, "configs", ".migration"))

    config_manager, _ = boot_and_migrate(boot_config_manager)

    assert config_names(users_dir) == ["General", "Star Citizen"]
    assert config_manager.find_default_config().name == "General"


# ── a long chain keeps what every step did ─────────────────────────────


def _settings_310() -> dict:
    """A 3.1.0 settings.yaml: the current template without what came later,
    speech-to-text still inside voice_activation, and one user value."""
    settings = read_yaml(path.join(TEMPLATES, "settings.yaml"))
    for key in ("hud_server", "pocket_tts", "llama_cpp", "spoken_language"):
        settings.pop(key, None)
    settings.pop("stt")
    va = settings["voice_activation"]
    va["stt_provider"] = "whispercpp"
    va["languages"] = ["en-US", "de-DE"]
    va["whispercpp"] = {"host": "http://192.168.1.50", "port": 8080, "enable": True}
    va["whispercpp_config"] = {"temperature": 0.0}
    va["fasterwhisper"] = {"model_size": "base", "device": "cpu", "compute_type": "auto", "enable": True}
    va["fasterwhisper_config"] = {"beam_size": 1, "additional_hotwords": []}
    settings["debug_mode"] = True
    return settings


def _defaults_310() -> dict:
    defaults = read_yaml(path.join(TEMPLATES, "defaults.yaml"))
    # Keys later versions dropped, one of them with a user value.
    defaults["features"]["skill_max_input_tokens"] = 12345
    defaults["features"]["remember_messages"] = 99
    defaults["features"]["condense_keep_recent"] = 6
    return defaults


@pytest.fixture
def migrated_310(users_dir, boot_config_manager):
    old_configs = path.join(users_dir, "3_1_0", "configs")
    makedirs(old_configs)
    write_yaml(path.join(old_configs, "settings.yaml"), _settings_310())
    write_yaml(path.join(old_configs, "defaults.yaml"), _defaults_310())
    with open(path.join(old_configs, ".migration"), "w", encoding="UTF-8") as f:
        f.write("Version 3_1_0 - test fixture\n")
    makedirs(path.join(old_configs, "General"))
    shutil.copyfile(
        path.join(TEMPLATES, "General", "Clippy.template.yaml"),
        path.join(old_configs, "General", "Clippy.yaml"),
    )
    return boot_and_migrate(boot_config_manager)


def test_a_long_chain_keeps_the_users_settings(users_dir, migrated_310):
    from api.enums import SttProvider
    from api.interface import SettingsConfig

    config_manager, service = migrated_310
    assert "Unable to migrate settings.yaml" not in service.log_message

    on_disk = read_yaml(path.join(users_dir, VERSION_DIR, "configs", "settings.yaml"))
    settings = SettingsConfig(**on_disk)

    assert settings.debug_mode is True
    # 3.1.0 -> 3.1.1 switched STT to Parakeet, 3.2.1 -> 3.2.2 moved it out of
    # voice_activation: both steps' work arrived.
    assert settings.stt.provider == SttProvider.PARAKEET
    # Fields no step adds came from the current template.
    assert settings.hud_server and settings.pocket_tts and settings.llama_cpp
    # What a step deleted stays deleted; the backfill does not bring it back.
    for key in ("whispercpp", "whispercpp_config", "fasterwhisper", "fasterwhisper_config"):
        assert key not in on_disk["stt"]
    assert "stt_provider" not in on_disk["voice_activation"]
    assert config_manager.settings_config.debug_mode is True


def test_each_step_writes_its_settings_for_the_next(users_dir, migrated_310):
    intermediate = read_yaml(path.join(users_dir, "3_1_1", "configs", "settings.yaml"))
    assert intermediate["voice_activation"]["stt_provider"] == "parakeet"


def test_dropped_default_keys_leave_the_file(users_dir, migrated_310):
    _, service = migrated_310
    assert "Unable to migrate defaults.yaml" not in service.log_message

    features = read_yaml(path.join(users_dir, VERSION_DIR, "configs", "defaults.yaml"))["features"]
    for key in ("skill_max_input_tokens", "condense_max_messages", "remember_messages", "condense_keep_recent"):
        assert key not in features


# ── a later step after the 3.1.4 conversion ────────────────────────────


def test_the_conversion_runs_in_its_own_step_folder(users_dir, boot_config_manager, monkeypatch):
    """With a step after 3.1.4, 3_1_4 is an intermediate folder. The legacy
    state still has to be converted there and carried to the end."""
    import services.config_manager as cm_module
    import services.config_migration_service as mig_module
    from services.migrations.base_migration import BaseMigration

    class Migration314ToNext(BaseMigration):
        old_version = "3_1_4"
        new_version = "3_1_9"

    real_discover = mig_module.discover_migrations
    only_up_to_314 = [m for m in real_discover() if m[0] <= "3_1_3"]
    monkeypatch.setattr(
        mig_module,
        "discover_migrations",
        lambda: only_up_to_314 + [("3_1_4", "3_1_9", Migration314ToNext)],
    )

    def writable_dir(subdir: str = ""):
        full_path = path.join(users_dir, "3_1_9", subdir) if subdir else path.join(users_dir, "3_1_9")
        os.makedirs(full_path, exist_ok=True)
        return full_path

    monkeypatch.setattr(cm_module, "get_writable_dir", writable_dir)
    make_old_version(
        users_dir,
        OLD_VERSION_DIR,
        {".Star Citizen": {"Computer.yaml": None}, "_General": {"Clippy.yaml": None}},
    )

    config_manager, _ = boot_and_migrate(boot_config_manager)

    assert config_names(users_dir, "3_1_9") == ["General"]
    with open(path.join(users_dir, "3_1_9", "configs", "context.yaml"), encoding="UTF-8") as f:
        context = yaml.safe_load(f)
    assert context["default_config"] == "General"
    assert "Star Citizen" in context["deleted_template_configs"]
    assert config_manager.find_default_config().name == "General"
