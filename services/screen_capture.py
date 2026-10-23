"""Screenshots for skills (`self.wingman.screen`), on every OS.

Windows, macOS and Linux under X11 use mss. Under Wayland mss only sees the
XWayland windows and gives black for the rest, so a Wayland session asks the
desktop instead, in this order:

1. KDE Plasma: Spectacle in background mode. KDE lets it take screenshots
   without asking.
2. Sway, Hyprland and other wlroots desktops: grim.
3. Any desktop with xdg-desktop-portal (GNOME among them): the Screenshot
   portal. The desktop may ask the user once to allow it.

Under Wayland there is no picking a monitor: the shot covers the monitor the
desktop tool chooses (Spectacle: the one under the mouse) or all of them.
"""

import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from typing import Optional
from urllib.parse import unquote, urlparse

from PIL import Image

PORTAL_TIMEOUT = 60
"""Seconds to wait for the portal: the first time the desktop may ask the user."""


class ScreenCaptureError(RuntimeError):
    """The screen could not be captured; the message says what to do."""


def is_wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY")) or os.environ.get("XDG_SESSION_TYPE") == "wayland"


def capture(display: int = 1, region: Optional[dict] = None) -> Image.Image:
    """An RGB image of monitor `display` (1 = the first, 0 = all of them, as
    in mss), or of `region` ({"left", "top", "width", "height"}) when given.
    Blocking: call it from a thread."""
    if is_wayland():
        image = _wayland()
        if region:
            image = image.crop((
                region["left"], region["top"],
                region["left"] + region["width"], region["top"] + region["height"],
            ))
        return image
    return _mss(display, region)


def _mss(display: int, region: Optional[dict]) -> Image.Image:
    from mss import mss
    from mss.exception import ScreenShotError

    try:
        return _grab(mss, display, region)
    except ScreenShotError as e:
        if sys.platform == "darwin":
            raise ScreenCaptureError(
                "macOS did not allow the screenshot. Allow Wingman AI under System Settings, "
                "Privacy & Security, Screen Recording."
            ) from e
        raise ScreenCaptureError(f"The screen could not be captured: {e}") from e


def _grab(mss, display: int, region: Optional[dict]) -> Image.Image:
    with mss() as sct:
        if region:
            shot = sct.grab(region)
        else:
            if not 0 <= display < len(sct.monitors):
                display = 1 if len(sct.monitors) > 1 else 0
            shot = sct.grab(sct.monitors[display])
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


# ─────────────────────────────── Wayland ─────────────────────────────── #


def _wayland() -> Image.Image:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "kde" in desktop and shutil.which("spectacle"):
        return _with_file(lambda path: ["spectacle", "--background", "--nonotify", "--current", "--output", path])
    if shutil.which("grim") and not any(name in desktop for name in ("kde", "gnome")):
        return _with_file(lambda path: ["grim", path])
    return _portal()


def _with_file(command) -> Image.Image:
    """Run a tool that writes a PNG to the path it is given, and read it."""
    folder = tempfile.mkdtemp(prefix="wingman-shot-")
    path = os.path.join(folder, "screen.png")
    try:
        result = subprocess.run(
            command(path), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=20
        )
        if result.returncode != 0 or not os.path.exists(path):
            raise ScreenCaptureError(
                f"{command(path)[0]} could not take a screenshot: "
                f"{result.stderr.decode('utf-8', 'replace').strip()[:200]}"
            )
        with Image.open(path) as image:
            return image.convert("RGB")
    except subprocess.TimeoutExpired as e:
        raise ScreenCaptureError(f"{command(path)[0]} took too long to take a screenshot.") from e
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _portal() -> Image.Image:
    """org.freedesktop.portal.Screenshot, non-interactive. The portal saves
    the shot as a file and answers with its URI; the file is ours to delete."""
    try:
        from jeepney import DBusAddress, DBusErrorResponse, MatchRule, new_method_call
        from jeepney.bus_messages import message_bus
        from jeepney.io.blocking import open_dbus_connection
        from jeepney.wrappers import unwrap_msg
    except ImportError as e:
        raise ScreenCaptureError("Screenshots under Wayland need the jeepney package.") from e

    try:
        connection = open_dbus_connection(bus="SESSION")
    except Exception as e:
        raise ScreenCaptureError(f"No D-Bus session for the screenshot portal: {e}") from e
    try:
        token = f"wingman_{secrets.token_hex(8)}"
        sender = connection.unique_name.lstrip(":").replace(".", "_")
        request_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        rule = MatchRule(
            type="signal", interface="org.freedesktop.portal.Request",
            member="Response", path=request_path,
        )
        connection.send_and_get_reply(message_bus.AddMatch(rule))
        portal = DBusAddress(
            "/org/freedesktop/portal/desktop",
            bus_name="org.freedesktop.portal.Desktop",
            interface="org.freedesktop.portal.Screenshot",
        )
        with connection.filter(rule) as responses:
            reply = connection.send_and_get_reply(new_method_call(
                portal, "Screenshot", "sa{sv}",
                ("", {"handle_token": ("s", token), "interactive": ("b", False)}),
            ))
            try:
                unwrap_msg(reply)
            except DBusErrorResponse as e:
                raise ScreenCaptureError(f"The desktop has no screenshot portal: {e}") from e
            try:
                signal = connection.recv_until_filtered(responses, timeout=PORTAL_TIMEOUT)
            except TimeoutError as e:
                raise ScreenCaptureError("The screenshot portal did not answer in time.") from e
        code, results = signal.body
        if code != 0:
            raise ScreenCaptureError(
                "The desktop did not allow the screenshot. Allow Wingman AI to take screenshots when it asks."
            )
        path = unquote(urlparse(results["uri"][1]).path)
        try:
            with Image.open(path) as image:
                return image.convert("RGB")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    finally:
        connection.close()
