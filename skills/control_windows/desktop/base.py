"""What Control Windows needs from the desktop.

Every call is blocking; the skill runs them in a thread. Window calls take the
name the user said and act on every window it matches: an app's name or a
window title, case-insensitive, by substring. They return False when nothing
matched or the OS refused.
"""

from abc import ABC, abstractmethod

POSITIONS = ("left", "right", "top", "bottom")


class DesktopError(RuntimeError):
    """Something the user has to fix (a permission, a missing tool); the
    message says what, and the skill passes it on."""


class Desktop(ABC):
    @abstractmethod
    def list_windows(self) -> list[str]:
        """The open windows, as "App: title" or the title alone."""

    @abstractmethod
    def activate(self, name: str) -> bool: ...

    @abstractmethod
    def close(self, name: str) -> bool: ...

    @abstractmethod
    def minimize(self, name: str) -> bool: ...

    @abstractmethod
    def maximize(self, name: str) -> bool: ...

    @abstractmethod
    def restore(self, name: str) -> bool: ...

    @abstractmethod
    def move(self, name: str, position: str) -> bool:
        """Into one half of its screen: left, right, top or bottom."""

    @abstractmethod
    def open_app(self, name: str) -> bool:
        """Start an installed app whose name contains `name`."""

    @abstractmethod
    def get_clipboard(self) -> str:
        """The clipboard's text. KeyError when it holds no text."""

    @abstractmethod
    def set_clipboard(self, text: str) -> None: ...


def half(position: str, x: int, y: int, width: int, height: int) -> tuple[int, int, int, int]:
    """One half of the area (x, y, width, height) as (x, y, width, height)."""
    if position == "left":
        return x, y, width // 2, height
    if position == "right":
        return x + width // 2, y, width - width // 2, height
    if position == "top":
        return x, y, width, height // 2
    return x, y + height // 2, width, height - height // 2


def matches(name: str, *candidates: str) -> bool:
    needle = name.strip().lower()
    return bool(needle) and any(needle in (c or "").lower() for c in candidates)
