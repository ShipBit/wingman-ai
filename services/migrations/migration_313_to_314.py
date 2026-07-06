"""Migration from version 3.1.3 to 3.1.4.

Converts the legacy config state encoding into configs/context.yaml:

- Legacy encoded the default config as a "_" directory name prefix and
  logically deleted configs/wingmen as a "." prefix. Names and state constantly
  drifted apart, causing duplicated or resurrected configs on every restart or
  migration for years.
- Now directory/file names are immutable identity and all state (default
  config, deletion tombstones) lives in configs/context.yaml.

Conversion rules (conservative - never deletes user data):
- '.Star Citizen' (logically deleted): records a deletion tombstone and moves
  the directory to APPDATA/WingmanAI/archived_configs/ instead of deleting it.
- '_Star Citizen' (default): renamed to 'Star Citizen' and recorded as the
  default config in context.yaml.
- '_Star Citizen' AND 'Star Citizen' both present (the legacy duplication bug):
  both are kept; the prefixed one is renamed to 'Star Citizen (2)' etc. so the
  user can decide which one to delete - in a UI that works now.
- '.Computer.yaml' wingman markers: recorded as wingman deletion tombstones and
  archived.
"""

import os
from os import path
import shutil

from services.file import get_users_dir
from services.migrations.base_migration import BaseMigration

LEGACY_DELETED_PREFIX = "."
LEGACY_DEFAULT_PREFIX = "_"

ARCHIVE_SUBDIR = path.join("archived_configs", "pre_3_1_4")


class Migration313To314(BaseMigration):
    """Migration from 3.1.3 to 3.1.4: legacy prefix state -> context.yaml."""

    old_version = "3_1_3"
    new_version = "3_1_4"

    def execute(self) -> None:
        # Standard chain migration copies the old configs (still using legacy
        # prefixed names) into the new version directory first.
        super().execute()
        self.convert_to_context_state()

    # Conversion

    def convert_to_context_state(self) -> None:
        """Translate legacy prefix-encoded state into configs/context.yaml."""
        configs_path = self.service.latest_config_path
        config_manager = self.config_manager
        state = config_manager.context_state

        self.log_highlight("Converting legacy config state to context.yaml...")

        # Start from a clean slate - the state file was created with defaults
        # by the ConfigManager on startup before this migration ran.
        state.deleted_template_configs = []
        state.deleted_template_wingmen = {}
        default_candidates: list[str] = []

        dir_names = sorted(
            (
                name
                for name in os.listdir(configs_path)
                if path.isdir(path.join(configs_path, name))
            ),
            key=str.casefold,
        )

        # 1) Legacy logically deleted dirs ('.Star Citizen'): tombstone + archive.
        for dir_name in [
            d for d in dir_names if d.startswith(LEGACY_DELETED_PREFIX)
        ]:
            normalized = self._strip_legacy_prefixes(dir_name)
            if normalized and config_manager.has_template_config(normalized):
                state.deleted_template_configs.append(normalized)
                self.log(
                    f"- '{dir_name}' was logically deleted: '{normalized}' "
                    "will not be recreated from templates"
                )
            archived = self._archive(path.join(configs_path, dir_name))
            self.log(f"- archived '{dir_name}' to '{archived}'")

        # 2) Legacy default dirs ('_Star Citizen', corrupted '_.Star Citizen'):
        #    rename to the clean name; keep both on collision with a live dir.
        for dir_name in [
            d for d in dir_names if d.startswith(LEGACY_DEFAULT_PREFIX)
        ]:
            normalized = self._strip_legacy_prefixes(dir_name) or "Unnamed"
            target_name = self._unique_dir_name(configs_path, normalized)
            shutil.move(
                path.join(configs_path, dir_name),
                path.join(configs_path, target_name),
            )
            if target_name != normalized:
                self.log_warning(
                    f"- both '{dir_name}' and '{normalized}' existed (legacy duplication bug). "
                    f"Kept both: '{dir_name}' is now '{target_name}'."
                )
            else:
                self.log(f"- renamed default config '{dir_name}' to '{target_name}'")
            default_candidates.append(target_name)

        # 3) Legacy wingman deletion markers ('.Computer.yaml') in live dirs.
        for dir_name in sorted(
            (
                name
                for name in os.listdir(configs_path)
                if path.isdir(path.join(configs_path, name))
            ),
            key=str.casefold,
        ):
            dir_path = path.join(configs_path, dir_name)
            for filename in sorted(os.listdir(dir_path)):
                if not filename.startswith(
                    LEGACY_DELETED_PREFIX
                ) or not filename.endswith(".yaml"):
                    continue
                wingman_name = filename.lstrip(LEGACY_DELETED_PREFIX).removesuffix(
                    ".yaml"
                )
                if wingman_name and config_manager.has_template_wingman(
                    dir_name, wingman_name
                ):
                    state.deleted_template_wingmen.setdefault(dir_name, [])
                    if (
                        wingman_name
                        not in state.deleted_template_wingmen[dir_name]
                    ):
                        state.deleted_template_wingmen[dir_name].append(
                            wingman_name
                        )
                    self.log(
                        f"- Wingman '{wingman_name}' in '{dir_name}' was logically "
                        "deleted: it will not be recreated from templates"
                    )
                archived = self._archive(
                    path.join(dir_path, filename), subdir=dir_name
                )
                self.log(f"- archived '{dir_name}/{filename}' to '{archived}'")

        # 4) A tombstone is pointless (and would suppress future template
        #    updates) when a live dir with that name exists - drop those.
        live_dirs = {
            name
            for name in os.listdir(configs_path)
            if path.isdir(path.join(configs_path, name))
        }
        state.deleted_template_configs = [
            name for name in state.deleted_template_configs if name not in live_dirs
        ]

        # 5) Pick the default config.
        if default_candidates:
            state.default_config = default_candidates[0]
            if len(default_candidates) > 1:
                self.log_warning(
                    f"- multiple legacy default configs found ({', '.join(default_candidates)}). "
                    f"Picked '{state.default_config}'."
                )
        elif state.default_config not in live_dirs and live_dirs:
            state.default_config = sorted(live_dirs, key=str.casefold)[0]
            self.log(
                f"- no legacy default config found. Picked '{state.default_config}'."
            )

        config_manager.save_context_state()
        self.log_highlight(
            f"Converted config state: default '{state.default_config}', "
            f"{len(state.deleted_template_configs)} deleted config(s), "
            f"{sum(len(w) for w in state.deleted_template_wingmen.values())} deleted wingman/wingmen."
        )

    # Helpers

    @staticmethod
    def _strip_legacy_prefixes(name: str) -> str:
        while name and (
            name.startswith(LEGACY_DELETED_PREFIX)
            or name.startswith(LEGACY_DEFAULT_PREFIX)
        ):
            name = name[1:]
        return name

    @staticmethod
    def _unique_dir_name(parent: str, base: str) -> str:
        candidate = base
        counter = 2
        while path.exists(path.join(parent, candidate)):
            candidate = f"{base} ({counter})"
            counter += 1
        return candidate

    def _archive(self, source_path: str, subdir: str = "") -> str:
        """Move a legacy-deleted config dir/file into the (non-versioned)
        archive directory instead of deleting it. Never destroys user data."""
        archive_root = path.join(get_users_dir(), ARCHIVE_SUBDIR, subdir)
        os.makedirs(archive_root, exist_ok=True)

        base = path.basename(source_path).lstrip("._") or "archived"
        candidate = base
        counter = 2
        while path.exists(path.join(archive_root, candidate)):
            stem, ext = path.splitext(base)
            candidate = f"{stem} ({counter}){ext}"
            counter += 1

        target_path = path.join(archive_root, candidate)
        shutil.move(source_path, target_path)
        return target_path
