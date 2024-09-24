import base64
from enum import Enum
import json
from os import makedirs, path, remove, walk
import copy
import shutil
from typing import Optional, Tuple
from pydantic import BaseModel, ValidationError
import yaml
from api.enums import LogSource, LogType, enum_representer
from api.interface import (
    Config,
    ConfigDirInfo,
    NestedConfig,
    NewWingmanTemplate,
    SettingsConfig,
    WingmanConfig,
    WingmanConfigFileInfo,
)
from services.file import get_writable_dir
from services.printr import Printr

TEMPLATES_DIR = "templates"
CONFIGS_DIR = "configs"
SKILLS_DIR = "skills"

SETTINGS_CONFIG_FILE = "settings.yaml"
DEFAULT_CONFIG_FILE = "defaults.yaml"
SECRETS_FILE = "secrets.yaml"
DEFAULT_WINGMAN_AVATAR = "default-wingman-avatar.png"
DEFAULT_SKILLS_CONFIG = "default_config.yaml"

DELETED_PREFIX = "."
DEFAULT_PREFIX = "_"


class ConfigManager:
    def __init__(self, app_root_path: str):
        self.log_source_name = "ConfigManager"
        self.printr = Printr()

        self.templates_dir = path.join(app_root_path, TEMPLATES_DIR)
        self.config_dir = get_writable_dir(CONFIGS_DIR)
        self.skills_dir = get_writable_dir(SKILLS_DIR)

        self.copy_templates()

        self.settings_config_path = path.join(self.config_dir, SETTINGS_CONFIG_FILE)
        self.default_config_path = path.join(self.config_dir, DEFAULT_CONFIG_FILE)
        self.create_settings_config()
        self.settings_config = self.load_settings_config()
        self.default_config = self.load_defaults_config()

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
                server_only=True,
            )
            return fallback

        if count_default > 1:
            self.printr.print(
                f"Multiple default configs found. Picking the first found: {default_dir.directory}.",
                color=LogType.WARNING,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
                server_only=True,
            )
        return default_dir

    def create_config(self, config_name: str, template: Optional[ConfigDirInfo] = None):
        new_dir = get_writable_dir(path.join(self.config_dir, config_name))

        if template:
            for root, _, files in walk(
                path.join(self.templates_dir, CONFIGS_DIR, template.directory)
            ):
                for filename in files:
                    if filename.endswith("template.yaml"):
                        shutil.copyfile(
                            path.join(root, filename),
                            path.join(new_dir, filename.replace(".template", "")),
                        )
        return ConfigDirInfo(
            name=config_name,
            directory=config_name,
            is_default=False,
            is_deleted=False,
        )

    def get_config_dir_path(self, config_name: Optional[str] = "") -> str:
        return (
            path.join(self.config_dir, config_name) if config_name else self.config_dir
        )

    def copy_templates(self, force: bool = False):
        for root, dirs, files in walk(self.templates_dir):
            relative_path = path.relpath(root, self.templates_dir)
            if relative_path != ".":
                config_dir_name = (
                    relative_path.replace(DELETED_PREFIX, "", 1)
                    .replace(DEFAULT_PREFIX, "", 1)
                    .replace(f"{CONFIGS_DIR}{path.sep}", "", 1)
                    .replace("/", path.sep)
                )
                config_dir = self.get_config_dir(config_dir_name)
                if not force and config_dir:
                    # skip logically deleted and default (renamed) config dirs
                    continue

            # Create the same relative path in the target directory
            target_path = get_writable_dir(
                relative_path if relative_path != "." else ""
            )

            if not path.exists(target_path):
                makedirs(target_path)

            for filename in files:
                # yaml files
                if filename == ".DS_Store":
                    continue

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
                else:
                    new_filepath = path.join(target_path, filename)
                    already_exists = path.exists(new_filepath)
                    if force or not already_exists:
                        shutil.copyfile(path.join(root, filename), new_filepath)
                        self.printr.print(
                            f"Created file {new_filepath} from template.",
                            color=LogType.INFO,
                            server_only=True,
                            source=LogSource.SYSTEM,
                            source_name=self.log_source_name,
                        )

    def get_config_dirs(self) -> list[ConfigDirInfo]:
        """Gets all config dirs."""
        return self.__get_dirs_info(self.config_dir)

    def get_config_template_dirs(self) -> list[ConfigDirInfo]:
        """Gets all config template dirs."""
        return self.__get_dirs_info(path.join(self.templates_dir, CONFIGS_DIR))

    def __get_template_dir(self, config_dir: ConfigDirInfo) -> Optional[ConfigDirInfo]:
        """Gets the template directory for a given config directory."""
        template_dir = path.join(self.templates_dir, CONFIGS_DIR, config_dir.directory)
        if not path.exists(template_dir):
            # check if "defaulted" template dir exists
            default_template_dir = path.join(
                self.templates_dir,
                CONFIGS_DIR,
                f"{DEFAULT_PREFIX}{config_dir.directory}",
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
            path.join(self.templates_dir, CONFIGS_DIR, config_dir.directory)
        ):
            for filename in files:
                # templates are never logically deleted
                base_file_name = filename.replace(".template", "")
                if (
                    filename.endswith("template.yaml")
                    # but the given wingman config might be logically deleted
                    and base_file_name == wingman_file.file
                    or (
                        wingman_file.file.startswith(DELETED_PREFIX)
                        and base_file_name == wingman_file.file[1:]
                    )
                ):
                    file_info = WingmanConfigFileInfo(
                        file=base_file_name,
                        name=base_file_name,
                        is_deleted=False,
                        avatar=self.__load_image_as_base64(
                            self.get_wingman_avatar_path(template_dir, base_file_name)
                        ),
                    )
                    return (
                        template_dir,
                        file_info,
                    )
        return (None, None)

    def __load_image_as_base64(self, file_path: str):
        with open(file_path, "rb") as image_file:
            image_bytes = image_file.read()

        base64_encoded_data = base64.b64encode(image_bytes)
        base64_string = base64_encoded_data.decode("utf-8")
        base64_data_uri = f"data:image/png;base64,{base64_string}"

        return base64_data_uri

    def get_new_wingman_template(self):
        parsed_config = self.read_default_config()
        wingman_config = {
            "name": "",
            "description": "",
            "record_key": "",
            "disabled": False,
            "commands": [],
            "skills": [],
            "prompts": {"backstory": ""},
        }
        validated_config = self.merge_configs(parsed_config, wingman_config)
        return NewWingmanTemplate(
            wingman_config=validated_config,
            avatar=self.__load_image_as_base64(
                path.join(self.templates_dir, CONFIGS_DIR, DEFAULT_WINGMAN_AVATAR)
            ),
        )

    def parse_config(
        self, config_dir: Optional[ConfigDirInfo] = None
    ) -> Tuple[ConfigDirInfo, Config]:
        """Loads and validates a config. If no config_dir is given, the default config is loaded."""
        if not config_dir:
            config_dir = self.find_default_config()

        config_path = path.join(self.config_dir, config_dir.directory)
        default_config = self.read_default_config()

        for root, _, files in walk(config_path):
            for filename in files:
                if filename.endswith(".yaml") and not filename.startswith("."):
                    wingman_config = self.read_config(path.join(root, filename))
                    merged_config = self.merge_configs(default_config, wingman_config)
                    default_config["wingmen"][
                        filename.replace(".yaml", "")
                    ] = merged_config

        validated_config = Config(**default_config)
        # not catching ValidationExceptions here, because we can't recover from it
        # TODO: Notify the client about the error somehow

        return config_dir, validated_config

    def rename_config(self, config_dir: ConfigDirInfo, new_name: str):
        if new_name == config_dir.name:
            self.printr.print(
                f"Skip rename config {config_dir.name} because the name did not change.",
                color=LogType.WARNING,
                server_only=True,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )
            return None
        if new_name.startswith(DEFAULT_PREFIX) or new_name.startswith(DELETED_PREFIX):
            self.printr.toast_error(
                f"Unable to rename '{config_dir.name}' to '{new_name}'. The name must not start with '{DEFAULT_PREFIX}' or '{DELETED_PREFIX}'."
            )
            return None

        old_path = path.join(self.config_dir, config_dir.directory)
        new_dir_name = (
            new_name if not config_dir.is_default else f"{DEFAULT_PREFIX}{new_name}"
        )
        new_path = path.join(self.config_dir, new_dir_name)

        if path.exists(new_path):
            self.printr.toast_error(
                f"Unable to rename '{config_dir.name}' to '{new_name}'. The target already exists."
            )
            return None

        if self.__get_template_dir(config_dir):
            # if we'd rename this, Wingman will recreate it on next launch -
            # so we create the new one and rename the old dir to ".<name>" .
            shutil.copytree(old_path, new_path)
            shutil.move(
                old_path,
                path.join(self.config_dir, f"{DELETED_PREFIX}{config_dir.name}"),
            )

            self.printr.print(
                f"Logically deleted config '{config_dir.name}' and created new config '{new_name}'.",
                color=LogType.INFO,
                server_only=True,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )
        else:
            shutil.move(path.join(self.config_dir, config_dir.directory), new_path)
            self.printr.print(
                f"Renamed config '{config_dir.directory}' to '{new_dir_name}'.",
                color=LogType.INFO,
                server_only=True,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )
        return ConfigDirInfo(
            name=new_name,
            directory=new_dir_name,
            is_default=new_dir_name.startswith(DEFAULT_PREFIX),
            is_deleted=new_dir_name.startswith(DELETED_PREFIX),
        )

    def delete_config(self, config_dir: ConfigDirInfo, force: bool = False):
        config_path = path.join(self.config_dir, config_dir.directory)
        if config_dir.is_deleted:
            self.printr.print(
                f"Skip delete config {config_dir.name} because it is already marked as deleted.",
                color=LogType.WARNING,
                server_only=True,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )
            return False

        if path.exists(config_path):
            if not force and self.__get_template_dir(config_dir):
                # if we'd delete this, Wingman would recreate it on next launch -
                # so we rename it to ".<name>" and interpret this as "logical delete" later.
                shutil.move(
                    config_path,
                    path.join(
                        self.config_dir,
                        f"{DELETED_PREFIX}{config_dir.name}",
                    ),
                )
                config_dir.is_deleted = True
                self.printr.print(
                    f"Renamed config '{config_dir.name}' to '{DELETED_PREFIX}{config_dir.name}' (logical delete).",
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

            if config_dir.is_default:
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

    def set_default_config(self, config_dir: ConfigDirInfo):
        """Sets a config as the new default config (and unsets the old one)."""
        if config_dir.is_deleted:
            self.printr.print(
                f"Unable to set deleted config {config_dir.name} as default config.",
                color=LogType.ERROR,
                server_only=True,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )
            return False

        old_default = self.find_default_config()
        if config_dir.is_default:
            self.printr.print(
                f"Config {config_dir.name} is already the default config.",
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

        new_dir = path.join(self.config_dir, f"{DEFAULT_PREFIX}{config_dir.name}")
        shutil.move(
            path.join(self.config_dir, config_dir.directory),
            new_dir,
        )
        config_dir.directory = new_dir
        config_dir.is_default = True

        self.printr.print(
            f"Set config {config_dir.name} as default config.",
            color=LogType.INFO,
            server_only=True,
            source=LogSource.SYSTEM,
            source_name=self.log_source_name,
        )
        return True

    def get_wingmen_configs(self, config_dir: ConfigDirInfo):
        """Gets all wingmen configs for a given config."""
        config_path = path.join(self.config_dir, config_dir.directory)
        wingmen: list[WingmanConfigFileInfo] = []
        for _, _, files in walk(config_path):
            for filename in files:
                if filename.endswith(".yaml"):
                    base_file_name = filename.replace(".yaml", "").replace(".", "", 1)
                    wingman_file = WingmanConfigFileInfo(
                        file=filename,
                        name=base_file_name,
                        is_deleted=filename.startswith(DELETED_PREFIX),
                        avatar=self.__load_image_as_base64(
                            self.get_wingman_avatar_path(config_dir, base_file_name)
                        ),
                    )
                    wingmen.append(wingman_file)
        return wingmen

    def save_wingman_config(
        self,
        config_dir: ConfigDirInfo,
        wingman_file: WingmanConfigFileInfo,
        wingman_config: WingmanConfig,
    ):
        # write avatar base64 str to file
        if wingman_file.avatar:
            avatar_path = self.get_wingman_avatar_path(
                config_dir=config_dir,
                wingman_file_base_name=wingman_file.name,
                create=True,
            )
            if "base64," in wingman_file.avatar:
                avatar = wingman_file.avatar.split("base64,", 1)[1]
            image_data = base64.b64decode(avatar)
            with open(avatar_path, "wb") as file:
                file.write(image_data)

        # wingman was renamed
        if wingman_config.name != wingman_file.name:
            old_config_path = path.join(
                self.config_dir, config_dir.directory, wingman_file.file
            )

            # check if there is a template for the old name
            tpl, wng = self.__get_template(config_dir, wingman_file)
            if tpl and wng:
                # leave a .[OLD] file so that it won't be recreated next time
                shutil.copyfile(
                    old_config_path,
                    path.join(
                        self.config_dir,
                        config_dir.directory,
                        f"{DELETED_PREFIX}{wng.file}",
                    ),
                )

            # move the config
            shutil.move(
                old_config_path,
                path.join(
                    self.config_dir,
                    config_dir.directory,
                    wingman_config.name + ".yaml",
                ),
            )

            # move the avatar
            old_avatar_path = path.join(
                self.config_dir,
                config_dir.directory,
                wingman_file.name + ".png",
            )
            if path.exists(old_avatar_path):
                shutil.move(
                    old_avatar_path,
                    path.join(
                        self.config_dir,
                        config_dir.directory,
                        wingman_config.name + ".png",
                    ),
                )

            wingman_file.name = wingman_config.name
            wingman_file.file = wingman_config.name + ".yaml"

        config_path = path.join(
            self.config_dir,
            config_dir.directory,
            wingman_file.file,
        )
        default_config = self.read_default_config()
        wingman_config_dict = self.convert_to_dict(wingman_config)
        wingman_config_diff = self.deep_diff(default_config, wingman_config_dict)

        if wingman_config.skills:
            skills = []

            for skill_config in wingman_config.skills:
                skill_dir = skill_config.module.replace(".main", "").replace(".", "/")
                skill_default_config_path = path.join(
                    get_writable_dir(skill_dir), DEFAULT_SKILLS_CONFIG
                )
                skill_default_config = self.read_config(skill_default_config_path)
                skill_config_diff = self.deep_diff(
                    skill_default_config, self.convert_to_dict(skill_config)
                )
                skill_config_diff["module"] = skill_config.module
                skills.append(skill_config_diff)

            wingman_config_diff["skills"] = skills

        return self.write_config(config_path, wingman_config_diff)

    def get_wingman_avatar_path(
        self, config_dir: ConfigDirInfo, wingman_file_base_name: str, create=False
    ):
        avatar_path = path.join(
            self.config_dir, config_dir.directory, f"{wingman_file_base_name}.png"
        )
        default_avatar_path = path.join(
            self.templates_dir, CONFIGS_DIR, DEFAULT_WINGMAN_AVATAR
        )
        return (
            avatar_path if create or path.exists(avatar_path) else default_avatar_path
        )

    def delete_wingman_config(
        self, config_dir: ConfigDirInfo, wingman_file: WingmanConfigFileInfo
    ):
        config_path = path.join(
            self.config_dir, config_dir.directory, wingman_file.file
        )
        avatar_path = path.join(
            self.config_dir, config_dir.directory, f"{wingman_file.name}.png"
        )

        try:
            if path.exists(avatar_path):
                remove(avatar_path)

            remove(config_path)
            self.printr.print(
                f"Deleted config {config_path}.",
                color=LogType.INFO,
                server_only=True,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )
            wingman_file.is_deleted = True
            return True
        except FileNotFoundError:
            self.printr.toast_error(
                f"Unable to delete {config_path}. The file does not exist."
            )
        except PermissionError:
            self.printr.toast_error(
                f"You do not have permissions to delete file {config_path}."
            )
        except OSError as e:
            self.printr.toast_error(
                f"Error when trying to delete file {config_path}: {e.strerror}"
            )
        return False

    def read_default_config(self):
        config = self.read_config(self.default_config_path)
        config["wingmen"] = {}
        return config

    def read_config(self, file_path: str):
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

    def write_config(self, file_path: str, content) -> bool:
        yaml.add_multi_representer(Enum, enum_representer)

        dir_path = path.dirname(file_path)
        if not path.exists(dir_path):
            makedirs(dir_path)

        with open(file_path, "w", encoding="UTF-8") as stream:
            try:
                yaml.dump(
                    (
                        content
                        if isinstance(content, dict)
                        else content.dict(exclude_none=True)
                    ),
                    stream,
                )
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
        parsed = self.read_config(self.settings_config_path)
        if parsed:
            try:
                validated = SettingsConfig(**parsed)
                return validated
            except ValidationError as e:
                self.printr.toast_error(
                    f"Invalid config '{self.settings_config_path}':\n{str(e)}"
                )
        return SettingsConfig()

    def load_defaults_config(self):
        """Load and validate Defaults config"""
        parsed = self.read_default_config()
        if parsed:
            try:
                validated = NestedConfig(**parsed)
                return validated
            except ValidationError as e:
                self.printr.toast_error(
                    f"Invalid default config '{self.default_config_path}':\n{str(e)}"
                )
        return None

    def load_wingman_config(
        self, config_dir: ConfigDirInfo, wingman_file: WingmanConfigFileInfo
    ):
        """Load and validate Wingman config"""
        full_path = path.join(self.config_dir, config_dir.directory, wingman_file.file)
        default_config = self.read_default_config()
        wingman_config_parsed = self.read_config(full_path)
        merged_config = self.merge_configs(default_config, wingman_config_parsed)
        return merged_config

    def save_settings_config(self):
        """Write Settings config to file"""
        return self.write_config(self.settings_config_path, self.settings_config)

    def save_defaults_config(self):
        """Write Defaults config to file"""
        return self.write_config(self.default_config_path, self.default_config)

    # Config merging:

    def convert_to_dict(self, obj):
        if isinstance(obj, BaseModel):
            json_obj = obj.model_dump_json(exclude_none=True, exclude_unset=True)
            return json.loads(json_obj)
        elif isinstance(obj, dict):
            return {k: self.convert_to_dict(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.convert_to_dict(i) for i in obj]
        return obj

    def deep_diff(self, default_config, wingman_config):
        """
        Recursively compare two dictionaries and return an object that only contains the changes defined in the wingman_config.
        """
        diff = {}

        for key in wingman_config:
            if key == "id":
                diff[key] = wingman_config[key]
                continue

            wingman_value = wingman_config[key]
            default_value = default_config.get(key, None)

            if default_value is None:
                # If the key is not in the default config, it's a new addition.
                diff[key] = wingman_value
            elif isinstance(wingman_value, dict) and isinstance(default_value, dict):
                # If the key exists in both configurations and both values are dictionaries, recurse.
                nested_diff = self.deep_diff(default_value, wingman_value)
                if nested_diff:
                    diff[key] = nested_diff
            elif isinstance(wingman_value, list) and isinstance(default_value, list):
                # If the values are lists, compare each element.
                list_diff = self.__diff_lists(default_value, wingman_value)
                if list_diff:
                    diff[key] = list_diff
            elif wingman_value != default_value:
                # If the values are different, record the difference.
                diff[key] = wingman_value

        return diff

    def __diff_lists(self, default_list, wingman_list):
        """
        Compare two lists and return the differences.
        """
        if all(isinstance(item, dict) for item in default_list + wingman_list):
            # If both lists contain dictionaries, use identifiers to compare
            identifier = None
            for id_key in ["id", "module", "name"]:
                if any(id_key in item for item in default_list + wingman_list):
                    identifier = id_key
                    break
            if identifier:
                default_dict = {
                    item[identifier]: item
                    for item in default_list
                    if identifier in item
                }
                wingman_dict = {
                    item[identifier]: item
                    for item in wingman_list
                    if identifier in item
                }
                diff = []
                for item_key in wingman_dict:
                    if item_key in default_dict:
                        nested_diff = self.deep_diff(
                            default_dict[item_key], wingman_dict[item_key]
                        )
                        if nested_diff:
                            diff.append(nested_diff)
                    else:
                        diff.append(wingman_dict[item_key])
                return diff
            else:
                # If the dictionaries don't have an identifier key, take the wingman list as diff
                return wingman_list
        else:
            # If the lists are basic types or not dictionaries, sort and compare
            default_list_sorted = sorted(default_list)
            wingman_list_sorted = sorted(wingman_list)
            diff = []
            len_default = len(default_list_sorted)

            for i, wingman_value in enumerate(wingman_list_sorted):
                if i < len_default:
                    default_value = default_list_sorted[i]
                    if isinstance(wingman_value, dict) and isinstance(
                        default_value, dict
                    ):
                        nested_diff = self.deep_diff(default_value, wingman_value)
                        if nested_diff:
                            diff.append(nested_diff)
                    elif wingman_value != default_value:
                        diff.append(wingman_value)
                else:
                    diff.append(wingman_value)

            return diff

    def __deep_merge(self, source: dict, updates: dict) -> dict:
        """
        Deep merge two dictionaries.
        """
        if updates is None:
            return source

        for key, val in updates.items():
            if (
                isinstance(val, dict)
                and key in source
                and isinstance(source[key], dict)
            ):
                source[key] = self.__deep_merge(source[key], val)
            elif (
                isinstance(val, list)
                and key in source
                and isinstance(source[key], list)
            ):
                source[key] = self.__merge_list(source[key], val)
            else:
                source[key] = val
        return source

    def __merge_list(self, source: list, updates: list) -> list:
        """
        Merges two lists of dictionaries based on a unique identifier key if available.
        For generic lists without identifiable keys, the override list replaces the base list.
        """
        # Check if items in both lists are dictionaries with an "id" key
        if all(isinstance(item, dict) and "id" in item for item in source + updates):
            base_dict = {item["id"]: item for item in source}
            for item in updates:
                item_id = item["id"]
                if item_id in base_dict:
                    base_dict[item_id] = self.__deep_merge(base_dict[item_id], item)
                else:
                    base_dict[item_id] = item
            return list(base_dict.values())
        else:
            # Generic list replacement: assume override list replaces base list
            return updates

    def __merge_command_lists(self, default_commands, wingman_commands):
        """Merge two lists of commands, where wingman-specific commands override or get added based on the 'name' key."""

        if wingman_commands is None:
            return default_commands

        # Use a dictionary to ensure unique names and allow easy overrides
        merged_commands = {cmd["name"]: cmd for cmd in default_commands}
        for cmd in wingman_commands:
            merged_commands[cmd["name"]] = (
                cmd  # Will override or add the wingman-specific command
            )
        # Convert merged commands back to a list since that's the expected format
        return list(merged_commands.values())

    def merge_configs(self, default: Config, wingman):
        """Merge general settings with a specific wingman's overrides, including commands."""
        # Start with a copy of the wingman's specific config to keep it intact.
        merged = wingman.copy()

        for key in [
            "prompts",
            "features",
            "sound",
            "openai",
            "mistral",
            "groq",
            "cerebras",
            "google",
            "openrouter",
            "local_llm",
            "edge_tts",
            "elevenlabs",
            "azure",
            "whispercpp",
            "xvasynth",
            "wingman_pro",
            "perplexity",
        ]:
            if key in default:
                # Use copy.deepcopy to ensure a full deep copy is made and original is untouched.
                merged[key] = self.__deep_merge(
                    copy.deepcopy(default[key]), wingman.get(key, {})
                )

        # Commands
        if "commands" in default and "commands" in wingman:
            merged["commands"] = self.__merge_command_lists(
                default["commands"], wingman["commands"]
            )
        elif "commands" in default:
            # If the wingman config does not have commands, use the general ones
            merged["commands"] = default["commands"]

        # Skills
        if "skills" in wingman:
            merged_skills = []
            for skill_config_wingman in wingman["skills"]:
                skill_dir = (
                    skill_config_wingman["module"]
                    .replace(".main", "")
                    .replace(".", "/")
                    .split("/")[1]
                )

                skill_default_config_path = path.join(
                    self.skills_dir, skill_dir, DEFAULT_SKILLS_CONFIG
                )
                skill_config = self.read_config(skill_default_config_path)
                skill_config = self.__deep_merge(skill_config, skill_config_wingman)

                merged_skills.append(skill_config)

            merged["skills"] = merged_skills
        elif "skills" in default:
            merged["skills"] = default["skills"]

        return WingmanConfig(**merged)
