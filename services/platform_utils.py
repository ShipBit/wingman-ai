"""Shared platform helpers."""

import sys

_PLATFORM_MAP = {"win32": "windows", "darwin": "darwin", "linux": "linux"}


def normalize_platform(platform: str | None = None) -> str:
    """Return a normalized platform name (``windows``/``darwin``/``linux``).

    Falls back to the raw ``sys.platform`` string if no mapping exists.
    """
    raw = platform if platform is not None else sys.platform
    return _PLATFORM_MAP.get(raw, raw)


def drop_other_platform_properties(skill_manifest: dict | None) -> dict | None:
    """A skill's default_config.yaml without the custom properties whose
    `platforms` leave out this system, so the UI never offers them here."""
    if not skill_manifest or not skill_manifest.get("custom_properties"):
        return skill_manifest
    here = normalize_platform()
    skill_manifest["custom_properties"] = [
        prop
        for prop in skill_manifest["custom_properties"]
        if not isinstance(prop, dict) or not prop.get("platforms") or here in prop["platforms"]
    ]
    return skill_manifest
