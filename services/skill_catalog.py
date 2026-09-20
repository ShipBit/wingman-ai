"""SkillCatalog — Core-global, static pre-flight gate for skills.

Scans every available skill manifest ONCE at startup and assigns an eligibility verdict
without instantiating or activating anything. Per-Wingman managers consume the eligible set.
Pure data + dedup; broadcasting is done by WingmanCore.
"""

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from api.interface import SkillConfig
from services.module_manager import ModuleManager
from services.platform_utils import normalize_platform
from services.printr import Printr
from api.enums import LogType

SKILL_API_VERSION = 3
SUPPORTED_SKILL_API_VERSIONS = {3}

printr = Printr()


class SkillVerdict(str, Enum):
    OK = "ok"
    LEGACY = "legacy"      # missing / unsupported api_version
    INVALID = "invalid"    # unreadable manifest or failed import probe


_VERDICT_TO_OUTCOME = {
    SkillVerdict.OK: "ok",
    SkillVerdict.LEGACY: "legacy_v2",
    SkillVerdict.INVALID: "quarantined",
}


def _id_hash(folder: str) -> str:
    return hashlib.sha256(folder.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class SkillCatalogEntry:
    folder: str
    name: Optional[str]
    version: Optional[str]
    origin: str                 # "bundled" | "custom"
    api_version: Optional[int]
    verdict: SkillVerdict
    reason: str
    id_hash: str

    @property
    def outcome(self) -> str:
        return _VERDICT_TO_OUTCOME[self.verdict]


class SkillCatalog:
    """Process-wide singleton (house pattern, like Printr/SecretKeeper)."""

    _instance: "SkillCatalog | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._entries = []
            cls._instance._runtime_outcomes = {}  # id_hash -> dict (deduped)
        return cls._instance

    # ---- scanning ----

    def scan(self) -> list[SkillCatalogEntry]:
        """Scan all available skills and compute verdicts. Idempotent per boot."""
        self._entries = []
        self._runtime_outcomes = {}
        for folder, config_path, is_custom, _is_local in ModuleManager.read_available_skill_configs():
            self._entries.append(self._evaluate(folder, config_path, is_custom))

        ok = [e.folder for e in self._entries if e.verdict == SkillVerdict.OK]
        skipped = [(e.folder, e.verdict.value) for e in self._entries if e.verdict != SkillVerdict.OK]
        printr.print(
            f"SkillCatalog: {len(ok)} eligible, {len(skipped)} skipped {skipped}",
            color=LogType.INFO, server_only=True,
        )
        return self._entries

    def _evaluate(self, folder: str, config_path: str, is_custom: bool) -> SkillCatalogEntry:
        origin = "custom" if is_custom else "bundled"
        h = _id_hash(folder)

        raw = ModuleManager.read_config(config_path)
        if not raw:
            return SkillCatalogEntry(folder, None, None, origin, None,
                                     SkillVerdict.INVALID, "manifest unreadable", h)

        name = raw.get("name")
        version = raw.get("version")
        api_version = raw.get("api_version")

        if api_version is None:
            return SkillCatalogEntry(folder, name, version, origin, None,
                                     SkillVerdict.LEGACY, "missing api_version (pre-v3)", h)
        if api_version not in SUPPORTED_SKILL_API_VERSIONS:
            return SkillCatalogEntry(folder, name, version, origin, api_version,
                                     SkillVerdict.LEGACY, f"unsupported api_version {api_version}", h)

        try:
            config = SkillConfig(**raw)
        except Exception as e:
            return SkillCatalogEntry(folder, name, version, origin, api_version,
                                     SkillVerdict.INVALID, f"invalid manifest: {e}", h)

        if config.platforms and normalize_platform() not in config.platforms:
            return SkillCatalogEntry(folder, name, version, origin, api_version,
                                     SkillVerdict.OK,
                                     f"eligible; import probe skipped (platform {config.platforms})", h)

        try:
            ModuleManager.probe_import(config)
        except Exception as e:
            return SkillCatalogEntry(folder, name, version, origin, api_version,
                                     SkillVerdict.INVALID, f"import probe failed: {e}", h)

        return SkillCatalogEntry(folder, name, version, origin, api_version,
                                 SkillVerdict.OK, "ok", h)

    # ---- consumers ----

    def entries(self) -> list[SkillCatalogEntry]:
        return list(self._entries)

    def eligible_folders(self) -> set[str]:
        return {e.folder for e in self._entries if e.verdict == SkillVerdict.OK}

    def ineligible_skill_names(self) -> set[str]:
        """Skill class names that are NOT eligible (legacy/invalid). Used to auto-disable
        them from Wingman configs. Excludes entries with no name."""
        return {e.name for e in self._entries if e.verdict != SkillVerdict.OK and e.name}

    def ineligible_folders(self) -> set[str]:
        """Skill FOLDER names that are NOT eligible. Needed next to
        ineligible_skill_names() because `discoverable_skills` stores skill names
        while a Wingman's `skills` entries are addressed by module/folder."""
        return {e.folder for e in self._entries if e.verdict != SkillVerdict.OK}

    def is_eligible(self, folder: str) -> bool:
        return folder in self.eligible_folders()

    def entry_for_folder(self, folder: str) -> SkillCatalogEntry | None:
        return next((e for e in self._entries if e.folder == folder), None)

    # ---- per-Wingman runtime failures (deduped by id_hash) ----

    def record_runtime_failure(self, folder: str, error: str) -> dict | None:
        """Called by WingmanSkillManager when an eligible skill crashes at
        instantiate/prepare/activate. Returns the telemetry record the FIRST time
        a given skill fails this boot, else None (deduped)."""
        h = _id_hash(folder)
        if h in self._runtime_outcomes:
            return None
        entry = self.entry_for_folder(folder)
        record = {
            "skill": (entry.name if entry else None) or folder,
            "version": entry.version if entry else None,
            "origin": entry.origin if entry else "custom",
            "outcome": "failed",
            "api_version": entry.api_version if entry else None,
            "id_hash": h,
        }
        self._runtime_outcomes[h] = record
        return record

    def telemetry_records(self) -> list[dict]:
        """Scan verdicts (one per skill) as telemetry records."""
        return [
            {
                "skill": e.name or e.folder,
                "version": e.version,
                "origin": e.origin,
                "outcome": e.outcome,
                "api_version": e.api_version,
                "id_hash": e.id_hash,
            }
            for e in self._entries
        ]

    def drain_runtime_records(self) -> list[dict]:
        """Return + clear recorded runtime-failure records (so WingmanCore broadcasts each once)."""
        records = list(self._runtime_outcomes.values())
        return records
