"""The process that holds the HUD's windows on macOS.

AppKit works on the main thread only, and Core's main thread serves the API.
So the macOS backend (macos.py) starts this as its own small process: it runs
an AppKit event loop, makes one borderless panel per HUD window and puts the
images the overlay rendered on them. Core sends the commands over stdin and
gets the mouse back over stdout.

Every message is a 4-byte big-endian length, a JSON header of that length
and, when the header has "n", n bytes of payload (an image's RGBA pixels).

Coordinates are the HUD's: points on the virtual desktop, origin at the top
left of the main display, y going down (Quartz's global display space). This
process turns them into Cocoa's, whose y goes up from the bottom of the main
display.

Run by itself: `python hud_server/platform/macos_host.py`, or `WingmanAiCore
--hud-host` in a build. It imports nothing from Core.
"""

import json
import os
import struct
import sys
import threading

import objc
from AppKit import (
    NSApplication,
    NSBackingStoreBuffered,
    NSColor,
    NSCursor,
    NSEvent,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSTrackingArea,
    NSView,
)
from Foundation import NSData
from PyObjCTools import AppHelper
from Quartz import (
    CGColorSpaceCreateDeviceRGB,
    CGDataProviderCreateWithCFData,
    CGImageCreate,
    kCGBitmapByteOrderDefault,
    kCGImageAlphaLast,
    kCGRenderingIntentDefault,
)

# AppKit constants, as numbers: their Python names moved between PyObjC releases
_STYLE_BORDERLESS = 0
_STYLE_NONACTIVATING_PANEL = 1 << 7
_POLICY_ACCESSORY = 1
"""No Dock icon, no menu bar, never the active app."""
_LEVEL_SCREEN_SAVER = 1000
"""Above full-screen apps and games."""
_ON_EVERY_SPACE = (1 << 0) | (1 << 4) | (1 << 6) | (1 << 8)
"""canJoinAllSpaces, stationary, ignoresCycle, fullScreenAuxiliary."""
_TRACKING = 0x01 | 0x02 | 0x80 | 0x200
"""mouseEnteredAndExited, mouseMoved, activeAlways, inVisibleRect."""

_out = sys.stdout.buffer
_out_lock = threading.Lock()
# Nothing else may write to the channel to Core
sys.stdout = sys.stderr

_windows: dict[int, "NSPanel"] = {}
_color_space = CGColorSpaceCreateDeviceRGB()


def _send(header: dict) -> None:
    data = json.dumps(header).encode("utf-8")
    with _out_lock:
        try:
            _out.write(struct.pack(">I", len(data)) + data)
            _out.flush()
        except (BrokenPipeError, OSError):
            os._exit(0)


def _main_height() -> float:
    """Height of the main display, the one whose top left is the HUD's 0,0."""
    screens = NSScreen.screens()
    return screens[0].frame().size.height if screens else 0.0


def _cocoa_rect(x: float, y: float, w: float, h: float):
    return NSMakeRect(x, _main_height() - y - h, w, h)


def _hud_point(event) -> tuple[int, int]:
    """The mouse of an event in HUD coordinates."""
    location = NSEvent.mouseLocation()
    return round(location.x), round(_main_height() - location.y)


_CURSORS = {
    "arrow": lambda: NSCursor.arrowCursor(),
    "move": lambda: NSCursor.openHandCursor(),
    "resize_ns": lambda: NSCursor.resizeUpDownCursor(),
    "resize_we": lambda: NSCursor.resizeLeftRightCursor(),
    # AppKit has diagonal resize cursors, but no public name for them
    "resize_nwse": lambda: _private_cursor("_windowResizeNorthWestSouthEastCursor"),
    "resize_nesw": lambda: _private_cursor("_windowResizeNorthEastSouthWestCursor"),
}


def _private_cursor(selector: str):
    if NSCursor.respondsToSelector_(selector):
        return getattr(NSCursor, selector)()
    return NSCursor.crosshairCursor()


class HudView(NSView):
    """A window's content: the image as its layer, the mouse sent to Core."""

    def initWithFrame_(self, frame):
        self = objc.super(HudView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.wid = 0
        self.setWantsLayer_(True)
        self.addTrackingArea_(
            NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                frame, _TRACKING, self, None
            )
        )
        return self

    def acceptsFirstMouse_(self, event):
        return True

    @objc.python_method
    def _pointer(self, kind: str, event) -> None:
        x, y = _hud_point(event)
        _send({"ev": "pointer", "id": self.wid, "type": kind, "x": x, "y": y})

    def mouseMoved_(self, event):
        # As Windows does it: where to show which cursor, then the move
        self._pointer("hover", event)
        self._pointer("move", event)

    def mouseDown_(self, event):
        self._pointer("press", event)

    def mouseDragged_(self, event):
        # Keeps coming while the button is held, also outside the window
        self._pointer("move", event)

    def mouseUp_(self, event):
        self._pointer("release", event)

    def mouseExited_(self, event):
        NSCursor.arrowCursor().set()


def _panel(wid: int, x: float, y: float, w: float, h: float):
    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        _cocoa_rect(x, y, w, h),
        _STYLE_BORDERLESS | _STYLE_NONACTIVATING_PANEL,
        NSBackingStoreBuffered,
        False,
    )
    panel.setOpaque_(False)
    panel.setBackgroundColor_(NSColor.clearColor())
    panel.setHasShadow_(False)
    panel.setLevel_(_LEVEL_SCREEN_SAVER)
    panel.setCollectionBehavior_(_ON_EVERY_SPACE)
    panel.setIgnoresMouseEvents_(True)
    panel.setAcceptsMouseMovedEvents_(True)
    panel.setHidesOnDeactivate_(False)
    panel.setReleasedWhenClosed_(False)
    view = HudView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
    view.wid = wid
    panel.setContentView_(view)
    # Invisible until the first image, as the overlay expects
    panel.setAlphaValue_(0.0)
    panel.orderFrontRegardless()
    return panel


def _image(width: int, height: int, pixels: bytes):
    """An RGBA image with straight alpha, as the overlay renders it."""
    provider = CGDataProviderCreateWithCFData(NSData.dataWithBytes_length_(pixels, len(pixels)))
    return CGImageCreate(
        width, height, 8, 32, width * 4, _color_space,
        kCGBitmapByteOrderDefault | kCGImageAlphaLast,
        provider, None, False, kCGRenderingIntentDefault,
    )


def _handle(header: dict, payload: bytes) -> None:
    op = header.get("op")
    wid = header.get("id")
    panel = _windows.get(wid)

    if op == "create":
        _windows[wid] = _panel(wid, header["x"], header["y"], header["w"], header["h"])
    elif op == "destroy" and panel is not None:
        panel.orderOut_(None)
        panel.close()
        del _windows[wid]
    elif op == "move" and panel is not None:
        panel.setFrame_display_(_cocoa_rect(header["x"], header["y"], header["w"], header["h"]), False)
    elif op == "present" and panel is not None:
        w, h = header["w"], header["h"]
        panel.setFrame_display_(_cocoa_rect(header["x"], header["y"], w, h), False)
        panel.contentView().layer().setContents_(_image(w, h, payload))
        panel.setAlphaValue_(header["opacity"] / 255)
    elif op == "show" and panel is not None:
        panel.orderFrontRegardless()
    elif op == "hide" and panel is not None:
        panel.orderOut_(None)
    elif op == "raise" and panel is not None:
        panel.orderFrontRegardless()
    elif op == "click_through" and panel is not None:
        panel.setIgnoresMouseEvents_(bool(header["through"]))
    elif op == "cursor":
        make = _CURSORS.get(header.get("name"))
        if make is not None:
            make().set()
    elif op == "quit":
        _quit()


def _quit() -> None:
    for panel in list(_windows.values()):
        panel.orderOut_(None)
    _windows.clear()
    AppHelper.stopEventLoop()
    os._exit(0)


def _read_exact(stream, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = stream.read(n - len(data))
        if not chunk:
            raise EOFError
        data += chunk
    return data


def _read_commands() -> None:
    """Off the main thread: every command goes to the main thread in order."""
    stream = sys.stdin.buffer
    try:
        while True:
            (length,) = struct.unpack(">I", _read_exact(stream, 4))
            header = json.loads(_read_exact(stream, length))
            payload = _read_exact(stream, header["n"]) if header.get("n") else b""
            AppHelper.callAfter(_handle, header, payload)
    except (EOFError, ValueError, OSError):
        # Core is gone: so is the HUD
        AppHelper.callAfter(_quit)


def main() -> int:
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(_POLICY_ACCESSORY)
    threading.Thread(target=_read_commands, name="HudHostCommands", daemon=True).start()
    AppHelper.callAfter(_send, {"ev": "ready"})
    AppHelper.runEventLoop(installInterrupt=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
