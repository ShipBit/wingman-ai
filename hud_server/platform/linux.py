"""The HUD's windows on Linux: X11 windows with per-pixel alpha.

Each HUD window is an override-redirect window (no window manager frame, not
in the task list, never focused) on a 32-bit ARGB visual, so a compositor
blends it over the game. An empty input shape lets the mouse through; the
preview gives the window its input back.

Wayland sessions run it through XWayland, which every desktop ships. Games
under Proton and most native ones use XWayland too, so the HUD sits in the
same X server as the game. A native Wayland game in fullscreen may cover it,
depending on how the compositor stacks override-redirect windows. Under gamescope the
windows are marked as an external overlay, as MangoHud's are.

Without DISPLAY (a Wayland session without XWayland, a server) the HUD stays
off and says why. Without a compositor an ARGB window has no transparency:
`start` refuses then instead of drawing black boxes.

The HUD draws in X pixels. Desktop scaling (GNOME, KDE) does not apply to
override-redirect windows, so on a scaled display the HUD looks smaller.
"""

import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from PIL import Image, ImageChops

from api.enums import LogType
from services.printr import Printr
from hud_server.platform.base import (
    Cursor,
    FontSet,
    HudBackend,
    HudPlatformError,
    Monitor,
    OsFamily,
    Pointer,
    PointerHandler,
)

printr = Printr()

RAISE_SECONDS = 1.0
"""How often shown windows are put back on top: an override-redirect window
has no "always on top", and a game that comes to the front covers it."""

_FONT_FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _why_unsupported() -> Optional[str]:
    if not sys.platform.startswith("linux"):
        return "The Linux HUD runs on Linux only."
    if not os.environ.get("DISPLAY"):
        return "The HUD needs X11 or XWayland, and DISPLAY is not set."
    from hud_server.platform import x11

    if x11.load() is None:
        return "The HUD needs libX11 and libXext, and one of them is missing."
    return None


_CURSOR_SHAPES = {
    Cursor.ARROW: "XC_left_ptr",
    Cursor.MOVE: "XC_fleur",
    Cursor.RESIZE_NS: "XC_sb_v_double_arrow",
    Cursor.RESIZE_WE: "XC_sb_h_double_arrow",
    Cursor.RESIZE_NWSE: "XC_top_left_corner",
    Cursor.RESIZE_NESW: "XC_top_right_corner",
}


@dataclass
class _Window:
    xid: int
    gc: Any
    x: int
    y: int
    width: int
    height: int
    shown: bool = True
    mapped: bool = False
    image: Optional[Any] = None
    """The last picture, kept for Expose: X keeps nothing of a window's content."""
    image_size: tuple = (0, 0)
    handler: Optional[PointerHandler] = None
    cursor: Optional[Cursor] = None
    extra: dict = field(default_factory=dict)


class LinuxBackend(HudBackend):
    os = OsFamily.LINUX

    def __init__(self) -> None:
        reason = _why_unsupported()
        self.supported = reason is None
        self.unsupported_reason = reason
        self._display = None
        self._screen = 0
        self._root = 0
        self._visual = None
        self._colormap = 0
        self._windows: dict[int, _Window] = {}
        self._cursors: dict[Cursor, int] = {}
        self._last_raise = 0.0
        self._error_handler = None
        self._font_cache: dict[str, Optional[FontSet]] = {}
        self._lock = threading.Lock()

    @property
    def _x(self):
        from hud_server.platform import x11

        return x11.load().x11

    # ─────────────────────────────── lifecycle ─────────────────────────────── #

    def start(self) -> None:
        if not self.supported:
            raise HudPlatformError(self.unsupported_reason)
        from hud_server.platform import x11

        lib = self._x
        # monitors() opens its own connection from other threads
        lib.XInitThreads()
        self._display = lib.XOpenDisplay(None)
        if not self._display:
            raise HudPlatformError(f"Could not open the X display {os.environ.get('DISPLAY')}.")

        # The default handler ends the process on any X error; a vanished
        # window must not take Core with it
        def on_error(display, event):
            return 0

        self._error_handler = x11.ErrorHandler(on_error)
        lib.XSetErrorHandler(self._error_handler)

        self._screen = lib.XDefaultScreen(self._display)
        self._root = lib.XRootWindow(self._display, self._screen)
        info = x11.XVisualInfo()
        if not lib.XMatchVisualInfo(self._display, self._screen, 32, x11.TrueColor, ctypes.byref(info)):
            self.stop()
            raise HudPlatformError(
                "The HUD needs a compositor for transparent windows, and this X display has none."
            )
        self._visual = info.visual
        self._colormap = lib.XCreateColormap(self._display, self._root, self._visual, x11.AllocNone)

    def stop(self) -> None:
        if not self._display:
            return
        lib = self._x
        for window in list(self._windows.values()):
            self.destroy_window(window)
        for cursor in self._cursors.values():
            lib.XFreeCursor(self._display, cursor)
        self._cursors.clear()
        if self._colormap:
            lib.XFreeColormap(self._display, self._colormap)
            self._colormap = 0
        lib.XCloseDisplay(self._display)
        self._display = None

    def pump_events(self) -> None:
        if not self._display:
            return
        from hud_server.platform import x11

        lib = self._x
        event = x11.XEvent()
        while lib.XPending(self._display):
            lib.XNextEvent(self._display, ctypes.byref(event))
            window = self._windows.get(event.xany.window)
            if window is None:
                continue
            kind = event.type
            if kind == x11.Expose:
                self._blit(window)
            elif kind == x11.MotionNotify:
                # As Windows does it: where to show which cursor, then the move
                self._pointer(window, Pointer.HOVER, event.xbutton)
                self._pointer(window, Pointer.MOVE, event.xbutton)
            elif kind == x11.ButtonPress and event.xbutton.button == x11.Button1:
                self._pointer(window, Pointer.PRESS, event.xbutton)
            elif kind == x11.ButtonRelease and event.xbutton.button == x11.Button1:
                self._pointer(window, Pointer.RELEASE, event.xbutton)

        now = time.monotonic()
        if now - self._last_raise >= RAISE_SECONDS:
            self._last_raise = now
            for window in self._windows.values():
                if window.shown and window.mapped:
                    lib.XRaiseWindow(self._display, window.xid)
            lib.XFlush(self._display)

    def _pointer(self, window: _Window, pointer: Pointer, event) -> None:
        if window.handler is None:
            return
        cursor = window.handler(pointer, event.x_root, event.y_root)
        if cursor is not None and cursor != window.cursor:
            window.cursor = cursor
            self._x.XDefineCursor(self._display, window.xid, self._cursor(cursor))
            self._x.XFlush(self._display)

    def _cursor(self, cursor: Cursor) -> int:
        from hud_server.platform import x11

        if cursor not in self._cursors:
            shape = getattr(x11, _CURSOR_SHAPES[cursor])
            self._cursors[cursor] = self._x.XCreateFontCursor(self._display, shape)
        return self._cursors[cursor]

    # ─────────────────────────────── windows ─────────────────────────────── #

    def create_window(self, title, x, y, width, height) -> Optional[_Window]:
        if not self._display:
            return None
        from hud_server.platform import x11

        lib = self._x
        attrs = x11.XSetWindowAttributes()
        attrs.override_redirect = 1
        attrs.colormap = self._colormap
        attrs.background_pixel = 0
        attrs.border_pixel = 0
        attrs.event_mask = (
            x11.ExposureMask | x11.ButtonPressMask | x11.ButtonReleaseMask
            | x11.PointerMotionMask | x11.LeaveWindowMask
        )
        mask = x11.CWOverrideRedirect | x11.CWColormap | x11.CWBackPixel | x11.CWBorderPixel | x11.CWEventMask
        width, height = max(1, int(width)), max(1, int(height))
        xid = lib.XCreateWindow(
            self._display, self._root, int(x), int(y), width, height, 0, 32,
            x11.InputOutput, self._visual, mask, ctypes.byref(attrs),
        )
        if not xid:
            return None
        lib.XStoreName(self._display, xid, title.encode("utf-8", "replace"))
        # A notification to compositors: no shadow, no animation, kept on top
        window_type = lib.XInternAtom(self._display, b"_NET_WM_WINDOW_TYPE", 0)
        notification = ctypes.c_ulong(lib.XInternAtom(self._display, b"_NET_WM_WINDOW_TYPE_NOTIFICATION", 0))
        lib.XChangeProperty(
            self._display, xid, window_type, x11.XA_ATOM, 32, x11.PropModeReplace,
            ctypes.byref(notification), 1,
        )
        # gamescope (Steam Deck and Bazzite game mode) shows only the game and
        # windows marked as an external overlay, the way MangoHud is shown.
        # Other compositors ignore the property.
        overlay = lib.XInternAtom(self._display, b"GAMESCOPE_EXTERNAL_OVERLAY", 0)
        on = ctypes.c_ulong(1)
        lib.XChangeProperty(
            self._display, xid, overlay, x11.XA_CARDINAL, 32, x11.PropModeReplace,
            ctypes.byref(on), 1,
        )
        window = _Window(
            xid=xid, gc=lib.XCreateGC(self._display, xid, 0, None),
            x=int(x), y=int(y), width=width, height=height,
        )
        self._windows[xid] = window
        self.set_click_through(window, True)
        # Mapped with its first picture: an empty ARGB window can show black
        lib.XFlush(self._display)
        return window

    def destroy_window(self, window: _Window) -> None:
        if not self._display or self._windows.pop(window.xid, None) is None:
            return
        lib = self._x
        if window.gc:
            lib.XFreeGC(self._display, window.gc)
        lib.XDestroyWindow(self._display, window.xid)
        lib.XFlush(self._display)
        window.image = None

    def move_window(self, window: _Window, x, y, width, height) -> None:
        window.x, window.y = int(x), int(y)
        window.width, window.height = max(1, int(width)), max(1, int(height))
        if self._display:
            self._x.XMoveResizeWindow(self._display, window.xid, window.x, window.y, window.width, window.height)
            self._x.XFlush(self._display)

    def raise_window(self, window: _Window) -> None:
        if self._display and window.mapped:
            self._x.XRaiseWindow(self._display, window.xid)
            self._x.XFlush(self._display)

    def show_window(self, window: _Window) -> None:
        window.shown = True
        if self._display and window.image is not None and not window.mapped:
            self._x.XMapRaised(self._display, window.xid)
            window.mapped = True
            self._x.XFlush(self._display)

    def hide_window(self, window: _Window) -> None:
        window.shown = False
        if self._display and window.mapped:
            self._x.XUnmapWindow(self._display, window.xid)
            window.mapped = False
            self._x.XFlush(self._display)

    def present(self, window: _Window, image, opacity: int) -> None:
        if not self._display:
            return
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        w, h = image.size
        window.image = ctypes.create_string_buffer(_premultiplied_bgra(image, opacity), w * h * 4)
        window.image_size = (w, h)
        if (w, h) != (window.width, window.height):
            window.width, window.height = w, h
            self._x.XMoveResizeWindow(self._display, window.xid, window.x, window.y, w, h)
        if window.shown and not window.mapped:
            self._x.XMapRaised(self._display, window.xid)
            window.mapped = True
        self._blit(window)

    def _blit(self, window: _Window) -> None:
        """The kept picture onto the window (after present, and on Expose)."""
        if window.image is None or not self._display:
            return
        from hud_server.platform import x11

        lib = self._x
        w, h = window.image_size
        ximage = lib.XCreateImage(
            self._display, self._visual, 32, x11.ZPixmap, 0, ctypes.cast(window.image, ctypes.c_void_p),
            w, h, 32, w * 4,
        )
        if not ximage:
            raise RuntimeError(f"XCreateImage failed for {w}x{h}")
        lib.XPutImage(self._display, window.xid, window.gc, ximage, 0, 0, 0, 0, w, h)
        # Only the structure: the pixels belong to window.image
        lib.XFree(ximage)
        lib.XFlush(self._display)

    # ─────────────────────────────── mouse ─────────────────────────────── #

    def set_click_through(self, window: _Window, click_through: bool) -> None:
        if not self._display:
            return
        from hud_server.platform import x11

        xext = x11.load().xext
        if click_through:
            # No input region: every click goes to what is below
            xext.XShapeCombineRectangles(
                self._display, window.xid, x11.ShapeInput, 0, 0, None, 0, x11.ShapeSet, x11.Unsorted
            )
        else:
            # The default region again: the whole window
            xext.XShapeCombineMask(self._display, window.xid, x11.ShapeInput, 0, 0, 0, x11.ShapeSet)
        self._x.XFlush(self._display)

    def set_pointer_handler(self, window: _Window, handler: Optional[PointerHandler]) -> None:
        window.handler = handler

    def capture_pointer(self, window: _Window) -> None:
        # X grabs the pointer for the window a button went down in, until it is released
        pass

    def release_pointer(self) -> None:
        pass

    def cursor_position(self) -> tuple[int, int]:
        if not self._display:
            return 0, 0
        root, child = ctypes.c_ulong(), ctypes.c_ulong()
        rx, ry, wx, wy = ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
        mask = ctypes.c_uint()
        self._x.XQueryPointer(
            self._display, self._root, ctypes.byref(root), ctypes.byref(child),
            ctypes.byref(rx), ctypes.byref(ry), ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(mask),
        )
        return rx.value, ry.value

    # ─────────────────────────────── screen and fonts ─────────────────────────────── #

    def monitors(self) -> list[Monitor]:
        """From XRandR, the primary first; its own connection, so any thread may ask."""
        if not self.supported:
            return []
        from hud_server.platform import x11

        libs = x11.load()
        lib = libs.x11
        display = lib.XOpenDisplay(None)
        if not display:
            return []
        try:
            screen = lib.XDefaultScreen(display)
            root = lib.XRootWindow(display, screen)
            monitors: list[Monitor] = []
            if libs.xrandr is not None:
                count = ctypes.c_int()
                infos = libs.xrandr.XRRGetMonitors(display, root, 1, ctypes.byref(count))
                if infos:
                    try:
                        for i in range(count.value):
                            info = infos[i]
                            monitors.append(
                                Monitor(info.x, info.y, info.width, info.height, bool(info.primary))
                            )
                    finally:
                        libs.xrandr.XRRFreeMonitors(infos)
            if not monitors:
                monitors.append(
                    Monitor(0, 0, lib.XDisplayWidth(display, screen), lib.XDisplayHeight(display, screen), True)
                )
            return sorted(monitors, key=lambda m: not m.primary)
        except Exception as e:
            printr.print(f"[HUD] Could not list the monitors: {e}", color=LogType.WARNING, server_only=True)
            return []
        finally:
            lib.XCloseDisplay(display)

    def font_set(self, family: str) -> Optional[FontSet]:
        """The family's files from fontconfig (fc-match picks the nearest one
        installed: Arial becomes Liberation Sans on most systems)."""
        key = family.lower()
        if key not in self._font_cache:
            self._font_cache[key] = self._find_fonts(family)
        return self._font_cache[key]

    @staticmethod
    def _find_fonts(family: str) -> Optional[FontSet]:
        if shutil.which("fc-match") is None:
            return None

        def match(pattern: str) -> str:
            try:
                result = subprocess.run(
                    ["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True, timeout=5
                )
                path = result.stdout.strip()
                return path if path and os.path.exists(path) else _FONT_FALLBACK
            except Exception:
                return _FONT_FALLBACK

        return FontSet(
            normal=match(f"{family}:style=Regular"),
            bold=match(f"{family}:style=Bold"),
            italic=match(f"{family}:style=Italic"),
            bold_italic=match(f"{family}:style=Bold Italic"),
            code=match("monospace"),
            emoji=(match("DejaVu Sans"), match("Noto Sans Symbols2")),
        )


def _premultiplied_bgra(image, opacity: int) -> bytes:
    """ARGB32 as X wants it on a little-endian machine: B, G, R, A per pixel,
    colour multiplied by alpha. The window's opacity is baked into the alpha:
    an override-redirect window has no opacity of its own."""
    r, g, b, a = image.split()
    opacity = max(0, min(255, int(opacity)))
    if opacity < 255:
        a = a.point(lambda v: v * opacity // 255)
    premultiplied = Image.merge(
        "RGBA", (ImageChops.multiply(r, a), ImageChops.multiply(g, a), ImageChops.multiply(b, a), a)
    )
    return premultiplied.tobytes("raw", "BGRA")
