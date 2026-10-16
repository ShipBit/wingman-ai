"""The in-game name of an item the game logs only by class name and GUID.

Shop lines carry `itemName[Food_burrito_01_a] itemClassGUID[b9867b9a-...]`,
never the name the player sees ("Dak Galbi Chicken Burrito"). The item-name
table maps both to the name. It is built per patch from the game's English
localization and item records (Mallachi's build_item_names.py in the SC Log
Reader repository).

Names change with every patch, far more often than Wingman ships, so the table
stays current the way the reading rules do (rules.py): Core starts with the
higher revision of the copy it ships (data/item_names.json) and the last valid
download, and checks GitHub with the rules. A download replaces the running
table only when it validates and carries a higher revision. It is a file of its
own: the rules must stay small, and an older Core must never meet a key it
rejects.

An item without an entry gets a tidied class name, never the raw code.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

import aiohttp

from services.sc_gamelog.rules import FETCH_TIMEOUT_SECONDS, _write_atomic

NAMES_URL = (
    "https://raw.githubusercontent.com/Diftic/wingman-ai/main/"
    "skills/sc_log_reader/updates/item_names.json"
)
TABLE = Path(__file__).resolve().parent / "data" / "item_names.json"
MAX_TABLE_BYTES = 4 * 1024 * 1024
MAX_ENTRIES = 100_000
_VARIANT = re.compile(r"^(.+?)(?:_\d\d){1,2}$")
_MAX_NAME = 128
# Ship components are sold under their class with "_SCItem" appended. The
# table can list more suffixes; this one stays even when it does not.
_DEFAULT_SUFFIXES = ("_scitem",)


class TableError(ValueError):
    pass


class _Table:
    def __init__(self, data: dict) -> None:
        if not isinstance(data, dict) or data.get("format_version") != 1:
            raise TableError("unknown table format")
        revision = data.get("revision", 0)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise TableError("invalid revision")
        self.revision = revision
        maps = []
        for key in ("by_guid", "by_class"):
            entries = data.get(key, {})
            if not isinstance(entries, dict) or len(entries) > MAX_ENTRIES:
                raise TableError(f"invalid {key}")
            if not all(isinstance(k, str) and isinstance(v, str) and v for k, v in entries.items()):
                raise TableError(f"invalid {key} entry")
            maps.append({k.lower(): v[:_MAX_NAME] for k, v in entries.items()})
        self.by_guid, self.by_class = maps
        suffixes = data.get("strip_suffixes", [])
        if (
            not isinstance(suffixes, list)
            or len(suffixes) > 16
            or not all(isinstance(s, str) and 0 < len(s) <= 32 for s in suffixes)
        ):
            raise TableError("invalid strip_suffixes")
        self.suffixes = tuple(dict.fromkeys(_DEFAULT_SUFFIXES + tuple(s.lower() for s in suffixes)))
        # Some keys carry a manufacturer prefix: SASU_<class>. Used only when one does.
        self.prefixed: dict[str, list[str]] = {}
        for key, name in self.by_class.items():
            prefix, sep, rest = key.partition("_")
            if sep and rest and prefix.isalpha():
                self.prefixed.setdefault(rest, []).append(name)

    @classmethod
    def load(cls, raw: bytes) -> "_Table":
        if len(raw) > MAX_TABLE_BYTES:
            raise TableError("table is larger than 4 MB")
        try:
            return cls(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, ValueError) as error:
            if isinstance(error, TableError):
                raise
            raise TableError("not JSON") from error


_EMPTY = _Table({"format_version": 1})
_current: Optional[_Table] = None


def _active() -> _Table:
    global _current
    if _current is None:
        try:
            _current = _Table.load(TABLE.read_bytes())
        except (OSError, TableError):
            _current = _EMPTY  # No table: tidied class names only.
    return _current


def _strip(cls: str, table: _Table) -> str:
    for suffix in table.suffixes:
        if cls.endswith(suffix) and len(cls) > len(suffix):
            return cls[: -len(suffix)]
    return cls


def lookup(guid: Optional[str], class_name: Optional[str]) -> Optional[str]:
    """The in-game name, or None when the table does not know the item."""
    table = _active()
    if isinstance(guid, str) and guid.lower() in table.by_guid:
        return table.by_guid[guid.lower()]
    if not isinstance(class_name, str) or not class_name:
        return None
    cls = _strip(class_name.lower(), table)
    if cls in table.by_class:
        return table.by_class[cls]
    if len(table.prefixed.get(cls, ())) == 1:
        return table.prefixed[cls][0]
    m = _VARIANT.match(cls)
    while m:  # The base item without its colour variant: ..._01_01_07 -> ..._01.
        if m.group(1) in table.by_class:
            return table.by_class[m.group(1)]
        m = _VARIANT.match(m.group(1))
    return None


def tidy(class_name: str) -> str:
    """ESPR_BallisticCannon_Barrel_S3 -> ESPR Ballistic Cannon Barrel S3."""
    cls = class_name[: len(_strip(class_name.lower(), _active()))]
    words = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", cls.replace("_", " ")).split()
    return " ".join(w if w.isupper() or not w.isalpha() else w.capitalize() for w in words)[:_MAX_NAME]


def display_name(guid: Optional[str], class_name: Optional[str]) -> Optional[str]:
    """The in-game name, else the tidied class name; None without a class name."""
    name = lookup(guid, class_name)
    if name:
        return name
    return tidy(class_name) if isinstance(class_name, str) and class_name else None


class ItemNamesSource:
    """Holds the running table and replaces it when GitHub has a newer one."""

    def __init__(self, cache_dir: str, url: str = NAMES_URL) -> None:
        global _current
        self.url = url
        self._cache = Path(cache_dir) / "item_names.json"
        self._etag: Optional[str] = None
        self.last_check: Optional[float] = None
        self.problem: Optional[str] = None
        try:
            bundled = _Table.load(TABLE.read_bytes())
        except (OSError, TableError):
            bundled = _EMPTY
        try:
            cached = _Table.load(self._cache.read_bytes())
        except (OSError, TableError):
            cached = None
        # A Core update can ship a newer table than the last download.
        _current = cached if cached and cached.revision > bundled.revision else bundled

    @property
    def revision(self) -> int:
        return _active().revision

    async def _fetch(self) -> tuple[int, bytes, Optional[str]]:
        headers = {"Accept": "application/json", "User-Agent": "WingmanAI-SCGameLog"}
        if self._etag:
            headers["If-None-Match"] = self._etag
        timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(self.url, headers=headers, allow_redirects=False) as resp:
                if resp.status != 200:
                    return resp.status, b"", None
                chunks, size = [], 0
                while size <= MAX_TABLE_BYTES:
                    chunk = await resp.content.readany()
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                return resp.status, b"".join(chunks)[: MAX_TABLE_BYTES + 1], resp.headers.get("ETag")

    async def check(self) -> bool:
        """Ask GitHub for a newer table. True when it replaced the running one.
        Never raises: without it, the names are just as current as before."""
        global _current
        self.last_check = time.time()
        try:
            status, raw, etag = await self._fetch()
        except (aiohttp.ClientError, TimeoutError, OSError) as error:
            self.problem = type(error).__name__
            return False
        if status == 304:
            self.problem = None
            return False
        if status != 200:
            self.problem = f"HTTP {status}"
            return False
        try:
            candidate = _Table.load(raw)
        except TableError as error:
            self.problem = str(error)
            return False
        self._etag, self.problem = etag, None
        if candidate.revision <= _active().revision:
            return False
        try:
            _write_atomic(self._cache, raw)
        except OSError:
            pass  # Still use it for this run; the next start downloads it again.
        _current = candidate
        return True
