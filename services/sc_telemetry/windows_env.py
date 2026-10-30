"""The switch in the game: the Windows user environment variable GRPC_CLIENT_SERVER_ENABLED.

Star Citizen inherits it from the RSI Launcher, which reads the user environment when it starts. A change only takes
effect after the launcher is quit completely (tray too) and started again.

Only Windows. On Linux (the game under Wine or Proton, through Lutris or Steam) Wingman cannot see or set the
environment the game starts with: `MANAGED` is False, `is_set()` returns None and the client tells the user to add the
variable to their launcher. Everything else about telemetry has no OS code.
"""
from __future__ import annotations

import platform

VARIABLE = "GRPC_CLIENT_SERVER_ENABLED"
VALUE = "true"
_ENV_KEY = "Environment"
_HWND_BROADCAST = 0xFFFF
_WM_SETTINGCHANGE = 0x001A
_SMTO_ABORTIFHUNG = 0x0002
_BROADCAST_TIMEOUT_MS = 5000
MANAGED = platform.system() == "Windows"
"""True where Core can switch telemetry in the game itself."""


def is_set() -> bool | None:
    """True when the user variable is 'true' (any case) or '1'; None where it can't be known."""
    if not MANAGED:
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _ENV_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VARIABLE)
    except FileNotFoundError:
        return False
    return str(value).strip().lower() in ("true", "1")


def set_variable(on: bool) -> bool:
    """Set or remove the user variable and tell Windows the environment changed. False when Windows was not told
    in time; the variable is set anyway, new processes started from Explorer may just not see it yet."""
    if not MANAGED:
        raise OSError("Star Citizen telemetry can only be switched on Windows")
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _ENV_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, VARIABLE, 0, winreg.REG_SZ, VALUE)
        else:
            try:
                winreg.DeleteValue(key, VARIABLE)
            except FileNotFoundError:
                pass
    return _broadcast_environment_change()


def _broadcast_environment_change() -> bool:
    """New processes started from Explorer (the launcher's shortcut) pick the change up after this."""
    import ctypes
    from ctypes import wintypes

    send = ctypes.windll.user32.SendMessageTimeoutW
    send.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR, wintypes.UINT,
                     wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))
    send.restype = ctypes.c_size_t
    result = ctypes.c_size_t()
    return bool(send(_HWND_BROADCAST, _WM_SETTINGCHANGE, 0, _ENV_KEY, _SMTO_ABORTIFHUNG,
                     _BROADCAST_TIMEOUT_MS, ctypes.byref(result)))
