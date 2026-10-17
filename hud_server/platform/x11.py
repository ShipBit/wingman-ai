"""The ctypes bindings the Linux backend (linux.py) uses: Xlib, the shape
extension for click-through and XRandR for the monitors.

Loaded only on Linux, by linux.py. `load()` returns None when a library is
missing, so the HUD reports itself unsupported instead of failing.
"""

import ctypes
import ctypes.util
from ctypes import POINTER, Structure, c_char_p, c_int, c_long, c_uint, c_ulong, c_void_p
from typing import Optional

# ─────────────────────────────── constants ─────────────────────────────── #

InputOutput = 1
TrueColor = 4
AllocNone = 0
ZPixmap = 2
PropModeReplace = 0
XA_ATOM = 4
XA_CARDINAL = 6

CWBackPixel = 1 << 1
CWBorderPixel = 1 << 3
CWOverrideRedirect = 1 << 9
CWEventMask = 1 << 11
CWColormap = 1 << 13

ButtonPressMask = 1 << 2
ButtonReleaseMask = 1 << 3
EnterWindowMask = 1 << 4
LeaveWindowMask = 1 << 5
PointerMotionMask = 1 << 6
ExposureMask = 1 << 15

ButtonPress = 4
ButtonRelease = 5
MotionNotify = 6
LeaveNotify = 8
Expose = 12

Button1 = 1

ShapeSet = 0
ShapeInput = 2
Unsorted = 0

# X cursor font shapes (X11/cursorfont.h)
XC_left_ptr = 68
XC_fleur = 52
XC_sb_v_double_arrow = 116
XC_sb_h_double_arrow = 108
XC_top_left_corner = 134
XC_top_right_corner = 136


# ─────────────────────────────── structures ─────────────────────────────── #


class XSetWindowAttributes(Structure):
    _fields_ = [
        ("background_pixmap", c_ulong),
        ("background_pixel", c_ulong),
        ("border_pixmap", c_ulong),
        ("border_pixel", c_ulong),
        ("bit_gravity", c_int),
        ("win_gravity", c_int),
        ("backing_store", c_int),
        ("backing_planes", c_ulong),
        ("backing_pixel", c_ulong),
        ("save_under", c_int),
        ("event_mask", c_long),
        ("do_not_propagate_mask", c_long),
        ("override_redirect", c_int),
        ("colormap", c_ulong),
        ("cursor", c_ulong),
    ]


class XVisualInfo(Structure):
    _fields_ = [
        ("visual", c_void_p),
        ("visualid", c_ulong),
        ("screen", c_int),
        ("depth", c_int),
        ("c_class", c_int),
        ("red_mask", c_ulong),
        ("green_mask", c_ulong),
        ("blue_mask", c_ulong),
        ("colormap_size", c_int),
        ("bits_per_rgb", c_int),
    ]


class XAnyEvent(Structure):
    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", c_int),
        ("display", c_void_p),
        ("window", c_ulong),
    ]


class XButtonEvent(Structure):
    """Also the layout of XMotionEvent and XCrossingEvent up to `y_root`."""

    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", c_int),
        ("display", c_void_p),
        ("window", c_ulong),
        ("root", c_ulong),
        ("subwindow", c_ulong),
        ("time", c_ulong),
        ("x", c_int),
        ("y", c_int),
        ("x_root", c_int),
        ("y_root", c_int),
        ("state", c_uint),
        ("button", c_uint),
        ("same_screen", c_int),
    ]


class XEvent(ctypes.Union):
    _fields_ = [
        ("type", c_int),
        ("xany", XAnyEvent),
        ("xbutton", XButtonEvent),
        ("pad", c_long * 24),
    ]


class XRRMonitorInfo(Structure):
    _fields_ = [
        ("name", c_ulong),
        ("primary", c_int),
        ("automatic", c_int),
        ("noutput", c_int),
        ("x", c_int),
        ("y", c_int),
        ("width", c_int),
        ("height", c_int),
        ("mwidth", c_int),
        ("mheight", c_int),
        ("outputs", c_void_p),
    ]


ErrorHandler = ctypes.CFUNCTYPE(c_int, c_void_p, c_void_p)


# ─────────────────────────────── libraries ─────────────────────────────── #


class Libs:
    def __init__(self, x11, xext, xrandr) -> None:
        self.x11 = x11
        self.xext = xext
        self.xrandr = xrandr


def _open(name: str, fallback: str):
    path = ctypes.util.find_library(name) or fallback
    try:
        return ctypes.CDLL(path)
    except OSError:
        return None


def _bind(lib, name: str, restype, *argtypes) -> None:
    function = getattr(lib, name)
    function.restype = restype
    function.argtypes = list(argtypes)


_libs: Optional[Libs] = None
_loaded = False


def load() -> Optional[Libs]:
    """libX11 and libXext with their signatures, libXrandr when present.
    None without X11 or the shape extension."""
    global _libs, _loaded
    if _loaded:
        return _libs
    _loaded = True
    x11 = _open("X11", "libX11.so.6")
    xext = _open("Xext", "libXext.so.6")
    if x11 is None or xext is None:
        return None
    xrandr = _open("Xrandr", "libXrandr.so.2")

    d, w = c_void_p, c_ulong
    _bind(x11, "XInitThreads", c_int)
    _bind(x11, "XOpenDisplay", c_void_p, c_char_p)
    _bind(x11, "XCloseDisplay", c_int, d)
    _bind(x11, "XDefaultScreen", c_int, d)
    _bind(x11, "XRootWindow", w, d, c_int)
    _bind(x11, "XDisplayWidth", c_int, d, c_int)
    _bind(x11, "XDisplayHeight", c_int, d, c_int)
    _bind(x11, "XMatchVisualInfo", c_int, d, c_int, c_int, c_int, POINTER(XVisualInfo))
    _bind(x11, "XCreateColormap", w, d, w, c_void_p, c_int)
    _bind(x11, "XFreeColormap", c_int, d, w)
    _bind(
        x11, "XCreateWindow", w, d, w, c_int, c_int, c_uint, c_uint, c_uint, c_int, c_uint,
        c_void_p, c_ulong, POINTER(XSetWindowAttributes),
    )
    _bind(x11, "XDestroyWindow", c_int, d, w)
    _bind(x11, "XMapRaised", c_int, d, w)
    _bind(x11, "XUnmapWindow", c_int, d, w)
    _bind(x11, "XRaiseWindow", c_int, d, w)
    _bind(x11, "XMoveResizeWindow", c_int, d, w, c_int, c_int, c_uint, c_uint)
    _bind(x11, "XStoreName", c_int, d, w, c_char_p)
    _bind(x11, "XInternAtom", c_ulong, d, c_char_p, c_int)
    _bind(x11, "XChangeProperty", c_int, d, w, c_ulong, c_ulong, c_int, c_int, c_void_p, c_int)
    _bind(x11, "XCreateGC", c_void_p, d, w, c_ulong, c_void_p)
    _bind(x11, "XFreeGC", c_int, d, c_void_p)
    _bind(
        x11, "XCreateImage", c_void_p, d, c_void_p, c_uint, c_int, c_int, c_void_p,
        c_uint, c_uint, c_int, c_int,
    )
    _bind(
        x11, "XPutImage", c_int, d, w, c_void_p, c_void_p, c_int, c_int, c_int, c_int,
        c_uint, c_uint,
    )
    _bind(x11, "XFree", c_int, c_void_p)
    _bind(x11, "XFlush", c_int, d)
    _bind(x11, "XSync", c_int, d, c_int)
    _bind(x11, "XPending", c_int, d)
    _bind(x11, "XNextEvent", c_int, d, POINTER(XEvent))
    _bind(
        x11, "XQueryPointer", c_int, d, w, POINTER(c_ulong), POINTER(c_ulong),
        POINTER(c_int), POINTER(c_int), POINTER(c_int), POINTER(c_int), POINTER(c_uint),
    )
    _bind(x11, "XCreateFontCursor", c_ulong, d, c_uint)
    _bind(x11, "XDefineCursor", c_int, d, w, c_ulong)
    _bind(x11, "XFreeCursor", c_int, d, c_ulong)
    _bind(x11, "XSetErrorHandler", c_void_p, ErrorHandler)
    _bind(
        xext, "XShapeCombineRectangles", None, d, w, c_int, c_int, c_int, c_void_p, c_int,
        c_int, c_int,
    )
    _bind(xext, "XShapeCombineMask", None, d, w, c_int, c_int, c_int, c_ulong, c_int)
    if xrandr is not None:
        try:
            _bind(xrandr, "XRRGetMonitors", POINTER(XRRMonitorInfo), d, w, c_int, POINTER(c_int))
            _bind(xrandr, "XRRFreeMonitors", None, POINTER(XRRMonitorInfo))
        except AttributeError:
            # XRandR older than 1.5 has no monitors: the screen's size stands in
            xrandr = None

    _libs = Libs(x11, xext, xrandr)
    return _libs
