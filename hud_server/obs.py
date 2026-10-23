"""Streams the HUD windows to an OBS Browser Source (GET /obs, WS /obs/ws).

Every window goes out as its own PNG when its picture changes; a move or a
fade is a small JSON message. Each event carries a sequence number, so the
page drops anything older than what it already shows, whatever order the
encoder and the sockets deliver it in."""

import asyncio
import io
import json
import struct
import threading
from dataclasses import dataclass, replace
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from PIL import Image
from fastapi import WebSocket

from api.enums import LogType
from hud_server.constants import THREAD_NAME_OBS_ENCODER
from services.printr import Printr

printr = Printr()

# A client that takes longer than this for one message is dropped
SEND_TIMEOUT = 5.0

OBS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Wingman AI HUD</title>
    <link rel="icon" href="data:,">
    <style>
        * { margin: 0; padding: 0; }
        html, body { width: 100vw; height: 100vh; overflow: hidden; background: transparent; }
        canvas { display: block; width: 100%; height: 100%; object-fit: contain; }
    </style>
</head>
<body>
    <canvas id="hud"></canvas>
    <script>
        const canvas = document.getElementById("hud");
        const ctx = canvas.getContext("2d");
        // id -> {x, y, opacity, visible, bitmap, content, state}: the newest picture
        // and the newest placement, each with the sequence number it came with
        const windows = new Map();
        let generation = 0;
        // Sequence number of the last clear: anything older is gone
        let floor = -1;
        let scheduled = false;

        function requestRender() {
            if (scheduled) return;
            scheduled = true;
            requestAnimationFrame(render);
        }

        function render() {
            scheduled = false;
            ctx.globalAlpha = 1;
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            for (const win of windows.values()) {
                if (!win.visible || !win.bitmap || win.opacity <= 0) continue;
                ctx.globalAlpha = Math.min(1, win.opacity);
                ctx.drawImage(win.bitmap, win.x, win.y);
            }
        }

        function entry(id) {
            let win = windows.get(id);
            if (!win) {
                win = { x: 0, y: 0, opacity: 0, visible: false, bitmap: null, content: -1, state: -1 };
                windows.set(id, win);
            }
            return win;
        }

        function clearWindows() {
            for (const win of windows.values()) if (win.bitmap) win.bitmap.close();
            windows.clear();
            requestRender();
        }

        // Placement on: the window shown last is on top, as on screen
        function place(id, win, x, y, opacity, seq) {
            if (!win.visible) {
                windows.delete(id);
                windows.set(id, win);
            }
            Object.assign(win, { x, y, opacity, visible: true, state: seq });
        }

        function onControl(msg) {
            if (msg.type === "init" || msg.type === "resize") {
                // The server sends every window again after init
                if (msg.type === "init") {
                    clearWindows();
                    floor = -1;
                }
                canvas.width = msg.width;
                canvas.height = msg.height;
            } else if (msg.type === "state") {
                const win = entry(msg.id);
                if (msg.seq <= floor || msg.seq <= win.state) return;
                place(msg.id, win, msg.x, msg.y, msg.opacity, msg.seq);
            } else if (msg.type === "hide") {
                const win = entry(msg.id);
                if (msg.seq <= floor || msg.seq <= win.state) return;
                // Also refuses pictures sent before the hide that are still on their way
                if (win.bitmap) win.bitmap.close();
                Object.assign(win, { visible: false, bitmap: null, state: msg.seq, content: msg.seq });
            } else if (msg.type === "clear") {
                clearWindows();
                // Refuses everything sent before the clear that is still on its way
                floor = msg.seq;
                return;
            }
            requestRender();
        }

        // [4-byte header length][JSON header][PNG]
        async function onFrame(data, gen) {
            const view = new DataView(data);
            const headerLength = view.getUint32(0);
            const meta = JSON.parse(new TextDecoder().decode(new Uint8Array(data, 4, headerLength)));
            const bitmap = await createImageBitmap(
                new Blob([new Uint8Array(data, 4 + headerLength)], { type: "image/png" }),
                { premultiplyAlpha: "premultiply", colorSpaceConversion: "none" },
            );
            const win = gen === generation && meta.seq > floor ? entry(meta.id) : null;
            if (!win || meta.seq <= win.content) {
                bitmap.close();
                return;
            }
            if (win.bitmap) win.bitmap.close();
            win.bitmap = bitmap;
            win.content = meta.seq;
            if (meta.state > win.state) place(meta.id, win, meta.x, meta.y, meta.opacity, meta.state);
            requestRender();
        }

        function connect() {
            const gen = ++generation;
            const protocol = location.protocol === "https:" ? "wss:" : "ws:";
            const ws = new WebSocket(`${protocol}//${location.host}/obs/ws`);
            ws.binaryType = "arraybuffer";
            ws.onmessage = (event) => {
                if (typeof event.data === "string") {
                    onControl(JSON.parse(event.data));
                } else {
                    onFrame(event.data, gen).catch((e) => console.error("[Wingman HUD]", e));
                }
            };
            ws.onclose = () => {
                if (gen !== generation) return;
                // Nothing stale on the stream while Core is away
                generation++;
                clearWindows();
                setTimeout(connect, 1500);
            };
            ws.onerror = () => ws.close();
        }

        connect();
    </script>
</body>
</html>
"""


@dataclass
class _Window:
    canvas: Image.Image
    content_seq: int
    state_seq: int
    x: int
    y: int
    opacity: float


class _Client:
    """One Browser Source. Keeps only the newest message of each kind per
    window until it is sent: a client that stops reading costs one HUD's worth."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.task: Optional[asyncio.Task] = None
        self._queue: Dict[tuple, Any] = {}
        self._ready = asyncio.Event()

    def put(self, key: tuple, data) -> None:
        """On the event loop. The order of the latest of each key is kept."""
        self._queue.pop(key, None)
        self._queue[key] = data
        self._ready.set()

    async def run(self, on_gone) -> None:
        try:
            while True:
                await self._ready.wait()
                self._ready.clear()
                while self._queue:
                    data = self._queue.pop(next(iter(self._queue)))
                    send = self.ws.send_bytes(data) if isinstance(data, bytes) else self.ws.send_text(data)
                    await asyncio.wait_for(send, SEND_TIMEOUT)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Gone or stalled: the page reconnects and gets everything again
            on_gone(self.ws)
            try:
                await self.ws.close()
            except Exception:
                pass


class ObsBroadcaster:
    """The HUD windows as OBS sees them, and the Browser Sources watching.

    The overlay thread reports what each window shows; an encoder thread turns
    pictures into PNGs, only while a client is connected; the server's event
    loop sends them."""

    def __init__(self, framerate: int = 60) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._framerate = max(1, framerate)
        self._width = 1920
        self._height = 1080
        # Replaced, never changed in place: other threads read it without a lock
        self._clients: frozenset = frozenset()

        self._cond = threading.Condition()
        self._seq = 0
        self._windows: Dict[str, _Window] = {}
        self._pending: set = set()
        self._worker: Optional[threading.Thread] = None
        self._worker_stop: Optional[threading.Event] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def set_framerate(self, framerate: int) -> None:
        self._framerate = max(1, framerate)

    def set_dimensions(self, width: int, height: int) -> None:
        with self._cond:
            if width <= 0 or height <= 0 or (width, height) == (self._width, self._height):
                return
            self._width, self._height = width, height
            # Under the lock: a client connecting now gets this or an init with the new size
            self._dispatch(("resize",), {"type": "resize", "width": width, "height": height})

    # ─────────────────────────── from the overlay ─────────────────────────── #

    def show_window(self, name: str, canvas: Image.Image, x: int, y: int, opacity: float) -> None:
        """A window shows a new picture. The canvas must not change afterwards."""
        with self._cond:
            self._seq += 1
            self._windows[name] = _Window(canvas, self._seq, self._seq, x, y, opacity)
            if self._clients:
                self._pending.add(name)
                self._cond.notify()

    def move_window(self, name: str, x: int, y: int, opacity: float) -> None:
        """A window moved or faded; its picture is the same."""
        with self._cond:
            win = self._windows.get(name)
            if win is None:
                return
            self._seq += 1
            win.state_seq, win.x, win.y, win.opacity = self._seq, x, y, opacity
            msg = {"type": "state", "id": name, "seq": self._seq, "x": x, "y": y, "opacity": opacity}
        self._dispatch(("state", name), msg)

    def hide_window(self, name: str) -> None:
        with self._cond:
            if self._windows.pop(name, None) is None:
                return
            self._pending.discard(name)
            self._seq += 1
            msg = {"type": "hide", "id": name, "seq": self._seq}
        self._dispatch(("hide", name), msg)

    def clear(self) -> None:
        """The overlay stopped: no windows anymore."""
        with self._cond:
            self._windows.clear()
            self._pending.clear()
            self._seq += 1
            msg = {"type": "clear", "seq": self._seq}
        self._dispatch(("clear",), msg)

    # ─────────────────────────── from the server ─────────────────────────── #

    async def connect(self, ws: WebSocket) -> None:
        """Size the client's canvas, then send it every window."""
        self._loop = asyncio.get_running_loop()
        client = _Client(ws)
        with self._cond:
            init = {"type": "init", "width": self._width, "height": self._height, "fps": self._framerate}
            client.put(("init",), json.dumps(init))
            self._clients = self._clients | {client}
            if self._worker is None:
                self._worker_stop = threading.Event()
                self._worker = threading.Thread(
                    target=self._encode_loop, args=(self._worker_stop,), name=THREAD_NAME_OBS_ENCODER, daemon=True
                )
                self._worker.start()
            # The others get them again too and drop them: same sequence numbers
            self._pending.update(self._windows)
            self._cond.notify()
        client.task = asyncio.create_task(client.run(self.disconnect))

    def disconnect(self, ws: WebSocket) -> None:
        """On the event loop."""
        gone = {client for client in self._clients if client.ws is ws}
        self._clients = self._clients - gone
        for client in gone:
            if client.task is not None and client.task is not asyncio.current_task():
                client.task.cancel()

    def snapshot(self) -> bytes:
        """All visible windows on one transparent screen-sized PNG."""
        with self._cond:
            windows = [replace(win) for win in self._windows.values()]
            size = (self._width, self._height)
        frame = Image.new("RGBA", size, (0, 0, 0, 0))
        for win in windows:
            if win.opacity <= 0:
                continue
            image = win.canvas
            if win.opacity < 1:
                image = image.copy()
                image.putalpha(image.getchannel("A").point(lambda a: round(a * win.opacity)))
            # Part of a window may lie off screen (its shadow at the edge)
            left, top = max(0, -win.x), max(0, -win.y)
            if left < image.width and top < image.height:
                frame.alpha_composite(image, (win.x + left, win.y + top), (left, top))
        return _png(frame)

    def get_status(self) -> Dict[str, Any]:
        with self._cond:
            shown = len(self._windows)
        return {
            "subscribers": len(self._clients),
            "width": self._width,
            "height": self._height,
            "fps": self._framerate,
            "windows": shown,
        }

    def stop(self) -> None:
        """Stop encoding and sending; a client connecting later starts it again."""
        with self._cond:
            worker, stop = self._worker, self._worker_stop
            self._worker = self._worker_stop = None
            self._pending.clear()
            if stop is not None:
                stop.set()
            self._cond.notify_all()
            clients, self._clients = self._clients, frozenset()
        if worker is not None:
            worker.join(timeout=1.0)
        loop = self._loop
        for client in clients:
            if client.task is not None and loop is not None and not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(client.task.cancel)
                except RuntimeError:
                    pass

    # ─────────────────────────── encoding and sending ─────────────────────────── #

    def _encode_loop(self, stop: threading.Event) -> None:
        while True:
            with self._cond:
                while not stop.is_set() and not self._pending:
                    self._cond.wait()
                if stop.is_set():
                    return
                jobs = [(name, self._windows[name].canvas, self._windows[name].content_seq) for name in self._pending]
                self._pending.clear()

            for name, canvas, content_seq in jobs:
                try:
                    png = _png(canvas)
                except Exception as e:
                    printr.print(f"[HUD OBS] Encoding {name} failed: {e}", color=LogType.ERROR, server_only=True)
                    continue
                with self._cond:
                    win = self._windows.get(name)
                    # Hidden meanwhile, or a newer picture is queued already
                    if win is None or win.content_seq != content_seq:
                        continue
                    header = {
                        "id": name, "seq": content_seq, "state": win.state_seq,
                        "x": win.x, "y": win.y, "opacity": win.opacity,
                    }
                header_bytes = json.dumps(header).encode("utf-8")
                self._dispatch(("picture", name), struct.pack(">I", len(header_bytes)) + header_bytes + png)

    def _dispatch(self, key: tuple, message) -> None:
        """Queue for every client, from any thread."""
        loop = self._loop
        if not self._clients or loop is None or loop.is_closed():
            return
        data = message if isinstance(message, bytes) else json.dumps(message)
        try:
            loop.call_soon_threadsafe(self._deliver, key, data)
        except RuntimeError:
            pass  # The loop closed in between

    def _deliver(self, key: tuple, data) -> None:
        for client in self._clients:
            client.put(key, data)


def same_origin(headers) -> bool:
    """Whether a request comes from the /obs page or no web page at all. The
    API allows every origin, but no other site may watch the HUD."""
    origin = headers.get("origin")
    return origin is None or urlsplit(origin).netloc == headers.get("host")


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    # Fastest zlib level: sent over localhost, a smaller PNG saves nothing
    image.save(buffer, format="PNG", compress_level=1)
    return buffer.getvalue()
