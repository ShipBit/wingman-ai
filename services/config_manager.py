import base64
from enum import Enum
import json
from os import makedirs, path, remove, walk
import copy
import shutil
import re
from typing import Optional, Tuple
from pydantic import BaseModel, ValidationError
from dataclasses import asdict, is_dataclass
from pathlib import Path

import yaml
from api.enums import LogSource, LogType
from api.interface import (
    Config,
    ConfigDirInfo,
    McpConfig,
    NestedConfig,
    NewWingmanTemplate,
    SettingsConfig,
    WingmanConfig,
    WingmanConfigFileInfo,
)
from services.file import get_writable_dir, get_custom_skills_dir
from services.printr import Printr

TEMPLATES_DIR = "templates"
CONFIGS_DIR = "configs"
SKILLS_DIR = "skills"

SETTINGS_CONFIG_FILE = "settings.yaml"
DEFAULT_CONFIG_FILE = "defaults.yaml"
MCP_CONFIG_FILE = "mcp.yaml"
SECRETS_FILE = "secrets.yaml"
DEFAULT_WINGMAN_AVATAR = "default-wingman-avatar.png"
DEFAULT_SKILLS_CONFIG = "default_config.yaml"

DELETED_PREFIX = "."
DEFAULT_PREFIX = "_"


_WINGMAN_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9 -]*$")


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
        self.mcp_config_path = path.join(self.config_dir, MCP_CONFIG_FILE)
        self.create_settings_config()
        self.settings_config = self.load_settings_config()
        # Load defaults silently - migration may need to run first to fix validation errors
        self.default_config = self.load_defaults_config(silent_on_error=True)
        # Load MCP config silently - migration may need to run first
        self.mcp_config = self.load_mcp_config(silent_on_error=True)

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
        """Copy templates to the user's config directory.

        Note: Skills are NO LONGER copied from templates. Built-in skills are now
        loaded directly from the bundled location (_internal/skills/ in release).
        Custom skills go in APPDATA/WingmanAI/custom_skills/ (not versioned).

        This method now only copies config templates (configs/, migration/*/configs/).
        Skills directories are skipped entirely.
        """
        for root, dirs, files in walk(self.templates_dir):
            relative_path = path.relpath(root, self.templates_dir)
            path_parts = relative_path.split(path.sep)

            # Skip ALL skills directories - both top-level and within migration folders
            # e.g., "skills/...", "migration/1_8_0/skills/...", etc.
            if "skills" in path_parts:
                continue

            if relative_path != ".":
                config_dir_name = (
                    relative_path.replace(DELETED_PREFIX, "", 1)
                    .replace(DEFAULT_PREFIX, "", 1)
                    .replace(f"{CONFIGS_DIR}{path.sep}", "", 1)
                    .replace("/", path.sep)
                )
                config_dir = self.get_config_dir(config_dir_name)
                if not force and config_dir and config_dir.is_deleted:
                    # skip logically deleted config dirs
                    continue

            # Create the same relative path in the target directory
            target_path = get_writable_dir(
                relative_path if relative_path != "." else ""
            )

            if not path.exists(target_path):
                makedirs(target_path)

            for filename in files:
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
        from services.module_manager import ModuleManager

        parsed_config = self.read_default_config()

        # Get discoverable_mcps from servers that are discoverable by default in mcp.yaml
        discoverable_mcps = []
        mcp_config = self.mcp_config
        if mcp_config and mcp_config.servers:
            discoverable_mcps = [
                server.name
                for server in mcp_config.servers
                if server.discoverable_by_default
            ]

        # Get discoverable_skills from skills where discoverable_by_default is True
        discoverable_skills = []
        try:
            all_skills = ModuleManager.read_available_skills()
            for skill in all_skills:
                # Check if skill has discoverable_by_default set to True (default)
                if skill.config.discoverable_by_default is not False:
                    discoverable_skills.append(skill.name)
        except Exception as e:
            self.printr.print(
                f"Could not read skills for discoverable_skills: {e}",
                color=LogType.WARNING,
                server_only=True,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )

        wingman_config = {
            "name": "",
            "description": "",
            "record_key": "",
            "disabled": False,
            "commands": [],
            "skills": [],
            "prompts": {"backstory": ""},
            "discoverable_mcps": discoverable_mcps,
            "discoverable_skills": discoverable_skills,
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

    def _validate_wingman_name(self, name: str) -> str:
        """Validate Wingman name using the same constraints as the client.

        Client pattern: ^[a-zA-Z0-9][a-zA-Z0-9 -]*$
        """

        if name is None:
            raise ValueError("Wingman name is required.")

        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Wingman name is required.")

        if not _WINGMAN_NAME_PATTERN.fullmatch(cleaned):
            raise ValueError(
                "Invalid Wingman name. Use letters, numbers, spaces, and '-' only; must start with a letter or number."
            )

        return cleaned

    def _wingman_name_exists_in_config_dir(
        self, config_dir: ConfigDirInfo, name: str
    ) -> bool:
        """Check whether a wingman name already exists in the target context.

        Treats case-insensitive collisions as existing (important on macOS/Windows).
        Also treats logically-deleted '.Name.yaml' as existing.
        """

        target_path = path.join(self.config_dir, config_dir.directory)
        wanted = name.casefold()

        for _, _, files in walk(target_path):
            for filename in files:
                if not filename.endswith(".yaml"):
                    continue

                base_file_name = filename.replace(".yaml", "")
                if base_file_name.startswith(DELETED_PREFIX):
                    base_file_name = base_file_name.replace(DELETED_PREFIX, "", 1)
                if base_file_name.casefold() == wanted:
                    return True

        return False

    def duplicate_wingman_config(
        self,
        source_config_dir: ConfigDirInfo,
        source_wingman_file: WingmanConfigFileInfo,
        target_config_dir: ConfigDirInfo,
        new_name: str,
    ) -> WingmanConfigFileInfo:
        """Duplicate an existing Wingman configuration into another context.

        Copies all settings from the source Wingman (via merged/validated WingmanConfig),
        but writes them under a new filename and sets the internal 'name' field to match.
        Also copies the avatar PNG if present.
        """

        if source_wingman_file.is_deleted or source_wingman_file.file.startswith(
            DELETED_PREFIX
        ):
            raise ValueError("Cannot duplicate a deleted/hidden Wingman.")

        cleaned_name = self._validate_wingman_name(new_name)

        if self._wingman_name_exists_in_config_dir(target_config_dir, cleaned_name):
            raise FileExistsError(
                f"Wingman '{cleaned_name}' already exists in '{target_config_dir.name}'."
            )

        source_config_path = path.join(
            self.config_dir, source_config_dir.directory, source_wingman_file.file
        )
        if not path.exists(source_config_path):
            raise FileNotFoundError(
                f"Source Wingman config not found: '{source_wingman_file.file}' in '{source_config_dir.name}'."
            )

        source_config_raw = self.read_config(source_config_path)
        if source_config_raw is None:
            raise ValueError("Failed to read source Wingman configuration.")
        if not isinstance(source_config_raw, dict):
            raise ValueError("Invalid Wingman config format; expected a YAML mapping.")

        # Ensure the internal name matches the filename stem.
        source_config_raw["name"] = cleaned_name

        # Clear push-to-talk binding in the duplicate so the user can rebind.
        source_config_raw["record_key"] = ""
        source_config_raw["record_key_codes"] = None
        source_config_raw["record_mouse_button"] = ""
        source_config_raw["record_joystick_button"] = None
        source_config_raw["is_voice_activation_default"] = False

        target_config_path = path.join(
            self.config_dir, target_config_dir.directory, f"{cleaned_name}.yaml"
        )
        written = self.write_config(target_config_path, source_config_raw)
        if not written:
            raise OSError(
                f"Failed to write duplicated Wingman config to '{target_config_path}'."
            )

        new_wingman_file = WingmanConfigFileInfo(
            name=cleaned_name,
            file=f"{cleaned_name}.yaml",
            is_deleted=False,
            avatar=source_wingman_file.avatar,
        )

        # Always create the duplicated avatar file from the source avatar (base64 data URI).
        # This avoids relying on a physical source .png being present on disk.
        try:
            target_avatar_path = path.join(
                self.config_dir, target_config_dir.directory, f"{cleaned_name}.png"
            )

            avatar_str = source_wingman_file.avatar
            if not avatar_str:
                # Extremely defensive fallback: write the default avatar.
                default_avatar_path = self.get_wingman_avatar_path(
                    target_config_dir, cleaned_name
                )
                shutil.copyfile(default_avatar_path, target_avatar_path)
            else:
                avatar_b64 = (
                    avatar_str.split("base64,", 1)[1]
                    if "base64," in avatar_str
                    else avatar_str
                )
                image_data = base64.b64decode(avatar_b64)
                with open(target_avatar_path, "wb") as file:
                    file.write(image_data)
        except Exception as e:
            self.printr.print(
                f"Failed to copy duplicated avatar for '{cleaned_name}': {e}",
                color=LogType.WARNING,
                server_only=True,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )

        # Return the canonical file info as it will appear to the client.
        wingmen = self.get_wingmen_configs(target_config_dir)
        created = next(
            (w for w in wingmen if w.name == cleaned_name and not w.is_deleted), None
        )
        return created if created else new_wingman_file

    def save_last_wingman_message(
        self,
        config_dir: ConfigDirInfo,
        wingman_file: WingmanConfigFileInfo,
        last_message: str,
    ):
        message_file = wingman_file.file.replace(".yaml", ".last-message.txt")
        message_path = path.join(self.config_dir, config_dir.directory, message_file)
        try:
            with open(message_path, "w", encoding="utf-8") as file:
                file.write(last_message)
                return True
        except:
            self.printr.toast_error(
                f"Unable to save last message for Wingman '{wingman_file.name}'."
            )
        return False

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

        # Strip skills to only keep module, prompt, custom_properties, and discovery_keywords with overridden values
        # Other skill fields come from skill default_config.yaml and shouldn't be saved per wingman
        if "skills" in wingman_config_dict and wingman_config_dict["skills"]:
            stripped_skills = []
            for skill in wingman_config_dict["skills"]:
                has_custom_props = skill.get("custom_properties")
                has_prompt = skill.get("prompt")
                has_discovery_keywords = skill.get("discovery_keywords")

                if has_custom_props or has_prompt or has_discovery_keywords:
                    stripped_skill = {"module": skill.get("module")}

                    # Keep prompt override if present
                    if has_prompt:
                        stripped_skill["prompt"] = has_prompt

                    # Keep discovery_keywords override if present
                    if has_discovery_keywords:
                        stripped_skill["discovery_keywords"] = has_discovery_keywords

                    # Only keep id and value for each custom property
                    # Other fields (name, hint, property_type, etc.) come from skill defaults
                    if has_custom_props:
                        stripped_skill["custom_properties"] = [
                            {"id": prop.get("id"), "value": prop.get("value")}
                            for prop in skill.get("custom_properties", [])
                        ]

                    stripped_skills.append(stripped_skill)
            wingman_config_dict["skills"] = stripped_skills if stripped_skills else None

        wingman_config_diff = self.deep_diff(default_config, wingman_config_dict)

        return self.write_config(config_path, wingman_config_diff)

    def save_wingman_commands(
        self,
        config_dir: ConfigDirInfo,
        wingman_file: WingmanConfigFileInfo,
        commands: list,
    ):
        """Save only the commands section of a wingman config.

        This performs a partial YAML update - it reads the existing YAML file,
        updates only the commands field, and writes it back. This avoids
        serializing the entire wingman config and reduces the risk of data loss.

        Args:
            config_dir: The config directory info
            wingman_file: The wingman file info
            commands: The commands list from wingman.config.commands
        """
        config_path = path.join(
            self.config_dir,
            config_dir.directory,
            wingman_file.file,
        )

        # Read existing YAML
        existing_yaml = {}
        if path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as file:
                existing_yaml = yaml.safe_load(file) or {}

        # Convert commands to dict format
        commands_dict = []
        if commands:
            for command in commands:
                command_dict = self.convert_to_dict(command)
                commands_dict.append(command_dict)

        # Get default config to diff against
        default_config = self.read_default_config()
        default_commands = default_config.get("commands", [])

        # Only save commands if they differ from defaults
        if commands_dict != default_commands:
            existing_yaml["commands"] = commands_dict
        elif "commands" in existing_yaml:
            # Remove commands key if it matches defaults (keep config minimal)
            del existing_yaml["commands"]

        # Write back the YAML with only commands changed
        return self.write_config(config_path, existing_yaml)

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

    def restore_wingman_from_template(
        self, config_dir: ConfigDirInfo, wingman_file: WingmanConfigFileInfo
    ) -> None:
        """Overwrite a Wingman config with its shipped template defaults.

        Eligibility is intentionally simple (and matches UI behavior): only specific
        shipped Wingmen within specific shipped contexts are restorable.

        This performs a full replace of the Wingman YAML file.
        """

        if wingman_file.is_deleted or wingman_file.file.startswith(DELETED_PREFIX):
            raise ValueError("Cannot restore defaults for a deleted/hidden Wingman.")

        template_yaml_path, template_dir_name = self._resolve_wingman_template_yaml(
            config_dir=config_dir, wingman_name=wingman_file.name
        )
        if not template_yaml_path or not template_dir_name:
            raise FileNotFoundError(
                f"No template found for Wingman '{wingman_file.name}' in '{config_dir.name}'."
            )

        target_yaml_path = path.join(
            self.config_dir,
            config_dir.directory,
            f"{wingman_file.name}.yaml",
        )

        # Full replace.
        shutil.copyfile(template_yaml_path, target_yaml_path)
        self.printr.print(
            f"Restored Wingman '{wingman_file.name}' in '{config_dir.name}' from template.",
            color=LogType.INFO,
            server_only=True,
            source=LogSource.SYSTEM,
            source_name=self.log_source_name,
        )

        # Restore avatar if a template avatar exists, else delete the custom avatar
        # so the UI falls back to the default wingman avatar.
        template_avatar_path = path.join(
            self.templates_dir,
            CONFIGS_DIR,
            template_dir_name,
            f"{wingman_file.name}.png",
        )
        target_avatar_path = path.join(
            self.config_dir,
            config_dir.directory,
            f"{wingman_file.name}.png",
        )
        try:
            if path.exists(template_avatar_path):
                shutil.copyfile(template_avatar_path, target_avatar_path)
            elif path.exists(target_avatar_path):
                remove(target_avatar_path)
        except (OSError, PermissionError) as e:
            self.printr.print(
                f"Failed to restore avatar for '{wingman_file.name}': {e}",
                color=LogType.WARNING,
                server_only=True,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )

    def can_restore_wingman_from_template(
        self, config_dir: ConfigDirInfo, wingman_file: WingmanConfigFileInfo
    ) -> bool:
        """Return True if a shipped template exists for this Wingman in this context."""

        if wingman_file.is_deleted or wingman_file.file.startswith(DELETED_PREFIX):
            return False

        template_yaml_path, _ = self._resolve_wingman_template_yaml(
            config_dir=config_dir, wingman_name=wingman_file.name
        )
        return bool(template_yaml_path)

    def _resolve_wingman_template_yaml(
        self, config_dir: ConfigDirInfo, wingman_name: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Resolve the shipped template YAML path for a Wingman.

        This scans the template directory in the Wingman AI installation (or repo
        when running from source) and supports default-prefixed template folders
        such as '_Star Citizen'.
        """

        templates_root = path.join(self.templates_dir, CONFIGS_DIR)
        if not path.exists(templates_root):
            return (None, None)

        candidates: list[str] = []

        # Prefer exact matches first.
        preferred = [
            config_dir.directory,
            config_dir.name,
            f"{DEFAULT_PREFIX}{config_dir.name}",
        ]
        for d in preferred:
            # Defensive: some legacy code paths may accidentally set `directory` to an
            # absolute path. We only accept plain directory names here.
            if not d or path.isabs(d) or path.sep in d:
                continue

            if path.exists(path.join(templates_root, d)) and d not in candidates:
                candidates.append(d)

        # Then add any other template dirs whose normalized name matches.
        try:
            _, dirs, _ = next(walk(templates_root))
        except StopIteration:
            dirs = []

        def normalize_dir_name(dir_name: str) -> str:
            return dir_name.replace(DELETED_PREFIX, "", 1).replace(
                DEFAULT_PREFIX, "", 1
            )

        for d in dirs:
            if normalize_dir_name(d) == config_dir.name and d not in candidates:
                candidates.append(d)

        template_filename = f"{wingman_name}.template.yaml"
        for template_dir_name in candidates:
            template_yaml_path = path.join(
                templates_root, template_dir_name, template_filename
            )
            if path.exists(template_yaml_path):
                return (template_yaml_path, template_dir_name)

        return (None, None)

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
                # Migration legacy: older versions accidentally wrote Python object tags
                # (e.g. !!python/object:api.interface.ElevenlabsVoiceConfig). These are
                # not supported by safe_load and should never be present in user configs.
                # We defensively strip them and retry as plain YAML.
                error_str = str(e)
                if "tag:yaml.org,2002:python/object:" in error_str:
                    try:
                        stream.seek(0)
                        raw = stream.read()
                        sanitized = re.sub(
                            r"(^|\s)(!!python/object:[^\s]+)",
                            r"\1",
                            raw,
                            flags=re.MULTILINE,
                        )
                        sanitized = re.sub(
                            r"(^|\s)(!python/object:[^\s]+)",
                            r"\1",
                            sanitized,
                            flags=re.MULTILINE,
                        )
                        parsed = yaml.safe_load(sanitized)
                        self.printr.print(
                            f"Sanitized legacy python/object YAML tags in '{file_path}'.",
                            color=LogType.WARNING,
                            server_only=True,
                            source=LogSource.SYSTEM,
                            source_name=self.log_source_name,
                        )
                        return parsed
                    except Exception:
                        # Fall through to the normal error toast below
                        pass

                self.printr.toast_error(
                    f"Could not read config '{file_path}':\n{error_str}"
                )
        return None

    def __make_yaml_safe(self, value):
        """Convert nested config structures into YAML-safe primitives.

        PyYAML's default dumper may emit !!python/object tags when encountering
        arbitrary Python objects (e.g. Pydantic models nested inside dicts).
        This ensures we only write plain YAML that safe_load can read.
        """

        if value is None:
            return None

        if isinstance(value, Enum):
            return value.value

        if isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, Path):
            return str(value)

        if is_dataclass(value):
            return self.__make_yaml_safe(asdict(value))

        # Pydantic v2 models (and other objects exposing model_dump)
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return self.__make_yaml_safe(model_dump(exclude_none=True))

        if isinstance(value, dict):
            return {
                self.__make_yaml_safe(k): self.__make_yaml_safe(v)
                for k, v in value.items()
            }

        if isinstance(value, (list, tuple, set)):
            return [self.__make_yaml_safe(v) for v in value]

        # Last resort: stringify unknown objects (should be rare in configs)
        return str(value)

    def write_config(self, file_path: str, content) -> bool:
        dir_path = path.dirname(file_path)
        if not path.exists(dir_path):
            makedirs(dir_path)

        with open(file_path, "w", encoding="UTF-8") as stream:
            try:
                raw = (
                    content
                    if isinstance(content, dict)
                    else content.model_dump(exclude_none=True)
                )
                yaml.safe_dump(
                    self.__make_yaml_safe(raw),
                    stream,
                    sort_keys=False,
                    allow_unicode=True,
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

    def load_defaults_config(self, silent_on_error: bool = False):
        """Load and validate Defaults config"""
        parsed = self.read_default_config()
        if parsed:
            try:
                validated = NestedConfig(**parsed)
                return validated
            except ValidationError as e:
                if not silent_on_error:
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

    def perform_hardware_scan(self, system_manager):
        """Scans for hardware changes and updates settings accordingly."""
        if self.settings_config.hardware_scan_performed:
            return

        self.printr.print(
            "Performing initial hardware scan...",
            color=LogType.STARTUP,
            server_only=True,
            source=LogSource.SYSTEM,
            source_name=self.log_source_name,
        )

        changes = False
        if system_manager.is_cuda_available():
            self.settings_config.voice_activation.fasterwhisper.device = "cuda"
            self.settings_config.voice_activation.fasterwhisper.compute_type = "auto"
            self.printr.print(
                f"- GPU detected: {system_manager.get_gpu_name()}",
                color=LogType.STARTUP,
                server_only=True,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )
            self.printr.print(
                "- Auto-configured FasterWhisper to use CUDA",
                color=LogType.STARTUP,
                server_only=True,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )
            changes = True
        else:
            self.printr.print(
                "- No NVIDIA GPU detected, keeping current STT settings",
                color=LogType.STARTUP,
                server_only=True,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )

        self.settings_config.hardware_scan_performed = True
        self.save_settings_config()

        if changes:
            self.printr.print(
                "Hardware scan complete. Settings updated.",
                color=LogType.STARTUP,
                server_only=True,
                source=LogSource.SYSTEM,
                source_name=self.log_source_name,
            )

    def load_mcp_config(self, silent_on_error: bool = False) -> Optional[McpConfig]:
        """Load and validate MCP config from mcp.yaml"""
        if not path.exists(self.mcp_config_path):
            if not silent_on_error:
                self.printr.print(
                    f"MCP config not found at {self.mcp_config_path}",
                    color=LogType.WARNING,
                    server_only=True,
                )
            return McpConfig(servers=[])

        parsed = self.read_config(self.mcp_config_path)
        if parsed:
            try:
                validated = McpConfig(**parsed)
                return validated
            except ValidationError as e:
                if not silent_on_error:
                    self.printr.toast_error(
                        f"Invalid MCP config '{self.mcp_config_path}':\n{str(e)}"
                    )
        return McpConfig(servers=[])

    def save_mcp_config(self):
        """Write MCP config to file"""
        return self.write_config(self.mcp_config_path, self.mcp_config)

    def read_mcp_config(self) -> dict:
        """Read raw MCP config as dict (for migration)"""
        if path.exists(self.mcp_config_path):
            return self.read_config(self.mcp_config_path) or {}
        return {}

    # Config merging:

    def convert_to_dict(self, obj):
        if isinstance(obj, BaseModel):
            # Use exclude_unset=False to preserve runtime-set fields like discoverable_skills.
            # Without this, fields not in the original YAML get dropped during save,
            # causing them to revert to defaults on reload.
            json_obj = obj.model_dump_json(exclude_none=True, exclude_unset=False)
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
            "hume",
            "inworld",
            "azure",
            "whispercpp",
            "fasterwhisper",
            "xvasynth",
            "pocket_tts",
            "wingman_pro",
            "perplexity",
            "xai",
            "openai_compatible_tts",
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

                # Look for skill default_config.yaml in multiple locations:
                # 1. Bundled skills directory (set by main.py)
                # 2. Custom skills directory (non-versioned)
                # 3. Legacy: versioned APPDATA skills directory
                from services.module_manager import get_bundled_skills_dir

                skill_default_config_path = None
                search_paths = []

                # 1. Bundled skills
                bundled_dir = get_bundled_skills_dir()
                if bundled_dir:
                    bundled_path = path.join(
                        bundled_dir, skill_dir, DEFAULT_SKILLS_CONFIG
                    )
                    search_paths.append(bundled_path)
                    if path.exists(bundled_path):
                        skill_default_config_path = bundled_path

                # 2. Custom skills (non-versioned)
                if not skill_default_config_path:
                    custom_path = path.join(
                        get_custom_skills_dir(), skill_dir, DEFAULT_SKILLS_CONFIG
                    )
                    search_paths.append(custom_path)
                    if path.exists(custom_path):
                        skill_default_config_path = custom_path

                # 3. Legacy: versioned APPDATA (for migration compatibility)
                if not skill_default_config_path:
                    legacy_path = path.join(
                        self.skills_dir, skill_dir, DEFAULT_SKILLS_CONFIG
                    )
                    search_paths.append(legacy_path)
                    if path.exists(legacy_path):
                        skill_default_config_path = legacy_path

                if skill_default_config_path:
                    skill_config = self.read_config(skill_default_config_path)
                    skill_config = self.__deep_merge(skill_config, skill_config_wingman)
                else:
                    # Custom skill without default_config.yaml - use wingman config as-is
                    skill_config = skill_config_wingman
                    self.printr.print(
                        f"Custom skill '{skill_dir}' has no default_config.yaml, using wingman configuration only.",
                        color=LogType.WARNING,
                        server_only=True,
                        source=LogSource.SYSTEM,
                        source_name=self.log_source_name,
                    )

                merged_skills.append(skill_config)

            merged["skills"] = merged_skills
        elif "skills" in default:
            merged["skills"] = default["skills"]

        # discoverable_mcps - inherit from default if not overridden in wingman config
        if "discoverable_mcps" not in wingman and "discoverable_mcps" in default:
            merged["discoverable_mcps"] = default["discoverable_mcps"]

        return WingmanConfig(**merged)
