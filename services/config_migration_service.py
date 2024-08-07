from datetime import datetime
from os import path, walk
import os
import shutil
from typing import Callable, Optional
from pydantic import ValidationError
from api.enums import LogType
from api.interface import NestedConfig, SettingsConfig
from services.config_manager import (
    CONFIGS_DIR,
    DEFAULT_PREFIX,
    DELETED_PREFIX,
    ConfigManager,
)
from services.file import get_users_dir
from services.printr import Printr

MIGRATION_LOG = ".migration"


class ConfigMigrationService:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.printr = Printr()
        self.log_message: str = datetime.now().strftime("%Y-%m-%d-%H-%M-%S") + "\n"

    # MIGRATIONS

    def migrate_140_to_150(self):
        def migrate_settings(old: dict, new: SettingsConfig) -> dict:
            old["voice_activation"]["whispercpp_config"] = {
                "temperature": new.voice_activation.whispercpp_config.temperature
            }
            old["voice_activation"]["whispercpp"] = self.config_manager.convert_to_dict(
                new.voice_activation.whispercpp
            )
            self.log("- applied new split whispercpp settings/config structure")

            old["xvasynth"] = self.config_manager.convert_to_dict(new.xvasynth)
            self.log("- adding new XVASynth settings")
            return old

        def migrate_defaults(old: dict, new: NestedConfig) -> dict:
            # add new properties
            old["sound"]["volume"] = new.sound.volume
            old["google"] = self.config_manager.convert_to_dict(new.google)
            self.log("- added new properties: sound.volume, google")

            # remove obsolete properties
            old["openai"].pop("summarize_model")
            old["mistral"].pop("summarize_model")
            old["groq"].pop("summarize_model")
            old["openrouter"].pop("summarize_model")
            old["azure"].pop("summarize")
            old["wingman_pro"].pop("summarize_deployment")
            self.log("- removed obsolete properties: summarize_model")

            # rest of whispercpp moved to settings.yaml
            old["whispercpp"] = {"temperature": new.whispercpp.temperature}
            self.log("- cleaned up whispercpp properties")

            # xvasynth was restructured
            old["xvasynth"] = self.config_manager.convert_to_dict(new.xvasynth)
            self.log("- resetting and restructuring XVASynth")

            # patching new default values
            old["features"]["stt_provider"] = new.features.stt_provider.value
            self.log("- set whispercpp as new default STT provider")
            old["openai"]["conversation_model"] = new.openai.conversation_model.value
            old["azure"]["conversation"][
                "deployment_name"
            ] = new.azure.conversation.deployment_name
            old["wingman_pro"][
                "conversation_deployment"
            ] = new.wingman_pro.conversation_deployment.value
            self.log("- set gpt-4o-mini as new default LLM model")

            return old

        def migrate_wingman(old: dict, new: Optional[dict]) -> dict:
            def find_skill(skills, module_name):
                return next(
                    (skill for skill in skills if skill.get("module") == module_name),
                    None,
                )

            # remove obsolete properties
            old.get("openai", {}).pop("summarize_model", None)
            old.get("mistral", {}).pop("summarize_model", None)
            old.get("groq", {}).pop("summarize_model", None)
            old.get("openrouter", {}).pop("summarize_model", None)
            old.get("azure", {}).pop("summarize", None)
            old.get("wingman_pro", {}).pop("summarize_deployment", None)
            self.log(
                "- removed obsolete properties: summarize_model (if there were any)"
            )

            old.pop("whispercpp", None)
            self.log("- removed old whispercpp config (if there was any)")

            old.pop("xvasynth", None)
            self.log("- removed old xvasynth config (if there was any)")

            voice_changer = find_skill(
                old.get("skills", []), "skills.voice_changer.main"
            )
            if voice_changer:
                voice_changer_custom_properties = voice_changer.get(
                    "custom_properties", []
                )
                voice_changer_voices = next(
                    (
                        prop
                        for prop in voice_changer_custom_properties
                        if prop.get("id") == "voice_changer_voices"
                    ),
                    None,
                )
                if voice_changer_voices:
                    voice_changer_custom_properties.remove(voice_changer_voices)
                    self.log("- removed old VoiceChanger voices custom property")

            radio_chatter = find_skill(
                old.get("skills", []), "skills.skills.radio_chatter.main"
            )
            if radio_chatter:
                radio_chatter_custom_properties = voice_changer.get(
                    "custom_properties", []
                )
                radio_chatter_voices = next(
                    (
                        prop
                        for prop in radio_chatter_custom_properties
                        if prop.get("id") == "voices"
                    ),
                    None,
                )
                if radio_chatter_voices:
                    radio_chatter_custom_properties.remove(radio_chatter_voices)
                    self.log("- removed changed RadioChatter custom property: voices")

                radio_chatter_volume = next(
                    (
                        prop
                        for prop in radio_chatter_custom_properties
                        if prop.get("id") == "volume"
                    ),
                    None,
                )
                if radio_chatter_volume:
                    radio_chatter_custom_properties.remove(radio_chatter_volume)
                    self.log("- removed changed RadioChatter custom property: volume")

            return old

        self.migrate(
            old_version="1_4_0",
            new_version="1_5_0",
            migrate_settings=migrate_settings,
            migrate_defaults=migrate_defaults,
            migrate_wingman=migrate_wingman,
        )

    # INTERNAL

    def log(self, message: str, highlight: bool = False):
        self.printr.print(
            message,
            color=LogType.SUBTLE if not highlight else LogType.PURPLE,
            server_only=True,
        )
        self.log_message += f"{message}\n"

    def err(self, message: str):
        self.printr.print(
            message,
            color=LogType.ERROR,
            server_only=True,
        )
        self.log_message += f"{message}\n"

    def copy_file(self, old_file: str, new_file: str):
        new_dir = path.dirname(new_file)
        if not path.exists(new_dir):
            os.makedirs(new_dir)

        shutil.copyfile(old_file, new_file)

        self.log(f"Copied file: {path.basename(new_file)}")

    def migrate(
        self,
        old_version: str,
        new_version: str,
        migrate_settings: Callable[[dict, SettingsConfig], dict],
        migrate_defaults: Callable[[dict, NestedConfig], dict],
        migrate_wingman: Callable[[dict, Optional[dict]], dict],
    ) -> None:
        users_dir = get_users_dir()
        old_config_path = path.join(users_dir, old_version, CONFIGS_DIR)
        new_config_path = path.join(users_dir, new_version, CONFIGS_DIR)

        already_migrated = path.exists(path.join(new_config_path, MIGRATION_LOG))
        if already_migrated:
            self.log(
                f"Migration from {old_version} to {new_version} already completed!"
            )
            return

        self.log(
            f"Starting migration from {old_config_path} to {new_config_path}",
            True,
        )

        for root, _dirs, files in walk(old_config_path):
            for filename in files:
                old_file = path.join(root, filename)
                new_file = old_file.replace(old_config_path, new_config_path)

                if filename == ".DS_Store":
                    continue
                # secrets
                if filename == "secrets.yaml":
                    self.copy_file(old_file, new_file)
                # settings
                elif filename == "settings.yaml":
                    self.log("Migrating settings.yaml...", True)
                    migrated_settings = migrate_settings(
                        old=self.config_manager.read_config(old_file),
                        new=self.config_manager.settings_config,
                    )
                    try:
                        self.config_manager.settings_config = SettingsConfig(
                            **migrated_settings
                        )
                        self.config_manager.save_settings_config()
                    except ValidationError as e:
                        self.err(f"Unable to migrate settings.yaml:\n{str(e)}")
                # defaults
                elif filename == "defaults.yaml":
                    self.log("Migrating defaults.yaml...", True)
                    migrated_defaults = migrate_defaults(
                        old=self.config_manager.read_config(old_file),
                        new=self.config_manager.default_config,
                    )
                    try:
                        self.config_manager.default_config = NestedConfig(
                            **migrated_defaults
                        )
                        self.config_manager.save_defaults_config()
                    except ValidationError as e:
                        self.err(f"Unable to migrate defaults.yaml:\n{str(e)}")
                # Wingmen
                elif filename.endswith(".yaml"):
                    self.log(f"Migrating Wingman {filename}...", True)
                    # defaults are already migrated because the Wingman config is in a subdirectory
                    default_config = self.config_manager.read_default_config()
                    migrated_wingman = migrate_wingman(
                        old=self.config_manager.read_config(old_file),
                        new=(
                            self.config_manager.read_config(new_file)
                            if path.exists(new_file)
                            else None
                        ),
                    )
                    try:
                        # validate the merged config
                        _wingman_config = self.config_manager.merge_configs(
                            default_config, migrated_wingman
                        )
                        # diff it
                        wingman_diff = self.config_manager.deep_diff(
                            default_config, migrated_wingman
                        )
                        # save it
                        self.config_manager.write_config(new_file, wingman_diff)

                        # The old file was logically deleted and a new one exists that isn't yet
                        new_base_file = path.join(
                            root.replace(old_config_path, new_config_path),
                            filename.replace(DELETED_PREFIX, "", 1),
                        )
                        if filename.startswith(DELETED_PREFIX) and path.exists(
                            new_base_file
                        ):
                            os.remove(new_base_file)

                            avatar = new_base_file.replace(".yaml", ".png")
                            if path.exists(avatar):
                                os.remove(avatar)
                            self.log(
                                f"Logically deleting Wingman {filename} like in the previous version"
                            )
                    except ValidationError as e:
                        self.err(f"Unable to migrate {filename}:\n{str(e)}")
                else:
                    self.copy_file(old_file, new_file)

            # the old dir was logically deleted and a new one exists that isn't yet
            new_base_dir = root.replace(old_config_path, new_config_path).replace(
                DELETED_PREFIX, "", 1
            )
            new_undeleted_default_dir = root.replace(
                old_config_path, new_config_path
            ).replace(DELETED_PREFIX, DEFAULT_PREFIX, 1)

            target_dir = (
                new_undeleted_default_dir
                if path.exists(new_undeleted_default_dir)
                else new_base_dir if path.exists(new_base_dir) else None
            )
            if os.path.basename(root).startswith(DELETED_PREFIX) and path.exists(
                target_dir
            ):
                shutil.rmtree(target_dir)
                self.log(
                    f"Logically deleting config {root} like in the previous version"
                )

        success_message = "Migration completed successfully!"
        self.printr.print(
            success_message,
            color=LogType.POSITIVE,
            server_only=True,
        )
        self.log_message += f"{success_message}\n"

        with open(
            path.join(new_config_path, MIGRATION_LOG), "w", encoding="UTF-8"
        ) as stream:
            stream.write(self.log_message)
