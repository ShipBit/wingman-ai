"""The HUD's windows on Linux: not written yet.

A backend implements HudBackend (base.py) and sets `supported = True`. It
needs, per window, a borderless ARGB window that stays above other apps and
lets the mouse through: on X11 an override-redirect window with an empty
input shape (XShape), on Wayland a wlr-layer-shell surface (GNOME has none).
`present` uploads the RGBA image; `monitors` comes from XRandR or the
compositor.
"""

from hud_server.platform.base import OsFamily, UnsupportedBackend


class LinuxBackend(UnsupportedBackend):
    os = OsFamily.LINUX
    unsupported_reason = "The HUD does not run on Linux yet."
