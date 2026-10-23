"""The desktop Control Windows works on, one implementation per OS.

`get_desktop()` loads the one for the OS Wingman runs on. Each module imports
its OS libraries itself, so another OS never loads them.
"""

import sys

from skills.control_windows.desktop.base import Desktop, DesktopError


def get_desktop() -> Desktop:
    if sys.platform == "win32":
        from skills.control_windows.desktop.windows import WindowsDesktop

        return WindowsDesktop()
    if sys.platform == "darwin":
        from skills.control_windows.desktop.macos import MacDesktop

        return MacDesktop()
    from skills.control_windows.desktop.linux import LinuxDesktop

    return LinuxDesktop()


__all__ = ["Desktop", "DesktopError", "get_desktop"]
