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
  if their contents are identical, the prefixed copy is archived; otherwise
  both are kept and the prefixed one is renamed to 'Star Citizen (2)' etc. so
  the user can decide which one to delete - in a UI that works now.
- '.Computer.yaml' wingman markers: recorded as wingman deletion tombstones and
  archived.

The conversion operates on THIS step's version directory (3_1_4), never on
the chain's latest directory - a user jumping e.g. 2.1.1 -> 3.1.x runs this
as an intermediate step and later steps copy context.yaml forward verbatim.
It is also safe to re-run: the .migration marker is only written after the
whole step succeeded, and a re-run starts from the context.yaml written by
the previous attempt.
"""

import filecmp
import os
from os import path
import shutil

from pydantic import ValidationError

from services.config_manager import CONFIGS_DIR, CONTEXT_FILE, ConfigContextState
from services.file import get_users_dir
from services.migrations.base_migration import (
    BaseMigration,
    LEGACY_DELETED_PREFIX,
    LEGACY_DEFAULT_PREFIX,
    strip_legacy_prefixes,
)

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
        configs_path = path.join(get_users_dir(), self.new_version, CONFIGS_DIR)
        config_manager = self.config_manager
        state = self._load_step_state(configs_path)
        default_candidates: list[str] = []

        self.log_highlight("Converting legacy config state to context.yaml...")

        dir_names = self._list_config_dirs(configs_path)

        # 1) Legacy logically deleted dirs ('.Star Citizen'): tombstone + archive.
        for dir_name in [
            d for d in dir_names if d.startswith(LEGACY_DELETED_PREFIX)
        ]:
            normalized = strip_legacy_prefixes(dir_name)
            if (
                normalized
                and config_manager.has_template_config(normalized)
                and normalized not in state.deleted_template_configs
            ):
                state.deleted_template_configs.append(normalized)
                self.log(
                    f"- '{dir_name}' was logically deleted: '{normalized}' "
                    "will not be recreated from templates"
                )
            archived = self._archive(path.join(configs_path, dir_name))
            self.log(f"- archived '{dir_name}' to '{archived}'")

        # 2) Legacy default dirs ('_Star Citizen', corrupted '_.Star Citizen'):
        #    rename to the clean name. On collision with a live dir, archive
        #    the prefixed copy if the contents are identical (also makes a
        #    crashed-and-rerun migration converge), otherwise keep both.
        for dir_name in [
            d for d in dir_names if d.startswith(LEGACY_DEFAULT_PREFIX)
        ]:
            normalized = strip_legacy_prefixes(dir_name) or "Unnamed"
            prefixed_path = path.join(configs_path, dir_name)
            clean_path = path.join(configs_path, normalized)

            if path.isdir(clean_path) and self._dirs_equal(
                prefixed_path, clean_path
            ):
                archived = self._archive(prefixed_path)
                self.log(
                    f"- '{dir_name}' and '{normalized}' were identical: "
                    f"archived the prefixed copy to '{archived}'"
                )
                default_candidates.append(normalized)
                continue

            target_name = self._unique_name(configs_path, normalized)
            shutil.move(prefixed_path, path.join(configs_path, target_name))
            if target_name != normalized:
                self.log_warning(
                    f"- both '{dir_name}' and '{normalized}' existed (legacy duplication bug). "
                    f"Kept both: '{dir_name}' is now '{target_name}'."
                )
            else:
                self.log(f"- renamed default config '{dir_name}' to '{target_name}'")
            default_candidates.append(target_name)

        # 3) Legacy wingman deletion markers ('.Computer.yaml') in live dirs.
        for dir_name in self._list_config_dirs(configs_path):
            dir_path = path.join(configs_path, dir_name)
            for filename in sorted(os.listdir(dir_path)):
                if not filename.startswith(
                    LEGACY_DELETED_PREFIX
                ) or not filename.endswith(".yaml"):
                    continue
                wingman_name = strip_legacy_prefixes(filename).removesuffix(".yaml")
                if wingman_name and config_manager.has_template_wingman(
                    dir_name, wingman_name
                ):
                    deleted = state.deleted_template_wingmen.setdefault(
                        dir_name, []
                    )
                    if wingman_name not in deleted:
                        deleted.append(wingman_name)
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
        live_dirs = set(self._list_config_dirs(configs_path))
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

        config_manager.write_config(path.join(configs_path, CONTEXT_FILE), state)

        # If this step's directory IS the latest version directory, the
        # ConfigManager booted from it before the migration ran and still
        # caches the pre-conversion state - resync it from the file.
        if path.realpath(configs_path) == path.realpath(
            self.service.latest_config_path
        ):
            config_manager.context_state = config_manager.load_context_state()

        self.log_highlight(
            f"Converted config state: default '{state.default_config}', "
            f"{len(state.deleted_template_configs)} deleted config(s), "
            f"{sum(len(w) for w in state.deleted_template_wingmen.values())} deleted wingman/wingmen."
        )

    # Helpers

    def _load_step_state(self, configs_path: str) -> ConfigContextState:
        """Load the context state already written into this step's directory.

        Starts fresh if there is none (first run) or it is unreadable. A prior
        (crashed and re-run) attempt's tombstones are preserved this way.
        """
        state_path = path.join(configs_path, CONTEXT_FILE)
        if path.exists(state_path):
            parsed = self.config_manager.read_config(state_path)
            if parsed:
                try:
                    return ConfigContextState.model_validate(parsed)
                except ValidationError:
                    self.log_warning(
                        f"- unreadable '{state_path}', converting from scratch"
                    )
        return ConfigContextState()

    @staticmethod
    def _list_config_dirs(configs_path: str) -> list[str]:
        """List directory names in the step's configs dir, sorted for determinism."""
        return sorted(
            (
                name
                for name in os.listdir(configs_path)
                if path.isdir(path.join(configs_path, name))
            ),
            key=str.casefold,
        )

    @staticmethod
    def _dirs_equal(dir_a: str, dir_b: str) -> bool:
        """Whether two directories have identical file trees and contents."""
        cmp = filecmp.dircmp(dir_a, dir_b)
        if cmp.left_only or cmp.right_only or cmp.funny_files:
            return False
        _, mismatch, errors = filecmp.cmpfiles(
            dir_a, dir_b, cmp.common_files, shallow=False
        )
        if mismatch or errors:
            return False
        return all(
            Migration313To314._dirs_equal(
                path.join(dir_a, sub), path.join(dir_b, sub)
            )
            for sub in cmp.common_dirs
        )

    @staticmethod
    def _unique_name(parent: str, base: str, split_ext: bool = False) -> str:
        """First non-colliding 'base', 'base (2)', 'base (3)', ... in parent."""
        candidate = base
        counter = 2
        while path.exists(path.join(parent, candidate)):
            if split_ext:
                stem, ext = path.splitext(base)
                candidate = f"{stem} ({counter}){ext}"
            else:
                candidate = f"{base} ({counter})"
            counter += 1
        return candidate

    def _archive(self, source_path: str, subdir: str = "") -> str:
        """Move a legacy-deleted config dir/file into the (non-versioned)
        archive directory instead of deleting it. Never destroys user data."""
        archive_root = path.join(get_users_dir(), ARCHIVE_SUBDIR, subdir)
        os.makedirs(archive_root, exist_ok=True)

        base = strip_legacy_prefixes(path.basename(source_path)) or "archived"
        candidate = self._unique_name(archive_root, base, split_ext=True)

        target_path = path.join(archive_root, candidate)
        shutil.move(source_path, target_path)
        return target_path
