"""Screenshots through DXGI Desktop Duplication (dxcam), on Windows only.

mss takes the shot through GDI: Windows copies the whole composed desktop
from the GPU while it waits for it, and a game running at full load can stutter
for that moment. Desktop Duplication copies the frame on the GPU first and only
then reads it. A skill switches it on per user ("Use DXCam capture"), since we
only know it helps from the user's game.

Anything that goes wrong here returns None, and the caller takes the shot with
mss as before: dxcam not bundled, no DirectX 11, the monitor on a GPU that
cannot duplicate it, a rotated monitor (dxcam needs OpenCV to turn it).
"""

import time
from typing import Optional

from PIL import Image

from api.enums import LogType
from services.printr import Printr

FIRST_FRAME_TIMEOUT = 0.5
"""Seconds to wait for the first frame of a new duplication. It usually comes
with the next refresh of the monitor."""

printr = Printr()
_warned = False


def capture(display: int) -> Optional[Image.Image]:
    """An RGB image of mss monitor `display` (1 = the first), or None."""
    try:
        return _capture(display)
    except Exception as e:
        _warn(f"DXCam capture failed, using the standard capture: {e}")
        return None


def _warn(message: str):
    # Once per run: every screenshot would repeat it
    global _warned
    if not _warned:
        _warned = True
        printr.print(message, color=LogType.WARNING, server_only=True)


def _capture(display: int) -> Optional[Image.Image]:
    rect = _monitor_rect(display)
    if rect is None:
        return None
    import dxcam

    # dxcam numbers monitors per GPU, mss across the desktop. The factory
    # that `import dxcam` builds is the only place that has the outputs with
    # their position, so match those to the mss monitor.
    factory = getattr(dxcam, "__factory")
    for device_idx, outputs in enumerate(factory.outputs):
        for output_idx, output in enumerate(outputs):
            output.update_desc()
            c = output.desc.DesktopCoordinates
            if (c.left, c.top, c.right - c.left, c.bottom - c.top) == rect:
                return _grab(dxcam, device_idx, output_idx)
    _warn(f"DXCam found no monitor at {rect}, using the standard capture.")
    return None


def _monitor_rect(display: int) -> Optional[tuple[int, int, int, int]]:
    """Left, top, width and height of mss monitor `display`. None for 0 (all
    monitors): Desktop Duplication shows one monitor at a time."""
    from mss import mss

    if display == 0:
        return None
    with mss() as sct:
        if not 1 <= display < len(sct.monitors):
            display = 1
        m = sct.monitors[display]
        return m["left"], m["top"], m["width"], m["height"]


def _grab(dxcam, device_idx: int, output_idx: int) -> Optional[Image.Image]:
    # A new duplication per shot: while one is open, Windows may compose the
    # game's window through the desktop, which costs frames all the time.
    # BGRA is what the GPU has, so dxcam converts nothing and needs no OpenCV.
    camera = dxcam.create(device_idx=device_idx, output_idx=output_idx, output_color="BGRA")
    try:
        deadline = time.monotonic() + FIRST_FRAME_TIMEOUT
        frame = camera.grab()
        while frame is None and time.monotonic() < deadline:
            time.sleep(0.01)
            frame = camera.grab()
    finally:
        camera.release()
    if frame is None:
        _warn("DXCam got no frame in time, using the standard capture.")
        return None
    height, width = frame.shape[:2]
    return Image.frombytes("RGB", (width, height), frame.tobytes(), "raw", "BGRX")
