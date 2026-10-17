"""The bridge between the HUD and the operating system.

The overlay renders on every OS; only a backend touches the OS's windows.
`create_backend()` loads the backend for the OS Core runs on, and
`hud_supported()` tells whether that OS has one. Windows and macOS have
one; Linux is registered but not written yet (see linux.py).

Adding an OS: implement HudBackend (base.py) in its module and set
`supported = True`. Nothing else in the HUD changes.
"""

import importlib
import platform
from typing import Optional

from hud_server.platform.base import (
    Cursor,
    FontSet,
    HudBackend,
    HudPlatformError,
    Monitor,
    OsFamily,
    Pointer,
    PointerHandler,
    UnsupportedBackend,
)

__all__ = [
    "Cursor",
    "FontSet",
    "HudBackend",
    "HudPlatformError",
    "Monitor",
    "OsFamily",
    "Pointer",
    "PointerHandler",
    "UnsupportedBackend",
    "create_backend",
    "current_os",
    "get_backend",
    "hud_supported",
    "unsupported_reason",
]

# Imported only on their own OS: each may load OS libraries at import time
BACKENDS: dict[OsFamily, tuple[str, str]] = {
    OsFamily.WINDOWS: ("hud_server.platform.windows", "WindowsBackend"),
    OsFamily.LINUX: ("hud_server.platform.linux", "LinuxBackend"),
    OsFamily.MACOS: ("hud_server.platform.macos", "MacOsBackend"),
}

_SYSTEMS = {
    "Windows": OsFamily.WINDOWS,
    "Linux": OsFamily.LINUX,
    "Darwin": OsFamily.MACOS,
}

_backend: Optional[HudBackend] = None


def current_os() -> Optional[OsFamily]:
    return _SYSTEMS.get(platform.system())


def create_backend(os_family: Optional[OsFamily] = None) -> HudBackend:
    """A new backend for `os_family` (default: this OS). Never raises: an OS
    without a backend, or one that fails to load, gets an UnsupportedBackend
    that says why."""
    os_family = os_family or current_os()
    if os_family is None:
        return UnsupportedBackend(f"The HUD does not run on {platform.system() or 'this system'}.")
    module_name, class_name = BACKENDS[os_family]
    try:
        return getattr(importlib.import_module(module_name), class_name)()
    except Exception as e:
        return UnsupportedBackend(
            f"The HUD backend for {os_family.value} failed to load: {type(e).__name__}: {e}",
            os_family,
        )


def get_backend() -> HudBackend:
    """This OS's backend, shared, for questions (supported? which monitors?).
    The overlay makes its own with `create_backend()`."""
    global _backend
    if _backend is None:
        _backend = create_backend()
    return _backend


def hud_supported() -> bool:
    return get_backend().supported


def unsupported_reason() -> Optional[str]:
    return get_backend().unsupported_reason
