import os
import json
import time
import shutil

from collections import OrderedDict
from pathlib import Path

# Added Union for return type hint, Literal for storage_mode hint
from typing import Any, Tuple, Optional, Dict, Union, Literal

from services.printr import Printr
from wingmen.star_citizen_services.helper import find_best_match


printr = Printr()

# Define the allowed storage modes using Literal for better type hinting
StorageMode = Literal["bytes", "json"]

DEBUG = True


CACHE_DIR = os.path.join("cache_data")


class CacheManager:
    """
    Manages an LRU cache with disk persistence, supporting both raw bytes
    (e.g., audio files) and JSON-serializable objects.

    Stores metadata (path, hits, timestamp, storage_mode) in a JSON file and
    actual data in a separate subdirectory. Includes functionality to remove
    the most recently added entry during the current session.
    """

    def __init__(
        self,
        config,
        app_root_dir: str,
        cache_name: str,
        max_memory_size: int = 100
    ):
        self.cache_name = cache_name
        self.config = config
        self.debug = self.config.get("features", {}).get("debug_mode", False) or DEBUG
        
        self.cache_base_path = os.path.join(
            app_root_dir, CACHE_DIR
        )
        self.cache_metadata_file = Path(self.cache_base_path) / f"{self.cache_name}.json"
        self.cache_data_path = Path(self.cache_base_path) / self.cache_name

        self.max_memory_size = max_memory_size

        self.memory_cache: OrderedDict[str, str] = OrderedDict()
        # Full cache data: key -> [file_path_str, hit_count, last_used_timestamp, storage_mode]
        self.disk_data: Dict[str, Tuple[str, int, float, StorageMode]] = {}
        self._dirty = False
        self._last_added_key: Optional[str] = None
        self._last_key_flagged_for_removal: bool = False

        self.cache_data_path.mkdir(parents=True, exist_ok=True)

        self.load()  # Note: load() does not restore _last_added_key

    def load(self):
        """Loads cache metadata from the JSON file."""
        # Reset last added key on load, as it's session-specific
        self._last_added_key = None
        if not self.cache_metadata_file.exists():
            printr.print(
                f"Cache metadata file not found: {self.cache_metadata_file}. Starting fresh.",
                tags="info",
                console_only=True,
            )
            return

        try:
            with open(self.cache_metadata_file, "r", encoding="utf-8") as f:
                loaded_json = json.load(f)
                self.disk_data = {}
                for k, v in loaded_json.items():
                    if isinstance(v, list) and len(v) == 4:
                        mode = v[3] if v[3] in ("bytes", "json") else "bytes"
                        self.disk_data[k] = (str(v[0]), int(v[1]), float(v[2]), mode)
                    elif isinstance(v, list) and len(v) == 3:
                        printr.print_warn(
                            f"Found old cache format entry for key '{k}'. Assuming 'bytes' storage.",
                            console_only=True,
                        )
                        self.disk_data[k] = (str(v[0]), int(v[1]), float(v[2]), "bytes")
                    else:
                        printr.print_warn(
                            f"Skipping invalid cache metadata entry for key '{k}': {v}",
                            console_only=True,
                        )

                printr.print(
                    f"Loaded {len(self.disk_data)} metadata items from cache: {self.cache_metadata_file}",
                    tags="info",
                    console_only=True,
                )
        except (json.JSONDecodeError, IOError, TypeError, ValueError, IndexError) as e:
            printr.print_err(
                f"Error loading or parsing cache metadata file {self.cache_metadata_file}: {e}. Starting fresh.",
                console_only=True,
            )
            self.disk_data = {}

    def save(self):
        """Saves the cache metadata (including storage_mode) to the JSON file."""
        if not self._dirty:
            return

        try:
            data_to_save = {k: list(v) for k, v in self.disk_data.items()}
            with open(self.cache_metadata_file, "w", encoding="utf-8") as f:
                json.dump(data_to_save, f, indent=4, ensure_ascii=False)
            printr.print(
                f"Saved {len(self.disk_data)} metadata items to cache: {self.cache_metadata_file}",
                tags="info",
                console_only=True,
            )
            self._dirty = False
        except IOError as e:
            printr.print_err(
                f"Error saving cache metadata file {self.cache_metadata_file}: {e}",
                console_only=True,
            )

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieves data associated with a key. Reads raw bytes or parses JSON
        based on the stored storage_mode. Updates the timestamp on access.
        Returns bytes, a deserialized JSON object, or None if not found/error.
        """
        file_path_str = None
        storage_mode: Optional[StorageMode] = None

        # 1. Check memory cache
        if key in self.memory_cache:
            if key in self.disk_data:
                self.memory_cache.move_to_end(key)
                file_path_str = self.memory_cache[key]
                _, _, _, storage_mode = self.disk_data[key]
            else:
                printr.print_warn(
                    f"Cache inconsistency: Key '{key}' in memory but not disk. Removing memory entry."
                )
                del self.memory_cache[key]
                return None

        # 2. Check disk data
        elif key in self.disk_data:
            file_path_str, _, _, storage_mode = self.disk_data[key]
            self.memory_cache[key] = file_path_str
            self.memory_cache.move_to_end(key)
            if len(self.memory_cache) > self.max_memory_size:
                self.memory_cache.popitem(last=False)

        # 3. Read data if path and mode found
        if file_path_str and storage_mode:
            file_path = Path(file_path_str)
            if file_path.exists():
                try:
                    data: Optional[Any] = None
                    if storage_mode == "bytes":
                        with open(file_path, "rb") as f:
                            data = f.read()
                    elif storage_mode == "json":
                        with open(file_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    else:
                        printr.print_err(
                            f"Unknown storage mode '{storage_mode}' for key '{key}'. Removing."
                        )
                        self._remove_entry(key)
                        return None

                    self._update_metadata(
                        key
                    )  # Update hits/timestamp on successful get
                    return data

                except (json.JSONDecodeError, IOError, Exception) as e:
                    printr.print_err(
                        f"Error reading/decoding cache file {file_path} for key '{key}': {e}. Removing."
                    )
                    self._remove_entry(key)
                    return None
            else:
                printr.print_warn(
                    f"Cache file not found for key '{key}' at {file_path_str}. Removing metadata."
                )
                self._remove_entry(key)  # Remove metadata if file is missing
                return None

        # 4. Not found
        return None

    def put(
        self,
        key: str,
        data: Any,
        storage_mode: StorageMode,
        file_extension: Optional[str] = None,
        flag_for_removal: bool = False,
    ):
        """
        Adds or updates an item in the cache, storing it either as raw bytes
        or as a JSON file based on storage_mode.

        Args:
            key: The cache key.
            data: The data to store (bytes if storage_mode='bytes',
                  JSON-serializable object if storage_mode='json').
            storage_mode: How to store the data ('bytes' or 'json').
            file_extension: Optional file extension (defaults to .bin or .json).
        """
        if not key or not data or not storage_mode:
            printr.print_err(
                f"Invalid arguments for put: key='{key}', data='{data}', storage_mode='{storage_mode}'"
            )
            return
        
        timestamp = time.time()
        hit_count = 1
        if storage_mode not in ("bytes", "json"):
            raise ValueError(
                f"Invalid storage_mode: '{storage_mode}'. Must be 'bytes' or 'json'."
            )

        if file_extension is None:
            file_extension = ".bin" if storage_mode == "bytes" else ".json"
        elif not file_extension.startswith("."):
            file_extension = "." + file_extension

        # Using key directly as filename base. Consider sanitizing or hashing if keys can contain problematic chars.
        filename = key + file_extension
        file_path = self.cache_data_path / filename
        file_path_str = str(file_path)

        if self._last_key_flagged_for_removal:
            # the previous key was flagged for removal, so we need to remove it first, before adding the new one
            self.remove_last_added_entry()
            self._last_key_flagged_for_removal = False

        # Write data
        try:
            if storage_mode == "bytes":
                if not isinstance(data, bytes):
                    raise TypeError(
                        f"Data must be bytes for storage_mode 'bytes', got {type(data).__name__}"
                    )
                with open(file_path, "wb") as f:
                    f.write(data)
            elif storage_mode == "json":
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)

        except (TypeError, IOError, Exception) as e:
            printr.print_err(
                f"Error writing cache file {file_path} for key '{key}' (mode: {storage_mode}): {e}"
            )
            # Attempt cleanup if file was partially written or exists from before
            try:
                file_path.unlink(missing_ok=True)
            except OSError:
                pass
            # --- IMPORTANT: Do not update metadata or last_added_key if write failed ---
            return

        # Update metadata
        self.disk_data[key] = (file_path_str, hit_count, timestamp, storage_mode)

        # Update memory cache
        self.memory_cache[key] = file_path_str
        self.memory_cache.move_to_end(key)
        if len(self.memory_cache) > self.max_memory_size:
            self.memory_cache.popitem(last=False)

        self._dirty = True
        self._last_added_key = key
        self._last_key_flagged_for_removal = flag_for_removal
        
    def _update_metadata(self, key: str):
        """Internal: Updates hit count and timestamp for an existing key."""
        if key in self.disk_data:
            file_path_str, hit_count, _, storage_mode = self.disk_data[key]
            self.disk_data[key] = (
                file_path_str,
                hit_count + 1,
                time.time(),  # Update timestamp on access
                storage_mode,
            )
            self._dirty = True

    def _remove_entry(self, key: str):
        """Internal: Removes an entry from memory, disk metadata, and the data file."""
        removed_from_memory = False
        removed_from_disk = False
        file_path_str = None

        # Retrieve path before deleting metadata
        if key in self.disk_data:
            file_path_str, _, _, _ = self.disk_data[key]
            del self.disk_data[key]
            removed_from_disk = True
            self._dirty = True  # Mark dirty only if disk metadata changed

        if key in self.memory_cache:
            del self.memory_cache[key]
            removed_from_memory = True

        # Delete the associated data file if we found its path
        if file_path_str:
            try:
                Path(file_path_str).unlink(missing_ok=True)
            except OSError as e:
                printr.print_err(f"Error deleting cache file {file_path_str}: {e}")

        if key == self._last_added_key:
            self._last_added_key = None

        if self.debug and (removed_from_memory or removed_from_disk):
            printr.print(f"Removed cache entry for key '{key}' (Memory: {removed_from_memory}, Disk: {removed_from_disk})", tags="info", console_only=True)

    def remove_last_added_entry(self) -> Optional[str]:
        """
        Removes the most recently added cache entry (based on the last `put`
        call in the current session).

        Returns:
            The key of the removed entry, or None if no entry has been added
            in this session yet or the last added entry was already removed.
        """
        if self._last_added_key is None:
            printr.print(
                "No 'last added entry' tracked in this session to remove.",
                tags="info",
                console_only=True,
            )
            return None

        key_to_remove = self._last_added_key
        printr.print(
            f"Removing last added cache entry: Key='{key_to_remove}'",
            tags="info",
            console_only=True,
        )

        # Important: Reset _last_added_key *before* calling _remove_entry.
        # This prevents issues if _remove_entry fails partially or if called again.
        # _remove_entry will also set it to None if it succeeds, but doing it here is safer.
        self._last_added_key = None

        try:
            self._remove_entry(key_to_remove)
            return key_to_remove
        except Exception as e:
            # Should be unlikely if _remove_entry handles its errors, but just in case.
            printr.print_err(
                f"An unexpected error occurred during the removal of last added entry '{key_to_remove}': {e}"
            )
            # _last_added_key is already None, so state is relatively safe.
            return None  # Indicate failure

    # Method to remove the oldest entry (based on timestamp) - kept for reference or potential use
    def remove_oldest_entry(self) -> Optional[str]:
        """
        Finds and removes the least recently used (oldest timestamp) entry
        from the cache (memory, disk metadata, and data file).
        """
        if not self.disk_data:
            printr.print(
                "Cache is empty, cannot remove oldest entry.",
                tags="info",
                console_only=True,
            )
            return None

        oldest_key: Optional[str] = None
        try:
            oldest_key = min(self.disk_data, key=lambda k: self.disk_data[k][2])
            timestamp = self.disk_data[oldest_key][2]
            printr.print(
                f"Removing oldest cache entry: Key='{oldest_key}', Timestamp={timestamp}",
                tags="info",
                console_only=True,
            )
            self._remove_entry(oldest_key)
            return oldest_key
        except Exception as e:
            printr.print_err(f"Error removing oldest cache entry: {e}")
            return None

    def clear(self):
        """Clears the cache (memory, metadata file, and data directory)."""
        self.memory_cache.clear()
        self.disk_data = {}
        self._dirty = False
        # --- NEW: Reset last added key on clear ---
        self._last_added_key = None
        # --- END NEW ---

        try:
            self.cache_metadata_file.unlink(missing_ok=True)
        except OSError as e:
            printr.print_err(
                f"Error deleting cache metadata file {self.cache_metadata_file}: {e}"
            )

        try:
            if self.cache_data_path.exists():
                shutil.rmtree(self.cache_data_path)
                printr.print(
                    f"Cleared cache, deleted metadata file, and data directory: {self.cache_data_path}",
                    tags="info",
                )
                self.cache_data_path.mkdir(exist_ok=True)  # Recreate dir
        except OSError as e:
            printr.print_err(
                f"Error deleting cache data directory {self.cache_data_path}: {e}"
            )

    def get_stats(self) -> dict:
        """Returns basic statistics about the cache."""
        # ... (get_stats remains the same as the previous version) ...
        sorted_hits = sorted(
            self.disk_data.items(), key=lambda item: item[1][1], reverse=True
        )
        top_hits = [(k, v[1], v[3]) for k, v in sorted_hits[:10]]

        total_size_bytes = 0
        item_count = 0
        try:
            for file_path_str, _, _, _ in self.disk_data.values():
                p = Path(file_path_str)
                if p.is_file():
                    total_size_bytes += p.stat().st_size
                    item_count += 1
                elif p.exists():
                    printr.print_warn(
                        f"Cache item path exists but is not a file: {p}",
                        console_only=True,
                    )
        except Exception as e:
            printr.print_warn(
                f"Could not calculate total cache data size accurately: {e}"
            )
            total_size_bytes = -1

        return {
            "metadata_file_path": str(self.cache_metadata_file),
            "cache_data_path": str(self.cache_data_path),
            "max_memory_size": self.max_memory_size,
            "current_memory_size": len(self.memory_cache),
            "total_disk_items_metadata": len(self.disk_data),
            "actual_data_files_found": item_count,
            "total_data_size_mb": (
                round(total_size_bytes / (1024 * 1024), 2)
                if total_size_bytes >= 0
                else "N/A"
            ),
            "top_10_by_hits": top_hits,
            # --- NEW: Add last added key info to stats ---
            "last_added_key_in_session": self._last_added_key,
            # --- END NEW ---
        }


# --- END OF FILE cache_manager.py ---
