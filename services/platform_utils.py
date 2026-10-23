"""Shared platform helpers."""

import sys

_PLATFORM_MAP = {"win32": "windows", "darwin": "darwin", "linux": "linux"}


def normalize_platform(platform: str | None = None) -> str:
    """Return a normalized platform name (``windows``/``darwin``/``linux``).

    Falls back to the raw ``sys.platform`` string if no mapping exists.
    """
    raw = platform if platform is not None else sys.platform
    return _PLATFORM_MAP.get(raw, raw)
