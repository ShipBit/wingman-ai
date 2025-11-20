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
MINIMUM_SUPPORTED_VERSION = "1_7_0"  # Versions older than this require a fresh start


class ConfigMigrationService:
    def __init__(self, config_manager: ConfigManager, system_manager: SystemManager):
        self.config_manager = config_manager
        self.system_manager = system_manager
        self.printr = Printr()
        self.log_message: str = datetime.now().strftime("%Y-%m-%d-%H-%M-%S") + "\n"
        self.users_dir = get_users_dir()
        self.templates_dir = config_manager.templates_dir
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

        # Check if the version is too old to migrate
        if self.is_version_too_old(earliest_version):
            self.log(
                f"Version {earliest_version.replace('_', '.')} is too old (minimum supported: {MINIMUM_SUPPORTED_VERSION.replace('_', '.')}). Resetting to fresh configs.",
                True,
            )
            self.reset_to_fresh_configs()
            return

        self.log(
            f"Starting migration from version {earliest_version.replace('_', '.')} to {self.latest_version.replace('_', '.')}",
            True,
        )

        # If the latest version directory already exists (e.g., created by ConfigManager),
        # clean up any template configs that will be migrated from old versions
        latest_existing_version = self.find_latest_existing_version(self.users_dir)
        if path.exists(self.latest_config_path) and latest_existing_version:
            self.remove_duplicate_template_configs(
                latest_existing_version, self.latest_version
            )

        # Copy custom skills from the LATEST existing version to new version
        # This ensures we get the most up-to-date custom skills
        self.log(
            f"Found latest existing version for custom skills: {latest_existing_version}"
        )
        custom_skills = []
        if latest_existing_version and latest_existing_version != self.latest_version:
            custom_skills = self.copy_custom_skills(
                latest_existing_version, self.latest_version
            )
        else:
            self.log(
                f"Skipping custom skills copy - latest_existing_version: {latest_existing_version}, latest_version: {self.latest_version}"
            )

        # Perform migrations
        current_version = earliest_version
        while current_version != self.latest_version:
            next_version = self.find_next_version(current_version)
            self.perform_migration(current_version, next_version)
            current_version = next_version

        # Warn about custom skills that need manual review
        if custom_skills:
            for skill_name in custom_skills:
                warning_message = f"Custom skill '{skill_name}' was copied from the old version and might need manual migration!"
                self.printr.print(
                    warning_message,
                    color=LogType.WARNING,
                    server_only=True,
                )
                self.log_message += f"{warning_message}\n"

        self.log(
            f"Migration completed successfully. Current version: {self.latest_version.replace('_', '.')}",
            True,
        )

    def find_earliest_existing_version(self, users_dir):
        # Get all version directories (not just valid ones for migration)
        all_versions = next(os.walk(users_dir))[1]
        # Filter to version-like directories (format: X_Y_Z)
        version_dirs = [
            v for v in all_versions if v.replace("_", "").replace(".", "").isdigit()
        ]
        version_dirs.sort(key=lambda v: [int(n) for n in v.split("_")])

        for version in version_dirs:
            if version != self.latest_version:
                return version

        return None

    def find_latest_existing_version(self, users_dir):
        """Find the most recent existing version directory (excluding the target latest version)."""
        # Get all version directories
        all_versions = next(os.walk(users_dir))[1]
        # Filter to version-like directories (format: X_Y_Z)
        version_dirs = [
            v for v in all_versions if v.replace("_", "").replace(".", "").isdigit()
        ]
        # Sort by version number (newest first)
        version_dirs.sort(key=lambda v: [int(n) for n in v.split("_")], reverse=True)

        self.log(f"All version directories found: {version_dirs}")
        self.log(f"Latest version (target): {self.latest_version}")

        # Return the first one that's not the latest version
        for version in version_dirs:
            if version != self.latest_version:
                self.log(f"Selected latest existing version: {version}")
                return version

        self.log("No suitable version found for custom skills migration")
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

    def is_version_too_old(self, version):
        """Check if a version is older than the minimum supported version."""
        version_parts = [int(n) for n in version.split("_")]
        min_parts = [int(n) for n in MINIMUM_SUPPORTED_VERSION.split("_")]
        return version_parts < min_parts

    def reset_to_fresh_configs(self):
        """Copy fresh configs and skills from templates to the latest version directory."""
        try:
            configs_template = path.join(self.templates_dir, "configs")
            skills_template = path.join(self.templates_dir, "skills")

            latest_dir = path.join(self.users_dir, self.latest_version)

            # Remove existing latest version directory if it exists
            if path.exists(latest_dir):
                shutil.rmtree(latest_dir)
                self.log(f"Removed existing {self.latest_version} directory")

            # Create the latest version directory
            os.makedirs(latest_dir, exist_ok=True)

            # Copy configs
            if path.exists(configs_template):
                shutil.copytree(configs_template, path.join(latest_dir, CONFIGS_DIR))
                self.log("Copied fresh configs from templates")

            # Copy skills
            if path.exists(skills_template):
                shutil.copytree(skills_template, path.join(latest_dir, "skills"))
                self.log("Copied fresh skills from templates")

            # Create migration log
            migration_file = path.join(latest_dir, CONFIGS_DIR, MIGRATION_LOG)
            with open(migration_file, "w", encoding="UTF-8") as stream:
                stream.write(self.log_message)

            self.log("Fresh configs and skills installed successfully!", True)

        except Exception as e:
            self.err(f"Failed to reset to fresh configs: {str(e)}")
            raise

    def copy_custom_skills(self, old_version: str, new_version: str) -> list[str]:
        """Copy custom skills (not in templates) from old version to new version.

        Returns:
            List of custom skill names that were copied
        """
        old_skills_dir = path.join(self.users_dir, old_version, "skills")
        new_skills_dir = path.join(self.users_dir, new_version, "skills")
        template_skills_dir = path.join(self.templates_dir, "skills")

        custom_skills_copied = []

        if not path.exists(old_skills_dir):
            self.log(
                f"No old skills directory found at {old_skills_dir}, skipping custom skills migration"
            )
            return custom_skills_copied

        # Get list of template skill names
        template_skills = set()
        if path.exists(template_skills_dir):
            template_skills = set(os.listdir(template_skills_dir))

        self.log(f"Checking for custom skills in: {old_skills_dir}")

        # Find custom skills (exist in old but not in templates)
        for skill_name in os.listdir(old_skills_dir):
            old_skill_path = path.join(old_skills_dir, skill_name)
            if not path.isdir(old_skill_path) or skill_name.startswith("."):
                continue

            self.log(
                f"Evaluating skill: {skill_name} - Is custom? {skill_name not in template_skills}"
            )

            # If skill is not in templates, it's a custom skill
            if skill_name not in template_skills:
                new_skill_path = path.join(new_skills_dir, skill_name)

                try:
                    # Remove existing directory if it exists (might be partially created)
                    if path.exists(new_skill_path):
                        self.log(
                            f"Removing existing directory for custom skill '{skill_name}' before copying"
                        )
                        shutil.rmtree(new_skill_path)

                    # Copy the entire custom skill directory
                    shutil.copytree(old_skill_path, new_skill_path)

                    # Count all files in the copied directory
                    file_count = sum(
                        len(files) for _, _, files in os.walk(new_skill_path)
                    )

                    self.log(
                        f"Copied CUSTOM skill skills/{skill_name} from old version ({file_count} files)"
                    )
                    custom_skills_copied.append(skill_name)
                except Exception as e:
                    self.err(f"Failed to copy custom skill '{skill_name}': {str(e)}")

        return custom_skills_copied

    # MIGRATIONS

    def migrate_170_to_180(self):
        def migrate_settings(old: dict, new: dict) -> dict:
            old_region = old["wingman_pro"]["region"]
            if old_region == "europe":
                old["wingman_pro"][
                    "base_url"
                ] = "https://wingman-api-europe.azurewebsites.net"
            else:
                old["wingman_pro"][
                    "base_url"
                ] = "https://wingman-api-usa.azurewebsites.net"

            self.log(f"- set new base url based on region {old_region}")

            old["voice_activation"]["fasterwhisper_config"]["hotwords"] = []
            old["voice_activation"]["fasterwhisper_config"]["additional_hotwords"] = []
            self.log("- reset Voice Activation hotwords")

            old["cancel_tts_key"] = "Shift+y"
            self.log("- set new 'Shut up key' to 'Shift+y'")
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

            # FasterWhisper hotwords
            old["fasterwhisper"]["hotwords"] = []
            old["fasterwhisper"]["additional_hotwords"] = []
            self.log("- reset FasterWhisper hotwords")

            return old

        def migrate_wingman(old: dict, new: Optional[dict]) -> dict:
            # skill overrides
            if old.get("skills", None):
                for skill in old["skills"]:
                    skill.pop("description", None)
                    skill.pop("examples", None)
                    skill.pop("category", None)
                    skill.pop("hint", None)

                    skill_module = skill.get("module", "")
                    self.log(
                        f"- Skill {skill_module}: removed property overrides: description, examples, category, hint"
                    )

            # perplexity model
            if old.get("perplexity", {}).get("conversation_model", None):
                # models got replaced
                old["perplexity"]["conversation_model"] = "sonar"
                self.log(
                    "- migrated perplexity model to new default (sonar), previous models don't exist anymore"
                )

            if old.get("fasterwhisper", None):
                old["fasterwhisper"]["hotwords"] = []
                old["fasterwhisper"]["additional_hotwords"] = []
            self.log("- reset FasterWhisper hotwords")

            return old

        self.migrate(
            old_version="1_7_0",
            new_version="1_8_0",
            migrate_settings=migrate_settings,
            migrate_defaults=migrate_defaults,
            migrate_wingman=migrate_wingman,
        )

    def migrate_180_to_181(self):
        def migrate_settings(old: dict, new: dict) -> dict:
            return old

        def migrate_defaults(old: dict, new: dict) -> dict:
            return old

        def migrate_wingman(old: dict, new: Optional[dict]) -> dict:
            return old

        self.migrate(
            old_version="1_8_0",
            new_version="1_8_1",
            migrate_settings=migrate_settings,
            migrate_defaults=migrate_defaults,
            migrate_wingman=migrate_wingman,
        )

    def migrate_181_to_182(self):
        def migrate_settings(old: dict, new: dict) -> dict:
            return old

        def migrate_defaults(old: dict, new: dict) -> dict:
            old["inworld"] = new["inworld"]
            self.log("- added new property: inworld")

            old["elevenlabs"]["use_tts_prompt"] = False
            old["elevenlabs"]["tts_prompt"] = new["elevenlabs"]["tts_prompt"]
            self.log(
                "- added new property: elevenlabs.use_tts_prompt, elevenlabs.tts_prompt"
            )

            old["openai"]["output_streaming"] = True
            self.log("- added new property: openai.output_streaming")

            old["openai_compatible_tts"]["output_streaming"] = True
            self.log("- added new property: openai_compatible_tts.output_streaming")

            return old

        def migrate_wingman(old: dict, new: Optional[dict]) -> dict:
            return old

        self.migrate(
            old_version="1_8_1",
            new_version="1_8_2",
            migrate_settings=migrate_settings,
            migrate_defaults=migrate_defaults,
            migrate_wingman=migrate_wingman,
        )

    def migrate_182_to_190(self):
        def migrate_settings(old: dict, new: dict) -> dict:
            return old

        def migrate_defaults(old: dict, new: dict) -> dict:
            old["xai"] = new["xai"]
            self.log("- added new property: xai")

            return old

        def migrate_wingman(old: dict, new: Optional[dict]) -> dict:
            return old

        self.migrate(
            old_version="1_8_2",
            new_version="1_9_0",
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

    def normalize_config_name(self, config_name: str) -> str:
        """Remove DEFAULT_PREFIX and DELETED_PREFIX from config name for comparison.

        This allows us to detect when '_Star Citizen' and 'Star Citizen' are the same config.
        """
        normalized = config_name
        if normalized.startswith(DELETED_PREFIX):
            normalized = normalized[len(DELETED_PREFIX) :]
        if normalized.startswith(DEFAULT_PREFIX):
            normalized = normalized[len(DEFAULT_PREFIX) :]
        return normalized

    def remove_duplicate_template_configs(
        self, old_version: str, new_version: str
    ) -> None:
        """Remove template configs from new version that exist in old version.

        This prevents duplicates when templates are copied before migration runs.
        For example, if old version has 'Star Citizen' (undefaulted) and new version
        has '_Star Citizen' (template), we remove the template since the old version
        will be migrated.
        """
        old_config_path = path.join(self.users_dir, old_version, CONFIGS_DIR)
        new_config_path = path.join(self.users_dir, new_version, CONFIGS_DIR)

        if not path.exists(old_config_path) or not path.exists(new_config_path):
            return

        # Get normalized config names from old version
        old_config_normalized = set()
        for item in os.listdir(old_config_path):
            item_path = path.join(old_config_path, item)
            if path.isdir(item_path) and not item.startswith("."):
                normalized = self.normalize_config_name(item)
                old_config_normalized.add(normalized)
                self.log(
                    f"Old config found for duplicate check: {item} (normalized: {normalized})"
                )

        # Remove new configs that match old configs (after normalization)
        for item in os.listdir(new_config_path):
            item_path = path.join(new_config_path, item)
            if path.isdir(item_path) and not item.startswith("."):
                normalized = self.normalize_config_name(item)
                if normalized in old_config_normalized:
                    shutil.rmtree(item_path)
                    self.log(
                        f"Removed template config '{item}' - will be migrated from old version (normalized: {normalized})",
                        highlight=True,
                    )
                    # Also remove associated avatar if it exists
                    avatar_path = path.join(new_config_path, f"{item}.png")
                    if path.exists(avatar_path):
                        os.remove(avatar_path)

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
            migration_template_path = path.join(
                self.templates_dir, "migration", new_version
            )
            if path.exists(migration_template_path):
                # Get list of config directories from old version (normalized names)
                # Include ALL configs regardless of their state (default, undefaulted, or deleted)
                # because if ANY version exists, we should skip the template
                old_config_normalized = set()
                if path.exists(old_config_path):
                    for item in os.listdir(old_config_path):
                        item_path = path.join(old_config_path, item)
                        if path.isdir(item_path) and not item.startswith("."):
                            # Add ALL configs (including deleted ones) after normalizing
                            normalized = self.normalize_config_name(item)
                            old_config_normalized.add(normalized)
                            self.log(
                                f"Old config found: {item} (normalized: {normalized})"
                            )

                # Copy migration template but skip configs that exist in old version (in any state)
                template_config_path = path.join(migration_template_path, CONFIGS_DIR)
                new_version_path = path.join(users_dir, new_version)

                # First, copy the entire template structure
                shutil.copytree(migration_template_path, new_version_path)
                self.log(
                    f"{new_version} configs not found during multi-step migration. Copied migration templates from {migration_template_path}."
                )

                # Now remove template configs that have any version in old configs
                # (whether default, undefaulted, or deleted)
                if path.exists(template_config_path):
                    for item in os.listdir(template_config_path):
                        item_path = path.join(template_config_path, item)
                        new_item_path = path.join(new_version_path, CONFIGS_DIR, item)
                        if path.isdir(item_path) and not item.startswith("."):
                            normalized = self.normalize_config_name(item)
                            if normalized in old_config_normalized:
                                # This template config exists in old version (in some form)
                                # Remove template to avoid duplicates - old version will be migrated
                                if path.exists(new_item_path):
                                    shutil.rmtree(new_item_path)
                                    self.log(
                                        f"Skipped template config '{item}' - config exists in old version (normalized: {normalized})",
                                        highlight=True,
                                    )
                                # Also remove associated avatar if it exists
                                avatar_path = path.join(
                                    new_version_path,
                                    CONFIGS_DIR,
                                    item.replace(".yaml", ".png"),
                                )
                                if path.exists(avatar_path):
                                    os.remove(avatar_path)
            else:
                self.err(f"Migration template not found: {migration_template_path}")
                raise FileNotFoundError(
                    f"Migration template not found: {migration_template_path}"
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
                    except FileNotFoundError as e:
                        # Likely a custom skill that doesn't have templates
                        error_str = str(e)
                        if "skills" in error_str and "default_config.yaml" in error_str:
                            self.log(
                                f"Warning: {filename} uses custom skill(s) without templates. "
                                f"Custom skills have been copied but may need manual review.",
                                True,
                            )
                        else:
                            self.err(f"Unable to migrate {filename}:\n{error_str}")
                        # Copy the wingman file anyway so user doesn't lose it
                        if not path.exists(new_file):
                            new_file_dir = path.dirname(new_file)
                            if not path.exists(new_file_dir):
                                os.makedirs(new_file_dir)
                            shutil.copyfile(old_file, new_file)
                        continue
                    except Exception as e:
                        self.err(f"Unable to migrate {filename}:\n{str(e)}")
                        # Copy the wingman file anyway so user doesn't lose it
                        if not path.exists(new_file):
                            shutil.copyfile(old_file, new_file)
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
    ("1_7_0", "1_8_0", ConfigMigrationService.migrate_170_to_180),
    ("1_8_0", "1_8_1", ConfigMigrationService.migrate_180_to_181),
    ("1_8_1", "1_8_2", ConfigMigrationService.migrate_181_to_182),
    ("1_8_2", "1_9_0", ConfigMigrationService.migrate_182_to_190),
    # Add new migrations here in order
]
