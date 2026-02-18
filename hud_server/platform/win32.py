import sys

if sys.platform != "win32":
    raise ImportError("hud_server.platform.win32 is only available on Windows")

import ctypes
from ctypes import wintypes

from api.enums import LogType
from services.printr import Printr
from hud_server.constants import (
    LOG_MONITORS_AVAILABLE,
    LOG_MONITOR_NONE,
    LOG_MONITOR_SELECTED,
    LOG_MONITOR_FALLBACK_GETSYSTEMMETRICS,
    LOG_MONITOR_FALLBACK_UNAVAILABLE,
    LOG_MONITOR_NONE_AVAILABLE,
    LOG_MONITOR_ERROR,
)

printr = Printr()

# Windows API Constants
GWL_EXSTYLE = -20
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x80000
WS_EX_TRANSPARENT = 0x20
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
LWA_ALPHA = 0x00000002
LWA_COLORKEY = 0x00000001
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_SHOWWINDOW = 0x0040
SWP_NOACTIVATE = 0x0010
SWP_ASYNCWINDOWPOS = 0x4000
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0

# Function pointers
# Use fresh WinDLL instances to isolate argtypes from other modules sharing windll
user32 = ctypes.WinDLL("user32.dll", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32.dll", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)

SW_SHOWNOACTIVATE = 4
HWND_TOPMOST = wintypes.HWND(-1)

# Use platform-appropriate types for WPARAM and LPARAM (64-bit on x64)
if ctypes.sizeof(ctypes.c_void_p) == 8:
    WPARAM = ctypes.c_uint64
    LPARAM = ctypes.c_int64
    LRESULT = ctypes.c_int64
else:
    WPARAM = ctypes.c_uint
    LPARAM = ctypes.c_long
    LRESULT = ctypes.c_long

WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint, WPARAM, LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("style", ctypes.c_uint),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HICON),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class RGBQUAD(ctypes.Structure):
    _fields_ = [
        ("rgbBlue", ctypes.c_byte),
        ("rgbGreen", ctypes.c_byte),
        ("rgbRed", ctypes.c_byte),
        ("rgbReserved", ctypes.c_byte),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


# Setup Function Prototypes
user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.SetLayeredWindowAttributes.argtypes = [
    wintypes.HWND,
    wintypes.COLORREF,
    wintypes.BYTE,
    wintypes.DWORD,
]
user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND,
    wintypes.HDC,
    ctypes.POINTER(wintypes.POINT),
    ctypes.POINTER(wintypes.SIZE),
    wintypes.HDC,
    ctypes.POINTER(wintypes.POINT),
    wintypes.COLORREF,
    ctypes.POINTER(RGBQUAD),
    wintypes.DWORD,
]

# Multi-monitor support - define types first
MONITORINFOF_PRIMARY = 1


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(wintypes.RECT),
    LPARAM,
)

# Setup function prototypes for multi-monitor APIs
user32.EnumDisplayMonitors.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(wintypes.RECT),
    MONITORENUMPROC,
    LPARAM,
]
user32.EnumDisplayMonitors.restype = wintypes.BOOL
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL


# Basic Win32 message structures for a non-blocking pump
class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", ctypes.c_uint),
        ("wParam", WPARAM),
        ("lParam", LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


# WinAPI signatures we need for message pumping
# Use c_void_p for MSG pointers to avoid strict type checking issues with byref()
user32.PeekMessageW.argtypes = [
    ctypes.c_void_p,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.UINT,
]
user32.PeekMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.c_void_p]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
user32.DispatchMessageW.restype = LRESULT

PM_REMOVE = 0x0001

# WinEvent hook constants for reactive foreground monitoring
EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002

# Callback type for SetWinEventHook
WINEVENTPROC = ctypes.WINFUNCTYPE(
    None,  # void return
    wintypes.HANDLE,  # hWinEventHook
    wintypes.DWORD,  # event
    wintypes.HWND,  # hwnd
    ctypes.c_long,  # idObject
    ctypes.c_long,  # idChild
    wintypes.DWORD,  # idEventThread
    wintypes.DWORD,  # dwmsEventTime
)

# SetWinEventHook / UnhookWinEvent prototypes
user32.SetWinEventHook.argtypes = [
    wintypes.DWORD,  # eventMin
    wintypes.DWORD,  # eventMax
    wintypes.HMODULE,  # hmodWinEventProc
    WINEVENTPROC,  # lpfnWinEventProc
    wintypes.DWORD,  # idProcess
    wintypes.DWORD,  # idThread
    wintypes.DWORD,  # dwFlags
]
user32.SetWinEventHook.restype = wintypes.HANDLE

user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
user32.UnhookWinEvent.restype = wintypes.BOOL


def _wnd_proc(hwnd, msg, wparam, lparam):
    """Window procedure callback - must handle all message types safely."""
    try:
        return user32.DefWindowProcW(hwnd, msg, WPARAM(wparam), LPARAM(lparam))
    except:
        return 0


_wnd_proc_callback = WNDPROC(_wnd_proc)
_class_registered = False
_class_name = "WingmanHeadsUpOverlay"


def _ensure_window_class():
    global _class_registered
    if _class_registered:
        return True
    hInstance = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = _wnd_proc_callback
    wc.hInstance = hInstance
    wc.lpszClassName = _class_name
    if user32.RegisterClassExW(ctypes.byref(wc)):
        _class_registered = True
        return True
    return False


# Common helpers
def force_on_top(hwnd):
    user32.SetWindowPos(
        hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    )


# ─────────────────────────────── Multi-Monitor Support ─────────────────────────────── #


# Store callback globally to prevent garbage collection
_enum_callback = None


def get_all_monitors():
    """Get information about all connected monitors.

    Returns:
        list: List of monitor info dicts with keys: left, top, right, bottom, width, height, is_primary
    """
    global _enum_callback

    monitors = []
    try:
        # Use a closure to capture monitors list
        def callback(hmonitor, hdc, lprect, lparam):
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(hmonitor, ctypes.byref(mi)):
                monitors.append(
                    {
                        "left": mi.rcMonitor.left,
                        "top": mi.rcMonitor.top,
                        "right": mi.rcMonitor.right,
                        "bottom": mi.rcMonitor.bottom,
                        "width": mi.rcMonitor.right - mi.rcMonitor.left,
                        "height": mi.rcMonitor.bottom - mi.rcMonitor.top,
                        "is_primary": bool(mi.dwFlags & MONITORINFOF_PRIMARY),
                    }
                )
            return True

        _enum_callback = MONITORENUMPROC(callback)
        user32.EnumDisplayMonitors(None, None, _enum_callback, 0)
    except Exception as e:
        printr.print(LOG_MONITOR_ERROR.format(e), color=LogType.ERROR, server_only=True)
    return monitors


def get_monitor_dimensions(screen_index: int = 1):
    """Get the dimensions and offset of a specific monitor by index.

    Args:
        screen_index: Monitor index (1 = primary, 2 = secondary, etc.)

    Returns:
        tuple: (width, height, offset_x, offset_y) of the requested monitor
    """
    monitors = get_all_monitors()

    # Log available monitors
    if monitors:
        monitor_list = ", ".join(
            f"{i+1}: {m['width']}x{m['height']}{' (primary)' if m['is_primary'] else ''}"
            for i, m in enumerate(monitors)
        )
        printr.print(
            LOG_MONITORS_AVAILABLE.format(monitor_list),
            color=LogType.INFO,
            server_only=True,
        )
    else:
        printr.print(LOG_MONITOR_NONE, color=LogType.WARNING, server_only=True)

    if not monitors:
        # Fallback to primary monitor using GetSystemMetrics
        width = (
            user32.GetSystemMetrics(0) if hasattr(user32, "GetSystemMetrics") else 1920
        )
        height = (
            user32.GetSystemMetrics(1) if hasattr(user32, "GetSystemMetrics") else 1080
        )
        printr.print(
            LOG_MONITOR_FALLBACK_GETSYSTEMMETRICS.format(screen_index, width, height),
            color=LogType.WARNING,
            server_only=True,
        )
        return width, height, 0, 0

    # Adjust index to 0-based
    index = screen_index - 1

    if index < len(monitors):
        monitor = monitors[index]
        printr.print(
            LOG_MONITOR_SELECTED.format(
                screen_index, monitor["width"], monitor["height"]
            ),
            color=LogType.INFO,
            server_only=True,
        )
        return monitor["width"], monitor["height"], monitor["left"], monitor["top"]

    # If the requested screen doesn't exist, return the last available monitor
    if monitors:
        monitor = monitors[-1]
        printr.print(
            LOG_MONITOR_FALLBACK_UNAVAILABLE.format(
                screen_index, len(monitors), monitor["width"], monitor["height"]
            ),
            color=LogType.WARNING,
            server_only=True,
        )
        return monitor["width"], monitor["height"], monitor["left"], monitor["top"]

    # Ultimate fallback
    printr.print(LOG_MONITOR_NONE_AVAILABLE, color=LogType.WARNING, server_only=True)
    return 1920, 1080, 0, 0
