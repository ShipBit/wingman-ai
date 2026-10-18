"""Where the active window is, for a screenshot of just that window.

One function per OS. Each returns {"top", "left", "width", "height"} in the
coordinates mss captures in, or None when it cannot tell: the screenshot then
shows the whole screen. OS libraries are imported inside, so another OS never
loads them.
"""

import os
import sys
from typing import Optional

Box = dict[str, int]


def active_window_bbox() -> Optional[Box]:
    if sys.platform == "win32":
        return _windows()
    if sys.platform == "darwin":
        return _macos()
    return _linux()


def _box(left, top, width, height) -> Optional[Box]:
    if width <= 0 or height <= 0:
        return None
    return {"top": int(top), "left": int(left), "width": int(width), "height": int(height)}


def _windows() -> Optional[Box]:
    import pygetwindow as gw

    window = gw.getActiveWindow()
    if not window:
        return None
    return _box(window.left, window.top, window.width, window.height)


def _macos() -> Optional[Box]:
    """The frontmost app's frontmost window, from Quartz: the list is in
    front-to-back order. Points, as mss captures on macOS."""
    from AppKit import NSWorkspace
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGNullWindowID,
        kCGWindowListExcludeDesktopElements,
        kCGWindowListOptionOnScreenOnly,
    )

    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    pid = app.processIdentifier() if app is not None else None
    infos = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements, kCGNullWindowID
    ) or []
    windows = [info for info in infos if info.get("kCGWindowLayer", 0) == 0]
    # The frontmost app's window; else the topmost window of any app (the
    # frontmost app can be one without windows, like the login window)
    ordered = [w for w in windows if w.get("kCGWindowOwnerPID") == pid] + windows
    for info in ordered:
        bounds = info.get("kCGWindowBounds") or {}
        box = _box(bounds.get("X", 0), bounds.get("Y", 0), bounds.get("Width", 0), bounds.get("Height", 0))
        if box:
            return box
    return None


def _linux() -> Optional[Box]:
    """_NET_ACTIVE_WINDOW from the window manager, with its frame. Not in a
    Wayland session: there it names only XWayland windows, and a native
    Wayland window in front would give the wrong one."""
    if os.environ.get("WAYLAND_DISPLAY") or not os.environ.get("DISPLAY"):
        return None
    import ctypes
    import ctypes.util
    from ctypes import POINTER, byref, c_char_p, c_int, c_long, c_uint, c_ulong, c_void_p

    try:
        x = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
    except OSError:
        return None
    d = c_void_p
    x.XOpenDisplay.restype, x.XOpenDisplay.argtypes = c_void_p, [c_char_p]
    x.XCloseDisplay.argtypes = [d]
    x.XDefaultRootWindow.restype, x.XDefaultRootWindow.argtypes = c_ulong, [d]
    x.XInternAtom.restype, x.XInternAtom.argtypes = c_ulong, [d, c_char_p, c_int]
    x.XGetWindowProperty.argtypes = [
        d, c_ulong, c_ulong, c_long, c_long, c_int, c_ulong, POINTER(c_ulong), POINTER(c_int),
        POINTER(c_ulong), POINTER(c_ulong), POINTER(c_void_p),
    ]
    x.XFree.argtypes = [c_void_p]
    x.XGetGeometry.argtypes = [
        d, c_ulong, POINTER(c_ulong), POINTER(c_int), POINTER(c_int), POINTER(c_uint),
        POINTER(c_uint), POINTER(c_uint), POINTER(c_uint),
    ]
    x.XTranslateCoordinates.argtypes = [
        d, c_ulong, c_ulong, c_int, c_int, POINTER(c_int), POINTER(c_int), POINTER(c_ulong),
    ]

    display = x.XOpenDisplay(None)
    if not display:
        return None
    try:
        root = x.XDefaultRootWindow(display)

        def longs(window: int, name: str) -> list[int]:
            kind, fmt, count, after, data = c_ulong(), c_int(), c_ulong(), c_ulong(), c_void_p()
            atom = x.XInternAtom(display, name.encode(), 0)
            if x.XGetWindowProperty(
                display, window, atom, 0, 64, 0, 0, byref(kind), byref(fmt), byref(count),
                byref(after), byref(data),
            ) != 0 or not data.value:
                return []
            try:
                return list((c_long * count.value).from_address(data.value)) if fmt.value == 32 else []
            finally:
                x.XFree(data)

        active = longs(root, "_NET_ACTIVE_WINDOW")
        if not active or not active[0]:
            return None
        window = active[0]
        geometry_root, gx, gy = c_ulong(), c_int(), c_int()
        width, height, border, depth = c_uint(), c_uint(), c_uint(), c_uint()
        if not x.XGetGeometry(display, window, byref(geometry_root), byref(gx), byref(gy),
                              byref(width), byref(height), byref(border), byref(depth)):
            return None
        left, top, child = c_int(), c_int(), c_ulong()
        x.XTranslateCoordinates(display, window, root, 0, 0, byref(left), byref(top), byref(child))
        # Title bar and borders, which the window manager draws around it
        frame = (longs(window, "_NET_FRAME_EXTENTS") + [0, 0, 0, 0])[:4]
        fl, fr, ft, fb = frame
        return _box(left.value - fl, top.value - ft, width.value + fl + fr, height.value + ft + fb)
    finally:
        x.XCloseDisplay(display)
