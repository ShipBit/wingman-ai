from datetime import datetime
from os import path, walk
import os
import shutil
from typing import Callable, Optional
from pydantic import ValidationError
from api.enums import LogType
from api.interface import CustomProperty, NestedConfig, SettingsConfig
from services.config_manager import (
    CONFIGS_DIR,
    DEFAULT_PREFIX,
    DELETED_PREFIX,
    ConfigManager,
)
from services.file import get_users_dir, get_custom_skills_dir, get_audio_library_dir
from services.printr import Printr
from services.secret_keeper import SecretKeeper
from services.system_manager import SystemManager

MIGRATION_LOG = ".migration"
MINIMUM_SUPPORTED_VERSION = "1_7_0"  # Versions older than this require a fresh start


class ConfigMigrationService:
    def __init__(
        self,
        config_manager: ConfigManager,
        system_manager: SystemManager,
    ):
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

        # Find the latest migratable version to start migration from
        # (skips legacy versions and any intermediate versions the user already has)
        start_version = self.find_latest_migratable_version(self.users_dir)

        if not start_version:
            self.log("No valid version directories found for migration.", True)
            # Fresh install - apply CUDA auto-detection for FasterWhisper
            self._apply_fresh_install_cuda_settings()
            return

        # Check if the latest version is already migrated

        migration_file = path.join(self.latest_config_path, MIGRATION_LOG)

        if path.exists(migration_file):
            self.log(
                f"Found {self.latest_version} configs. No migrations needed.", False
            )
            return

        self.log(
            f"Starting migration from version {start_version.replace('_', '.')} to {self.latest_version.replace('_', '.')}",
            True,
        )

        # If the latest version directory already exists (e.g., created by ConfigManager),
        # clean up any template configs that will be migrated from old versions
        if path.exists(self.latest_config_path) and start_version:
            self.remove_duplicate_template_configs(start_version, self.latest_version)

        # Copy custom skills from the LATEST existing version to new version
        # This ensures we get the most up-to-date custom skills
        self.log(f"Found latest existing version for custom skills: {start_version}")
        custom_skills = []
        if start_version and start_version != self.latest_version:
            custom_skills = self.copy_custom_skills(start_version, self.latest_version)
        else:
            self.log(
                f"Skipping custom skills copy - start_version: {start_version}, latest_version: {self.latest_version}"
            )

        # Migrate audio library from versioned location to non-versioned location
        # Only check 1.8.1 and 1.8.2 (most users come from 1.8.1, 1.8.2 was dev-only)
        self.migrate_audio_library()

        # Perform migrations
        current_version = start_version
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

    def find_latest_migratable_version(self, users_dir):
        """Find the latest migratable version to start migration from.

        Returns the latest migratable version present in the user's directory,
        skipping intermediate versions and versions that are too old.
        For example, if user has 1.8.1 and 1.8.2, migration starts from 1.8.2.
        """
        # Get all version directories (not just valid ones for migration)
        all_versions = next(os.walk(users_dir))[1]
        # Filter to version-like directories (format: X_Y_Z)
        version_dirs = [
            v for v in all_versions if v.replace("_", "").replace(".", "").isdigit()
        ]
        # Sort descending to get latest version first
        version_dirs.sort(key=lambda v: [int(n) for n in v.split("_")], reverse=True)

        for version in version_dirs:
            # Skip the target version
            if version == self.latest_version:
                continue
            # Skip versions that are too old to migrate
            if self.is_version_too_old(version):
                self.log(
                    f"Ignoring legacy version {version.replace('_', '.')} (older than minimum supported {MINIMUM_SUPPORTED_VERSION.replace('_', '.')})"
                )
                continue
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
        return [
            v
            for v in versions
            if self.is_valid_version(v) and not self.is_version_too_old(v)
        ]

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

    def _apply_fresh_install_cuda_settings(self):
        """Auto-detect CUDA availability and update FasterWhisper settings for fresh installs.

        This ensures that fresh installations automatically use CUDA if available,
        rather than defaulting to CPU.
        """
        cuda_available = self.system_manager.is_cuda_available()
        gpu_name = self.system_manager.get_gpu_name()

        device = "cuda" if cuda_available else "cpu"
        compute_type = "auto"

        self.log(
            "Fresh install detected - configuring FasterWhisper for optimal performance"
        )
        self.log(f"- detected GPU: {gpu_name or 'None'}")
        self.log(
            f"- setting voice_activation.fasterwhisper.device to '{device}' (CUDA {'available' if cuda_available else 'not available'})"
        )
        self.log(
            f"- setting voice_activation.fasterwhisper.compute_type to '{compute_type}'"
        )

        # Update the settings config
        settings = self.config_manager.settings_config
        if (
            settings
            and settings.voice_activation
            and settings.voice_activation.fasterwhisper
        ):
            settings.voice_activation.fasterwhisper.device = device
            settings.voice_activation.fasterwhisper.compute_type = compute_type
            self.config_manager.save_settings_config()
            self.log("- settings saved successfully")

    def reset_to_fresh_configs(self):
        """Copy fresh configs from templates to the latest version directory.

        Note: Skills are NO LONGER copied here. Built-in skills are loaded directly
        from the bundled location. Custom skills persist in the non-versioned
        custom_skills/ directory.
        """
        try:
            configs_template = path.join(self.templates_dir, "configs")

            latest_dir = path.join(self.users_dir, self.latest_version)

            # Remove existing latest version directory contents, but preserve 'logs' directory
            # because the log file may be locked by the logging system
            if path.exists(latest_dir):
                for item in os.listdir(latest_dir):
                    item_path = path.join(latest_dir, item)
                    if item == "logs":
                        # Skip logs directory - it may contain open log files
                        self.log("Preserving logs directory during reset")
                        continue
                    if path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                self.log(
                    f"Cleared existing {self.latest_version} directory (preserved logs)"
                )

            # Create the latest version directory
            os.makedirs(latest_dir, exist_ok=True)

            # Copy configs only (skills are now loaded from bundled location)
            if path.exists(configs_template):
                shutil.copytree(configs_template, path.join(latest_dir, CONFIGS_DIR))
                self.log("Copied fresh configs from templates")

            # Create migration log
            migration_file = path.join(latest_dir, CONFIGS_DIR, MIGRATION_LOG)
            with open(migration_file, "w", encoding="UTF-8") as stream:
                stream.write(self.log_message)

            self.log("Fresh configs installed successfully!", True)

        except Exception as e:
            self.err(f"Failed to reset to fresh configs: {str(e)}")
            raise

    def migrate_audio_library(self) -> None:
        """Migrate audio library from versioned location to non-versioned location.

        Starting with 1.9.0, audio library is stored in a non-versioned location:
        APPDATA/WingmanAI/audio_library/ (persists across updates)

        This method checks 1.8.1 and 1.8.2 for existing audio libraries and migrates them.
        """
        # Target: non-versioned audio library directory
        target_audio_library = get_audio_library_dir()

        # Check 1.8.2 first (dev version), then 1.8.1 (most users)
        versions_to_check = ["1_8_2", "1_8_1"]
        source_audio_library = None
        source_version = None

        for version in versions_to_check:
            potential_path = path.join(self.users_dir, version, "audio_library")
            if path.exists(potential_path) and path.isdir(potential_path):
                # Check if it has any audio files
                has_audio_files = any(
                    f.endswith((".mp3", ".wav"))
                    for _, _, files in os.walk(potential_path)
                    for f in files
                )
                if has_audio_files:
                    source_audio_library = potential_path
                    source_version = version
                    break

        if not source_audio_library:
            self.log("No audio library found in 1.8.1 or 1.8.2, skipping migration")
            return

        self.log(
            f"Found audio library in {source_version.replace('_', '.')}, migrating to non-versioned location",
            highlight=True,
        )

        files_copied = 0
        files_skipped = 0

        # Walk through all files in the source audio library
        for root, _dirs, files in os.walk(source_audio_library):
            for file in files:
                if not file.endswith((".mp3", ".wav")):
                    continue

                # Calculate relative path from source audio library
                rel_path = path.relpath(root, source_audio_library)
                rel_path = "" if rel_path == "." else rel_path

                # Create target directory structure
                if rel_path:
                    target_dir = path.join(target_audio_library, rel_path)
                else:
                    target_dir = target_audio_library

                if not path.exists(target_dir):
                    os.makedirs(target_dir)

                source_file = path.join(root, file)
                target_file = path.join(target_dir, file)

                # Skip if file already exists (don't overwrite)
                if path.exists(target_file):
                    files_skipped += 1
                    continue

                try:
                    shutil.copy2(source_file, target_file)
                    files_copied += 1
                except Exception as e:
                    self.err(f"Failed to copy audio file '{file}': {str(e)}")

        self.log(
            f"Audio library migration complete: {files_copied} files copied, {files_skipped} files skipped (already exist)",
            highlight=True,
        )

    def copy_custom_skills(self, old_version: str, new_version: str) -> list[str]:
        """Copy custom skills from old versioned location to new non-versioned custom_skills directory.

        Starting with 1.9.0, custom skills are stored in a non-versioned location:
        APPDATA/WingmanAI/custom_skills/ (persists across updates)

        This method migrates custom skills from the old versioned location to the new one.

        Returns:
            List of custom skill names that were copied
        """
        old_skills_dir = path.join(self.users_dir, old_version, "skills")
        # NEW: Custom skills now go to non-versioned location
        custom_skills_target_dir = get_custom_skills_dir()

        # Get list of built-in skill names from bundled skills directory
        # We need to determine which skills are custom (not built-in)
        from services.module_manager import get_bundled_skills_dir, SKILLS_DIR

        builtin_skills = set()

        # Check bundled skills directory
        bundled_dir = get_bundled_skills_dir()
        if bundled_dir and path.exists(bundled_dir):
            builtin_skills.update(os.listdir(bundled_dir))

        # Check source skills directory (dev mode)
        if path.exists(SKILLS_DIR):
            builtin_skills.update(os.listdir(SKILLS_DIR))

        # Also check migration template skills (for older version detection)
        template_skills_dir = path.join(
            self.templates_dir, "migration", new_version, "skills"
        )
        if path.exists(template_skills_dir):
            builtin_skills.update(os.listdir(template_skills_dir))

        # Legacy: Also check old templates/skills location
        legacy_template_skills = path.join(self.templates_dir, "skills")
        if path.exists(legacy_template_skills):
            builtin_skills.update(os.listdir(legacy_template_skills))

        # Skills that were removed in 1.9.0 (converted to MCP servers)
        # These should NOT be detected as custom skills during migration
        removed_builtin_skills = {
            "google_search",
            "web_search",
            "time_and_date_retriever",
            "ask_perplexity",
            "nms_assistant",
        }

        builtin_skills.update(removed_builtin_skills)

        custom_skills_copied = []

        if not path.exists(old_skills_dir):
            self.log(
                f"No old skills directory found at {old_skills_dir}, skipping custom skills migration"
            )
            return custom_skills_copied

        self.log(f"Checking for custom skills in: {old_skills_dir}")
        self.log(f"Built-in skills detected: {sorted(builtin_skills)}")

        # Find custom skills (exist in old but not in built-in skills)
        for skill_name in os.listdir(old_skills_dir):
            old_skill_path = path.join(old_skills_dir, skill_name)
            if not path.isdir(old_skill_path) or skill_name.startswith("."):
                continue

            is_custom = skill_name not in builtin_skills

            # If skill is not in built-in skills, it's a custom skill
            if is_custom:
                self.log(f"Found custom skill: {skill_name}", warning=True)
                new_skill_path = path.join(custom_skills_target_dir, skill_name)

                try:
                    # Skip if already exists in custom skills (don't overwrite)
                    if path.exists(new_skill_path):
                        self.log(
                            f"Custom skill '{skill_name}' already exists in custom_skills directory, skipping"
                        )
                        continue

                    # Copy the entire custom skill directory
                    shutil.copytree(old_skill_path, new_skill_path)

                    # Count all files in the copied directory
                    file_count = sum(
                        len(files) for _, _, files in os.walk(new_skill_path)
                    )

                    self.log(
                        f"Migrated CUSTOM skill '{skill_name}' to custom_skills/ ({file_count} files)",
                        highlight=True,
                    )
                    custom_skills_copied.append(skill_name)
                except Exception as e:
                    self.err(f"Failed to migrate custom skill '{skill_name}': {str(e)}")

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
            # Auto-detect CUDA availability and set FasterWhisper device accordingly
            cuda_available = self.system_manager.is_cuda_available()
            gpu_name = self.system_manager.get_gpu_name()

            device = "cuda" if cuda_available else "cpu"
            compute_type = "auto"

            # Ensure the structure exists
            if "voice_activation" not in old:
                old["voice_activation"] = {}
            if "fasterwhisper" not in old["voice_activation"]:
                old["voice_activation"]["fasterwhisper"] = {}

            old["voice_activation"]["fasterwhisper"]["device"] = device
            old["voice_activation"]["fasterwhisper"]["compute_type"] = compute_type

            self.log(f"- detected GPU: {gpu_name or 'None'}")
            self.log(
                f"- set voice_activation.fasterwhisper.device to '{device}' (CUDA {'available' if cuda_available else 'not available'})"
            )
            self.log(
                f"- set voice_activation.fasterwhisper.compute_type to '{compute_type}'"
            )

            return old

        # Models removed from Wingman Pro - migrate to gpt-4o-mini
        removed_wingman_pro_models = [
            "gpt-4o",
            "mistral-large-latest",
            "llama3-8b",
            "llama3-70b",
        ]

        def migrate_defaults(old: dict, new: dict) -> dict:
            old["xai"] = new["xai"]
            self.log("- added new property: xai")

            # Migrate deprecated Wingman Pro conversation models
            if "wingman_pro" in old and "conversation_deployment" in old["wingman_pro"]:
                current_model = old["wingman_pro"]["conversation_deployment"]
                if current_model in removed_wingman_pro_models:
                    old["wingman_pro"]["conversation_deployment"] = "gpt-4o-mini"
                    self.log(
                        f"- migrated wingman_pro.conversation_deployment from '{current_model}' to 'gpt-4o-mini' (model removed)"
                    )

            old["google"]["conversation_model"] = "gemini-flash-latest"
            self.log("- set Google default model to gemini-flash-latest")
            old["mistral"]["conversation_model"] = "mistral-medium-latest"
            self.log("- set Mistral default model to mistral-medium-latest")
            old["cerebras"]["conversation_model"] = "qwen-3-32b"
            self.log("- set Cerebras default model to qwen-3-32b")
            old["openrouter"]["conversation_model"] = "google/gemini-2.5-flash"
            self.log("- set OpenRouter default model to google/gemini-2.5-flash")
            old["groq"]["conversation_model"] = "qwen/qwen3-32b"
            self.log("- set Groq default model to qwen/qwen3-32b")

            # Force override prompts with new MCP-optimized versions
            # These new prompts establish tool-first behavior and cleaner TTS instructions
            if "prompts" not in old:
                old["prompts"] = {}
            old["prompts"]["system_prompt"] = new["prompts"]["system_prompt"]
            self.log(
                "- force updated prompts.system_prompt (MCP tool-first architecture)"
            )

            # Force update TTS prompts for ElevenLabs and Inworld
            if "elevenlabs" in new:
                old["elevenlabs"]["tts_prompt"] = new["elevenlabs"]["tts_prompt"]
                self.log("- force updated elevenlabs.tts_prompt (new v3 audio tags)")

            if "inworld" in new:
                old["inworld"]["tts_prompt"] = new["inworld"]["tts_prompt"]
                self.log("- force updated inworld.tts_prompt (new audio markup format)")
                if "audio_config" in old["inworld"]:
                    del old["inworld"]["audio_config"]["pitch"]
                    self.log(
                        "- removed inworld.audio_config.pitch (no longer supported)"
                    )
                    # Add streaming_sample_rate_hertz for better streaming quality
                    old["inworld"]["audio_config"]["streaming_sample_rate_hertz"] = new[
                        "inworld"
                    ]["audio_config"]["streaming_sample_rate_hertz"]
                    self.log("- added inworld.audio_config.streaming_sample_rate_hertz")

            return old

        def migrate_wingman(old: dict, new: Optional[dict]) -> dict:
            # Clear prompt overrides so everyone uses the new defaults
            # IMPORTANT: We keep 'backstory' - only clear system_prompt and tts_prompt
            changes_made = []

            # Migrate deprecated Wingman Pro conversation models
            if "wingman_pro" in old and "conversation_deployment" in old["wingman_pro"]:
                current_model = old["wingman_pro"]["conversation_deployment"]
                if current_model in removed_wingman_pro_models:
                    old["wingman_pro"]["conversation_deployment"] = "gpt-4o-mini"
                    changes_made.append(
                        f"wingman_pro.conversation_deployment ('{current_model}' -> 'gpt-4o-mini')"
                    )

            # Clear system_prompt override (force use of new default)
            if "prompts" in old:
                if "system_prompt" in old["prompts"]:
                    del old["prompts"]["system_prompt"]
                    changes_made.append("prompts.system_prompt")
                # Remove prompts dict if empty
                if not old["prompts"]:
                    del old["prompts"]

            # Clear ElevenLabs tts_prompt override
            if "elevenlabs" in old and "tts_prompt" in old["elevenlabs"]:
                del old["elevenlabs"]["tts_prompt"]
                changes_made.append("elevenlabs.tts_prompt")
                # Remove elevenlabs dict if empty
                if not old["elevenlabs"]:
                    del old["elevenlabs"]

            # Clear Inworld tts_prompt override
            if "inworld" in old and "tts_prompt" in old["inworld"]:
                del old["inworld"]["tts_prompt"]
                changes_made.append("inworld.tts_prompt")
                # Remove inworld dict if empty
                if not old["inworld"]:
                    del old["inworld"]

            # Skills removed in 1.9.0 (converted to MCP servers or deprecated)
            # We must remove any config overrides for these skills
            removed_skill_modules = {
                "skills.google_search.main",
                "skills.web_search.main",
                "skills.time_and_date_retriever.main",
                "skills.nms_assistant.main",
                "skills.ask_perplexity.main",
            }

            # Clean up old skills array but PRESERVE custom property and prompt overrides
            # Skills are now auto-loaded, but overrides per wingman still need to be saved
            # Skip overrides for removed skills - they no longer exist
            if "skills" in old:
                skills_with_overrides = []
                for skill in old["skills"]:
                    skill_module = skill.get("module", "")

                    # Skip removed skills entirely - don't preserve their overrides
                    if skill_module in removed_skill_modules:
                        changes_made.append(
                            f"removed skill config for '{skill_module}' (skill deprecated)"
                        )
                        continue

                    has_custom_props = skill.get("custom_properties")
                    has_prompt = skill.get("prompt")

                    if has_custom_props or has_prompt:
                        stripped_skill = {"module": skill_module}

                        # Keep prompt override if present
                        if has_prompt:
                            stripped_skill["prompt"] = has_prompt

                        # Custom properties in wingman config are diffs - they only contain
                        # the id and overridden values. We need to merge with the skill's
                        # default_config.yaml to get complete valid CustomProperty objects.
                        if has_custom_props:
                            valid_props = []
                            skill_module = skill.get("module", "")

                            # Get the skill's default custom properties
                            skill_default_props = (
                                self._get_skill_default_custom_properties(skill_module)
                            )

                            for prop in has_custom_props:
                                prop_id = prop.get("id")
                                if not prop_id:
                                    continue

                                # Find the default property with this id
                                default_prop = skill_default_props.get(prop_id)
                                if default_prop:
                                    # Merge: start with default, override with wingman values
                                    merged_prop = default_prop.copy()
                                    merged_prop.update(prop)
                                    # Remove examples field if present (not needed in wingman config)
                                    merged_prop.pop("examples", None)

                                    try:
                                        CustomProperty(**merged_prop)
                                        valid_props.append(merged_prop)
                                    except ValidationError as e:
                                        self.log(
                                            f"- skipped custom property '{prop_id}' in skill '{skill_module}': validation failed after merge",
                                            warning=True,
                                        )
                                else:
                                    # No default found - try to validate as-is (might be a custom skill prop)
                                    try:
                                        CustomProperty(**prop)
                                        valid_props.append(prop)
                                    except ValidationError:
                                        self.log(
                                            f"- skipped custom property '{prop_id}' in skill '{skill_module}': no default found and incomplete",
                                            warning=True,
                                        )

                            if valid_props:
                                stripped_skill["custom_properties"] = valid_props

                        # Only add skill if it still has overrides
                        if stripped_skill.get("prompt") or stripped_skill.get(
                            "custom_properties"
                        ):
                            skills_with_overrides.append(stripped_skill)

                if skills_with_overrides:
                    old["skills"] = skills_with_overrides
                    changes_made.append(
                        f"skills (kept {len(skills_with_overrides)} skill(s) with overrides)"
                    )
                else:
                    del old["skills"]
                    changes_made.append("skills (removed - no overrides)")

            # Set disabled_skills for known wingmen (opt-out model)
            wingman_name = old.get("name", "")

            # Star Citizen wingmen: ATC and Computer get same blacklist
            sc_blacklist = [
                "APIRequest",
                "ATSTelemetry",
                "AudioDeviceChanger",
                "ControlWindows",
                "FileManager",
                "Msfs2020Control",
                "QuickCommands",
                "RadioChatter",
                "Spotify",
                "ThinkingSound",
                "TypingAssistant",
                "UEXCorp",
                "VoiceChanger",
            ]

            # Clippy blacklist (general assistant)
            clippy_blacklist = [
                "ATSTelemetry",
                "AudioDeviceChanger",
                "Msfs2020Control",
                "QuickCommands",
                "RadioChatter",
                "Spotify",
                "ThinkingSound",
                "UEXCorp",
                "VoiceChanger",
            ]

            if wingman_name in ("ATC", "Computer"):
                old["disabled_skills"] = sc_blacklist
                changes_made.append(
                    f"disabled_skills (SC wingman: {len(sc_blacklist)} skills disabled)"
                )
            elif wingman_name == "Clippy":
                old["disabled_skills"] = clippy_blacklist
                changes_made.append(
                    f"disabled_skills (Clippy: {len(clippy_blacklist)} skills disabled)"
                )
            else:
                # For all other wingmen, remove deprecated skills from disabled_skills
                # (these skills have been removed, replaced by MCP servers)
                removed_skill_names = {
                    "AskPerplexity",
                    "GoogleSearch",
                    "WebSearch",
                    "TimeAndDateRetriever",
                    "NMSAssistant",
                    "StarHead",
                }
                if "disabled_skills" in old and old["disabled_skills"]:
                    removed_from_disabled = [
                        s for s in old["disabled_skills"] if s in removed_skill_names
                    ]
                    if removed_from_disabled:
                        old["disabled_skills"] = [
                            s
                            for s in old["disabled_skills"]
                            if s not in removed_skill_names
                        ]
                        changes_made.append(
                            f"disabled_skills (removed {', '.join(removed_from_disabled)} - skills deprecated)"
                        )
                    # Clean up empty disabled_skills list
                    if not old["disabled_skills"]:
                        del old["disabled_skills"]

            # MCP servers are now centralized in mcp.yaml
            # Remove old per-wingman mcp array if it exists (shouldn't in 1.8.2, but clean up)
            if "mcp" in old:
                del old["mcp"]
                changes_made.append("mcp (removed - now centralized in mcp.yaml)")

            # For custom wingmen without disabled_mcps, disable all optional MCP servers
            # wingman_date_time is always enabled for all wingmen (not in this list)
            # This ensures migrated custom wingmen start with a clean slate
            # Users can then enable specific MCPs as needed
            # Template-based wingmen already have their disabled_mcps defined
            if "disabled_mcps" not in old or old["disabled_mcps"] is None:
                optional_mcp_servers = [
                    "wingman_websearch",
                    "wingman_perplexity",
                    "wingman_starhead",
                    "wingman_no_mans_sky",
                ]  # All optional servers from mcp.template.yaml (excludes wingman_date_time)
                old["disabled_mcps"] = optional_mcp_servers
                changes_made.append(
                    f"disabled_mcps (initialized with all {len(optional_mcp_servers)} optional MCPs disabled)"
                )

            if changes_made:
                self.log(f"- cleared/updated: {', '.join(changes_made)}")

            return old

        def migrate_mcp(old: dict, new: dict) -> dict:
            # For 1.8.2 -> 1.9.0, we're creating mcp.yaml fresh from template
            # Just use the new template values
            return new

        def migrate_secrets(old: dict) -> dict:
            if "local_llm" not in old:
                old["local_llm"] = "not-set"
                self.log("- added new secret: local_llm")
            return old

        self.migrate(
            old_version="1_8_2",
            new_version="1_9_0",
            migrate_settings=migrate_settings,
            migrate_defaults=migrate_defaults,
            migrate_wingman=migrate_wingman,
            migrate_secrets=migrate_secrets,
            migrate_mcp=migrate_mcp,
        )

    # INTERNAL

    def _get_skill_default_custom_properties(
        self, skill_module: str
    ) -> dict[str, dict]:
        """Get the default custom properties from a skill's default_config.yaml.

        Args:
            skill_module: The skill module path (e.g., 'skills.vision_ai.main')

        Returns:
            A dict mapping property id to the full property dict from default_config.yaml
        """
        from services.module_manager import get_bundled_skills_dir

        # Extract skill directory name from module path
        # e.g., 'skills.vision_ai.main' -> 'vision_ai'
        skill_dir = skill_module.replace(".main", "").replace(".", "/").split("/")[-1]

        # Search for default_config.yaml in multiple locations
        search_paths = []

        # 1. Bundled skills (in the app)
        bundled_dir = get_bundled_skills_dir()
        if bundled_dir:
            search_paths.append(
                path.join(bundled_dir, skill_dir, "default_config.yaml")
            )

        # 2. Source skills directory (dev mode)
        from services.module_manager import SKILLS_DIR

        search_paths.append(path.join(SKILLS_DIR, skill_dir, "default_config.yaml"))

        # 3. Custom skills directory
        search_paths.append(
            path.join(get_custom_skills_dir(), skill_dir, "default_config.yaml")
        )

        # Find and read the default_config.yaml
        for config_path in search_paths:
            if path.exists(config_path):
                try:
                    config = self.config_manager.read_config(config_path)
                    if config and "custom_properties" in config:
                        # Build a dict keyed by id for easy lookup
                        return {
                            prop["id"]: prop
                            for prop in config["custom_properties"]
                            if "id" in prop
                        }
                except Exception:
                    pass

        return {}

    def log(self, message: str, highlight: bool = False, warning: bool = False):
        if warning:
            color = LogType.WARNING
        elif highlight:
            color = LogType.STARTUP
        else:
            color = LogType.SYSTEM
        self.printr.print(
            message,
            color=color,
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
        migrate_secrets: Optional[Callable[[dict], dict]] = None,
        migrate_mcp: Optional[Callable[[dict, dict], dict]] = None,
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
                if filename == ".DS_Store" or filename == MIGRATION_LOG:
                    continue

                old_file = path.join(root, filename)
                new_file = old_file.replace(old_config_path, new_config_path)

                # secrets
                if filename == "secrets.yaml":
                    if migrate_secrets:
                        self.log("Migrating secrets.yaml...", True)
                        old_secrets = self.config_manager.read_config(old_file) or {}
                        migrated_secrets = migrate_secrets(old_secrets)
                        # Write the migrated secrets
                        new_dir = path.dirname(new_file)
                        if not path.exists(new_dir):
                            os.makedirs(new_dir)
                        self.config_manager.write_config(new_file, migrated_secrets)
                        self.log("Migrated secrets.yaml", highlight=True)
                    else:
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

        # Handle directory deletions after processing all files
        for root, _dirs, _files in walk(old_config_path):
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
            if (
                target_dir
                and os.path.basename(root).startswith(DELETED_PREFIX)
                and path.exists(target_dir)
            ):
                shutil.rmtree(target_dir)
                self.log(
                    f"Logically deleting config {root} like in the previous version"
                )

        # Handle case where secrets.yaml doesn't exist in old version but we need to create it
        if migrate_secrets:
            new_secrets_file = path.join(new_config_path, "secrets.yaml")
            if not path.exists(new_secrets_file):
                self.log("Creating secrets.yaml (not found in old version)...", True)
                migrated_secrets = migrate_secrets({})
                if not path.exists(new_config_path):
                    os.makedirs(new_config_path)
                self.config_manager.write_config(new_secrets_file, migrated_secrets)
                self.log("Created secrets.yaml with new secrets", highlight=True)

                if new_config_path == self.latest_config_path:
                    secret_keeper = SecretKeeper()
                    secret_keeper.secrets = secret_keeper.load()

        # Handle mcp.yaml - this is a new file in 1.9.0
        if migrate_mcp:
            new_mcp_file = path.join(new_config_path, "mcp.yaml")
            old_mcp_file = path.join(old_config_path, "mcp.yaml")

            # Read the template mcp.yaml (from templates/configs/)
            # Note: template file is named mcp.template.yaml
            template_mcp_file = path.join(
                self.templates_dir, "configs", "mcp.template.yaml"
            )
            new_mcp_config = {}
            if path.exists(template_mcp_file):
                new_mcp_config = (
                    self.config_manager.read_config(template_mcp_file) or {}
                )

            if path.exists(old_mcp_file):
                # mcp.yaml exists in old version - migrate it
                self.log("Migrating mcp.yaml...", True)
                old_mcp_config = self.config_manager.read_config(old_mcp_file) or {}
                migrated_mcp = migrate_mcp(old_mcp_config, new_mcp_config)
            else:
                # mcp.yaml doesn't exist in old version - create from template
                self.log("Creating mcp.yaml (not found in old version)...", True)
                migrated_mcp = migrate_mcp({}, new_mcp_config)

            if not path.exists(new_config_path):
                os.makedirs(new_config_path)
            self.config_manager.write_config(new_mcp_file, migrated_mcp)
            self.log("Created/migrated mcp.yaml", highlight=True)

            # Reload mcp config if this is the latest version
            if new_config_path == self.latest_config_path:
                from api.interface import McpConfig

                try:
                    self.config_manager.mcp_config = McpConfig(**migrated_mcp)
                except Exception as e:
                    self.err(f"Failed to load migrated mcp.yaml: {str(e)}")

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
