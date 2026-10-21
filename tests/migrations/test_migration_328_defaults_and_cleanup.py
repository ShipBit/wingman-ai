"""3.2.8 brings the Wingmen Wingman ships to their current skills and MCP
servers without touching what the user made, and a run over several versions
leaves only the user's original version and the new one behind."""

from os import listdir, path

from tests.support import (
    TEMPLATES,
    VERSION_DIR,
    boot_and_migrate,
    make_old_version,
    read_yaml,
    write_yaml,
)

OLD_VERSION_DIR = "3_1_3"


def _old_computer() -> dict:
    """Computer as an older version shipped it: no web search, no events,
    and a backstory the user wrote."""
    computer = read_yaml(path.join(TEMPLATES, "Star Citizen", "Computer.template.yaml"))
    computer["discoverable_skills"] = ["Timer", "VisionAI"]
    computer["discoverable_mcps"] = ["wingman_date_time", "wingman_starhead"]
    computer["prompts"]["backstory"] = "My own Computer, grumpy and old."
    for command in computer["commands"]:
        if command["name"] == "More missiles":
            command["additional_context"] = "Missle salvo size cycled by +1"
    return computer


def _wingman(users_dir: str, config: str, name: str) -> dict:
    return read_yaml(path.join(users_dir, VERSION_DIR, "configs", config, f"{name}.yaml"))


def test_shipped_wingmen_are_brought_up_to_date_and_the_users_own_are_not(users_dir, boot_config_manager):
    old_configs = make_old_version(
        users_dir,
        OLD_VERSION_DIR,
        {"Star Citizen": {"Computer.yaml": _old_computer()}, "My Game": {"Computer.yaml": _old_computer()}},
    )
    defaults_file = path.join(old_configs, "defaults.yaml")
    defaults = read_yaml(defaults_file)
    defaults["inworld"]["model_id"] = "inworld-tts-1"
    write_yaml(defaults_file, defaults)

    boot_and_migrate(boot_config_manager)

    computer = _wingman(users_dir, "Star Citizen", "Computer")
    template = read_yaml(path.join(TEMPLATES, "Star Citizen", "Computer.template.yaml"))
    assert set(template["discoverable_mcps"]) <= set(computer["discoverable_mcps"])
    assert "wingman_websearch" in computer["discoverable_mcps"]
    assert set(template["discoverable_skills"]) <= set(computer["discoverable_skills"])
    assert computer["prompts"]["backstory"] == "My own Computer, grumpy and old."
    commands = {c["name"]: c for c in computer["commands"]}
    assert commands["More missiles"]["additional_context"] == "Missile salvo size cycled by +1"

    mine = _wingman(users_dir, "My Game", "Computer")
    assert "wingman_websearch" not in mine["discoverable_mcps"]
    assert "ScGameEvents" not in mine["discoverable_skills"]

    migrated = read_yaml(path.join(users_dir, VERSION_DIR, "configs", "defaults.yaml"))
    assert migrated["inworld"]["model_id"] == "inworld-tts-2-flash"


def test_only_the_users_original_versions_and_the_new_one_are_left(users_dir, boot_config_manager):
    make_old_version(users_dir, "3_1_0", {"Star Citizen": {"Computer.yaml": None}})
    make_old_version(users_dir, OLD_VERSION_DIR, {"Star Citizen": {"Computer.yaml": None}})

    _, service = boot_and_migrate(boot_config_manager)

    versions = {d for d in listdir(users_dir) if d[0].isdigit()}
    assert versions == {"3_1_0", OLD_VERSION_DIR, VERSION_DIR}
    final_log = path.join(users_dir, VERSION_DIR, "configs", ".migration")
    with open(final_log, encoding="UTF-8") as f:
        assert "Migrating from 3.1.3 to 3.1.4" in f.read()
    assert "Removed intermediate version 3.1.4" in service.log_message
