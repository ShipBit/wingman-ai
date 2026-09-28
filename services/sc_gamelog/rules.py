"""Where the Game.log rules come from, and how they stay current.

Star Citizen changes its log wording every few days, far more often than
Wingman ships. The rules therefore live on GitHub and are maintained there by
the community member who wrote the reader. Core checks for a newer revision at
start and every half hour.

At start the reader takes the higher revision of two copies: the last
download that passed validation (cached in the generated files) and the copy
shipped with this Core release (data/instructions.json). A download replaces
the running rules only when it validates and carries a higher revision. When
GitHub cannot be reached, the reader keeps working with what it has and the
status says so, together with whom to contact.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiohttp

from api.enums import ScGameLogRulesProblem as RulesProblem

from services.sc_gamelog.reader import (
    MAX_PACKAGE_BYTES,
    InstructionError,
    Instructions,
    ReaderUpgradeRequired,
    bundled_bytes,
)

RULES_URL = (
    "https://raw.githubusercontent.com/Diftic/wingman-ai/main/"
    "skills/sc_log_reader/updates/instructions.json"
)
CHECK_INTERVAL_SECONDS = 30 * 60
FETCH_TIMEOUT_SECONDS = 10

# Shown when a rules file names no maintainer of its own.
DEFAULT_MAINTAINER = {
    "name": "Mallachi",
    "url": "https://github.com/Diftic/wingman-ai",
}


@dataclass
class RulesStatus:
    version: str
    revision: int
    source: str
    """"downloaded" or "bundled"."""
    maintainer: dict
    last_check: Optional[float] = None
    """Unix time of the last attempt to reach GitHub."""
    last_success: Optional[float] = None
    """Unix time GitHub last answered with a usable file (or "not modified")."""
    problem: Optional[RulesProblem] = None
    detail: Optional[str] = None


def _write_atomic(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class RulesSource:
    """Holds the running rules and replaces them when GitHub has newer ones."""

    def __init__(self, cache_dir: str, url: str = RULES_URL) -> None:
        self.url = url
        self._cache = Path(cache_dir) / "rules.json"
        self._meta = Path(cache_dir) / "rules.meta.json"
        self.instructions, source = self._load_best()
        self.status = RulesStatus(
            version=str(self.instructions.version),
            revision=self.instructions.revision,
            source=source,
            maintainer=self._maintainer(self.instructions),
        )
        meta = self._read_meta()
        self.status.last_success = meta.get("last_success")
        self._etag: Optional[str] = meta.get("etag") if source == "downloaded" else None

    # --- loading ------------------------------------------------------------

    def _load_best(self) -> tuple[Instructions, str]:
        bundled = Instructions.load(bundled_bytes())
        try:
            cached = Instructions.load(self._cache.read_bytes())
        except (OSError, InstructionError):
            return bundled, "bundled"
        # A Core update can ship newer rules than the last download.
        if cached.revision > bundled.revision:
            return cached, "downloaded"
        return bundled, "bundled"

    def _read_meta(self) -> dict:
        try:
            meta = json.loads(self._meta.read_text(encoding="utf-8"))
            return meta if isinstance(meta, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_meta(self) -> None:
        try:
            _write_atomic(
                self._meta,
                json.dumps(
                    {"etag": self._etag, "last_success": self.status.last_success}
                ).encode(),
            )
        except OSError:
            pass

    @staticmethod
    def _maintainer(instructions: Instructions) -> dict:
        return dict(instructions.data.get("maintainer") or DEFAULT_MAINTAINER)

    # --- checking GitHub ----------------------------------------------------

    async def _fetch(self) -> tuple[int, bytes, Optional[str]]:
        headers = {"Accept": "application/json", "User-Agent": "WingmanAI-SCGameLog"}
        if self._etag:
            headers["If-None-Match"] = self._etag
        timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(self.url, headers=headers, allow_redirects=False) as resp:
                if resp.status != 200:
                    return resp.status, b"", None
                raw = await resp.content.read(MAX_PACKAGE_BYTES + 1)
                return resp.status, raw, resp.headers.get("ETag")

    async def check(self) -> Optional[Instructions]:
        """Ask GitHub for newer rules. Returns them when they should replace
        the running ones, else None. Never raises."""
        self.status.last_check = time.time()
        try:
            status, raw, etag = await self._fetch()
        except (aiohttp.ClientError, TimeoutError, OSError) as error:
            self._problem(RulesProblem.UNREACHABLE, type(error).__name__)
            return None

        if status == 304:
            self._ok()
            return None
        if status != 200:
            self._problem(RulesProblem.UNREACHABLE, f"HTTP {status}")
            return None
        if len(raw) > MAX_PACKAGE_BYTES:
            self._problem(RulesProblem.INVALID, "file is larger than 512 KB")
            return None

        try:
            candidate = Instructions.load(raw)
        except ReaderUpgradeRequired as error:
            self._problem(RulesProblem.NEEDS_UPDATE, str(error))
            return None
        except InstructionError as error:
            self._problem(RulesProblem.INVALID, str(error))
            return None

        self._etag = etag
        self._ok()
        if candidate.revision <= self.instructions.revision:
            return None

        try:
            _write_atomic(self._cache, raw)
        except OSError:
            pass  # Still use it for this run; the next start downloads it again.
        self.instructions = candidate
        self.status.version = str(candidate.version)
        self.status.revision = candidate.revision
        self.status.source = "downloaded"
        self.status.maintainer = self._maintainer(candidate)
        return candidate

    def _ok(self) -> None:
        self.status.last_success = time.time()
        self.status.problem = None
        self.status.detail = None
        self._write_meta()

    def _problem(self, problem: str, detail: str) -> None:
        self.status.problem = problem
        self.status.detail = detail
