"""Control Windows on macOS.

Apps through AppKit (NSWorkspace, NSRunningApplication), their windows through
the Accessibility API, which needs the Accessibility permission Wingman asks
for on its first start. The window list comes from Quartz; without the Screen
Recording permission macOS leaves out the titles and only the apps show.

Coordinates: the Accessibility API counts from the top left of the main
display, y going down; AppKit's screens count from its bottom left, y going up.
"""

import os
import subprocess
from pathlib import Path
from typing import Any, Optional

from AppKit import NSPasteboard, NSPasteboardTypeString, NSScreen, NSWorkspace
from ApplicationServices import (
    AXIsProcessTrusted,
    AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication,
    AXUIElementPerformAction,
    AXUIElementSetAttributeValue,
    AXValueCreate,
    AXValueGetValue,
    kAXCloseButtonAttribute,
    kAXMinimizedAttribute,
    kAXPositionAttribute,
    kAXPressAction,
    kAXRoleAttribute,
    kAXRaiseAction,
    kAXSizeAttribute,
    kAXTitleAttribute,
    kAXValueCGPointType,
    kAXValueCGSizeType,
    kAXWindowsAttribute,
)
from Quartz import (
    CGPointMake,
    CGSizeMake,
    CGWindowListCopyWindowInfo,
    kCGNullWindowID,
    kCGWindowListExcludeDesktopElements,
    kCGWindowListOptionOnScreenOnly,
)

from skills.control_windows.desktop.base import Desktop, DesktopError, half, matches

_REGULAR = 0
"""NSApplicationActivationPolicyRegular: an app with a Dock icon and windows."""

_APP_FOLDERS = (
    "/Applications",
    "/Applications/Utilities",
    "/System/Applications",
    "/System/Applications/Utilities",
    os.path.expanduser("~/Applications"),
)

_NO_PERMISSION = (
    "Wingman AI needs the Accessibility permission to control other apps' windows. "
    "Allow it in System Settings, Privacy & Security, Accessibility."
)


def _attribute(element, name) -> Any:
    error, value = AXUIElementCopyAttributeValue(element, name, None)
    return value if error == 0 else None


def _point(value) -> Optional[tuple[float, float]]:
    ok, point = AXValueGetValue(value, kAXValueCGPointType, None)
    return (point.x, point.y) if ok else None


def _size(value) -> Optional[tuple[float, float]]:
    ok, size = AXValueGetValue(value, kAXValueCGSizeType, None)
    return (size.width, size.height) if ok else None


class MacDesktop(Desktop):
    # ─────────────────────────────── finding ─────────────────────────────── #

    @staticmethod
    def _apps() -> list:
        return [
            app for app in NSWorkspace.sharedWorkspace().runningApplications()
            if app.activationPolicy() == _REGULAR
        ]

    @staticmethod
    def _names(app) -> tuple[str, ...]:
        """The shown name ("Rechner" on a German Mac) and the bundle's own
        ("Calculator"), so either finds the app."""
        names = [app.localizedName() or ""]
        url = app.bundleURL()
        if url is not None and url.path():
            names.append(Path(str(url.path())).stem)
        return tuple(names)

    def _require_permission(self) -> None:
        if not AXIsProcessTrusted():
            raise DesktopError(_NO_PERMISSION)

    def _targets(self, name: str) -> list[tuple[Any, list]]:
        """(app, its windows to act on) for every app the name matches, else
        for every window whose title it matches."""
        self._require_permission()
        by_app, by_title = [], []
        for app in self._apps():
            element = AXUIElementCreateApplication(app.processIdentifier())
            # Only real windows: without full Accessibility access macOS
            # hands out placeholders that are the app again
            windows = [
                w for w in (_attribute(element, kAXWindowsAttribute) or [])
                if _attribute(w, kAXRoleAttribute) == "AXWindow"
            ]
            if matches(name, *self._names(app)):
                by_app.append((app, windows))
                continue
            titled = [w for w in windows if matches(name, _attribute(w, kAXTitleAttribute))]
            if titled:
                by_title.append((app, titled))
        return by_app or by_title

    # ─────────────────────────────── windows ─────────────────────────────── #

    def list_windows(self) -> list[str]:
        infos = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements, kCGNullWindowID
        ) or []
        seen, result = set(), []
        for info in infos:
            if info.get("kCGWindowLayer", 0) != 0:
                continue
            owner = info.get("kCGWindowOwnerName") or ""
            title = info.get("kCGWindowName") or ""
            entry = f"{owner}: {title}" if title else owner
            if entry and entry not in seen:
                seen.add(entry)
                result.append(entry)
        # Minimized windows and apps without a window on this desktop
        for app in self._apps():
            name = app.localizedName()
            if name and not any(e == name or e.startswith(f"{name}: ") for e in seen):
                seen.add(name)
                result.append(name)
        return result

    def activate(self, name: str) -> bool:
        targets = self._targets(name)
        for app, windows in targets:
            for window in windows:
                AXUIElementSetAttributeValue(window, kAXMinimizedAttribute, False)
            if windows:
                AXUIElementPerformAction(windows[0], kAXRaiseAction)
            # Frontmost through Accessibility: a background process like Core
            # may not activate another app itself
            element = AXUIElementCreateApplication(app.processIdentifier())
            AXUIElementSetAttributeValue(element, "AXFrontmost", True)
        return bool(targets)

    def close(self, name: str) -> bool:
        self._require_permission()
        apps = [app for app in self._apps() if matches(name, *self._names(app))]
        if apps:
            # The app quits as from its menu, and asks about unsaved work itself
            return all(app.terminate() for app in apps)
        closed = False
        for _, windows in self._targets(name):
            for window in windows:
                button = _attribute(window, kAXCloseButtonAttribute)
                if button is not None and AXUIElementPerformAction(button, kAXPressAction) == 0:
                    closed = True
        return closed

    def minimize(self, name: str) -> bool:
        return self._set_each(name, kAXMinimizedAttribute, True)

    def restore(self, name: str) -> bool:
        return self._set_each(name, kAXMinimizedAttribute, False)

    def _set_each(self, name: str, attribute, value) -> bool:
        done = False
        for _, windows in self._targets(name):
            for window in windows:
                if AXUIElementSetAttributeValue(window, attribute, value) == 0:
                    done = True
        return done

    def maximize(self, name: str) -> bool:
        return self._place(name, None)

    def move(self, name: str, position: str) -> bool:
        return self._place(name, position)

    def _place(self, name: str, position: Optional[str]) -> bool:
        """The usable part of the window's screen (without menu bar and Dock),
        or one half of it."""
        placed = False
        for _, windows in self._targets(name):
            for window in windows:
                AXUIElementSetAttributeValue(window, kAXMinimizedAttribute, False)
                area = self._screen_area(window)
                x, y, width, height = half(position, *area) if position else area
                # Size, move, size again: a window may refuse a size that
                # would cross the screen's edge before it has moved
                AXUIElementSetAttributeValue(window, kAXSizeAttribute, AXValueCreate(kAXValueCGSizeType, CGSizeMake(width, height)))
                moved = AXUIElementSetAttributeValue(window, kAXPositionAttribute, AXValueCreate(kAXValueCGPointType, CGPointMake(x, y)))
                AXUIElementSetAttributeValue(window, kAXSizeAttribute, AXValueCreate(kAXValueCGSizeType, CGSizeMake(width, height)))
                placed = placed or moved == 0
        return placed

    @staticmethod
    def _screen_area(window) -> tuple[int, int, int, int]:
        """The visible frame of the screen the window's middle is on, in
        Accessibility coordinates."""
        screens = NSScreen.screens()
        main_height = screens[0].frame().size.height
        position = _point(_attribute(window, kAXPositionAttribute)) or (0, 0)
        size = _size(_attribute(window, kAXSizeAttribute)) or (0, 0)
        cx, cy = position[0] + size[0] / 2, position[1] + size[1] / 2
        chosen = screens[0]
        for screen in screens:
            frame = screen.frame()
            top = main_height - frame.origin.y - frame.size.height
            if frame.origin.x <= cx < frame.origin.x + frame.size.width and top <= cy < top + frame.size.height:
                chosen = screen
                break
        visible = chosen.visibleFrame()
        top = main_height - visible.origin.y - visible.size.height
        return int(visible.origin.x), int(top), int(visible.size.width), int(visible.size.height)

    # ─────────────────────────────── apps ─────────────────────────────── #

    def open_app(self, name: str) -> bool:
        needle = name.strip().lower()
        if not needle:
            return False
        found = []
        for folder in _APP_FOLDERS:
            root = Path(folder)
            if not root.is_dir():
                continue
            for app in root.glob("*.app"):
                if needle in app.stem.lower():
                    found.append(app)
        if not found:
            return False
        # "Notes" should start Notes, not "Sticky Notes"
        found.sort(key=lambda app: (app.stem.lower() != needle, len(app.stem)))
        try:
            return subprocess.run(
                ["open", str(found[0])],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
            ).returncode == 0
        except subprocess.TimeoutExpired:
            return False

    # ─────────────────────────────── clipboard ─────────────────────────────── #

    def get_clipboard(self) -> str:
        text = NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString)
        if text is None:
            raise KeyError("text")
        return str(text)

    def set_clipboard(self, text: str) -> None:
        board = NSPasteboard.generalPasteboard()
        board.clearContents()
        board.setString_forType_(text, NSPasteboardTypeString)
