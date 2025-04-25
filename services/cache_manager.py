# --- START OF FILE cache_manager.py ---

import json
import os
import time
import hashlib
import shutil
import pickle  # Keep pickle for potential future use or complex non-JSON objects? Maybe remove for now. Let's remove it to be clear.
from collections import OrderedDict
from pathlib import Path

# Added Union for return type hint, Literal for storage_mode hint
from typing import Any, Tuple, Optional, Dict, Union, Literal

from services.printr import Printr


printr = Printr()

# Define the allowed storage modes using Literal for better type hinting
StorageMode = Literal["bytes", "json"]

DEBUG = True


class CacheManager:
    """
    Manages an LRU cache with disk persistence, supporting both raw bytes
    (e.g., audio files) and JSON-serializable objects.

    Stores metadata (path, hits, timestamp, storage_mode) in a JSON file and
    actual data in a separate subdirectory.
    """

    def __init__(
        self,
        cache_file_path: str,
        max_memory_size: int = 100,
        data_subdir: str = "data",
    ):
        self.cache_file_path = Path(cache_file_path)
        self.max_memory_size = max_memory_size
        self.data_dir = self.cache_file_path.parent / data_subdir
        self.memory_cache: OrderedDict[str, str] = OrderedDict()
        # Full cache data: key -> [file_path_str, hit_count, last_used_timestamp, storage_mode]
        self.disk_data: Dict[str, Tuple[str, int, float, StorageMode]] = {}
        self._dirty = False

        self.cache_file_path.parent.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(exist_ok=True)

        self.load()

    def load(self):
        """Loads cache metadata from the JSON file."""
        if not self.cache_file_path.exists():
            printr.print(
                f"Cache metadata file not found: {self.cache_file_path}. Starting fresh.",
                tags="info",
                console_only=True,
            )
            return

        try:
            with open(self.cache_file_path, "r", encoding="utf-8") as f:
                loaded_json = json.load(f)
                self.disk_data = {}
                for k, v in loaded_json.items():
                    if isinstance(v, list) and len(v) == 4:
                        # New format: [path_str, hits, ts, mode]
                        # Ensure mode is valid
                        mode = (
                            v[3] if v[3] in ("bytes", "json") else "bytes"
                        )  # Default to bytes if invalid mode found
                        self.disk_data[k] = (str(v[0]), int(v[1]), float(v[2]), mode)
                    elif isinstance(v, list) and len(v) == 3:
                        # Older format (backward compatibility): [path_str, hits, ts]
                        # Assume 'bytes' mode for older entries
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
                    f"Loaded {len(self.disk_data)} metadata items from cache: {self.cache_file_path}",
                    tags="info",
                    console_only=True,
                )
        except (json.JSONDecodeError, IOError, TypeError, ValueError, IndexError) as e:
            printr.print_err(
                f"Error loading or parsing cache metadata file {self.cache_file_path}: {e}. Starting fresh.",
                console_only=True,
            )
            self.disk_data = {}  # Reset on error

    def save(self):
        """Saves the cache metadata (including storage_mode) to the JSON file."""
        if not self._dirty:
            return

        try:
            # Convert tuples to lists for JSON compatibility
            data_to_save = {k: list(v) for k, v in self.disk_data.items()}
            with open(self.cache_file_path, "w", encoding="utf-8") as f:
                json.dump(data_to_save, f, indent=4, ensure_ascii=False)
            printr.print(
                f"Saved {len(self.disk_data)} metadata items to cache: {self.cache_file_path}",
                tags="info",
                console_only=True,
            )
            self._dirty = False
        except IOError as e:
            printr.print_err(
                f"Error saving cache metadata file {self.cache_file_path}: {e}",
                console_only=True,
            )

    # Return type can be bytes or Any (from JSON), so Union[bytes, Any] or just Any
    def get(self, key: str) -> Optional[Any]:
        """
        Retrieves data associated with a key. Reads raw bytes or parses JSON
        based on the stored storage_mode.
        Returns bytes, a deserialized JSON object, or None if not found/error.
        """
        file_path_str = None
        storage_mode: Optional[StorageMode] = None

        # 1. Check memory cache (only stores path, need disk_data for mode)
        if key in self.memory_cache:
            if key in self.disk_data:
                self.memory_cache.move_to_end(key)
                file_path_str = self.memory_cache[key]
                # Retrieve storage mode from disk_data
                _, _, _, storage_mode = self.disk_data[key]
                # print(f"Cache hit (memory): {key} -> {file_path_str} (mode: {storage_mode})") # Debug
            else:
                # Inconsistency: key in memory but not in disk_data. Remove from memory.
                printr.print_warn(
                    f"Cache inconsistency: Key '{key}' found in memory but not in disk metadata. Removing memory entry."
                )
                del self.memory_cache[key]
                return None

        # 2. Check disk data (if not in memory)
        elif key in self.disk_data:
            file_path_str, _, _, storage_mode = self.disk_data[key]
            # Add to memory cache
            self.memory_cache[key] = file_path_str
            self.memory_cache.move_to_end(key)
            # Evict oldest if memory cache exceeds max size
            if len(self.memory_cache) > self.max_memory_size:
                self.memory_cache.popitem(last=False)
            # print(f"Cache hit (disk -> memory): {key} -> {file_path_str} (mode: {storage_mode})") # Debug

        # 3. If a file path and mode were found
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
                        # Should not happen if load/put logic is correct
                        printr.print_err(
                            f"Unknown storage mode '{storage_mode}' found for key '{key}'. Removing entry."
                        )
                        self._remove_entry(key)
                        return None

                    self._update_metadata(key)  # Update hits/timestamp
                    return data

                except json.JSONDecodeError as e:
                    printr.print_err(
                        f"Error decoding JSON cache file {file_path} for key '{key}': {e}. Removing entry."
                    )
                    self._remove_entry(key)
                    return None
                except IOError as e:
                    printr.print_err(f"Error reading cache data file {file_path}: {e}")
                    self._remove_entry(key)  # Remove inconsistent entry
                    return None
                except Exception as e:  # Catch unexpected errors during read/decode
                    printr.print_err(
                        f"Unexpected error processing cache file {file_path} for key '{key}': {e}. Removing entry."
                    )
                    self._remove_entry(key)
                    return None
            else:
                # Metadata points to a non-existent file
                printr.print_warn(
                    f"Cache metadata inconsistency: File not found for key '{key}' at {file_path_str}. Removing entry."
                )
                self._remove_entry(key)
                return None

        # 4. Not found
        # printr.print(f"Cache miss: {key}", tags="grey", console_only=True)
        return None

    # Added storage_mode parameter
    def put(
        self,
        key: str,
        data: Any,
        storage_mode: StorageMode,
        file_extension: Optional[str] = None,
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
        timestamp = time.time()
        hit_count = 1  # Start with 1 hit

        # Validate storage mode
        if storage_mode not in ("bytes", "json"):
            raise ValueError(
                f"Invalid storage_mode: '{storage_mode}'. Must be 'bytes' or 'json'."
            )

        # Determine default file extension if not provided
        if file_extension is None:
            file_extension = ".bin" if storage_mode == "bytes" else ".json"
        elif not file_extension.startswith("."):
            file_extension = "." + file_extension  # Ensure leading dot

        # Determine file path
        # Consider hashing the key if it contains invalid filesystem characters:
        # safe_key = hashlib.sha256(key.encode()).hexdigest()
        # filename = safe_key + file_extension
        filename = key + file_extension  # Using key directly for now
        file_path = self.data_dir / filename
        file_path_str = str(file_path)

        # Write data to file based on mode
        try:
            if storage_mode == "bytes":
                if not isinstance(data, bytes):
                    raise TypeError(
                        f"Data must be bytes when storage_mode is 'bytes', got {type(data).__name__}"
                    )
                with open(file_path, "wb") as f:
                    f.write(data)
            elif storage_mode == "json":
                # Try serializing before opening file to catch errors early (optional)
                # json.dumps(data) # This would check serializability but is inefficient
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(
                        data, f, ensure_ascii=False, indent=4
                    )  # Use indent for readability

        except (
            TypeError
        ) as e:  # Catches JSON serialization errors or wrong type for bytes
            printr.print_err(
                f"Error preparing data for cache key '{key}' (mode: {storage_mode}): {e}"
            )
            return  # Don't update cache if data is invalid for the mode
        except IOError as e:
            printr.print_err(f"Error writing cache data file {file_path}: {e}")
            # Attempt cleanup
            try:
                file_path.unlink(missing_ok=True)
            except OSError:
                pass
            return  # Don't update cache if file write fails
        except Exception as e:  # Catch unexpected errors
            printr.print_err(
                f"Unexpected error writing cache file {file_path} for key '{key}': {e}"
            )
            return

        # Update/add to full disk data (metadata including storage_mode)
        self.disk_data[key] = (file_path_str, hit_count, timestamp, storage_mode)

        # Update/add to memory cache (key -> path)
        self.memory_cache[key] = file_path_str
        self.memory_cache.move_to_end(key)

        # Evict oldest from memory if exceeds max size
        if len(self.memory_cache) > self.max_memory_size:
            self.memory_cache.popitem(last=False)

        self._dirty = True  # Mark metadata as needing save

    def _update_metadata(self, key: str):
        """Updates hit count and timestamp for a key, preserving storage_mode."""
        if key in self.disk_data:
            file_path_str, hit_count, _, storage_mode = self.disk_data[key]
            self.disk_data[key] = (
                file_path_str,
                hit_count + 1,
                time.time(),
                storage_mode,
            )
            self._dirty = True

    def _remove_entry(self, key: str):
        """Removes an entry from memory, disk metadata, and the data file."""
        if key in self.memory_cache:
            del self.memory_cache[key]
        if key in self.disk_data:
            file_path_str, _, _, _ = self.disk_data[key]
            # Delete the associated data file
            try:
                Path(file_path_str).unlink(missing_ok=True)
            except OSError as e:
                printr.print_err(f"Error deleting cache file {file_path_str}: {e}")
            # Delete metadata entry
            del self.disk_data[key]
            self._dirty = True

    def clear(self):
        """Clears the cache (memory, metadata file, and data directory)."""
        self.memory_cache.clear()
        self.disk_data = {}
        self._dirty = False

        try:
            self.cache_file_path.unlink(missing_ok=True)
        except OSError as e:
            printr.print_err(
                f"Error deleting cache metadata file {self.cache_file_path}: {e}"
            )

        try:
            if self.data_dir.exists():
                shutil.rmtree(self.data_dir)
                printr.print(
                    f"Cleared cache, deleted metadata file, and data directory: {self.data_dir}",
                    tags="info",
                )
                # Recreate the data directory
                self.data_dir.mkdir(exist_ok=True)
        except OSError as e:
            printr.print_err(
                f"Error deleting cache data directory {self.data_dir}: {e}"
            )

    def get_stats(self) -> dict:
        """Returns basic statistics about the cache."""
        sorted_hits = sorted(
            self.disk_data.items(), key=lambda item: item[1][1], reverse=True
        )
        # Include storage mode in top hits display
        top_hits = [
            (k, v[1], v[3]) for k, v in sorted_hits[:10]
        ]  # Top 10: key, hits, mode

        total_size_bytes = 0
        try:
            # Use Path objects directly from disk_data values if possible
            # Or iterate keys and construct paths
            for file_path_str, _, _, _ in self.disk_data.values():
                p = Path(file_path_str)
                if p.exists():
                    total_size_bytes += p.stat().st_size
        except Exception as e:
            printr.print_warn(f"Could not calculate total cache data size: {e}")
            total_size_bytes = -1

        return {
            "metadata_file_path": str(self.cache_file_path),
            "data_directory": str(self.data_dir),
            "max_memory_size": self.max_memory_size,
            "current_memory_size": len(self.memory_cache),
            "total_disk_items": len(self.disk_data),
            "total_data_size_mb": (
                round(total_size_bytes / (1024 * 1024), 2)
                if total_size_bytes >= 0
                else "N/A"
            ),
            "top_10_by_hits": top_hits,  # Now includes mode
        }


# --- END OF FILE cache_manager.py ---
