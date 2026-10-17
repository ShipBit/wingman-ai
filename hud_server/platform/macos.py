"""The HUD's windows on macOS: not written yet.

A backend implements HudBackend (base.py) and sets `supported = True`. It
needs, per window, a borderless, non-opaque NSPanel (PyObjC) at a level above
full-screen apps, with `ignoresMouseEvents` for click-through; `present`
puts the image on the window's content layer as a CGImage. AppKit only works
on the main thread, and the overlay runs on its own: the backend has to hand
its window calls to the main thread.
"""

from hud_server.platform.base import OsFamily, UnsupportedBackend


class MacOsBackend(UnsupportedBackend):
    os = OsFamily.MACOS
    unsupported_reason = "The HUD does not run on macOS yet."
