"""The HUD for OBS Browser Sources: what the overlay reports, what the page receives."""

import asyncio
import io
import json
import struct

import pytest
from PIL import Image
from starlette.websockets import WebSocketDisconnect

from hud_server.constants import GROUP_CHAT, GROUP_INFO
from hud_server.rendering.glass import SHADOW
from hud_server.obs import _Client
from hud_server.server import HudServer
from tests.support import HUD_HOST, FakeHudBackend, FakeObs, hold_encoding, hud_client, make_overlay, run_frames

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

        with hud_client(server).websocket_connect("/obs/ws") as ws:
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
        with hud_client(server).websocket_connect("/obs/ws") as ws:
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
        with hud_client(server).websocket_connect("/obs/ws") as ws:
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
    client = hud_client(server)
    stranger = {"origin": "https://example.com"}
    try:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/obs/ws", headers=stranger):
                pass
        assert client.get("/obs/frame.png", headers=stranger).status_code == 403

        # A site whose name now points at this PC sends its name as origin and host
        rebound = {"origin": "http://evil.example:7862", "host": "evil.example:7862"}
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/obs/ws", headers=rebound):
                pass
        assert client.get("/obs/frame.png", headers={"host": "evil.example:7862"}).status_code == 403

        # The /obs page itself, on this server
        with client.websocket_connect("/obs/ws", headers={"origin": f"http://{HUD_HOST}"}) as ws:
            assert receive(ws)["type"] == "init"
        with client.websocket_connect("/obs/ws", headers={"origin": "http://localhost:7862", "host": "localhost:7862"}) as ws:
            assert receive(ws)["type"] == "init"
    finally:
        server.obs_broadcaster.stop()


def test_a_stopped_stream_starts_again_for_the_next_page():
    server = HudServer(backend=FakeHudBackend())
    obs = server.obs_broadcaster
    client = hud_client(server)
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

        response = hud_client(server).get("/obs/frame.png")

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
        response = hud_client(server).get("/obs")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "/obs/ws" in response.text
    finally:
        server.obs_broadcaster.stop()


def test_chat_and_info_pages_are_served_for_browser_sources():
    server = HudServer(backend=FakeHudBackend())
    try:
        client = hud_client(server)
        for path, title, channel in (
            ("/obs", "Wingman AI HUD", "all"),
            ("/obs/chat", "Wingman AI HUD - Chat", "chat"),
            ("/obs/info", "Wingman AI HUD - Info", "info"),
        ):
            res = client.get(path)
            assert res.status_code == 200
            assert "text/html" in res.headers["content-type"]
            assert title in res.text
            assert f'DEFAULT_CHANNEL = "{channel}"' in res.text
    finally:
        server.obs_broadcaster.stop()


def test_obs_chat_and_info_channels_receive_only_their_windows_with_relative_coords():
    server = HudServer(backend=FakeHudBackend())
    obs = server.obs_broadcaster
    client = hud_client(server)
    try:
        # Chat container: x=100, y=200, w=400, h=500
        obs.set_container("chat", 100, 200, 400, 500)
        # Info container: x=800, y=150, w=350, h=450
        obs.set_container("info", 800, 150, 350, 450)

        # Show chat window, info window, and unrelated window
        # Body on screen at x=100, y=200 -> rect is (100 - SHADOW.left, 200 - SHADOW.top)
        chat_x = 100 - SHADOW.left
        chat_y = 200 - SHADOW.top
        obs.show_window(f"chat_{GROUP_CHAT}", Image.new("RGBA", (50, 50), (255, 0, 0, 255)), chat_x, chat_y, 1.0)

        info_x = 800 - SHADOW.left
        info_y = 150 - SHADOW.top
        obs.show_window(f"persistent_{GROUP_INFO}", Image.new("RGBA", (60, 60), (0, 255, 0, 255)), info_x, info_y, 0.8)

        obs.show_window("message_atc", Image.new("RGBA", (70, 70), (0, 0, 255, 255)), 50, 50, 1.0)

        # 1. Connect to /obs/ws?channel=chat
        with client.websocket_connect("/obs/ws?channel=chat") as ws:
            init = receive(ws)
            assert init["type"] == "init"
            assert init["width"] == 400 + SHADOW.left + SHADOW.right
            assert init["height"] == 500 + SHADOW.top + SHADOW.bottom
            assert init["channel"] == "chat"

            _, header, _ = receive_picture(ws, f"chat_{GROUP_CHAT}")
            # Inside chat container canvas, it sits at (0, 0)
            assert (header["x"], header["y"], header["opacity"]) == (0, 0, 1.0)

        # 2. Connect to /obs/ws?channel=info
        with client.websocket_connect("/obs/ws?channel=info") as ws:
            init = receive(ws)
            assert init["type"] == "init"
            assert init["width"] == 350 + SHADOW.left + SHADOW.right
            assert init["height"] == 450 + SHADOW.top + SHADOW.bottom
            assert init["channel"] == "info"

            _, header, _ = receive_picture(ws, f"persistent_{GROUP_INFO}")
            # Inside info container canvas, it sits at (0, 0)
            assert (header["x"], header["y"], header["opacity"]) == (0, 0, 0.8)

        # 3. Connect to /obs/ws (all)
        with client.websocket_connect("/obs/ws") as ws:
            init = receive(ws)
            assert init["type"] == "init"
            assert (init["width"], init["height"]) == (1920, 1080)

            # Collect the 3 pictures in whichever order the encoder delivers them
            headers = {}
            for _ in range(3):
                msg = receive(ws)
                if isinstance(msg, tuple):
                    headers[msg[0]["id"]] = msg[0]

            assert (headers[f"chat_{GROUP_CHAT}"]["x"], headers[f"chat_{GROUP_CHAT}"]["y"]) == (chat_x, chat_y)
            assert (headers[f"persistent_{GROUP_INFO}"]["x"], headers[f"persistent_{GROUP_INFO}"]["y"]) == (info_x, info_y)
            assert (headers["message_atc"]["x"], headers["message_atc"]["y"]) == (50, 50)
    finally:
        obs.stop()


def test_obs_channel_path_websocket():
    server = HudServer(backend=FakeHudBackend())
    obs = server.obs_broadcaster
    client = hud_client(server)
    try:
        obs.set_container("chat", 100, 200, 400, 500)
        with client.websocket_connect("/obs/chat/ws") as ws:
            init = receive(ws)
            assert init["type"] == "init"
            assert init["channel"] == "chat"
            assert init["width"] == 400 + SHADOW.left + SHADOW.right
    finally:
        obs.stop()


def test_container_resize_notifies_channel_clients():
    server = HudServer(backend=FakeHudBackend())
    obs = server.obs_broadcaster
    client = hud_client(server)
    try:
        obs.set_container("chat", 50, 50, 300, 400)
        with client.websocket_connect("/obs/ws?channel=chat") as ws:
            receive(ws)  # init
            obs.set_container("chat", 50, 50, 450, 550)
            msg = receive(ws)
            assert msg["type"] == "resize"
            assert msg["channel"] == "chat"
            assert msg["width"] == 450 + SHADOW.left + SHADOW.right
            assert msg["height"] == 550 + SHADOW.top + SHADOW.bottom
    finally:
        obs.stop()


def test_channel_snapshots_output_exact_canvas_sizes():
    server = HudServer(backend=FakeHudBackend())
    obs = server.obs_broadcaster
    client = hud_client(server)
    try:
        obs.set_container("chat", 100, 100, 300, 400)
        obs.set_container("info", 500, 100, 250, 350)

        chat_w = 300 + SHADOW.left + SHADOW.right
        chat_h = 400 + SHADOW.top + SHADOW.bottom
        info_w = 250 + SHADOW.left + SHADOW.right
        info_h = 350 + SHADOW.top + SHADOW.bottom

        # Chat snapshot
        res = client.get("/obs/chat/frame.png")
        assert res.status_code == 200
        chat_frame = Image.open(io.BytesIO(res.content))
        assert chat_frame.size == (chat_w, chat_h)

        # Info snapshot
        res = client.get("/obs/info/frame.png")
        assert res.status_code == 200
        info_frame = Image.open(io.BytesIO(res.content))
        assert info_frame.size == (info_w, info_h)

        # Full screen snapshot
        res = client.get("/obs/frame.png")
        assert res.status_code == 200
        full_frame = Image.open(io.BytesIO(res.content))
        assert full_frame.size == (1920, 1080)
    finally:
        obs.stop()


def test_obs_status_includes_containers():
    server = HudServer(backend=FakeHudBackend())
    obs = server.obs_broadcaster
    client = hud_client(server)
    try:
        obs.set_container("chat", 100, 100, 300, 400)
        obs.set_container("info", 500, 100, 250, 350)

        res = client.get("/obs/status")
        assert res.status_code == 200
        data = res.json()
        assert data["width"] == 1920
        assert data["height"] == 1080
        assert data["chat"]["width"] == 300 + SHADOW.left + SHADOW.right
        assert data["chat"]["height"] == 400 + SHADOW.top + SHADOW.bottom
        assert data["info"]["width"] == 250 + SHADOW.left + SHADOW.right
        assert data["info"]["height"] == 350 + SHADOW.top + SHADOW.bottom
    finally:
        obs.stop()


def test_channel_receives_translated_state_and_hides_with_isolation():
    server = HudServer(backend=FakeHudBackend())
    obs = server.obs_broadcaster
    client = hud_client(server)
    try:
        obs.set_container("chat", 100, 200, 400, 500)
        obs.set_container("info", 800, 150, 350, 450)

        with client.websocket_connect("/obs/ws?channel=chat") as ws:
            receive(ws)  # init

            # Show chat window
            chat_x = 100 - SHADOW.left
            chat_y = 200 - SHADOW.top
            obs.show_window(f"chat_{GROUP_CHAT}", Image.new("RGBA", (50, 50), (255, 0, 0, 255)), chat_x, chat_y, 1.0)
            _, header, _ = receive_picture(ws, f"chat_{GROUP_CHAT}")
            assert (header["x"], header["y"]) == (0, 0)

            # Move chat window (simulate lift animation ending: y rises by 10)
            obs.move_window(f"chat_{GROUP_CHAT}", chat_x, chat_y - 10, 0.9)
            msg = receive(ws)
            assert msg["type"] == "state"
            assert msg["id"] == f"chat_{GROUP_CHAT}"
            assert (msg["x"], msg["y"], msg["opacity"]) == (0, -10, 0.9)

            # Move an unrelated info window - should NOT reach chat socket
            obs.move_window(f"persistent_{GROUP_INFO}", 800, 150, 0.5)

            # Hide chat window
            obs.hide_window(f"chat_{GROUP_CHAT}")
            hide_msg = receive(ws)
            assert hide_msg["type"] == "hide"
            assert hide_msg["id"] == f"chat_{GROUP_CHAT}"
    finally:
        obs.stop()


def test_channel_snapshots_require_same_origin():
    server = HudServer(backend=FakeHudBackend())
    client = hud_client(server)
    stranger = {"origin": "https://example.com"}
    try:
        assert client.get("/obs/chat/frame.png", headers=stranger).status_code == 403
        assert client.get("/obs/info/frame.png", headers=stranger).status_code == 403
    finally:
        server.obs_broadcaster.stop()
