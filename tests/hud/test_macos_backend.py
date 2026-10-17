"""The macOS backend talks to its window process over a pipe: what it sends
for the overlay's window calls, and how the mouse comes back. No AppKit: the
process is a fake that records the bytes."""

import io
import json
import struct

from PIL import Image

from hud_server.platform.base import Cursor, Pointer
from hud_server.platform.macos import MacOsBackend


class FakeProcess:
    def __init__(self) -> None:
        self.stdin = io.BytesIO()

    def messages(self) -> list[tuple[dict, bytes]]:
        data, out, i = self.stdin.getvalue(), [], 0
        while i < len(data):
            (length,) = struct.unpack(">I", data[i : i + 4])
            header = json.loads(data[i + 4 : i + 4 + length])
            i += 4 + length
            payload = data[i : i + header.get("n", 0)]
            i += header.get("n", 0)
            out.append((header, payload))
        return out


def backend() -> tuple[MacOsBackend, FakeProcess]:
    mac = MacOsBackend()
    process = FakeProcess()
    mac._process = process
    return mac, process


def test_an_image_goes_to_the_window_process_with_its_pixels_and_place():
    mac, process = backend()
    window = mac.create_window("HUD_chat", 20, 30, 400, 100)
    mac.move_window(window, 50, 60, 400, 100)

    mac.present(window, Image.new("RGBA", (3, 2), (255, 0, 0, 128)), 200)

    header, payload = process.messages()[-1]
    assert header == {"op": "present", "id": window.id, "x": 50, "y": 60,
                      "w": 3, "h": 2, "opacity": 200, "n": 24}
    assert payload == bytes([255, 0, 0, 128]) * 6


def test_the_mouse_reaches_the_window_handler_on_the_overlay_thread():
    mac, process = backend()
    window = mac.create_window("HUD_preview_chat", 0, 0, 100, 100)
    seen = []

    def handler(pointer, x, y):
        seen.append((pointer, x, y))
        return Cursor.MOVE

    mac.set_pointer_handler(window, handler)
    mac._events.put({"ev": "pointer", "id": window.id, "type": "press", "x": 40, "y": 50})

    assert seen == []
    mac.pump_events()

    assert seen == [(Pointer.PRESS, 40, 50)]
    assert process.messages()[-1][0] == {"op": "cursor", "name": "move"}


def test_a_destroyed_window_gets_no_more_mouse():
    mac, process = backend()
    window = mac.create_window("HUD_preview_info", 0, 0, 100, 100)
    seen = []
    mac.set_pointer_handler(window, lambda *event: seen.append(event))
    mac.destroy_window(window)

    mac._events.put({"ev": "pointer", "id": window.id, "type": "move", "x": 1, "y": 1})
    mac.pump_events()

    assert seen == []
    assert process.messages()[-1][0] == {"op": "destroy", "id": window.id}
