from enum import Enum
from os import makedirs, path, remove, walk
import copy
import shutil
from pydantic import ValidationError
import yaml
from api.enums import LogSource, LogType, enum_representer
from api.interface import Config, SettingsConfig, WingmanConfig
from services.file import get_writable_dir
from services.printr import Printr

CONFIGS_DIR = "configs"
TEMPLATES_DIR = "configs/templates"
DEFAULT_CONFIG_DIR = "Star Citizen"
SETTINGS_CONFIG_FILE = "settings.yaml"
DEFAULT_TEMPLATE_FILE = "defaults.yaml"
SECRETS_FILE = "secrets.yaml"


class ConfigManager:
    def __init__(self, app_root_path: str):
        self.printr = Printr()

        self.config_dir = get_writable_dir(CONFIGS_DIR)
        self.templates_dir = path.join(app_root_path, TEMPLATES_DIR)

        self.settings_config_path = path.join(self.config_dir, SETTINGS_CONFIG_FILE)
        self.create_settings_config()
        self.settings_config = self.load_settings_config()

        self.create_configs_from_templates()
        self.log_source_name = "ConfigManager"

    def create_settings_config(self):
        if not path.exists(self.settings_config_path):
            try:
                with open(self.settings_config_path, "w", encoding="UTF-8"):
                    return True  # just create an empty file
            except OSError as e:
                self.printr.toast_error(
                    f"Could not create ({SETTINGS_CONFIG_FILE})\n{str(e)}"
                )
        return False

    def load_settings_config(self):
        """Load and validate Settings config"""
        parsed = self.__read_config(self.settings_config_path)
        if parsed:
            try:
                validated = SettingsConfig(**parsed)
                return validated
            except ValidationError as e:
                self.printr.toast_error(
                    f"Invalid config '{self.settings_config_path}':\n{str(e)}"
                )
        return None

    def save_settings_config(self):
        """Write Settings config to file"""
        return self.__write_config(self.settings_config_path, self.settings_config)

    def create_config(self, config_name: str, template: str = None):
        new_dir = get_writable_dir(path.join(self.config_dir, config_name))

        template_dir = path.join(self.templates_dir, template)
        if template_dir and path.exists(template_dir):
            for root, _, files in walk(template_dir):
                for filename in files:
                    if filename.endswith("template.yaml"):
                        shutil.copyfile(
                            path.join(root, filename),
                            path.join(new_dir, filename.replace(".template", "")),
                        )

    def create_configs_from_templates(self, force: bool = False):
        for root, dirs, files in walk(self.templates_dir):
            relative_path = path.relpath(root, self.templates_dir)

            # skip logical deleted configs (starting with ".")
            if (
                not force
                and relative_path != "."
                and path.exists(path.join(self.config_dir, f".{relative_path}"))
            ):
                continue

            # Create the same relative path in the target directory
            target_path = (
                self.config_dir
                if relative_path == "."
                else path.join(self.config_dir, relative_path)
            )

            if not path.exists(target_path):
                makedirs(target_path)

            for filename in files:
                if filename.endswith(".yaml"):
                    new_filename = filename.replace(".template", "")
                    new_filepath = path.join(target_path, new_filename)
                    already_exists = path.exists(new_filepath)
                    # don't recreate Wingmen configs starting with "." (logical deleted)
                    logical_deleted = path.exists(
                        path.join(target_path, f".{new_filename}")
                    )

                    if force or (not already_exists and not logical_deleted):
                        shutil.copyfile(path.join(root, filename), new_filepath)

    def get_config_names(self) -> list[str]:
        return [
            name for name in next(walk(self.config_dir))[1] if not name.startswith(".")
        ]

    def get_templated_config_names(self) -> list[str]:
        return [name for name in next(walk(self.templates_dir))[1]]

    def get_templated_wingmen_config_names(
        self, templated_config_name: str
    ) -> list[str]:
        template_dir = path.join(self.templates_dir, templated_config_name)
        if not path.exists(template_dir):
            return []

        for root, dirs, files in walk(template_dir):
            for filename in files:
                if filename.endswith("template.yaml"):
                    yield filename.replace(".template", "")

    def load_config(self, config_dir=DEFAULT_CONFIG_DIR) -> Config:
        config_path = path.join(self.config_dir, config_dir)

        if not path.exists(config_path):
            self.printr.toast_error(f"Config path '{config_path}' not found.")
            return None

        parsed_config = self.__read_default_config()

        for root, _, files in walk(config_path):
            for filename in files:
                if filename.endswith(".yaml") and not filename.startswith("."):
                    wingman_config = self.__read_config(path.join(root, filename))
                    merged_config = self.__merge_configs(parsed_config, wingman_config)
                    parsed_config["wingmen"][
                        filename.replace(".yaml", "")
                    ] = merged_config

        validated_config = Config(**parsed_config)
        # not catching ValifationExceptions here, because we can't recover from it
        # TODO: Notify the client about the error somehow

        self.printr.print(
            f"Loaded and validated config: {config_dir}.",
            color=LogType.INFO,
            server_only=True,
            source=LogSource.SYSTEM,
            source_name=self.log_source_name,
        )
        return validated_config

    def delete_config(self, config_name: str, force: bool = False):
        config_path = path.join(self.config_dir, config_name)

        if path.exists(config_path):
            if not force and config_name in self.get_template_config_names():
                # if we'd delete this, Wingman would recreate it on next launch -
                # so we rename it to ".<name>" and interpret this as "logical delete" later.
                shutil.move(config_path, path.join(self.config_dir, f".{config_name}"))
                self.printr.print(
                    f"Renamed config '{config_name}' to '.{config_name}' (logical delete).",
                    color=LogType.INFO,
                    server_only=True,
                    source=LogSource.SYSTEM,
                    source_name=self.log_source_name,
                )
            else:
                shutil.rmtree(config_path)
                self.printr.print(
                    f"Deleted config {config_path}.",
                    color=LogType.INFO,
                    server_only=True,
                    source=LogSource.SYSTEM,
                    source_name=self.log_source_name,
                )
            return True

        self.printr.toast_error(
            f"Unable to delete '{config_path}'. The path does not exist."
        )
        return False

    def save_wingman_config(
        self, config_name: str, wingman_name: str, wingman_config: WingmanConfig
    ):
        config_path = path.join(self.config_dir, config_name, f"{wingman_name}.yaml")
        return self.__write_config(config_path, wingman_config)

    def delete_wingman_config(self, config_name: str, wingman_name: str):
        wingman_config_name = f"{wingman_name}.yaml"
        file_path = path.join(self.config_dir, config_name, wingman_config_name)

        try:
            # if we'd delete this, Wingman would recreate it on next launch -
            # so we rename it to ".<name>" and interpret this as "logical delete" later.
            if wingman_config_name in self.get_templated_wingmen_config_names(
                config_name
            ):
                shutil.move(
                    file_path,
                    path.join(self.config_dir, config_name, f".{wingman_config_name}"),
                )
                self.printr.print(
                    f"Renamed wingman config '{wingman_config_name}' to '.{wingman_config_name}' (logical delete).",
                    color=LogType.INFO,
                    server_only=True,
                    source=LogSource.SYSTEM,
                    source_name=self.log_source_name,
                )
            else:
                remove(file_path)
                self.printr.print(
                    f"Deleted config {file_path}.",
                    color=LogType.INFO,
                    server_only=True,
                    source=LogSource.SYSTEM,
                    source_name=self.log_source_name,
                )
            return True
        except FileNotFoundError:
            self.printr.toast_error(
                f"Unable to delete {file_path}. The file does not exist."
            )
        except PermissionError:
            self.printr.toast_error(
                f"You do not have permissions to delete file {file_path}."
            )
        except OSError as e:
            self.printr.toast_error(
                f"Error when trying to delete file {file_path}: {e.strerror}"
            )
        return False

    def __read_config(self, file_path: str):
        """Loads a config file (without validating it)"""
        with open(file_path, "r", encoding="UTF-8") as stream:
            try:
                parsed = yaml.safe_load(stream)
                return parsed
            except yaml.YAMLError as e:
                self.printr.toast_error(
                    f"Could not read config '{file_path}':\n{str(e)}"
                )
        return None

    def __read_default_config(self):
        config = self.__read_config(path.join(self.config_dir, DEFAULT_TEMPLATE_FILE))
        config["wingmen"] = {}
        return config

    def __write_config(self, file_path: str, content) -> bool:
        yaml.add_multi_representer(Enum, enum_representer)
        with open(file_path, "w", encoding="UTF-8") as stream:
            try:
                yaml.dump(content.dict(exclude_none=True), stream)
                return True
            except yaml.YAMLError as e:
                self.printr.toast_error(
                    f"Could not write config '{file_path}')!\n{str(e)}"
                )
        return False

    def __deep_merge(self, source, updates):
        """Recursively merges updates into source."""
        if updates is None:
            return source

        for key, value in updates.items():
            if isinstance(value, dict):
                node = source.setdefault(key, {})
                self.__deep_merge(node, value)
            else:
                source[key] = value
        return source

    def __merge_command_lists(self, general_commands, wingman_commands):
        """Merge two lists of commands, where wingman-specific commands override or get added based on the 'name' key."""

        if wingman_commands is None:
            return general_commands

        # Use a dictionary to ensure unique names and allow easy overrides
        merged_commands = {cmd["name"]: cmd for cmd in general_commands}
        for cmd in wingman_commands:
            merged_commands[
                cmd["name"]
            ] = cmd  # Will override or add the wingman-specific command
        # Convert merged commands back to a list since that's the expected format
        return list(merged_commands.values())

    def __merge_configs(self, general: Config, wingman):
        """Merge general settings with a specific wingman's overrides, including commands."""
        # Start with a copy of the wingman's specific config to keep it intact.
        merged = wingman.copy()
        # Update 'openai', 'features', and 'edge_tts' sections from general config into wingman's config.
        for key in [
            "sound",
            "openai",
            "features",
            "edge_tts",
            "elevenlabs",
            "azure",
            "xvasynth",
        ]:
            if key in general:
                # Use copy.deepcopy to ensure a full deep copy is made and original is untouched.
                merged[key] = self.__deep_merge(
                    copy.deepcopy(general[key]), wingman.get(key, {})
                )

        # Special handling for merging the commands lists
        if "commands" in general and "commands" in wingman:
            merged["commands"] = self.__merge_command_lists(
                general["commands"], wingman["commands"]
            )
        elif "commands" in general:
            # If the wingman config does not have commands, use the general ones
            merged["commands"] = general["commands"]
        # No else needed; if 'commands' is not in general, we simply don't set it

        return WingmanConfig(**merged)
