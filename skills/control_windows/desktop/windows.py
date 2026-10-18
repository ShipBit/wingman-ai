"""Control Windows on Windows: PyGetWindow for the windows, the Start Menu's
shortcuts to start apps, clip-util for the clipboard. The behaviour the skill
had before it ran on other OSes."""

import os
import time
from pathlib import Path

import mouse.mouse as mouse
import pygetwindow as gw
from clipboard import Clipboard

from skills.control_windows.desktop.base import Desktop


def _start_menu_paths() -> list[Path]:
    paths = []
    for env_var in ("APPDATA", "PROGRAMDATA"):
        base = os.environ.get(env_var)
        if base:
            paths.append(Path(base, "Microsoft", "Windows", "Start Menu", "Programs"))
    return paths


def _files(directory: Path, extension: str):
    for item in directory.iterdir():
        if item.is_dir():
            yield from _files(item, extension)
        elif item.is_file() and item.suffix == extension:
            yield item


class WindowsDesktop(Desktop):
    def _windows(self, name: str):
        # An empty name would match every window
        if not name or not name.strip():
            return []
        name = name.strip()
        windows = gw.getWindowsWithTitle(name)
        # Microsoft puts a zero-width space into Edge's titles:
        # https://github.com/asweigart/PyGetWindow/issues/54
        if not windows and "microsoft edge" in name.lower():
            name = name.replace("Microsoft Edge", "Microsoft​ Edge")
            name = name.replace("microsoft edge", "Microsoft​ Edge")
            windows = gw.getWindowsWithTitle(name)
        return windows

    def _each(self, name: str, command: str) -> bool:
        windows = self._windows(name)
        for window in windows:
            try:
                getattr(window, command)()
            except AttributeError:
                pass
        return bool(windows)

    def list_windows(self) -> list[str]:
        return [t for t in gw.getAllTitles() if t and t.strip()]

    def activate(self, name: str) -> bool:
        windows = self._windows(name)
        if not windows:
            return False
        for window in windows:
            # A plain activate often fails:
            # https://github.com/asweigart/PyGetWindow/issues/36#issuecomment-919332733
            try:
                window.minimize()
                window.restore()
                window.activate()
            except Exception:
                return False
        return True

    def close(self, name: str) -> bool:
        windows = self._windows(name)
        if not windows:
            return False
        for window in windows:
            try:
                window.close()
            except Exception:
                return False
        return True

    def minimize(self, name: str) -> bool:
        return self._each(name, "minimize")

    def maximize(self, name: str) -> bool:
        return self._each(name, "maximize")

    def restore(self, name: str) -> bool:
        return self._each(name, "restore")

    def move(self, name: str, position: str) -> bool:
        moved = False
        for window in self._windows(name):
            if self._move_window(window, position):
                moved = True
        return moved

    @staticmethod
    def _move_window(window, position: str) -> bool:
        try:
            window.minimize()
            window.restore()
            # Maximized, the window shows what a full screen is in this setup
            window.maximize()
            time.sleep(0.5)
        except Exception:
            pass
        width, height = window.size
        try:
            if position == "left":
                window.resizeTo(int(width * 0.5), int(height))
                window.moveTo(0, 0)
            if position == "right":
                window.resizeTo(int(width * 0.5), int(height))
                window.moveTo(int(width * 0.5), 0)
            if position == "top":
                window.resizeTo(int(width), int(height * 0.5))
                window.moveTo(0, 0)
            if position == "bottom":
                window.resizeTo(int(width), int(height * 0.5))
                window.moveTo(0, int(height * 0.5))
            if (width, height) != window.size:
                return True
            # Some windows refuse: drag them by their title bar
            if position in ("left", "right"):
                target = 20 if position == "left" else width - 20
                mouse.move(int(width * 0.5), 10, duration=1.0)
                time.sleep(0.1)
                mouse.press(button="left")
                mouse.move(target, 10, duration=1.0)
                time.sleep(0.1)
                mouse.release(button="left")
                return True
            return False
        except Exception:
            return False

    def open_app(self, name: str) -> bool:
        if not name or not name.strip():
            return False
        name = name.strip().lower()
        for start_menu in _start_menu_paths():
            if not start_menu.exists():
                continue
            for shortcut in _files(start_menu, ".lnk"):
                if name in shortcut.stem.lower():
                    try:
                        os.startfile(str(shortcut))
                    except Exception:
                        return False
                    return True
        return False

    def get_clipboard(self) -> str:
        with Clipboard() as clipboard:
            return clipboard["text"]

    def set_clipboard(self, text: str) -> None:
        with Clipboard() as clipboard:
            clipboard.set_clipboard(text)
