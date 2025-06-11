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
from services.secret_keeper import SecretKeeper
from services.system_manager import SystemManager

MIGRATION_LOG = ".migration"


class ConfigMigrationService:
    def __init__(self, config_manager: ConfigManager, system_manager: SystemManager):
        self.config_manager = config_manager
        self.system_manager = system_manager
        self.printr = Printr()
        self.log_message: str = datetime.now().strftime("%Y-%m-%d-%H-%M-%S") + "\n"
        self.users_dir = get_users_dir()
        self.latest_version = MIGRATIONS[-1][1]
        self.latest_config_path = path.join(
            self.users_dir, self.latest_version, CONFIGS_DIR
        )

    def migrate_to_latest(self):

        # Find the earliest existing version that needs migration
        earliest_version = self.find_earliest_existing_version(self.users_dir)

        if not earliest_version:
            self.log("No valid version directories found for migration.", True)
            return

        # Check if the latest version is already migrated

        migration_file = path.join(self.latest_config_path, MIGRATION_LOG)

        if path.exists(migration_file):
            self.log(
                f"Found {self.latest_version} configs. No migrations needed.", False
            )
            return

        self.log(
            f"Starting migration from version {earliest_version.replace('_', '.')} to {self.latest_version.replace('_', '.')}",
            True,
        )

        # Perform migrations
        current_version = earliest_version
        while current_version != self.latest_version:
            next_version = self.find_next_version(current_version)
            self.perform_migration(current_version, next_version)
            current_version = next_version

        self.log(
            f"Migration completed successfully. Current version: {self.latest_version.replace('_', '.')}",
            True,
        )

    def find_earliest_existing_version(self, users_dir):
        versions = self.get_valid_versions(users_dir)
        versions.sort(key=lambda v: [int(n) for n in v.split("_")])

        for version in versions:
            if version != self.latest_version:
                return version

        return None

    def find_next_version(self, current_version):
        for old, new, _ in MIGRATIONS:
            if old == current_version:
                return new
        return None

    def perform_migration(self, old_version, new_version):
        migration_func = next(
            (m[2] for m in MIGRATIONS if m[0] == old_version and m[1] == new_version),
            None,
        )

        if migration_func:
            self.log(
                f"Migrating from {old_version.replace('_', '.')} to {new_version.replace('_', '.')}",
                True,
            )
            migration_func(self)
        else:
            self.err(f"No migration path found from {old_version} to {new_version}")
            raise ValueError(
                f"No migration path found from {old_version} to {new_version}"
            )

    def find_previous_version(self, users_dir, current_version):
        versions = self.get_valid_versions(users_dir)
        versions.sort(key=lambda v: [int(n) for n in v.split("_")])
        index = versions.index(current_version)
        return versions[index - 1] if index > 0 else None

    def get_valid_versions(self, users_dir):
        versions = next(os.walk(users_dir))[1]
        return [v for v in versions if self.is_valid_version(v)]

    def find_latest_user_version(self, users_dir):
        valid_versions = self.get_valid_versions(users_dir)
        return max(
            valid_versions,
            default=None,
            key=lambda v: [int(n) for n in v.split("_")],
        )

    def is_valid_version(self, version):
        return any(version in migration[:2] for migration in MIGRATIONS)

    # MIGRATIONS

    def migrate_140_to_150(self):
        def migrate_settings(old: dict, new: dict) -> dict:
            old["voice_activation"]["whispercpp_config"] = {
                "temperature": new["voice_activation"]["whispercpp_config"][
                    "temperature"
                ]
            }
            old["voice_activation"]["whispercpp"] = new["voice_activation"][
                "whispercpp"
            ]
            self.log("- applied new split whispercpp settings/config structure")

            old["xvasynth"] = new["xvasynth"]
            self.log("- added new XVASynth settings")

            old.pop("audio", None)
            self.log("- removed audio device settings because DirectSound was removed")
            return old

        def migrate_defaults(old: dict, new: dict) -> dict:
            # add new properties
            old["sound"]["volume"] = new["sound"]["volume"]
            if old["sound"].get("play_beep_apollo", None) is None:
                old["sound"]["play_beep_apollo"] = new["sound"]["play_beep_apollo"]
            old["google"] = new["google"]
            self.log("- added new properties: sound.volume, google")

            # remove obsolete properties
            old["features"].pop("summarize_provider")
            old["openai"].pop("summarize_model")
            old["mistral"].pop("summarize_model")
            old["groq"].pop("summarize_model")
            old["openrouter"].pop("summarize_model")
            old["azure"].pop("summarize")
            old["wingman_pro"].pop("summarize_deployment")
            self.log(
                "- removed obsolete properties: summarize_provider, summarize_model"
            )

            # rest of whispercpp moved to settings.yaml
            old["whispercpp"] = {"temperature": new["whispercpp"]["temperature"]}
            self.log("- cleaned up whispercpp properties")

            # xvasynth was restructured
            old["xvasynth"] = new["xvasynth"]
            self.log("- resetting and restructuring XVASynth")

            # patching new default values
            old["features"]["stt_provider"] = new["features"]["stt_provider"]
            self.log("- set whispercpp as new default STT provider")

            old["openai"]["conversation_model"] = new["openai"]["conversation_model"]
            old["azure"]["conversation"]["deployment_name"] = new["azure"][
                "conversation"
            ]["deployment_name"]
            old["wingman_pro"]["conversation_deployment"] = new["wingman_pro"][
                "conversation_deployment"
            ]
            self.log("- set gpt-4o-mini as new default LLM model")

            return old

        def migrate_wingman(old: dict, new: Optional[dict]) -> dict:
            def find_skill(skills, module_name):
                return next(
                    (skill for skill in skills if skill.get("module") == module_name),
                    None,
                )

            # remove obsolete properties
            old.get("features", {}).pop("summarize_provider", None)
            old.get("openai", {}).pop("summarize_model", None)
            old.get("mistral", {}).pop("summarize_model", None)
            old.get("groq", {}).pop("summarize_model", None)
            old.get("openrouter", {}).pop("summarize_model", None)
            old.get("azure", {}).pop("summarize", None)
            old.get("wingman_pro", {}).pop("summarize_deployment", None)
            self.log(
                "- removed obsolete properties: summarize_model (if there were any)"
            )

            changed_openai_model = False
            if old.get("openai", None):
                old["openai"]["conversation_model"] = "gpt-4o-mini"
                changed_openai_model = True
            if old.get("wingman_pro", None):
                old["wingman_pro"]["conversation_deployment"] = "gpt-4o-mini"
                changed_openai_model = True
            if changed_openai_model:
                self.log("- setting OpenAI model to gpt-4o-mini")

            if old.get("features", {}).get("stt_provider", None):
                old["features"]["stt_provider"] = "whispercpp"
                self.log("- setting STT provider to whispercpp")

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

    def migrate_150_to_160(self):
        def migrate_settings(old: dict, new: dict) -> dict:
            return old

        def migrate_defaults(old: dict, new: dict) -> dict:
            # add new properties
            old["cerebras"] = new["cerebras"]
            old["perplexity"] = new["perplexity"]

            self.log("- added new properties: cerebras, perplexity")

            return old

        def migrate_wingman(old: dict, new: Optional[dict]) -> dict:
            return old

        self.migrate(
            old_version="1_5_0",
            new_version="1_6_0",
            migrate_settings=migrate_settings,
            migrate_defaults=migrate_defaults,
            migrate_wingman=migrate_wingman,
        )

    def migrate_160_to_161(self):
        def migrate_settings(old: dict, new: dict) -> dict:
            return old

        def migrate_defaults(old: dict, new: dict) -> dict:
            return old

        def migrate_wingman(old: dict, new: Optional[dict]) -> dict:
            return old

        self.migrate(
            old_version="1_6_0",
            new_version="1_6_1",
            migrate_settings=migrate_settings,
            migrate_defaults=migrate_defaults,
            migrate_wingman=migrate_wingman,
        )

    def migrate_161_to_162(self):
        def migrate_settings(old: dict, new: dict) -> dict:
            return old

        def migrate_defaults(old: dict, new: dict) -> dict:
            return old

        def migrate_wingman(old: dict, new: Optional[dict]) -> dict:
            return old

        self.migrate(
            old_version="1_6_1",
            new_version="1_6_2",
            migrate_settings=migrate_settings,
            migrate_defaults=migrate_defaults,
            migrate_wingman=migrate_wingman,
        )

    def migrate_162_to_170(self):
        def migrate_settings(old: dict, new: dict) -> dict:
            old["voice_activation"]["whispercpp"].pop("use_cuda", None)
            old["voice_activation"]["whispercpp"].pop("language", None)
            old["voice_activation"]["whispercpp"].pop("translate_to_english", None)
            self.log("- removed old whispercpp settings (if there were any)")

            old["voice_activation"]["whispercpp"]["enable"] = False
            self.log("- disabled whispercpp by default")

            old["voice_activation"]["fasterwhisper"] = new["voice_activation"][
                "fasterwhisper"
            ]
            old["voice_activation"]["fasterwhisper_config"] = new["voice_activation"][
                "fasterwhisper_config"
            ]
            self.log("- added new fasterwhisper settings and config")

            old["voice_activation"]["stt_provider"] = "fasterwhisper"
            self.log("- set FasterWhisper as new default VA STT provider")

            old["streamer_mode"] = False
            self.log("- added new property streamer_mode")

            return old

        def migrate_defaults(old: dict, new: dict) -> dict:
            old["fasterwhisper"] = new["fasterwhisper"]
            self.log("- added new properties: fasterwhisper")

            old["features"]["stt_provider"] = "fasterwhisper"
            self.log("- made fasterwhisper new default STT provider")

            return old

        def migrate_wingman(old: dict, new: Optional[dict]) -> dict:
            if old.get("features", {}).get("stt_provider") == "whispercpp":
                old["features"]["stt_provider"] = "fasterwhisper"
                self.log("- changed STT provider from whispercpp to fasterwhisper")

            # migrate uexcorp skill
            if old.get("skills", None):
                uexcorp_skill = next(
                    (
                        skill
                        for skill in old["skills"]
                        if skill.get("module", "") == "skills.uexcorp.main"
                    ),
                    None,
                )
                if uexcorp_skill:
                    uexcorp_skill["custom_properties"] = [
                        {"id": "commodity_route_default_count"},
                        {"id": "tool_commodity_information"},
                        {"id": "tool_item_information"},
                        {"id": "tool_location_information"},
                        {"id": "tool_vehicle_information"},
                        {"id": "tool_commodity_route"},
                        {"id": "commodity_route_use_estimated_availability"},
                        {"id": "commodity_route_advanced_info"},
                        {"id": "tool_profit_calculation"},
                    ]
                    uexcorp_skill["examples"] = [
                        {
                            "answer": {
                                "de": "Du hast zwei profitable Handelsrouten zur Verfügung. Auf der ersten Route transportierst du [...]",
                                "en": "You have two highly profitable trading routes available. The first route involves [...]",
                            },
                            "question": {
                                "de": "Bitte gib mir die zwei besten Handelsrouten für meine Caterpillar, ich bin gerade bei Hurston.",
                                "en": "Please provide me a the best two trading routes for my Caterpillar, Im currently at Hurston.",
                            },
                        },
                        {
                            "answer": {
                                "de": 'Die Hull-C wird von Musashi Industrial & Starflight Concern hergestellt und gehört zur "HULL"-Serie. Sie dient als [...]',
                                "en": "The Hull-C is manufactured by Musashi Industrial & Starflight Concern and falls under the 'HULL' series. It [...]",
                            },
                            "question": {
                                "de": "Was kannst du mir über die Hull-C erzählen?",
                                "en": "What can you tell me about the Hull-C?",
                            },
                        },
                    ]
                    uexcorp_skill.pop("prompt", None)
                    self.log("- migrated UEXCorp skill to v2")
            return old

        self.migrate(
            old_version="1_6_2",
            new_version="1_7_0",
            migrate_settings=migrate_settings,
            migrate_defaults=migrate_defaults,
            migrate_wingman=migrate_wingman,
        )

    def migrate_170_to_171(self):
        def migrate_settings(old: dict, new: dict) -> dict:
            old_region = old["wingman_pro"]["region"]
            if old_region == "europe":
                old["wingman_pro"]["base_url"] = "https://wingman-api-europe.azurewebsites.net"
            else:
                old["wingman_pro"]["base_url"] = "https://wingman-api-usa.azurewebsites.net"

            self.log(f"- set new base url based on region {old_region}")
            return old

        def migrate_defaults(old: dict, new: dict) -> dict:
            # openai tts
            old["openai"]["tts_model"] = "tts-1"
            old["openai"]["tts_speed"] = 1.0
            self.log("- added new properties: openai.tts_model, openai.tts_speed")

            old["hume"] = new["hume"]
            self.log("- added new property: hume")

            # openai-compatible tts
            old["openai_compatible_tts"] = new["openai_compatible_tts"]
            self.log("- added new property: openai_compatible_tts")

            # perplexity model
            old["perplexity"]["conversation_model"] = "sonar"
            self.log(
                "- migrated perplexity model to new default (sonar), previous models don't exist anymore"
            )

            return old

        def migrate_wingman(old: dict, new: Optional[dict]) -> dict:
            # skill overrides
            if old.get("skills", None):
                for skill in old["skills"]:
                    skill.pop("description", None)
                    skill.pop("examples", None)
                    skill.pop("category", None)
                    skill.pop("hint", None)
                    self.log(
                        "- removed Skill property overrides: description, examples, category, hint"
                    )

            # perplexity model
            if old.get("perplexity", {}).get("conversation_model", None):
                # models got replaced
                old["perplexity"]["conversation_model"] = "sonar"
                self.log(
                    "- migrated perplexity model to new default (sonar), previous models don't exist anymore"
                )

            return old

        self.migrate(
            old_version="1_7_0",
            new_version="1_7_1",
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

        self.log(f"Copied file: {path.basename(new_file)}", highlight=True)

    def migrate(
        self,
        old_version: str,
        new_version: str,
        migrate_settings: Callable[[dict, dict], dict],
        migrate_defaults: Callable[[dict, dict], dict],
        migrate_wingman: Callable[[dict, Optional[dict]], dict],
    ) -> None:
        users_dir = get_users_dir()
        old_config_path = path.join(users_dir, old_version, CONFIGS_DIR)
        new_config_path = path.join(users_dir, new_version, CONFIGS_DIR)

        if not path.exists(path.join(users_dir, new_version)):
            shutil.copytree(
                path.join(users_dir, self.latest_version, "migration", new_version),
                path.join(users_dir, new_version),
            )
            self.log(
                f"{new_version} configs not found during multi-step migration. Copied migration templates."
            )

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

                if filename == ".DS_Store" or filename == MIGRATION_LOG:
                    continue
                # secrets
                if filename == "secrets.yaml":
                    self.copy_file(old_file, new_file)

                    if new_config_path == self.latest_config_path:
                        secret_keeper = SecretKeeper()
                        secret_keeper.secrets = secret_keeper.load()
                # settings
                elif filename == "settings.yaml":
                    self.log("Migrating settings.yaml...", True)
                    migrated_settings = migrate_settings(
                        old=self.config_manager.read_config(old_file),
                        new=self.config_manager.read_config(new_file),
                    )
                    try:
                        if new_config_path == self.latest_config_path:
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
                        new=self.config_manager.read_config(new_file),
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
                    try:
                        default_config = self.config_manager.read_default_config()
                        migrated_wingman = migrate_wingman(
                            old=self.config_manager.read_config(old_file),
                            new=(
                                self.config_manager.read_config(new_file)
                                if path.exists(new_file)
                                else None
                            ),
                        )
                        # validate the merged config
                        if new_config_path == self.latest_config_path:
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
                    except Exception as e:
                        self.err(f"Unable to migrate {filename}:\n{str(e)}")
                        continue
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


MIGRATIONS = [
    ("1_4_0", "1_5_0", ConfigMigrationService.migrate_140_to_150),
    ("1_5_0", "1_6_0", ConfigMigrationService.migrate_150_to_160),
    ("1_6_0", "1_6_1", ConfigMigrationService.migrate_160_to_161),
    ("1_6_1", "1_6_2", ConfigMigrationService.migrate_161_to_162),
    ("1_6_2", "1_7_0", ConfigMigrationService.migrate_162_to_170),
    ("1_7_0", "1_7_1", ConfigMigrationService.migrate_170_to_171),
    # Add new migrations here in order
]
