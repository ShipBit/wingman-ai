"""A settings.yaml older than the models must not stop Core from starting.

A user's 3.2.2 install had their 3.2.1 settings.yaml sitting in the 3_2_2
config folder. It has no `stt` block, which 3.2.2 requires, so validation
failed - and the fallback, `SettingsConfig()`, is not constructible either
because every field is required. ConfigManager's constructor raised, Core died
on line one of main.py, and the migration that would have repaired the file
never got to run: every following start hit the same wall.

These tests pin the repaired behavior: fill what is missing from the shipped
template, keep every user value, and never raise.
"""

from os import makedirs, path

import yaml

from tests.support import TEMPLATES, VERSION_DIR, read_yaml


def settings_321() -> dict:
    """A 3.2.1 settings.yaml: the current template with speech-to-text back
    inside voice_activation, where it lived until 3.2.2, and no `stt` block."""
    settings = read_yaml(path.join(TEMPLATES, "settings.yaml"))
    stt = settings.pop("stt")
    settings["voice_activation"] = {
        "enabled": False,
        "mute_toggle_key": "shift+x",
        "energy_threshold": 0.01,
        "stt_provider": "parakeet",
        "languages": ["en-US", "de-DE"],
        "parakeet": stt["parakeet"],
        "parakeet_config": stt["parakeet_config"],
    }
    # user values that have to survive
    settings["spoken_language"] = "de"
    settings["debug_mode"] = True
    settings["xvasynth"]["port"] = 8009
    return settings


def write_current_settings(users_dir: str, settings) -> str:
    """Put a settings.yaml into the CURRENT version's config folder, i.e.
    where ConfigManager reads it before any migration runs."""
    configs = path.join(users_dir, VERSION_DIR, "configs")
    makedirs(configs, exist_ok=True)
    settings_file = path.join(configs, "settings.yaml")
    with open(settings_file, "w", encoding="UTF-8") as f:
        if isinstance(settings, str):
            f.write(settings)
        else:
            yaml.safe_dump(settings, f)
    return settings_file


def test_old_settings_file_boots_and_keeps_user_values(users_dir, boot_config_manager):
    from api.enums import SttProvider

    settings_file = write_current_settings(users_dir, settings_321())

    config_manager = boot_config_manager()

    settings = config_manager.settings_config
    assert settings.stt.provider == SttProvider.PARAKEET
    assert settings.spoken_language.value == "de"
    assert settings.debug_mode is True
    assert settings.xvasynth.port == 8009
    # the repair is written back, so the next start reads a current file
    on_disk = read_yaml(settings_file)
    assert "stt" in on_disk
    assert on_disk["spoken_language"] == "de"


def test_empty_settings_file_boots_on_the_template(users_dir, boot_config_manager):
    settings_file = write_current_settings(users_dir, "")

    config_manager = boot_config_manager()

    template = read_yaml(path.join(TEMPLATES, "settings.yaml"))
    assert config_manager.settings_config.stt.provider.value == template["stt"]["provider"]
    assert "stt" in read_yaml(settings_file)


def test_a_bad_value_boots_on_defaults_and_leaves_the_file_alone(
    users_dir, boot_config_manager
):
    broken = read_yaml(path.join(TEMPLATES, "settings.yaml"))
    broken["hud_server"]["port"] = "not a port"
    settings_file = write_current_settings(users_dir, broken)

    config_manager = boot_config_manager()

    # Core is up on the shipped defaults ...
    assert config_manager.settings_config.hud_server.port == 7862
    # ... and the user's file is untouched, so nothing of theirs is lost
    assert read_yaml(settings_file)["hud_server"]["port"] == "not a port"


def test_a_current_settings_file_is_not_rewritten(users_dir, boot_config_manager):
    """Only a file that fails validation is repaired - a valid one is left
    exactly as the user wrote it, on every start."""
    current = read_yaml(path.join(TEMPLATES, "settings.yaml"))
    current["user_name"] = "Jan"
    settings_file = write_current_settings(users_dir, current)
    before = open(settings_file, encoding="UTF-8").read()

    config_manager = boot_config_manager()

    assert config_manager.settings_config.user_name == "Jan"
    assert open(settings_file, encoding="UTF-8").read() == before
