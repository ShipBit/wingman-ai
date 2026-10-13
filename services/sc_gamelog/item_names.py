"""The in-game name of an item the game logs only by class name and GUID.

Shop lines carry `itemName[Food_burrito_01_a] itemClassGUID[b9867b9a-...]`,
never the name the player sees ("Dak Galbi Chicken Burrito"). data/item_names.json
maps both to the name. It is built per patch from the game's English
localization and item records (Mallachi's build_item_names.py in the SC Log
Reader repository), apart from the reading rules: it is large and changes with
every patch, the rules must stay small enough for every client to download.

An item without an entry gets a tidied class name, never the raw code.
"""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

TABLE = Path(__file__).resolve().parent / "data" / "item_names.json"
_VARIANT = re.compile(r"^(.+?)(?:_\d\d){1,2}$")
_MAX_NAME = 128


@lru_cache(maxsize=1)
def _table() -> tuple[dict, dict, dict]:
    try:
        data = json.loads(TABLE.read_text(encoding="utf-8"))
        by_guid = {str(k).lower(): str(v) for k, v in data.get("by_guid", {}).items()}
        by_class = {str(k).lower(): str(v) for k, v in data.get("by_class", {}).items()}
    except (OSError, ValueError, AttributeError):
        return {}, {}, {}  # No table: tidied class names only.
    # Some keys carry a manufacturer prefix: SASU_<class>. Used only when one does.
    prefixed: dict[str, list[str]] = {}
    for key, name in by_class.items():
        prefix, sep, rest = key.partition("_")
        if sep and rest and prefix.isalpha():
            prefixed.setdefault(rest, []).append(name)
    return by_guid, by_class, prefixed


def lookup(guid: Optional[str], class_name: Optional[str]) -> Optional[str]:
    """The in-game name, or None when the table does not know the item."""
    by_guid, by_class, prefixed = _table()
    if isinstance(guid, str) and guid.lower() in by_guid:
        return by_guid[guid.lower()][:_MAX_NAME]
    if not isinstance(class_name, str) or not class_name:
        return None
    cls = class_name.lower()
    if cls in by_class:
        return by_class[cls][:_MAX_NAME]
    if len(prefixed.get(cls, ())) == 1:
        return prefixed[cls][0][:_MAX_NAME]
    m = _VARIANT.match(cls)
    while m:  # The base item without its colour variant: ..._01_01_07 -> ..._01.
        if m.group(1) in by_class:
            return by_class[m.group(1)][:_MAX_NAME]
        m = _VARIANT.match(m.group(1))
    return None


def tidy(class_name: str) -> str:
    """ESPR_BallisticCannon_Barrel_S3 -> ESPR Ballistic Cannon Barrel S3."""
    words = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", class_name.replace("_", " ")).split()
    return " ".join(w if w.isupper() or not w.isalpha() else w.capitalize() for w in words)[:_MAX_NAME]


def display_name(guid: Optional[str], class_name: Optional[str]) -> Optional[str]:
    """The in-game name, else the tidied class name; None without a class name."""
    name = lookup(guid, class_name)
    if name:
        return name
    return tidy(class_name) if isinstance(class_name, str) and class_name else None
