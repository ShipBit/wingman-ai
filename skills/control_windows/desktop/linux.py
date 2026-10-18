"""Control Windows on Linux.

Windows through X11 and the EWMH hints every desktop's window manager
understands (_NET_ACTIVE_WINDOW, _NET_CLOSE_WINDOW, _NET_WM_STATE...), by
ctypes, so nothing has to be installed. In a Wayland session that reaches the
XWayland windows (games under Proton, most native games, many apps); native
Wayland windows are out of reach by design there.

Apps start from their .desktop files, Flatpak's included. The clipboard goes
through wl-clipboard in a Wayland session and xclip or xsel under X11.
"""

import configparser
import ctypes
import ctypes.util
import os
import shlex
import shutil
import subprocess
from ctypes import POINTER, Structure, c_char_p, c_int, c_long, c_ulong, c_void_p
from pathlib import Path
from typing import Optional

from skills.control_windows.desktop.base import Desktop, DesktopError, half, matches

_NO_DISPLAY = (
    "Controlling windows needs X11 or XWayland, and this session has no X display."
)

_APP_FOLDERS = (
    "~/.local/share/applications",
    "~/.local/share/flatpak/exports/share/applications",
    "/var/lib/flatpak/exports/share/applications",
    "/usr/local/share/applications",
    "/usr/share/applications",
)

ClientMessage = 33
SubstructureNotifyMask = 1 << 19
SubstructureRedirectMask = 1 << 20
AnyPropertyType = 0
_NET_WM_STATE_REMOVE, _NET_WM_STATE_ADD = 0, 1
_FROM_PAGER = 2
"""Source indication: a pager or taskbar, which window managers obey."""


class _ClientMessage(Structure):
    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", c_int),
        ("display", c_void_p),
        ("window", c_ulong),
        ("message_type", c_ulong),
        ("format", c_int),
        ("data", c_long * 5),
    ]


class _Event(ctypes.Union):
    _fields_ = [("xclient", _ClientMessage), ("pad", c_long * 24)]


class _Monitor(Structure):
    _fields_ = [
        ("name", c_ulong), ("primary", c_int), ("automatic", c_int), ("noutput", c_int),
        ("x", c_int), ("y", c_int), ("width", c_int), ("height", c_int),
        ("mwidth", c_int), ("mheight", c_int), ("outputs", c_void_p),
    ]


# The handler is the process's, not a connection's: it has to outlive every
# connection, so it lives here
_IGNORE_X_ERRORS = ctypes.CFUNCTYPE(c_int, c_void_p, c_void_p)(lambda display, event: 0)


def _lib(name: str, fallback: str):
    try:
        return ctypes.CDLL(ctypes.util.find_library(name) or fallback)
    except OSError:
        return None


class _X:
    """libX11 with the few calls this needs, one connection per use."""

    def __init__(self) -> None:
        if not os.environ.get("DISPLAY"):
            raise DesktopError(_NO_DISPLAY)
        x = _lib("X11", "libX11.so.6")
        if x is None:
            raise DesktopError(_NO_DISPLAY)
        d, w = c_void_p, c_ulong
        for name, restype, argtypes in (
            ("XOpenDisplay", c_void_p, [c_char_p]),
            ("XCloseDisplay", c_int, [d]),
            ("XDefaultScreen", c_int, [d]),
            ("XRootWindow", w, [d, c_int]),
            ("XInternAtom", c_ulong, [d, c_char_p, c_int]),
            ("XGetWindowProperty", c_int, [
                d, w, c_ulong, c_long, c_long, c_int, c_ulong, POINTER(c_ulong), POINTER(c_int),
                POINTER(c_ulong), POINTER(c_ulong), POINTER(c_void_p),
            ]),
            ("XFree", c_int, [c_void_p]),
            ("XSendEvent", c_int, [d, w, c_int, c_long, POINTER(_Event)]),
            ("XIconifyWindow", c_int, [d, w, c_int]),
            ("XFlush", c_int, [d]),
            ("XSetErrorHandler", c_void_p, [c_void_p]),
        ):
            function = getattr(x, name)
            function.restype, function.argtypes = restype, argtypes
        self.x = x
        self.xrandr = _lib("Xrandr", "libXrandr.so.2")
        if self.xrandr is not None:
            try:
                self.xrandr.XRRGetMonitors.restype = POINTER(_Monitor)
                self.xrandr.XRRGetMonitors.argtypes = [d, w, c_int, POINTER(c_int)]
                self.xrandr.XRRFreeMonitors.argtypes = [POINTER(_Monitor)]
            except AttributeError:
                self.xrandr = None
        # The default handler ends the process on an X error, e.g. a window
        # that closed between listing and acting on it
        x.XSetErrorHandler(ctypes.cast(_IGNORE_X_ERRORS, c_void_p))
        self.display = x.XOpenDisplay(None)
        if not self.display:
            raise DesktopError(_NO_DISPLAY)
        self.screen = x.XDefaultScreen(self.display)
        self.root = x.XRootWindow(self.display, self.screen)

    def close(self) -> None:
        self.x.XCloseDisplay(self.display)

    def atom(self, name: str) -> int:
        return self.x.XInternAtom(self.display, name.encode(), 0)

    def _property(self, window: int, name: str) -> tuple[Optional[bytes], int, int]:
        """(raw data, format, item count) or (None, 0, 0)."""
        kind, fmt = c_ulong(), c_int()
        count, after, data = c_ulong(), c_ulong(), c_void_p()
        status = self.x.XGetWindowProperty(
            self.display, window, self.atom(name), 0, 1 << 16, 0, AnyPropertyType,
            ctypes.byref(kind), ctypes.byref(fmt), ctypes.byref(count), ctypes.byref(after),
            ctypes.byref(data),
        )
        if status != 0 or not data.value:
            return None, 0, 0
        try:
            # Format 32 items are C longs, whatever their size
            size = count.value * (ctypes.sizeof(c_long) if fmt.value == 32 else fmt.value // 8)
            return ctypes.string_at(data.value, size), fmt.value, count.value
        finally:
            self.x.XFree(data)

    def longs(self, window: int, name: str) -> list[int]:
        raw, fmt, count = self._property(window, name)
        if raw is None or fmt != 32:
            return []
        return list((c_long * count).from_buffer_copy(raw))

    def text(self, window: int, name: str) -> str:
        raw, _, _ = self._property(window, name)
        return raw.decode("utf-8", "replace") if raw else ""

    def send(self, window: int, message: str, *data: int) -> None:
        event = _Event()
        event.xclient.type = ClientMessage
        event.xclient.send_event = 1
        event.xclient.window = window
        event.xclient.message_type = self.atom(message)
        event.xclient.format = 32
        for i, value in enumerate(data[:5]):
            event.xclient.data[i] = value
        self.x.XSendEvent(
            self.display, self.root, 0, SubstructureRedirectMask | SubstructureNotifyMask,
            ctypes.byref(event),
        )
        self.x.XFlush(self.display)

    def monitors(self) -> list[tuple[int, int, int, int]]:
        if self.xrandr is None:
            return []
        count = c_int()
        infos = self.xrandr.XRRGetMonitors(self.display, self.root, 1, ctypes.byref(count))
        if not infos:
            return []
        try:
            return [(infos[i].x, infos[i].y, infos[i].width, infos[i].height) for i in range(count.value)]
        finally:
            self.xrandr.XRRFreeMonitors(infos)


class LinuxDesktop(Desktop):
    def _session(self) -> _X:
        return _X()

    def _clients(self, x: _X) -> list[tuple[int, str, str]]:
        """(window, app, title) of every window the window manager lists."""
        result = []
        for window in x.longs(x.root, "_NET_CLIENT_LIST"):
            title = x.text(window, "_NET_WM_NAME") or x.text(window, "WM_NAME")
            # WM_CLASS is "instance\0Class\0": the class names the app
            parts = [p for p in x.text(window, "WM_CLASS").split("\0") if p]
            app = parts[-1] if parts else ""
            result.append((window, app, title))
        return result

    def _targets(self, x: _X, name: str) -> list[int]:
        clients = self._clients(x)
        by_app = [w for w, app, _ in clients if matches(name, app)]
        return by_app or [w for w, _, title in clients if matches(name, title)]

    def _each(self, name: str, act) -> bool:
        x = self._session()
        try:
            windows = self._targets(x, name)
            for window in windows:
                act(x, window)
            return bool(windows)
        finally:
            x.close()

    def list_windows(self) -> list[str]:
        x = self._session()
        try:
            return [f"{app}: {title}" if app else title for _, app, title in self._clients(x) if title or app]
        finally:
            x.close()

    def activate(self, name: str) -> bool:
        return self._each(name, lambda x, w: x.send(w, "_NET_ACTIVE_WINDOW", _FROM_PAGER, 0, 0))

    def close(self, name: str) -> bool:
        return self._each(name, lambda x, w: x.send(w, "_NET_CLOSE_WINDOW", 0, _FROM_PAGER))

    def minimize(self, name: str) -> bool:
        return self._each(name, lambda x, w: x.x.XIconifyWindow(x.display, w, x.screen))

    def maximize(self, name: str) -> bool:
        return self._each(name, lambda x, w: self._maximized(x, w, True))

    def restore(self, name: str) -> bool:
        def restore(x: _X, window: int) -> None:
            self._maximized(x, window, False)
            x.send(window, "_NET_ACTIVE_WINDOW", _FROM_PAGER, 0, 0)

        return self._each(name, restore)

    @staticmethod
    def _maximized(x: _X, window: int, on: bool) -> None:
        x.send(
            window, "_NET_WM_STATE",
            _NET_WM_STATE_ADD if on else _NET_WM_STATE_REMOVE,
            x.atom("_NET_WM_STATE_MAXIMIZED_VERT"), x.atom("_NET_WM_STATE_MAXIMIZED_HORZ"),
            _FROM_PAGER,
        )

    def move(self, name: str, position: str) -> bool:
        def move(x: _X, window: int) -> None:
            self._maximized(x, window, False)
            area_x, area_y, width, height = self._work_area(x)
            left, top, w, h = half(position, area_x, area_y, width, height)
            # x, y, width and height given, gravity NorthWest, from a pager
            flags = 1 | (1 << 8) | (1 << 9) | (1 << 10) | (1 << 11) | (_FROM_PAGER << 12)
            x.send(window, "_NET_MOVERESIZE_WINDOW", flags, left, top, w, h)

        return self._each(name, move)

    @staticmethod
    def _work_area(x: _X) -> tuple[int, int, int, int]:
        """The usable area of the primary monitor: the desktop's work area
        (without panels) cut to the first monitor."""
        work = x.longs(x.root, "_NET_WORKAREA")[:4]
        monitors = x.monitors()
        if not monitors:
            return tuple(work) if len(work) == 4 else (0, 0, 1920, 1080)
        mx, my, mw, mh = monitors[0]
        if len(work) != 4:
            return mx, my, mw, mh
        wx, wy, ww, wh = work
        left, top = max(mx, wx), max(my, wy)
        right, bottom = min(mx + mw, wx + ww), min(my + mh, wy + wh)
        if right <= left or bottom <= top:
            return mx, my, mw, mh
        return left, top, right - left, bottom - top

    # ─────────────────────────────── apps ─────────────────────────────── #

    def open_app(self, name: str) -> bool:
        needle = name.strip().lower()
        if not needle:
            return False
        found = []
        for folder in _APP_FOLDERS:
            root = Path(os.path.expanduser(folder))
            if not root.is_dir():
                continue
            for desktop_file in root.glob("*.desktop"):
                entry = _desktop_entry(desktop_file)
                if entry is None:
                    continue
                label, command = entry
                if needle in label.lower() or needle in desktop_file.stem.lower():
                    found.append((label, desktop_file, command))
        if not found:
            return False
        # "Steam" should start Steam, not "Steam Link"
        found.sort(key=lambda f: (f[0].lower() != needle, len(f[0])))
        _, desktop_file, command = found[0]
        if shutil.which("gio"):
            # No pipes: the app inherits them, and reading them would wait
            # until the app quits
            try:
                return subprocess.run(
                    ["gio", "launch", str(desktop_file)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
                ).returncode == 0
            except subprocess.TimeoutExpired:
                return False
        try:
            subprocess.Popen(command, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            return False

    # ─────────────────────────────── clipboard ─────────────────────────────── #

    @staticmethod
    def _clipboard_tool(read: bool) -> list[str]:
        if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
            return ["wl-paste", "--no-newline"] if read else ["wl-copy"]
        if shutil.which("xclip"):
            return ["xclip", "-selection", "clipboard"] + (["-o"] if read else [])
        if shutil.which("xsel"):
            return ["xsel", "--clipboard"] + (["--output"] if read else ["--input"])
        raise DesktopError(
            "The clipboard needs wl-clipboard (Wayland) or xclip (X11). Install one with your package manager."
        )

    def get_clipboard(self) -> str:
        result = subprocess.run(self._clipboard_tool(True), capture_output=True, timeout=5)
        if result.returncode != 0:
            raise KeyError("text")
        return result.stdout.decode("utf-8", "replace")

    def set_clipboard(self, text: str) -> None:
        # wl-copy and xclip stay in the background to serve the clipboard
        process = subprocess.Popen(
            self._clipboard_tool(False), stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        process.stdin.write(text.encode("utf-8"))
        process.stdin.close()


def _desktop_entry(path: Path) -> Optional[tuple[str, list[str]]]:
    """(Name, command) of a launchable .desktop file, None for hidden ones."""
    parser = configparser.RawConfigParser(interpolation=None, strict=False)
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError, OSError):
        return None
    if not parser.has_section("Desktop Entry"):
        return None
    entry = parser["Desktop Entry"]
    if entry.get("Type", "Application") != "Application":
        return None
    if entry.get("NoDisplay", "").lower() == "true" or entry.get("Hidden", "").lower() == "true":
        return None
    label, command = entry.get("Name", ""), entry.get("Exec", "")
    if not label or not command:
        return None
    try:
        # Field codes (%f, %U, ...) are for files to open: none here
        parts = [p for p in shlex.split(command) if not (len(p) == 2 and p.startswith("%"))]
    except ValueError:
        return None
    return (label, parts) if parts else None
