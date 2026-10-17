"""What the overlay needs from the operating system, as one interface.

The overlay renders every HUD window into a PIL image itself, on every OS.
Putting that image on screen is the backend's job: transparent windows that
stay above other apps, let the mouse through and never take the focus.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

from api.enums import LogType
from services.printr import Printr
from hud_server.constants import (
    LOG_MONITORS_AVAILABLE,
    LOG_MONITOR_FALLBACK_UNAVAILABLE,
    LOG_MONITOR_NONE_AVAILABLE,
    LOG_MONITOR_SELECTED,
)

printr = Printr()


class OsFamily(str, Enum):
    """Named as in a skill's `platforms` list."""

    WINDOWS = "windows"
    MACOS = "darwin"
    LINUX = "linux"


class Cursor(str, Enum):
    ARROW = "arrow"
    MOVE = "move"
    RESIZE_NS = "resize_ns"
    RESIZE_WE = "resize_we"
    RESIZE_NWSE = "resize_nwse"
    RESIZE_NESW = "resize_nesw"


class Pointer(str, Enum):
    """What the mouse did over a window that takes the mouse."""

    HOVER = "hover"
    """Over the window; the handler answers with the cursor to show."""
    PRESS = "press"
    """Left button down."""
    MOVE = "move"
    RELEASE = "release"
    """Left button up."""
    LOST = "lost"
    """The capture ended without a release."""


PointerHandler = Callable[[Pointer, int, int], Optional[Cursor]]
"""(event, screen x, screen y) -> the cursor to show, or None to leave it."""


@dataclass(frozen=True)
class Monitor:
    """A monitor in the HUD's coordinates (the virtual desktop as this process
    sees it). With Windows display scaling those are scaled pixels."""

    x: int
    y: int
    width: int
    height: int
    primary: bool = False
    scale: float = 1.0
    """Physical pixels per HUD pixel: 1.25 for a monitor at 125 % scaling."""

    def describe(self) -> str:
        """'3072x1728', or '3072x1728 (3840x2160 at 125 %)' on a scaled monitor."""
        size = f"{self.width}x{self.height}"
        if abs(self.scale - 1.0) < 0.01:
            return size
        physical = f"{round(self.width * self.scale)}x{round(self.height * self.scale)}"
        return f"{size} ({physical} at {round(self.scale * 100)} %)"


FALLBACK_MONITOR = Monitor(0, 0, 1920, 1080, True)


@dataclass(frozen=True)
class FontSet:
    """Font files (full paths) the overlay draws one font family with."""

    normal: str
    bold: str
    italic: str
    bold_italic: str
    code: str
    emoji: tuple[str, ...] = ()


class HudPlatformError(RuntimeError):
    """The backend cannot draw the HUD here; the message says why."""


class HudBackend(ABC):
    """The windows of one operating system.

    Window calls, `start`, `stop` and `pump_events` run on the overlay thread:
    most OSes tie a window to the thread that made it. `monitors` and
    `font_set` may run on any thread. A window is whatever `create_window`
    returns; the overlay only hands it back.
    """

    os: Optional[OsFamily] = None
    supported = True
    """False where no backend is written yet; the HUD then stays off."""
    unsupported_reason: Optional[str] = None

    # ─────────────────────────────── lifecycle ─────────────────────────────── #

    @abstractmethod
    def start(self) -> None:
        """Prepare the overlay thread. Raises HudPlatformError if the HUD cannot run."""

    @abstractmethod
    def stop(self) -> None:
        """Release what `start` set up and every window still open."""

    @abstractmethod
    def pump_events(self) -> None:
        """Once per frame: handle the OS's events, keep shown windows above other apps."""

    # ─────────────────────────────── windows ─────────────────────────────── #

    @abstractmethod
    def create_window(self, title: str, x: int, y: int, width: int, height: int) -> Optional[Any]:
        """A shown, click-through, always-on-top window that never takes the
        focus. Its content stays invisible until the first `present`. None if
        the OS refused."""

    @abstractmethod
    def destroy_window(self, window: Any) -> None: ...

    @abstractmethod
    def move_window(self, window: Any, x: int, y: int, width: int, height: int) -> None: ...

    @abstractmethod
    def raise_window(self, window: Any) -> None:
        """Put the window back above other apps."""

    @abstractmethod
    def show_window(self, window: Any) -> None: ...

    @abstractmethod
    def hide_window(self, window: Any) -> None: ...

    @abstractmethod
    def present(self, window: Any, image: Any, opacity: int) -> None:
        """Show an RGBA PIL image (straight alpha) in the window, faded to
        `opacity` (0-255). The window takes the image's size. Raises on failure."""

    # ─────────────────────────────── mouse (preview) ─────────────────────────────── #

    @abstractmethod
    def set_click_through(self, window: Any, click_through: bool) -> None: ...

    @abstractmethod
    def set_pointer_handler(self, window: Any, handler: Optional[PointerHandler]) -> None:
        """Send the window's mouse events to `handler` (None stops them)."""

    @abstractmethod
    def capture_pointer(self, window: Any) -> None:
        """Keep sending this window the mouse while the button is held, even outside it."""

    @abstractmethod
    def release_pointer(self) -> None: ...

    @abstractmethod
    def cursor_position(self) -> tuple[int, int]:
        """The mouse in virtual desktop coordinates."""

    # ─────────────────────────────── screen and fonts ─────────────────────────────── #

    @abstractmethod
    def monitors(self) -> list[Monitor]:
        """Every monitor, in the order the OS reports them."""

    def font_set(self, family: str) -> Optional[FontSet]:
        """The files of a font family (or of the OS's UI font if it has none of
        that name). None leaves the overlay to Pillow's fallback fonts."""
        return None

    def monitor(self, screen: int) -> Monitor:
        """The HUD's monitor: screen 1 is the first, a missing one falls back to the last."""
        monitors = self.monitors()
        if not monitors:
            printr.print(LOG_MONITOR_NONE_AVAILABLE, color=LogType.WARNING, server_only=True)
            return FALLBACK_MONITOR

        printr.print(
            LOG_MONITORS_AVAILABLE.format(
                ", ".join(
                    f"{i + 1}: {m.describe()}{' primary' if m.primary else ''}"
                    for i, m in enumerate(monitors)
                )
            ),
            color=LogType.INFO,
            server_only=True,
        )
        index = max(1, screen) - 1
        if index < len(monitors):
            chosen = monitors[index]
            printr.print(
                LOG_MONITOR_SELECTED.format(screen, chosen.width, chosen.height),
                color=LogType.INFO,
                server_only=True,
            )
            return chosen

        chosen = monitors[-1]
        printr.print(
            LOG_MONITOR_FALLBACK_UNAVAILABLE.format(
                screen, len(monitors), chosen.width, chosen.height
            ),
            color=LogType.WARNING,
            server_only=True,
        )
        return chosen


class UnsupportedBackend(HudBackend):
    """An OS without a HUD backend: no windows, and `start` says why."""

    supported = False

    def __init__(self, reason: Optional[str] = None, os: Optional[OsFamily] = None) -> None:
        if reason:
            self.unsupported_reason = reason
        if os:
            self.os = os
        if not self.unsupported_reason:
            self.unsupported_reason = "The HUD does not run on this operating system."

    def start(self) -> None:
        raise HudPlatformError(self.unsupported_reason)

    def stop(self) -> None:
        pass

    def pump_events(self) -> None:
        pass

    def create_window(self, title, x, y, width, height):
        return None

    def destroy_window(self, window) -> None:
        pass

    def move_window(self, window, x, y, width, height) -> None:
        pass

    def raise_window(self, window) -> None:
        pass

    def show_window(self, window) -> None:
        pass

    def hide_window(self, window) -> None:
        pass

    def present(self, window, image, opacity) -> None:
        pass

    def set_click_through(self, window, click_through) -> None:
        pass

    def set_pointer_handler(self, window, handler) -> None:
        pass

    def capture_pointer(self, window) -> None:
        pass

    def release_pointer(self) -> None:
        pass

    def cursor_position(self) -> tuple[int, int]:
        return 0, 0

    def monitors(self) -> list[Monitor]:
        return []
