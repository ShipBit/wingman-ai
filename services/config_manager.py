from enum import Enum
from os import makedirs, path, remove, walk
import copy
import shutil
from typing import Optional, Tuple
from pydantic import ValidationError
import yaml
from api.enums import LogSource, LogType, enum_representer
from api.interface import (
    Config,
    ConfigDirInfo,
    SettingsConfig,
    WingmanConfig,
    WingmanConfigFileInfo,
)
from services.file import get_writable_dir
from services.printr import Printr

CONFIGS_DIR = "configs"
TEMPLATES_DIR = "configs/templates"
SETTINGS_CONFIG_FILE = "settings.yaml"
DEFAULT_TEMPLATE_FILE = "defaults.yaml"
SECRETS_FILE = "secrets.yaml"
DELETED_PREFIX = "."
DEFAULT_PREFIX = "_"


class ConfigManager:
    def __init__(self, app_root_path: str):
        self.log_source_name = "ConfigManager"
        self.printr = Printr()

        self.config_dir = get_writable_dir(CONFIGS_DIR)
        self.templates_dir = path.join(app_root_path, TEMPLATES_DIR)

        self.settings_config_path = path.join(self.config_dir, SETTINGS_CONFIG_FILE)
        self.create_settings_config()
        self.settings_config = self.load_settings_config()

        self.create_configs_from_templates()

    def find_default_config(self) -> ConfigDirInfo:
        """Find the (first) default config (name starts with "_") found or another normal config as fallback."""
        count_default = 0
        fallback: Optional[ConfigDirInfo] = None
        default_dir: Optional[ConfigDirInfo] = None
        for _, dirs, _ in walk(self.config_dir):
            for d in dirs:
                if d.startswith(DEFAULT_PREFIX):
                    count_default += 1
                    if not default_dir:
                        default_dir = ConfigDirInfo(
                            directory=d,
                            name=d.replace(DEFAULT_PREFIX, "", 1),
                            is_default=True,
                            is_deleted=False,
                        )
                # TODO: actually make fallback the new default by renaming it (?)
                elif not fallback:
                    fallback = ConfigDirInfo(
                        directory=d,
                        name=d,
                        is_default=False,
                        is_deleted=False,
                    )

        if count_default == 0:
            self.printr.print(
                f"No default config found. Picking the first normal config found: {fallback.directory} .",
                color=LogType.ERROR,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )
            return fallback

        if count_default > 1:
            self.printr.print(
                f"Multiple default configs found. Picking the first found: {default_dir.directory}.",
                color=LogType.WARNING,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )
        return default_dir

    def create_config(self, config_name: str, template: Optional[ConfigDirInfo] = None):
        new_dir = get_writable_dir(path.join(self.config_dir, config_name))

        if template:
            for root, _, files in walk(
                path.join(self.templates_dir, template.directory)
            ):
                for filename in files:
                    if filename.endswith("template.yaml"):
                        shutil.copyfile(
                            path.join(root, filename),
                            path.join(new_dir, filename.replace(".template", "")),
                        )

    def create_configs_from_templates(self, force: bool = False):
        for root, _, files in walk(self.templates_dir):
            relative_path = path.relpath(root, self.templates_dir)
            if relative_path != ".":
                config_dir = self.get_config_dir(
                    relative_path.replace(DELETED_PREFIX, "", 1).replace(
                        DEFAULT_PREFIX, "", 1
                    )
                )
                if not force and config_dir:
                    # skip logically deleted and default (renamed) config dirs
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
                    if logical_deleted:
                        self.printr.print(
                            f"Skipping creation of {new_filepath} because it is marked as deleted.",
                            color=LogType.WARNING,
                            server_only=True,
                            source=LogSource.SYSTEM,
                            source_name=self.log_source_name,
                        )

                    if force or (not already_exists and not logical_deleted):
                        shutil.copyfile(path.join(root, filename), new_filepath)
                        self.printr.print(
                            f"Created config {new_filepath} from template.",
                            color=LogType.INFO,
                            server_only=True,
                            source=LogSource.SYSTEM,
                            source_name=self.log_source_name,
                        )

    def get_config_dirs(self) -> list[ConfigDirInfo]:
        """Gets all config dirs."""
        return self.__get_dirs_info(self.config_dir)

    def get_template_dirs(self) -> list[ConfigDirInfo]:
        """Gets all config template dirs."""
        return self.__get_dirs_info(self.templates_dir)

    def __get_template_dir(self, config_dir: ConfigDirInfo) -> Optional[ConfigDirInfo]:
        """Gets the template directory for a given config directory."""
        template_dir = path.join(self.templates_dir, config_dir.directory)
        if not path.exists(template_dir):
            # check if "defaulted" template dir exists
            default_template_dir = path.join(
                self.templates_dir, f"{DEFAULT_PREFIX}.{config_dir.directory}"
            )
            if path.exists(default_template_dir):
                return ConfigDirInfo(
                    name=config_dir.name,
                    directory=default_template_dir,
                    is_default=True,
                    is_deleted=False,
                )
            return None
        return ConfigDirInfo(
            name=config_dir.name,
            directory=config_dir.directory,
            is_default=config_dir.is_default,
            is_deleted=False,
        )

    def __get_template(
        self, config_dir: ConfigDirInfo, wingman_file: WingmanConfigFileInfo
    ) -> Tuple[Optional[ConfigDirInfo], Optional[WingmanConfigFileInfo]]:
        template_dir = self.__get_template_dir(config_dir)
        if not template_dir:
            return (None, None)

        for root, dirs, files in walk(
            path.join(self.templates_dir, config_dir.directory)
        ):
            for filename in files:
                # templates are never logically deleted
                base_file_name = filename.replace(".template", "")
                if filename.endswith(
                    "template.yaml"
                    # but the given wingman config might be logically deleted
                ) and base_file_name == wingman_file.file.replace(
                    DELETED_PREFIX, "", 1
                ):
                    return (
                        template_dir,
                        WingmanConfigFileInfo(
                            file=base_file_name, name=base_file_name, is_deleted=False
                        ),
                    )
        return (None, None)

    def load_config(
        self, config_dir: Optional[ConfigDirInfo] = None
    ) -> Tuple[ConfigDirInfo, Config]:
        """Loads and validates a config. If no config_dir is given, the default config is loaded."""
        if not config_dir:
            config_dir = self.find_default_config()

        config_path = path.join(self.config_dir, config_dir.directory)
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
            f"Loaded and validated config: {config_dir.name}.",
            color=LogType.INFO,
            server_only=True,
            source=LogSource.SYSTEM,
            source_name=self.log_source_name,
        )
        return config_dir, validated_config

    def delete_config(self, config: ConfigDirInfo, force: bool = False):
        config_path = path.join(self.config_dir, config.directory)
        if config.is_deleted:
            self.printr.print(
                f"Skip delete config {config.name} because it is already marked as deleted.",
                color=LogType.WARNING,
                server_only=True,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )
            return False

        if path.exists(config_path):
            if not force and self.__get_template_dir(config):
                # if we'd delete this, Wingman would recreate it on next launch -
                # so we rename it to ".<name>" and interpret this as "logical delete" later.
                shutil.move(
                    config_path,
                    path.join(self.config_dir, f"{DELETED_PREFIX}{config.directory}"),
                )
                config.is_deleted = True
                self.printr.print(
                    f"Renamed config '{config.name}' to '{DELETED_PREFIX}{config.name}' (logical delete).",
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

            if config.is_default:
                # will return the first normal config found because we already deleted the default one
                new_default = self.find_default_config()
                self.set_default_config(new_default)

                self.printr.print(
                    f"Deleted config {config_path} was marked as default. Picked a new default config: {new_default.name}.",
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

    def set_default_config(self, config: ConfigDirInfo):
        """Sets a config as the new default config (and unsets the old one)."""
        if config.is_deleted:
            self.printr.print(
                f"Unable to set deleted config {config.name} as default config.",
                color=LogType.ERROR,
                server_only=True,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )
            return False

        old_default = self.find_default_config()
        if config.is_default or old_default.directory == config.directory:
            self.printr.print(
                f"Config {config.name} is already the default config.",
                color=LogType.WARNING,
                server_only=True,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )
            return False

        if old_default and old_default.directory.startswith(DEFAULT_PREFIX):
            shutil.move(
                path.join(self.config_dir, old_default.directory),
                path.join(
                    self.config_dir,
                    old_default.directory.replace(DEFAULT_PREFIX, "", 1),
                ),
            )
            old_default.is_default = False

            self.printr.print(
                f"Renamed config {old_default.name} to no longer be default.",
                color=LogType.INFO,
                server_only=True,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )

        new_dir = path.join(self.config_dir, f"{DEFAULT_PREFIX}{config.name}")
        shutil.move(
            path.join(self.config_dir, config.directory),
            new_dir,
        )
        config.directory = new_dir
        config.is_default = True

        self.printr.print(
            f"Set config {config.name} as default config.",
            color=LogType.INFO,
            server_only=True,
            source=LogSource.SYSTEM,
            source_name=self.log_source_name,
        )
        return True

    def get_wingmen_configs(self, config: ConfigDirInfo):
        """Gets all wingmen configs for a given config."""
        config_path = path.join(self.config_dir, config.directory)
        wingmen = []
        for root, _, files in walk(config_path):
            for filename in files:
                if filename.endswith(".yaml"):
                    wingmen.append(
                        WingmanConfigFileInfo(
                            file=filename,
                            name=filename.replace(".yaml", "").replace(".", "", 1),
                            is_deleted=filename.startswith(DELETED_PREFIX),
                        )
                    )
        return wingmen

    def save_wingman_config(
        self,
        config: ConfigDirInfo,
        wingman_file: WingmanConfigFileInfo,
        wingman_config: WingmanConfig,
    ):
        config_path = path.join(self.config_dir, config.directory, wingman_file.file)
        return self.__write_config(config_path, wingman_config)

    def delete_wingman_config(
        self, config_dir: ConfigDirInfo, wingman_file: WingmanConfigFileInfo
    ):
        file_path = path.join(self.config_dir, config_dir.directory, wingman_file.file)

        try:
            # if we'd delete this, Wingman would recreate it on next launch -
            # so we rename it to ".<name>" and interpret this as "logical delete" later.
            if self.__get_template(config_dir, wingman_file):
                shutil.move(
                    file_path,
                    path.join(
                        self.config_dir,
                        config_dir.directory,
                        f"{DELETED_PREFIX}{wingman_file.file}",
                    ),
                )
                self.printr.print(
                    f"Renamed wingman config '{wingman_file.file}' to '{DELETED_PREFIX}{wingman_file.file}' (logical delete).",
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
            wingman_file.is_deleted = True
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

    def __read_default_config(self):
        config = self.__read_config(path.join(self.config_dir, DEFAULT_TEMPLATE_FILE))
        config["wingmen"] = {}
        return config

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

    def __get_dirs_info(self, configs_path: str) -> ConfigDirInfo:
        return [
            ConfigDirInfo(
                directory=name,
                name=name.replace(DELETED_PREFIX, "", 1).replace(DEFAULT_PREFIX, "", 1),
                is_default=name.startswith(DEFAULT_PREFIX),
                is_deleted=name.startswith(DELETED_PREFIX),
            )
            for name in next(walk(configs_path))[1]
        ]

    def get_config_dir(self, config_name: str) -> Optional[ConfigDirInfo]:
        """Gets a config dir by name."""
        for config in self.get_config_dirs():
            if config.name == config_name:
                return config
        return None

    # Settings config:

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

    # Config merging:

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
