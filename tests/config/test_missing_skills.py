"""A wingman that names a skill which is not installed.

It has to load without that skill instead of failing validation, and a save
must keep the entry in the file, so the skill is back once it is installed
again. A skill the user removed on purpose is gone for good.
"""

from os import path

from tests.support import TEMPLATES, read_yaml, write_yaml


def test_merge_configs_skips_missing_custom_skill(boot_config_manager):
    config_manager = boot_config_manager()
    default_config = config_manager.read_default_config()

    wingman = read_yaml(path.join(TEMPLATES, "General", "Clippy.template.yaml"))
    wingman.setdefault("skills", []).append(
        {
            "module": "skills.test_missing_skill.main",
            "custom_properties": [{"id": "logging_enabled", "value": True}],
        }
    )

    merged = config_manager.merge_configs(default_config, wingman)

    assert all(
        skill.module != "skills.test_missing_skill.main"
        for skill in (merged.skills or [])
    )


def _get_wingman(config_manager, config_name: str, wingman_name: str):
    config_dir = next(
        d for d in config_manager.get_config_dirs() if d.name == config_name
    )
    wingman_file = next(
        f
        for f in config_manager.get_wingmen_configs(config_dir)
        if f.name == wingman_name
    )
    return config_dir, wingman_file


def test_save_wingman_config_preserves_uninstalled_skill_entries(
    boot_config_manager,
):
    config_manager = boot_config_manager()
    config_dir, wingman_file = _get_wingman(config_manager, "General", "Clippy")
    clippy_path = path.join(
        config_manager.config_dir, config_dir.directory, wingman_file.file
    )

    missing_entry = {
        "module": "skills.test_missing_skill.main",
        "custom_properties": [{"id": "logging_enabled", "value": True}],
    }
    raw = read_yaml(clippy_path)
    raw.setdefault("skills", []).append(missing_entry)
    write_yaml(clippy_path, raw)

    loaded = config_manager.load_wingman_config(config_dir, wingman_file)
    # load skips the uninstalled skill so the wingman still works ...
    assert all(
        skill.module != "skills.test_missing_skill.main"
        for skill in (loaded.skills or [])
    )

    config_manager.save_wingman_config(
        config_dir=config_dir, wingman_file=wingman_file, wingman_config=loaded
    )

    # ... but a load + save round-trip must not drop its entry from the YAML
    raw_after = read_yaml(clippy_path)
    preserved = [
        skill
        for skill in raw_after.get("skills") or []
        if skill.get("module") == "skills.test_missing_skill.main"
    ]
    assert preserved == [missing_entry]


def test_save_wingman_config_still_drops_deliberately_removed_skills(
    boot_config_manager,
):
    config_manager = boot_config_manager()
    config_dir, wingman_file = _get_wingman(config_manager, "General", "Clippy")
    clippy_path = path.join(
        config_manager.config_dir, config_dir.directory, wingman_file.file
    )

    raw = read_yaml(clippy_path)
    raw.setdefault("skills", []).append(
        {
            "module": "skills.timer.main",
            "prompt": "Always confirm timers.",
        }
    )
    write_yaml(clippy_path, raw)

    loaded = config_manager.load_wingman_config(config_dir, wingman_file)
    assert any(
        skill.module == "skills.timer.main" for skill in (loaded.skills or [])
    )

    # the user removes the (installed) timer skill in the UI
    loaded.skills = [
        skill for skill in loaded.skills if skill.module != "skills.timer.main"
    ]
    config_manager.save_wingman_config(
        config_dir=config_dir, wingman_file=wingman_file, wingman_config=loaded
    )

    raw_after = read_yaml(clippy_path)
    assert all(
        skill.get("module") != "skills.timer.main"
        for skill in raw_after.get("skills") or []
    )


def test_merge_configs_keeps_complete_inline_custom_skill(boot_config_manager):
    config_manager = boot_config_manager()
    default_config = config_manager.read_default_config()

    wingman = read_yaml(path.join(TEMPLATES, "General", "Clippy.template.yaml"))
    wingman.setdefault("skills", []).append(
        {
            "name": "TestSkill",
            "module": "skills.test_missing_skill.main",
            "display_name": "Test Skill",
            "description": {"en": "A legacy inline-configured custom skill."},
        }
    )

    merged = config_manager.merge_configs(default_config, wingman)

    assert any(
        skill.module == "skills.test_missing_skill.main"
        for skill in (merged.skills or [])
    )
