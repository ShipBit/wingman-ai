"""The HUD's windows on macOS.

AppKit works on the main thread only, and Core's main thread serves the API,
so the windows live in a small process of their own (macos_host.py). This
backend starts it, sends it the window commands and the rendered images, and
hands the mouse events it sends back to the overlay on the overlay thread.

Monitors and the cursor come from Quartz here directly: those calls work on
any thread. The HUD draws in points, the unit macOS lays windows out in; on a
Retina display one point is two pixels.
"""

import json
import os
import queue
import struct
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Optional

from api.enums import LogType
from services.printr import Printr
from hud_server.platform.base import (
    FontSet,
    HudBackend,
    HudPlatformError,
    Monitor,
    OsFamily,
    Pointer,
    PointerHandler,
)

printr = Printr()

_START_TIMEOUT = 15.0
"""Seconds the window process may take to come up (a cold build is slow)."""

_POINTERS = {
    "hover": Pointer.HOVER,
    "press": Pointer.PRESS,
    "move": Pointer.MOVE,
    "release": Pointer.RELEASE,
    "lost": Pointer.LOST,
}

_FONTS = "/System/Library/Fonts"
_SUPPLEMENTAL = "/System/Library/Fonts/Supplemental"


def _family(name: str) -> tuple[str, str, str, str]:
    """Regular, bold, italic and bold italic of a family in Supplemental."""
    return (
        f"{_SUPPLEMENTAL}/{name}.ttf",
        f"{_SUPPLEMENTAL}/{name} Bold.ttf",
        f"{_SUPPLEMENTAL}/{name} Italic.ttf",
        f"{_SUPPLEMENTAL}/{name} Bold Italic.ttf",
    )


# The HUD's fonts are Windows fonts. macOS has some of them; the others get
# the nearest it has (Segoe UI and Calibri: Arial, Consolas: Courier New).
_FONT_FILES = {
    "segoe ui": _family("Arial"),
    "arial": _family("Arial"),
    "calibri": _family("Arial"),
    "verdana": _family("Verdana"),
    "tahoma": (
        f"{_SUPPLEMENTAL}/Tahoma.ttf",
        f"{_SUPPLEMENTAL}/Tahoma Bold.ttf",
        f"{_SUPPLEMENTAL}/Tahoma.ttf",
        f"{_SUPPLEMENTAL}/Tahoma Bold.ttf",
    ),
    "trebuchet ms": (
        f"{_SUPPLEMENTAL}/Trebuchet MS.ttf",
        f"{_SUPPLEMENTAL}/Trebuchet MS Bold.ttf",
        f"{_SUPPLEMENTAL}/Trebuchet MS Italic.ttf",
        f"{_SUPPLEMENTAL}/Trebuchet MS Bold Italic.ttf",
    ),
    "consolas": _family("Courier New"),
    "courier new": _family("Courier New"),
}


def _host_command() -> list[str]:
    """How to start the window process: the build starts itself with a flag
    (main.py), a checkout runs the script."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--hud-host"]
    return [sys.executable, os.path.join(os.path.dirname(__file__), "macos_host.py")]


@dataclass
class _Window:
    id: int
    x: int
    y: int
    width: int
    height: int
    handler: Optional[PointerHandler] = None


class MacOsBackend(HudBackend):
    os = OsFamily.MACOS
    supported = sys.platform == "darwin"
    unsupported_reason = None if supported else "The macOS HUD runs on macOS only."

    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None
        self._events: "queue.Queue[dict]" = queue.Queue()
        self._ready = threading.Event()
        self._write_lock = threading.Lock()
        self._windows: dict[int, _Window] = {}
        self._next_id = 1

    # ─────────────────────────────── lifecycle ─────────────────────────────── #

    def start(self) -> None:
        if not self.supported:
            raise HudPlatformError(self.unsupported_reason)
        try:
            self._process = subprocess.Popen(
                _host_command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
            )
        except OSError as e:
            raise HudPlatformError(f"The HUD window process did not start: {e}") from e
        threading.Thread(target=self._read_events, name="HudHostEvents", daemon=True).start()
        if not self._ready.wait(_START_TIMEOUT):
            self.stop()
            raise HudPlatformError("The HUD window process did not answer.")

    def stop(self) -> None:
        process, self._process = self._process, None
        self._windows.clear()
        if process is None:
            return
        try:
            self._write(process, {"op": "quit"})
            process.stdin.close()
            process.wait(timeout=3)
        except Exception:
            process.kill()

    def pump_events(self) -> None:
        """The mouse events the window process sent, on the overlay thread."""
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                return
            window = self._windows.get(event.get("id"))
            pointer = _POINTERS.get(event.get("type"))
            if window is None or window.handler is None or pointer is None:
                continue
            cursor = window.handler(pointer, int(event["x"]), int(event["y"]))
            if cursor is not None:
                self._send({"op": "cursor", "name": cursor.value})

    def _read_events(self) -> None:
        process = self._process
        stream = process.stdout if process else None
        try:
            while stream is not None:
                head = stream.read(4)
                if len(head) < 4:
                    break
                (length,) = struct.unpack(">I", head)
                event = json.loads(stream.read(length))
                if event.get("ev") == "ready":
                    self._ready.set()
                elif event.get("ev") == "pointer":
                    self._events.put(event)
        except Exception as e:
            printr.print(f"[HUD] The window process stopped talking: {e}", color=LogType.WARNING, server_only=True)

    def _send(self, header: dict, payload: bytes = b"") -> None:
        process = self._process
        if process is None:
            return
        if payload:
            header = {**header, "n": len(payload)}
        try:
            self._write(process, header, payload)
        except (BrokenPipeError, OSError, ValueError) as e:
            raise RuntimeError(f"The HUD window process is gone: {e}") from e

    def _write(self, process: subprocess.Popen, header: dict, payload: bytes = b"") -> None:
        data = json.dumps(header).encode("utf-8")
        with self._write_lock:
            process.stdin.write(struct.pack(">I", len(data)) + data + payload)
            process.stdin.flush()

    # ─────────────────────────────── windows ─────────────────────────────── #

    def create_window(self, title, x, y, width, height) -> Optional[_Window]:
        if self._process is None:
            return None
        window = _Window(self._next_id, int(x), int(y), max(1, int(width)), max(1, int(height)))
        self._next_id += 1
        self._windows[window.id] = window
        self._send({"op": "create", "id": window.id, "x": window.x, "y": window.y,
                    "w": window.width, "h": window.height})
        return window

    def destroy_window(self, window: _Window) -> None:
        if self._windows.pop(window.id, None) is not None:
            self._send({"op": "destroy", "id": window.id})

    def move_window(self, window: _Window, x, y, width, height) -> None:
        window.x, window.y = int(x), int(y)
        window.width, window.height = max(1, int(width)), max(1, int(height))
        self._send({"op": "move", "id": window.id, "x": window.x, "y": window.y,
                    "w": window.width, "h": window.height})

    def raise_window(self, window: _Window) -> None:
        self._send({"op": "raise", "id": window.id})

    def show_window(self, window: _Window) -> None:
        self._send({"op": "show", "id": window.id})

    def hide_window(self, window: _Window) -> None:
        self._send({"op": "hide", "id": window.id})

    def present(self, window: _Window, image, opacity: int) -> None:
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        window.width, window.height = image.size
        self._send(
            {"op": "present", "id": window.id, "x": window.x, "y": window.y,
             "w": window.width, "h": window.height, "opacity": max(0, min(255, int(opacity)))},
            image.tobytes("raw", "RGBA"),
        )

    # ─────────────────────────────── mouse ─────────────────────────────── #

    def set_click_through(self, window: _Window, click_through: bool) -> None:
        self._send({"op": "click_through", "id": window.id, "through": bool(click_through)})

    def set_pointer_handler(self, window: _Window, handler: Optional[PointerHandler]) -> None:
        window.handler = handler

    def capture_pointer(self, window: _Window) -> None:
        # AppKit keeps sending a view the drag that started on it
        pass

    def release_pointer(self) -> None:
        pass

    def cursor_position(self) -> tuple[int, int]:
        import Quartz

        point = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        return round(point.x), round(point.y)

    # ─────────────────────────────── screen and fonts ─────────────────────────────── #

    def monitors(self) -> list[Monitor]:
        """In points, the main display first (its top left is 0,0)."""
        try:
            import Quartz

            error, displays, count = Quartz.CGGetActiveDisplayList(16, None, None)
            if error:
                return []
            main = Quartz.CGMainDisplayID()
            ordered = sorted(displays[:count], key=lambda d: d != main)
            monitors = []
            for display in ordered:
                bounds = Quartz.CGDisplayBounds(display)
                width, height = int(bounds.size.width), int(bounds.size.height)
                mode = Quartz.CGDisplayCopyDisplayMode(display)
                pixels = Quartz.CGDisplayModeGetPixelWidth(mode) if mode else width
                monitors.append(
                    Monitor(
                        x=int(bounds.origin.x),
                        y=int(bounds.origin.y),
                        width=width,
                        height=height,
                        primary=display == main,
                        scale=round(pixels / width, 2) if width else 1.0,
                    )
                )
            return monitors
        except Exception as e:
            printr.print(f"[HUD] Could not list the displays: {e}", color=LogType.WARNING, server_only=True)
            return []

    def font_set(self, family: str) -> Optional[FontSet]:
        normal, bold, italic, bold_italic = _FONT_FILES.get(family.lower(), _FONT_FILES["arial"])
        return FontSet(
            normal=normal,
            bold=bold,
            italic=italic,
            bold_italic=bold_italic,
            code=f"{_FONTS}/Menlo.ttc",
            emoji=(f"{_SUPPLEMENTAL}/Apple Symbols.ttf", f"{_FONTS}/Apple Symbols.ttf"),
        )
