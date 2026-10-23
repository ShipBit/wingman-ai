"""The HUD for OBS Browser Sources: what the overlay reports, what the page receives."""

import asyncio
import io
import json
import struct

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from hud_server.constants import GROUP_CHAT
from hud_server.obs import _Client
from hud_server.server import HudServer
from tests.support import FakeHudBackend, FakeObs, hold_encoding, make_overlay, run_frames

SLOW = (30, 30)  # the size of the pictures hold_encoding stops on

PREVIEW_CHAT = {"chat": {"x": 10, "y": 10, "width": 400, "max_height": 300}}


def show_message(overlay, group):
    overlay._handle_message({
        "type": "show_message", "group": group, "element": "message", "title": "Tower",
        "content": "Cleared for takeoff", "props": {"width": 360, "typewriter_effect": False, "duration": 600},
    })


def receive(ws):
    """The next message: a dict, or (header, png) for a window's picture."""
    message = ws.receive()
    if message.get("text") is not None:
        return json.loads(message["text"])
    data = message["bytes"]
    length = struct.unpack(">I", data[:4])[0]
    return json.loads(data[4:4 + length]), data[4 + length:]


def receive_picture(ws, name):
    """Messages up to `name`'s next picture: (the ones before, header, png)."""
    before = []
    while True:
        message = receive(ws)
        if isinstance(message, tuple) and message[0]["id"] == name:
            return before, *message
        before.append(message)


def test_the_overlay_reports_what_is_on_screen():
    obs = FakeObs()
    overlay = make_overlay(FakeHudBackend(), obs_broadcaster=obs)

    show_message(overlay, "atc")
    run_frames(overlay)

    canvas, x, y, opacity = obs.shown["message_atc"]
    win = overlay._windows["message_atc"]
    assert canvas is win["canvas"]
    assert (x, y) == win["_rect"][:2]
    assert opacity > 0

    overlay._handle_message({"type": "hide_message", "group": "atc", "element": "message"})
    run_frames(overlay, 60)
    assert "message_atc" not in obs.shown


def test_a_hidden_window_stays_on_the_stream_until_it_has_faded_out_on_screen():
    obs = FakeObs()
    overlay = make_overlay(FakeHudBackend(), obs_broadcaster=obs)
    show_message(overlay, "atc")
    run_frames(overlay)
    shown = obs.shown["message_atc"]

    overlay._handle_message({"type": "hide_element", "group": "atc", "element": "message"})
    run_frames(overlay, 1)
    # No longer presented: the OS window keeps its last picture while it fades
    assert obs.shown["message_atc"] == shown

    run_frames(overlay, 60)
    assert "message_atc" not in obs.shown


def test_a_preview_replaces_the_shared_chat_on_the_stream_and_leaves_with_it():
    obs = FakeObs()
    overlay = make_overlay(FakeHudBackend(), obs_broadcaster=obs)
    show_message(overlay, GROUP_CHAT)
    run_frames(overlay)
    assert set(obs.shown) == {f"message_{GROUP_CHAT}"}

    overlay._handle_preview_command({"type": "set_preview", "containers": PREVIEW_CHAT})
    run_frames(overlay)
    assert set(obs.shown) == {"preview_chat"}

    overlay._clear_preview()
    run_frames(overlay)
    # The preview took the shared chat's message with it, on screen too
    assert obs.shown == {}


def test_the_page_gets_the_windows_shown_before_it_connected():
    server = HudServer(backend=FakeHudBackend())
    obs = server.obs_broadcaster
    try:
        obs.show_window("atc", Image.new("RGBA", (40, 20), (255, 0, 0, 255)), 5, 6, 1.0)
        obs.move_window("atc", 50, 60, 0.5)

        with TestClient(server.app).websocket_connect("/obs/ws") as ws:
            assert receive(ws)["type"] == "init"
            _, header, png = receive_picture(ws, "atc")

        assert (header["x"], header["y"], header["opacity"]) == (50, 60, 0.5)
        assert Image.open(io.BytesIO(png)).size == (40, 20)
    finally:
        obs.stop()


@pytest.mark.parametrize("remove, removal", [
    (lambda obs: obs.hide_window("slow"), "hide"),
    (lambda obs: obs.clear(), "clear"),
])
def test_a_picture_still_encoding_is_not_sent_after_its_window_is_gone(monkeypatch, remove, removal):
    started, release = hold_encoding(monkeypatch, SLOW)
    server = HudServer(backend=FakeHudBackend())
    obs = server.obs_broadcaster
    try:
        with TestClient(server.app).websocket_connect("/obs/ws") as ws:
            receive(ws)
            obs.show_window("slow", Image.new("RGBA", SLOW), 0, 0, 1.0)
            assert started.wait(5)
            remove(obs)
            release.set()
            obs.show_window("next", Image.new("RGBA", (10, 10)), 0, 0, 1.0)

            before, _, _ = receive_picture(ws, "next")

        assert [m["type"] for m in before] == [removal]
    finally:
        obs.stop()


def test_the_newest_placement_wins_over_a_picture_still_encoding(monkeypatch):
    started, release = hold_encoding(monkeypatch, SLOW)
    server = HudServer(backend=FakeHudBackend())
    obs = server.obs_broadcaster
    try:
        with TestClient(server.app).websocket_connect("/obs/ws") as ws:
            receive(ws)
            obs.show_window("atc", Image.new("RGBA", SLOW), 0, 0, 0.2)
            assert started.wait(5)
            obs.move_window("atc", 10, 10, 1.0)
            release.set()

            before, header, _ = receive_picture(ws, "atc")

        # What the page shows: the placement with the highest sequence number
        placements = [(m["seq"], m["x"], m["opacity"]) for m in before if m["type"] == "state"]
        placements.append((header["state"], header["x"], header["opacity"]))
        assert max(placements)[1:] == (10, 1.0)
    finally:
        obs.stop()


def test_a_client_that_stops_reading_gets_only_the_newest_of_each_window():
    class StalledSocket:
        def __init__(self):
            self.sent, self.reading = [], asyncio.Event()

        async def send_bytes(self, data):
            await self.reading.wait()
            self.sent.append(data)

        send_text = send_bytes

    async def stall():
        ws = StalledSocket()
        client = _Client(ws)
        task = asyncio.create_task(client.run(lambda _: None))
        client.put(("picture", "atc"), b"1")
        await asyncio.sleep(0)  # stuck sending the first
        for data in (b"2", b"3", b"4"):
            client.put(("picture", "atc"), data)
        client.put(("state", "atc"), "moved")
        client.put(("state", "atc"), "moved again")
        ws.reading.set()
        await asyncio.sleep(0.05)
        task.cancel()
        return ws.sent

    assert asyncio.run(stall()) == [b"1", b"4", "moved again"]


def test_other_sites_cannot_watch_the_hud():
    server = HudServer(backend=FakeHudBackend())
    client = TestClient(server.app)
    stranger = {"origin": "https://example.com"}
    try:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/obs/ws", headers=stranger):
                pass
        assert client.get("/obs/frame.png", headers=stranger).status_code == 403

        # The /obs page itself, on this server
        with client.websocket_connect("/obs/ws", headers={"origin": "http://testserver"}) as ws:
            assert receive(ws)["type"] == "init"
    finally:
        server.obs_broadcaster.stop()


def test_a_stopped_stream_starts_again_for_the_next_page():
    server = HudServer(backend=FakeHudBackend())
    obs = server.obs_broadcaster
    client = TestClient(server.app)
    try:
        with client.websocket_connect("/obs/ws") as ws:
            receive(ws)
        obs.stop()

        obs.show_window("atc", Image.new("RGBA", (10, 10)), 0, 0, 1.0)
        with client.websocket_connect("/obs/ws") as ws:
            receive(ws)
            _, header, _ = receive_picture(ws, "atc")

        assert header["id"] == "atc"
    finally:
        obs.stop()


def test_the_snapshot_shows_the_hud_without_a_page_connected():
    server = HudServer(backend=FakeHudBackend())
    obs = server.obs_broadcaster
    try:
        obs.show_window("atc", Image.new("RGBA", (40, 20), (255, 0, 0, 255)), 100, 50, 0.5)
        # Partly off screen: the shadow of a window at the edge
        obs.show_window("edge", Image.new("RGBA", (40, 20), (0, 0, 255, 255)), -10, 0, 1.0)

        response = TestClient(server.app).get("/obs/frame.png")

        frame = Image.open(io.BytesIO(response.content))
        assert frame.size == (1920, 1080)
        assert frame.getpixel((110, 60)) == (255, 0, 0, 128)
        assert frame.getpixel((0, 0)) == (0, 0, 255, 255)
        assert frame.getpixel((500, 500))[3] == 0
    finally:
        obs.stop()


def test_the_page_is_served_for_the_browser_source():
    server = HudServer(backend=FakeHudBackend())
    try:
        response = TestClient(server.app).get("/obs")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "/obs/ws" in response.text
    finally:
        server.obs_broadcaster.stop()
