from os import makedirs, path, walk
import copy
import shutil
from pydantic import ValidationError
import yaml
from api.interface import Config, SettingsConfig, WingmanConfig
from services.file import get_writable_dir
from services.printr import Printr

CONFIGS_DIR = "configs"
TEMPLATES_DIR = "configs/templates"
DEFAULT_CONFIG_DIR = "Star Citizen"
SETTINGS_CONFIG_FILE = "settings.yaml"
DEFAULT_TEMPLATE_FILE = "defaults.yaml"


class ConfigManager:
    def __init__(self, app_root_path: str):
        self.printr = Printr()
        self.app_root_path = app_root_path

        self.config_dir = get_writable_dir(CONFIGS_DIR)

        self.settings_config_path = path.join(self.config_dir, SETTINGS_CONFIG_FILE)
        self.create_settings_config()
        self.settings_config = self.load_settings_config()

        self.config_dirs = self.__create_configs_from_templates()

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

    def load_default_config(self) -> Config:
        config = self.__read_config(path.join(self.config_dir, DEFAULT_TEMPLATE_FILE))
        config["wingmen"] = {}
        return config

    def load_config(self, config_dir=DEFAULT_CONFIG_DIR) -> Config:
        if config_dir not in self.config_dirs:
            self.printr.toast_error(f"Config '{config_dir}' not found!")

        config = self.load_default_config()

        for root, _, files in walk(path.join(self.config_dir, config_dir)):
            for filename in files:
                if filename.endswith(".yaml"):
                    wingman_config = self.__read_config(path.join(root, filename))
                    merged_config = self.__merge_configs(config, wingman_config)
                    config["wingmen"][filename.replace(".yaml", "")] = merged_config

        # not catching ValifationExceptions here, because we can't recover from it
        # TODO: Notify the client about the error somehow
        return Config(**config)

    def create_config(self, config_name: str, template: str = None):
        new_dir = get_writable_dir(path.join(self.config_dir, config_name))

        template_dir = path.join(self.app_root_path, TEMPLATES_DIR, template)
        if template_dir and path.exists(template_dir):
            for root, _, files in walk(template_dir):
                for filename in files:
                    if filename.endswith("template.yaml"):
                        shutil.copyfile(
                            path.join(root, filename),
                            path.join(new_dir, filename),
                        )

    def delete_config(self, config_name: str):
        config_path = path.join(self.config_dir, config_name)
        if path.exists(config_path):
            shutil.rmtree(config_path)

    def save_wingman_config(self, config_name: str, wingman_name: str, config: Config):
        config_path = path.join(self.config_dir, config_name, f"{wingman_name}.yaml")
        wingman_config = config.wingmen[wingman_name]
        return self.__write_config(config_path, wingman_config)

    def __create_configs_from_templates(self, override: bool = False):
        templates_dir = path.join(self.app_root_path, TEMPLATES_DIR)
        config_dirs = []

        for root, dirs, files in walk(templates_dir):
            if len(config_dirs) == 0:
                config_dirs = dirs

            relative_path = path.relpath(root, templates_dir)

            # Create the same relative path in the target directory
            target_path = (
                self.config_dir
                if relative_path == "."
                else path.join(self.config_dir, relative_path)
            )
            if not path.exists(target_path):
                makedirs(target_path)

            for filename in files:
                if (
                    filename.endswith(".template.yaml")
                    or filename == DEFAULT_TEMPLATE_FILE
                ):
                    new_filename = filename.replace(".template", "")

                    if override or not path.exists(
                        path.join(target_path, new_filename)
                    ):
                        shutil.copyfile(
                            path.join(root, filename),
                            path.join(target_path, new_filename),
                        )

        return config_dirs

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

    def __write_config(self, file_path: str, content) -> bool:
        with open(file_path, "w", encoding="UTF-8") as stream:
            try:
                yaml.dump(content.dict(exclude_none=True), stream)
            except yaml.YAMLError as e:
                self.printr.toast_error(
                    f"Could not write config '{file_path}')!\n{str(e)}"
                )
                return False
            return True

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
