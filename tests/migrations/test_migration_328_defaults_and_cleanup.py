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


def test_a_shipped_wingman_gets_what_its_template_has(users_dir, boot_config_manager):
    make_old_version(users_dir, OLD_VERSION_DIR, {"Star Citizen": {"Computer.yaml": _old_computer()}})

    boot_and_migrate(boot_config_manager)

    computer = _wingman(users_dir, "Star Citizen", "Computer")
    template = read_yaml(path.join(TEMPLATES, "Star Citizen", "Computer.template.yaml"))
    assert set(template["discoverable_mcps"]) <= set(computer["discoverable_mcps"])
    assert "wingman_websearch" in computer["discoverable_mcps"]
    assert set(template["discoverable_skills"]) <= set(computer["discoverable_skills"])
    assert computer["prompts"]["backstory"] == "My own Computer, grumpy and old."


def test_the_users_own_wingman_is_left_alone(users_dir, boot_config_manager):
    make_old_version(users_dir, OLD_VERSION_DIR, {"My Game": {"Computer.yaml": _old_computer()}})

    boot_and_migrate(boot_config_manager)

    mine = _wingman(users_dir, "My Game", "Computer")
    assert "wingman_websearch" not in mine["discoverable_mcps"]
    assert "ScGameEvents" not in mine["discoverable_skills"]


def test_the_intermediate_versions_are_removed(users_dir, boot_config_manager):
    make_old_version(users_dir, OLD_VERSION_DIR, {"Star Citizen": {"Computer.yaml": None}})

    _, service = boot_and_migrate(boot_config_manager)

    versions = {d for d in listdir(users_dir) if d[0].isdigit()}
    assert versions == {OLD_VERSION_DIR, VERSION_DIR}
    final_log = path.join(users_dir, VERSION_DIR, "configs", ".migration")
    with open(final_log, encoding="UTF-8") as f:
        assert "Migrating from 3.1.3 to 3.1.4" in f.read()
    assert "Removed intermediate version 3.1.4" in service.log_message


def test_versions_that_were_there_before_stay(users_dir, boot_config_manager):
    make_old_version(users_dir, "3_1_0", {"Star Citizen": {"Computer.yaml": None}})
    make_old_version(users_dir, OLD_VERSION_DIR, {"Star Citizen": {"Computer.yaml": None}})

    boot_and_migrate(boot_config_manager)

    versions = {d for d in listdir(users_dir) if d[0].isdigit()}
    assert versions == {"3_1_0", OLD_VERSION_DIR, VERSION_DIR}


def test_an_old_inworld_default_becomes_the_current_one(users_dir, boot_config_manager):
    old_configs = make_old_version(users_dir, OLD_VERSION_DIR, {"Star Citizen": {"Computer.yaml": None}})
    defaults_file = path.join(old_configs, "defaults.yaml")
    defaults = read_yaml(defaults_file)
    defaults["inworld"]["model_id"] = "inworld-tts-1"
    write_yaml(defaults_file, defaults)

    boot_and_migrate(boot_config_manager)

    migrated = read_yaml(path.join(users_dir, VERSION_DIR, "configs", "defaults.yaml"))
    assert migrated["inworld"]["model_id"] == "inworld-tts-2-flash"


def test_the_old_typos_in_command_texts_are_fixed(users_dir, boot_config_manager):
    make_old_version(users_dir, OLD_VERSION_DIR, {"Star Citizen": {"Computer.yaml": _old_computer()}})

    boot_and_migrate(boot_config_manager)

    commands = {c["name"]: c for c in _wingman(users_dir, "Star Citizen", "Computer")["commands"]}
    assert commands["More missiles"]["additional_context"] == "Missile salvo size cycled by +1"
