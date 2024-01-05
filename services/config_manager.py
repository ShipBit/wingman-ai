import os
import shutil
import copy
from pydantic import ValidationError
import yaml
from api.interface import Config, SettingsConfig, WingmanConfig
from services.printr import Printr

SYSTEM_CONFIG_PATH = "configs/system"
CONTEXT_CONFIG_PATH = "configs/configs"
CONTEXT_CONFIG_PATH_BUNDLED = "../configs"
DEFAULT_CONTEXT_CONFIG = "config.yaml"
EXAMPLE_CONTEXT_CONFIG = "config.example.yaml"
SETTINGS_CONFIG = "settings.yaml"


class ConfigManager:
    def __init__(self, app_root_path: str, app_is_bundled: bool):
        self.printr = Printr()
        self.settings_config: SettingsConfig = {}
        self.configs = [""]
        self.context_config_path: str = os.path.join(
            app_root_path,
            CONTEXT_CONFIG_PATH_BUNDLED if app_is_bundled else CONTEXT_CONFIG_PATH,
        )
        if not os.path.exists(self.context_config_path):
            os.makedirs(self.context_config_path)
        self.system_config_path: str = os.path.join(app_root_path, SYSTEM_CONFIG_PATH)
        self.load_settings_config()
        self.load_config_names()

    def load_settings_config(self):
        """Fetch Settings config from file and store it for future use"""
        parsed_config = self.__read_config_file(SETTINGS_CONFIG)
        try:
            self.settings_config = SettingsConfig(**parsed_config)
            return self.settings_config
        except ValidationError as e:
            self.printr.toast_error(f"Could not load settings config!\n{str(e)}")
            return None

    def save_settings_config(self):
        """Write Settings config to file"""
        return self.__write_config_file(SETTINGS_CONFIG, self.settings_config)

    def load_config_names(self):
        default_found = False
        file_prefix, file_ending = DEFAULT_CONTEXT_CONFIG.split(".")

        # Dynamically load all user configuration files from the provided directory
        for file in os.listdir(self.context_config_path):
            # Filter out all non-yaml files
            if file.endswith(f".{file_ending}") and file.startswith(f"{file_prefix}."):
                if file == DEFAULT_CONTEXT_CONFIG:
                    default_found = True
                else:
                    config_name = file.replace(f"{file_prefix}.", "").replace(
                        f".{file_ending}", ""
                    )
                    self.configs.append(config_name)

        if not default_found:
            # create default context from the systems example context config
            example_context: str = os.path.join(
                self.system_config_path, EXAMPLE_CONTEXT_CONFIG
            )
            default_context: str = os.path.join(
                self.context_config_path, DEFAULT_CONTEXT_CONFIG
            )
            if os.path.exists(example_context) and os.path.isfile(example_context):
                shutil.copyfile(example_context, default_context)

    def load_config(self, config_name=""):  # type: ignore
        # default name -> 'config.yaml'
        # context config -> 'config.{context}.yaml'
        file_name = f"config.{f'{config_name}.' if config_name else ''}yaml"

        parsed_config = self.__read_config_file(file_name, False)
        config = copy.deepcopy(parsed_config)
        config["wingmen"] = {}

        for wingman_name, wingman_config in parsed_config.get("wingmen", {}).items():
            merged_config = self.__merge_configs(config, wingman_config)
            config["wingmen"][wingman_name] = merged_config

        # not catching ValifationExceptions here, because we can't revover from it
        # TODO: Notify the client about the error somehow
        return Config(**config)

    def __read_config_file(self, config_name, is_system_config=True) -> dict[str, any]:  # type: ignore
        parsed_config = {}

        path = self.system_config_path if is_system_config else self.context_config_path
        config_file = os.path.join(path, config_name)
        if os.path.exists(config_file) and os.path.isfile(config_file):
            with open(config_file, "r", encoding="UTF-8") as stream:
                try:
                    parsed_config = yaml.safe_load(stream)
                except yaml.YAMLError as e:
                    self.printr.toast_error(
                        f"Could not load config ({config_name})!\n{str(e)}"
                    )

        return parsed_config

    def __write_config_file(self, config_name, content, is_system_config=True) -> bool:  # type: ignore
        path = self.system_config_path if is_system_config else self.context_config_path
        config_file = os.path.join(path, config_name)
        with open(config_file, "w", encoding="UTF-8") as stream:
            try:
                yaml.dump(content.dict(exclude_none=True), stream)
            except yaml.YAMLError as e:
                self.printr.toast_error(
                    f"Could not write config ({config_name})!\n{str(e)}"
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
        for key in ["sound", "openai", "features", "edge_tts", "elevenlabs", "azure", "xvasynth"]:
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
