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
from services.file import get_users_dir, get_custom_skills_dir, get_audio_library_dir
from services.migrations import discover_migrations
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

        # Auto-discover migrations from migrations/ directory
        self.migrations = discover_migrations()
        self.latest_version = self.migrations[-1][1] if self.migrations else None
        self.latest_config_path = (
            path.join(self.users_dir, self.latest_version, CONFIGS_DIR)
            if self.latest_version
            else None
        )

    def migrate_to_latest(self):
        # Check if the latest version already exists with configs
        migration_file = path.join(self.latest_config_path, MIGRATION_LOG)

        # If migration file exists, we're already migrated
        if path.exists(migration_file):
            self.log(f"Found {self.latest_version} configs. No migrations needed.")
            return

        # Find the latest migratable version to start migration from
        # Check this BEFORE checking if settings.yaml exists, because ConfigManager
        # may have created fresh template files even though we should migrate
        start_version = self.find_latest_migratable_version(self.users_dir)

        # If we found an old version to migrate from, proceed with migration
        if start_version:
            self.log_highlight(
                f"Starting migration from version {start_version.replace('_', '.')} to {self.latest_version.replace('_', '.')}"
            )

            # If the latest version directory already exists (e.g., created by ConfigManager),
            # clean up any template configs that will be migrated from old versions
            if path.exists(self.latest_config_path):
                self.remove_duplicate_template_configs(
                    start_version, self.latest_version
                )

            # Copy custom skills from the LATEST existing version to new version
            # This ensures we get the most up-to-date custom skills
            self.log(
                f"Found latest existing version for custom skills: {start_version}"
            )
            custom_skills = []
            if start_version != self.latest_version:
                custom_skills = self.copy_custom_skills(
                    start_version, self.latest_version
                )

            # Migrate audio library from versioned location to non-versioned location
            # Only check 1.8.1 and 1.8.2 (most users come from 1.8.1, 1.8.2 was dev-only)
            self.migrate_audio_library()

            # Perform migrations
            current_version = start_version
            while current_version != self.latest_version:
                next_version = self.find_next_version(current_version)
                if next_version is None:
                    self.err(
                        f"No migration path found from version {current_version} to {self.latest_version}. Migration aborted."
                    )
                    break
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

            self.log_highlight(
                f"Migration completed successfully. Current version: {self.latest_version.replace('_', '.')}"
            )
            return

        # No old version found - check if this is an existing installation or fresh install
        settings_file = path.join(self.latest_config_path, "settings.yaml")
        if path.exists(settings_file):
            self.log(
                f"Found existing {self.latest_version} configs. No migrations needed."
            )
            # Create migration marker to avoid this check on next startup
            with open(migration_file, "w") as f:
                f.write(f"Version {self.latest_version} - no migration required\n")
            return

        # No old version and no existing configs - fresh install
        self.log_highlight("No valid version directories found for migration.")
        self._apply_fresh_install_cuda_settings()

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
        """Find the next version in the migration chain."""
        for old, new, _ in self.migrations:
            if old == current_version:
                return new
        return None

    def perform_migration(self, old_version, new_version):
        """Execute a single migration step."""
        migration_class = next(
            (
                m[2]
                for m in self.migrations
                if m[0] == old_version and m[1] == new_version
            ),
            None,
        )

        if migration_class:
            self.log_highlight(
                f"Migrating from {old_version.replace('_', '.')} to {new_version.replace('_', '.')}"
            )
            # Instantiate and execute the migration
            migration = migration_class(self)
            migration.execute()
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
        """Check if a version exists in the migration chain."""
        return any(version in migration[:2] for migration in self.migrations)

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

        # Create migration marker to prevent this check on next startup
        migration_file = path.join(self.latest_config_path, MIGRATION_LOG)
        with open(migration_file, "w") as f:
            f.write(f"Fresh install - Version {self.latest_version}\n")
        self.log("- migration marker created")

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

            self.log_highlight("Fresh configs installed successfully!")

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

        self.log_highlight(
            f"Found audio library in {source_version.replace('_', '.')}, migrating to non-versioned location"
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

        self.log_highlight(
            f"Audio library migration complete: {files_copied} files copied, {files_skipped} files skipped (already exist)"
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
            for item in os.listdir(bundled_dir):
                item_path = path.join(bundled_dir, item)
                if self.is_valid_skill_directory(item_path):
                    builtin_skills.add(item)

        # Check source skills directory (dev mode)
        if path.exists(SKILLS_DIR):
            for item in os.listdir(SKILLS_DIR):
                item_path = path.join(SKILLS_DIR, item)
                if self.is_valid_skill_directory(item_path):
                    builtin_skills.add(item)

        # Legacy: Also check old templates/skills location
        legacy_template_skills = path.join(self.templates_dir, "skills")
        if path.exists(legacy_template_skills):
            for item in os.listdir(legacy_template_skills):
                item_path = path.join(legacy_template_skills, item)
                if self.is_valid_skill_directory(item_path):
                    builtin_skills.add(item)

        # Skills that were removed in 1.9.0 (converted to MCP servers)
        # These should NOT be detected as custom skills during migration
        removed_builtin_skills = {
            "google_search",
            "web_search",
            "time_and_date_retriever",
            "ask_perplexity",
            "nms_assistant",
            "star_head",
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
                self.log_warning(f"Found custom skill: {skill_name}")
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

                    self.log_highlight(
                        f"Migrated CUSTOM skill '{skill_name}' to custom_skills/ ({file_count} files)"
                    )
                    custom_skills_copied.append(skill_name)
                except Exception as e:
                    self.err(f"Failed to migrate custom skill '{skill_name}': {str(e)}")

        return custom_skills_copied

    # Helper methods for migrations

    def is_valid_skill_directory(self, skill_path: str) -> bool:
        """Check if a directory is a valid skill by verifying it has required files.

        A valid skill must have:
        - main.py (the skill implementation)
        - default_config.yaml (the skill configuration)

        Args:
            skill_path: Absolute path to the skill directory

        Returns:
            True if the directory contains both required files
        """
        if not path.isdir(skill_path):
            return False

        # Check for required files
        has_main = path.exists(path.join(skill_path, "main.py"))
        has_config = path.exists(path.join(skill_path, "default_config.yaml"))

        return has_main and has_config

    def get_skills_discoverable_by_default(self) -> list[str]:
        """Get list of BUILT-IN skill names that have discoverable_by_default=True (or unset).

        Custom skills are excluded - they must be explicitly added by the user.

        Returns:
            List of built-in skill names that should be discoverable by default
        """
        from services.module_manager import (
            ModuleManager,
            get_bundled_skills_dir,
            SKILLS_DIR,
        )

        # Get list of built-in skill directory names
        builtin_skills = set()

        # Check bundled skills directory
        bundled_dir = get_bundled_skills_dir()
        if bundled_dir and path.exists(bundled_dir):
            for item in os.listdir(bundled_dir):
                item_path = path.join(bundled_dir, item)
                if self.is_valid_skill_directory(item_path):
                    builtin_skills.add(item)

        # Check source skills directory (dev mode)
        if path.exists(SKILLS_DIR):
            for item in os.listdir(SKILLS_DIR):
                item_path = path.join(SKILLS_DIR, item)
                if self.is_valid_skill_directory(item_path):
                    builtin_skills.add(item)

        discoverable_by_default = []
        try:
            all_skills = ModuleManager.read_available_skills()
            for skill in all_skills:
                # Skip custom skills - only include built-in skills
                skill_folder = (
                    skill.config.module.split(".")[-2]
                    if "." in skill.config.module
                    else skill.name
                )
                if skill_folder not in builtin_skills:
                    continue

                # discoverable_by_default defaults to True, so check if it's not explicitly False
                if skill.config.discoverable_by_default is not False:
                    discoverable_by_default.append(skill.name)
        except Exception as e:
            self.log_warning(
                f"Warning: Could not read skills for discoverable_by_default check: {e}"
            )

        return discoverable_by_default

    def _get_all_skill_names(self) -> list[str]:
        """Get list of all available skill names.

        Returns:
            List of all skill names
        """
        from services.module_manager import ModuleManager

        all_names = []
        try:
            all_skills = ModuleManager.read_available_skills()
            for skill in all_skills:
                all_names.append(skill.name)
        except Exception as e:
            self.log_warning(f"Warning: Could not read skills for all skill names: {e}")

        return all_names

    def get_mcps_discoverable_by_default(self) -> list[str]:
        """Get list of MCP server names that have discoverable_by_default=True.

        Returns:
            List of MCP server names that should be discoverable by default
        """
        discoverable_by_default = []
        mcp_config = self.config_manager.mcp_config
        if mcp_config and mcp_config.servers:
            for server in mcp_config.servers:
                if server.discoverable_by_default:
                    discoverable_by_default.append(server.name)

        return discoverable_by_default

    def get_template_path(self, wingman_name: str) -> Optional[str]:
        """Get the path to a template.yaml file for a known wingman.

        Args:
            wingman_name: Name of the wingman (ATC, Computer, Clippy)

        Returns:
            Path to the template file, or None if not found
        """
        # Check different possible locations
        template_locations = [
            path.join(
                self.templates_dir,
                "configs",
                "_Star Citizen",
                f"{wingman_name}.template.yaml",
            ),
            path.join(
                self.templates_dir,
                "configs",
                "General",
                f"{wingman_name}.template.yaml",
            ),
        ]

        for template_path in template_locations:
            if path.exists(template_path):
                return template_path

        return None

    def get_skill_default_custom_properties(self, skill_module: str) -> dict[str, dict]:
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
                except Exception as e:
                    self.log_warning(
                        f"Failed to read or parse skill config '{config_path}': {e}"
                    )

        return {}

    def log(self, message: str):
        """Log a normal message."""
        self._log_with_color(message, LogType.SYSTEM)

    def log_highlight(self, message: str):
        """Log a highlighted message."""
        self._log_with_color(message, LogType.STARTUP)

    def log_warning(self, message: str):
        """Log a warning message."""
        self._log_with_color(message, LogType.WARNING)

    def err(self, message: str):
        """Log an error message."""
        self._log_with_color(message, LogType.ERROR)

    def _log_with_color(self, message: str, color: LogType):
        """Internal method to log with specified color."""
        self.printr.print(message, color=color, server_only=True)
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
                    self.log_highlight(
                        f"Removed template config '{item}' - will be migrated from old version (normalized: {normalized})"
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

        self.log_highlight(f"Copied file: {path.basename(new_file)}")

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
                                    self.log_highlight(
                                        f"Skipped template config '{item}' - config exists in old version (normalized: {normalized})"
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

        self.log_highlight(
            f"Starting migration from {old_config_path} to {new_config_path}"
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
                        self.log_highlight("Migrating secrets.yaml...")
                        old_secrets = self.config_manager.read_config(old_file) or {}
                        migrated_secrets = migrate_secrets(old_secrets)
                        # Write the migrated secrets
                        new_dir = path.dirname(new_file)
                        if not path.exists(new_dir):
                            os.makedirs(new_dir)
                        self.config_manager.write_config(new_file, migrated_secrets)
                        self.log_highlight("Migrated secrets.yaml")
                    else:
                        self.copy_file(old_file, new_file)

                    if new_config_path == self.latest_config_path:
                        secret_keeper = SecretKeeper()
                        secret_keeper.secrets = secret_keeper.load()
                # settings
                elif filename == "settings.yaml":
                    self.log_highlight("Migrating settings.yaml...")
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
                    self.log_highlight("Migrating defaults.yaml...")
                    migrated_defaults = migrate_defaults(
                        old=self.config_manager.read_config(old_file),
                        new=self.config_manager.read_config(new_file),
                    )
                    try:
                        # Only validate on final migration step (current schema may not match intermediate versions)
                        if new_config_path == self.latest_config_path:
                            self.config_manager.default_config = NestedConfig(
                                **migrated_defaults
                            )
                            self.config_manager.save_defaults_config()
                        else:
                            # Intermediate step - just write the file without validation
                            self.config_manager.write_config(
                                new_file, migrated_defaults
                            )
                    except ValidationError as e:
                        self.err(f"Unable to migrate defaults.yaml:\n{str(e)}")
                # Wingmen
                elif filename.endswith(".yaml"):
                    self.log_highlight(f"Migrating Wingman {filename}...")
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
                            self.log_highlight(
                                f"Warning: {filename} uses custom skill(s) without templates. "
                                f"Custom skills have been copied but may need manual review."
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
                self.log_highlight(
                    "Creating secrets.yaml (not found in old version)..."
                )
                migrated_secrets = migrate_secrets({})
                if not path.exists(new_config_path):
                    os.makedirs(new_config_path)
                self.config_manager.write_config(new_secrets_file, migrated_secrets)
                self.log_highlight("Created secrets.yaml with new secrets")

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
                self.log_highlight("Migrating mcp.yaml...")
                old_mcp_config = self.config_manager.read_config(old_mcp_file) or {}
                migrated_mcp = migrate_mcp(old_mcp_config, new_mcp_config)
            else:
                # mcp.yaml doesn't exist in old version - create from template
                self.log_highlight("Creating mcp.yaml (not found in old version)...")
                migrated_mcp = migrate_mcp({}, new_mcp_config)

            if not path.exists(new_config_path):
                os.makedirs(new_config_path)
            self.config_manager.write_config(new_mcp_file, migrated_mcp)
            self.log_highlight("Created/migrated mcp.yaml")

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
