"""
SC_Accountant - Commodity GUID Resolver

Maps Star Citizen commodity resource GUIDs to human-readable names.
The game log only exposes GUIDs for commodity trades; this module
provides a lookup table and persistent cache.

The built-in table lives in a local JSON file (``data/commodity_guid_map.json``)
rather than in code, so verified GUIDs can be added without a code change.
It is intentionally independent of market data; commodity naming must not
depend on the market feature being enabled.

Author: Mallachi
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from atomic_io import atomic_write_text

logger = logging.getLogger(__name__)

_DEFAULT_BUILTIN_MAP_PATH = Path(__file__).parent / "data" / "commodity_guid_map.json"


def _load_builtin_map(path: Path) -> dict[str, str]:
    """Load the bundled GUID-to-name reference table from disk.

    Returns an empty mapping if the file is missing or malformed, so lookup
    failures degrade to the truncated-GUID fallback instead of crashing.
    """
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning("Built-in GUID map at %s is not a JSON object", path)
            return {}
        return {str(k): str(v) for k, v in data.items()}
    except (OSError, json.JSONDecodeError):
        logger.exception("Failed to load built-in GUID map from %s", path)
        return {}


class GuidResolver:
    """Resolves commodity resource GUIDs to human-readable names.

    Combines a local built-in reference table with a persistent user cache
    that grows as new mappings are discovered (e.g. added manually after
    seeing an "Unknown" entry in the ledger).
    """

    def __init__(
        self,
        cache_path: Path,
        builtin_map_path: Path | None = None,
    ) -> None:
        self._cache_path = cache_path
        self._cache: dict[str, str] = {}
        self._builtin_map = _load_builtin_map(
            builtin_map_path or _DEFAULT_BUILTIN_MAP_PATH
        )
        self._logged_unknown: set[str] = set()
        self._load_cache()

    def resolve(self, guid: str) -> str:
        """Resolve a GUID to a human-readable name.

        Args:
            guid: The resource GUID from the game log.

        Returns:
            Human-readable commodity name, or a truncated GUID if unknown.
        """
        if not guid:
            return "Unknown"

        # Check user cache first (may contain corrections)
        if guid in self._cache:
            return self._cache[guid]

        # Check built-in reference table
        if guid in self._builtin_map:
            return self._builtin_map[guid]

        # Unknown: log once for later mapping, then return a truncated GUID
        if guid not in self._logged_unknown:
            self._logged_unknown.add(guid)
            logger.warning("GuidResolver: unknown commodity GUID '%s'", guid)

        short = guid[:8] if len(guid) > 8 else guid
        return f"Unknown ({short}...)"

    def add_mapping(self, guid: str, name: str) -> None:
        """Add or update a GUID-to-name mapping in the persistent cache."""
        if not guid or not name:
            return
        self._cache[guid] = name
        self._logged_unknown.discard(guid)
        self._save_cache()

    def add_mappings(self, mappings: dict[str, str]) -> None:
        """Bulk-add GUID-to-name mappings."""
        if not mappings:
            return
        self._cache.update(mappings)
        self._logged_unknown.difference_update(mappings.keys())
        self._save_cache()

    def get_all_mappings(self) -> dict[str, str]:
        """Return the combined mapping table (built-in + cache)."""
        combined = dict(self._builtin_map)
        combined.update(self._cache)
        return combined

    def get_unknown_guids(self) -> set[str]:
        """Return GUIDs seen this session that resolved to no known name."""
        return set(self._logged_unknown)

    def _load_cache(self) -> None:
        """Load the persistent GUID cache from disk."""
        if not self._cache_path.exists():
            return
        try:
            with open(self._cache_path, "r", encoding="utf-8") as f:
                self._cache = json.load(f)
            logger.info("Loaded %d GUID mappings from cache", len(self._cache))
        except (OSError, json.JSONDecodeError):
            logger.exception("Failed to load GUID cache from %s", self._cache_path)
            self._cache = {}

    def _save_cache(self) -> None:
        """Persist the GUID cache to disk."""
        try:
            atomic_write_text(self._cache_path, json.dumps(self._cache, indent=2))
        except OSError:
            logger.exception("Failed to save GUID cache to %s", self._cache_path)
