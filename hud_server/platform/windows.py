"""The HUD's windows on Windows: layered Win32 windows with per-pixel alpha."""

import ctypes
import os
import threading
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Optional

from PIL import Image, ImageChops

from api.enums import LogType
from services.printr import Printr
from hud_server.constants import LOG_MONITOR_ERROR, LOG_MONITOR_NONE
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
from hud_server.platform.win32 import (
    AC_SRC_ALPHA,
    AC_SRC_OVER,
    BI_RGB,
    BITMAPINFO,
    BITMAPINFOHEADER,
    BLENDFUNCTION,
    DEVMODEW,
    DIB_RGB_COLORS,
    ENUM_CURRENT_SETTINGS,
    EVENT_SYSTEM_FOREGROUND,
    GWL_EXSTYLE,
    HWND_TOPMOST,
    IDC_ARROW,
    IDC_SIZEALL,
    IDC_SIZENESW,
    IDC_SIZENS,
    IDC_SIZENWSE,
    IDC_SIZEWE,
    LPARAM,
    MA_NOACTIVATE,
    MONITORENUMPROC,
    MONITORINFOEXW,
    MONITORINFOF_PRIMARY,
    MSG,
    PM_REMOVE,
    SW_SHOWNOACTIVATE,
    SWP_HIDEWINDOW,
    SWP_NOACTIVATE,
    SWP_NOMOVE,
    SWP_NOSIZE,
    SWP_SHOWWINDOW,
    ULW_ALPHA,
    WINEVENT_OUTOFCONTEXT,
    WINEVENT_SKIPOWNPROCESS,
    WINEVENTPROC,
    WM_CAPTURECHANGED,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_MOUSEACTIVATE,
    WM_MOUSEMOVE,
    WM_SETCURSOR,
    WNDCLASSEXW,
    WNDPROC,
    WPARAM,
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WS_EX_TRANSPARENT,
    WS_POPUP,
    GetWindowLongPtr,
    SetWindowLongPtr,
    gdi32,
    kernel32,
    user32,
)

printr = Printr()

_CLASS_NAME = "WingmanHeadsUpOverlay"
_EX_STYLE = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE

_CURSORS = {
    Cursor.ARROW: IDC_ARROW,
    Cursor.MOVE: IDC_SIZEALL,
    Cursor.RESIZE_NS: IDC_SIZENS,
    Cursor.RESIZE_WE: IDC_SIZEWE,
    Cursor.RESIZE_NWSE: IDC_SIZENWSE,
    Cursor.RESIZE_NESW: IDC_SIZENESW,
}

_POINTER_MESSAGES = {
    WM_SETCURSOR: Pointer.HOVER,
    WM_LBUTTONDOWN: Pointer.PRESS,
    WM_MOUSEMOVE: Pointer.MOVE,
    WM_LBUTTONUP: Pointer.RELEASE,
    WM_CAPTURECHANGED: Pointer.LOST,
}

_FONT_FILES = {
    "segoe ui": ("segoeuisl.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    "arial": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "verdana": ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
    "tahoma": ("tahoma.ttf", "tahomabd.ttf", "tahoma.ttf", "tahomabd.ttf"),
    "trebuchet ms": ("trebuc.ttf", "trebucbd.ttf", "trebucit.ttf", "trebucbi.ttf"),
    "calibri": ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
    "consolas": ("consola.ttf", "consolab.ttf", "consolai.ttf", "consolaz.ttf"),
    "courier new": ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
}


# ─────────────────────────────── window procedure ─────────────────────────────── #

# hwnd -> handler(msg, wparam, lparam); a handler returns None to fall through
_message_handlers: dict = {}


def _wnd_proc(hwnd, msg, wparam, lparam):
    """Window procedure callback - must handle all message types safely."""
    try:
        handler = _message_handlers.get(int(hwnd)) if hwnd else None
        if handler is not None:
            result = handler(msg, wparam, lparam)
            if result is not None:
                return result
        return user32.DefWindowProcW(hwnd, msg, WPARAM(wparam), LPARAM(lparam))
    except:
        return 0


_wnd_proc_callback = WNDPROC(_wnd_proc)
_class_registered = False


def _ensure_window_class() -> bool:
    global _class_registered
    if _class_registered:
        return True
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = _wnd_proc_callback
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.lpszClassName = _CLASS_NAME
    if user32.RegisterClassExW(ctypes.byref(wc)):
        _class_registered = True
        return True
    return False


def _scale(device: str, width: int) -> float:
    """Physical pixels per HUD pixel. For a process that is not DPI aware, as
    Core is, Windows scales every monitor to 100 %: 3840 px at 125 % become
    3072 px. The HUD draws in those scaled pixels."""
    mode = DEVMODEW()
    mode.dmSize = ctypes.sizeof(DEVMODEW)
    if width > 0 and user32.EnumDisplaySettingsW(device, ENUM_CURRENT_SETTINGS, ctypes.byref(mode)):
        if mode.dmPelsWidth:
            return round(mode.dmPelsWidth / width, 2)
    return 1.0


def _cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _pointer_route(handler: PointerHandler):
    """Win32 mouse messages as the overlay's pointer events."""

    def on_message(msg, wparam, lparam):
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        event = _POINTER_MESSAGES.get(msg)
        if event is None:
            return None
        cursor = handler(event, *_cursor_pos())
        if cursor is not None:
            user32.SetCursor(user32.LoadCursorW(None, ctypes.c_void_p(_CURSORS[cursor])))
        if msg == WM_SETCURSOR:
            # TRUE stops DefWindowProc from putting the class cursor back
            return 1 if cursor is not None else None
        return 0

    return on_message


# ─────────────────────────────── backend ─────────────────────────────── #


@dataclass
class _Window:
    hwnd: Any
    window_dc: Any
    mem_dc: Any
    dib_bitmap: Any = None
    dib_bits: Any = None
    old_bitmap: Any = None
    dib_width: int = 0
    dib_height: int = 0
    shown: bool = True


class WindowsBackend(HudBackend):
    os = OsFamily.WINDOWS

    def __init__(self) -> None:
        self._windows: dict[int, _Window] = {}
        self._foreground_changed = threading.Event()
        self._win_event_hook = None
        self._win_event_proc = None  # keeps the ctypes callback alive

    # ─────────────────────────────── lifecycle ─────────────────────────────── #

    def start(self) -> None:
        if not _ensure_window_class():
            raise HudPlatformError("Failed to register window class")
        self._install_foreground_hook()

    def stop(self) -> None:
        self._uninstall_foreground_hook()
        for window in list(self._windows.values()):
            self.destroy_window(window)

    def pump_events(self) -> None:
        msg = MSG()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        # Another window took the foreground: put the HUD back on top
        if self._foreground_changed.is_set():
            self._foreground_changed.clear()
            for window in list(self._windows.values()):
                if window.shown:
                    self.raise_window(window)

    def _install_foreground_hook(self) -> None:
        """EVENT_SYSTEM_FOREGROUND fires when a different window comes to the
        front, so topmost is re-applied only then, not every frame. Out of
        context: the callback runs on this thread while it pumps messages."""

        def on_foreground_change(hook, event, hwnd, id_object, id_child, event_thread, event_time):
            self._foreground_changed.set()

        self._win_event_proc = WINEVENTPROC(on_foreground_change)
        self._win_event_hook = user32.SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND,
            EVENT_SYSTEM_FOREGROUND,
            None,
            self._win_event_proc,
            0,
            0,
            WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
        )

    def _uninstall_foreground_hook(self) -> None:
        if self._win_event_hook:
            try:
                user32.UnhookWinEvent(self._win_event_hook)
            except Exception:
                pass
        self._win_event_hook = None
        self._win_event_proc = None

    # ─────────────────────────────── windows ─────────────────────────────── #

    def create_window(self, title, x, y, width, height) -> Optional[_Window]:
        hwnd = user32.CreateWindowExW(
            _EX_STYLE, _CLASS_NAME, title, WS_POPUP,
            x, y, width, height,
            None, None, kernel32.GetModuleHandleW(None), None,
        )
        if not hwnd:
            return None
        # Do NOT call SetLayeredWindowAttributes here: once a window has been
        # given per-simple-transparency attributes that way, subsequent
        # UpdateLayeredWindow calls on it fail with ERROR_INVALID_PARAMETER (87).
        # The window stays undefined/invisible until the first real blit via
        # UpdateLayeredWindow (in present) establishes its content.
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, width, height, SWP_NOACTIVATE | SWP_SHOWWINDOW)
        window_dc = user32.GetDC(hwnd)
        window = _Window(hwnd=hwnd, window_dc=window_dc, mem_dc=gdi32.CreateCompatibleDC(window_dc))
        self._windows[int(hwnd)] = window
        return window

    def destroy_window(self, window: _Window) -> None:
        if window.hwnd is None:
            return
        hwnd = window.hwnd
        _message_handlers.pop(int(hwnd), None)
        self._windows.pop(int(hwnd), None)
        try:
            if window.old_bitmap and window.mem_dc:
                gdi32.SelectObject(window.mem_dc, window.old_bitmap)
            if window.dib_bitmap:
                gdi32.DeleteObject(window.dib_bitmap)
            if window.mem_dc:
                gdi32.DeleteDC(window.mem_dc)
            if window.window_dc:
                user32.ReleaseDC(hwnd, window.window_dc)
        except Exception:
            pass
        try:
            user32.DestroyWindow(hwnd)
        except Exception:
            pass
        window.hwnd = window.window_dc = window.mem_dc = None
        window.dib_bitmap = window.dib_bits = window.old_bitmap = None

    def move_window(self, window: _Window, x, y, width, height) -> None:
        user32.MoveWindow(window.hwnd, x, y, width, height, True)

    def raise_window(self, window: _Window) -> None:
        user32.SetWindowPos(
            window.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )

    def show_window(self, window: _Window) -> None:
        # Visibility set by SWP_HIDEWINDOW is independent of per-pixel alpha
        user32.SetWindowPos(
            window.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_SHOWWINDOW | SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
        window.shown = True

    def hide_window(self, window: _Window) -> None:
        user32.SetWindowPos(
            window.hwnd, None, 0, 0, 0, 0,
            SWP_HIDEWINDOW | SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
        window.shown = False

    def present(self, window: _Window, image, opacity: int) -> None:
        """UpdateLayeredWindow with true per-pixel alpha, so bg_opacity shows
        on screen instead of being dropped by a plain BitBlt."""
        if window.hwnd is None or window.mem_dc is None:
            return
        w, h = image.size
        if w != window.dib_width or h != window.dib_height:
            self._resize_dib(window, w, h)
        if not window.dib_bits:
            raise RuntimeError(f"CreateDIBSection failed for {w}x{h}")

        # AC_SRC_ALPHA needs premultiplied alpha: R/G/B scaled by their pixel's alpha
        r, g, b, a = image.split()
        premultiplied = Image.merge(
            "RGBA", (ImageChops.multiply(r, a), ImageChops.multiply(g, a), ImageChops.multiply(b, a), a)
        )
        ctypes.memmove(window.dib_bits, premultiplied.tobytes("raw", "BGRA"), w * h * 4)

        blend = BLENDFUNCTION()
        blend.BlendOp = AC_SRC_OVER
        blend.BlendFlags = 0
        blend.SourceConstantAlpha = max(0, min(255, int(opacity)))
        blend.AlphaFormat = AC_SRC_ALPHA
        size = wintypes.SIZE(w, h)
        src_pos = wintypes.POINT(0, 0)

        ctypes.set_last_error(0)
        ok = user32.UpdateLayeredWindow(
            window.hwnd, None, None, ctypes.byref(size), window.mem_dc,
            ctypes.byref(src_pos), 0, ctypes.byref(blend), ULW_ALPHA,
        )
        if not ok:
            raise RuntimeError(f"UpdateLayeredWindow failed, GetLastError={ctypes.get_last_error()}")

    @staticmethod
    def _resize_dib(window: _Window, w: int, h: int) -> None:
        if window.old_bitmap:
            gdi32.SelectObject(window.mem_dc, window.old_bitmap)
        if window.dib_bitmap:
            gdi32.DeleteObject(window.dib_bitmap)
        window.dib_bitmap = window.dib_bits = window.old_bitmap = None
        # Recorded once the bitmap exists, so a failed size is tried again
        window.dib_width = window.dib_height = 0

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        dib_bits = ctypes.c_void_p()
        dib_bitmap = gdi32.CreateDIBSection(
            window.mem_dc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(dib_bits), None, 0
        )
        if dib_bitmap:
            window.old_bitmap = gdi32.SelectObject(window.mem_dc, dib_bitmap)
            window.dib_bitmap = dib_bitmap
            window.dib_bits = dib_bits
            window.dib_width, window.dib_height = w, h

    # ─────────────────────────────── mouse ─────────────────────────────── #

    def set_click_through(self, window: _Window, click_through: bool) -> None:
        if window.hwnd is None:
            return
        style = GetWindowLongPtr(window.hwnd, GWL_EXSTYLE)
        if click_through:
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        SetWindowLongPtr(window.hwnd, GWL_EXSTYLE, style)

    def set_pointer_handler(self, window: _Window, handler: Optional[PointerHandler]) -> None:
        if window.hwnd is None:
            return
        if handler is None:
            _message_handlers.pop(int(window.hwnd), None)
        else:
            _message_handlers[int(window.hwnd)] = _pointer_route(handler)

    def capture_pointer(self, window: _Window) -> None:
        user32.SetCapture(window.hwnd)

    def release_pointer(self) -> None:
        user32.ReleaseCapture()

    def cursor_position(self) -> tuple[int, int]:
        return _cursor_pos()

    # ─────────────────────────────── screen and fonts ─────────────────────────────── #

    def monitors(self) -> list[Monitor]:
        monitors: list[Monitor] = []

        def on_monitor(hmonitor, hdc, lprect, lparam):
            mi = MONITORINFOEXW()
            mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
            if user32.GetMonitorInfoW(hmonitor, ctypes.byref(mi)):
                rect = mi.rcMonitor
                width = rect.right - rect.left
                monitors.append(
                    Monitor(
                        x=rect.left,
                        y=rect.top,
                        width=width,
                        height=rect.bottom - rect.top,
                        primary=bool(mi.dwFlags & MONITORINFOF_PRIMARY),
                        scale=_scale(mi.szDevice, width),
                    )
                )
            return True

        try:
            callback = MONITORENUMPROC(on_monitor)  # referenced until the call returns
            user32.EnumDisplayMonitors(None, None, callback, 0)
        except Exception as e:
            printr.print(LOG_MONITOR_ERROR.format(e), color=LogType.ERROR, server_only=True)

        if not monitors:
            printr.print(LOG_MONITOR_NONE, color=LogType.WARNING, server_only=True)
            width, height = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
            if width > 0 and height > 0:
                monitors.append(Monitor(0, 0, width, height, True))
        return monitors

    def font_set(self, family: str) -> Optional[FontSet]:
        folder = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        normal, bold, italic, bold_italic = _FONT_FILES.get(family.lower(), _FONT_FILES["segoe ui"])
        return FontSet(
            normal=os.path.join(folder, normal),
            bold=os.path.join(folder, bold),
            italic=os.path.join(folder, italic),
            bold_italic=os.path.join(folder, bold_italic),
            code=os.path.join(folder, "consola.ttf"),
            emoji=(os.path.join(folder, "seguiemj.ttf"), os.path.join(folder, "seguisym.ttf")),
        )
