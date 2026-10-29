"""Streams the HUD windows to an OBS Browser Source (GET /obs, WS /obs/ws).

Supports /obs (full screen HUD), /obs/chat (chat panel only), and /obs/info (info panel only).
Every window goes out as its own PNG when its picture changes; a move or a
fade is a small JSON message. Each event carries a sequence number, so the
page drops anything older than what it already shows, whatever order the
encoder and the sockets deliver it in."""

import asyncio
import io
import ipaddress
import json
import struct
import threading
from dataclasses import dataclass, replace
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from PIL import Image
from fastapi import WebSocket

from api.enums import LogType
from hud_server.constants import GROUP_CHAT, GROUP_INFO, THREAD_NAME_OBS_ENCODER
from hud_server.rendering.glass import SHADOW
from services.printr import Printr

printr = Printr()

# A client that takes longer than this for one message is dropped
SEND_TIMEOUT = 5.0

OBS_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>__TITLE__</title>
    <link rel="icon" href="data:,">
    <style>
        * { margin: 0; padding: 0; }
        html, body { overflow: hidden; background: transparent; }
        canvas { display: block; }
    </style>
</head>
<body>
    <canvas id="hud"></canvas>
    <script>
        const DEFAULT_CHANNEL = "__CHANNEL__";
        const params = new URLSearchParams(location.search);
        const CHANNEL = params.get("channel") || DEFAULT_CHANNEL;
        const canvas = document.getElementById("hud");
        const ctx = canvas.getContext("2d");
        // id -> {x, y, opacity, visible, bitmap, content, state}: the newest picture
        // and the newest placement, each with the sequence number it came with
        const windows = new Map();
        let generation = 0;
        // Sequence number of the last clear: anything older is gone
        let floor = -1;
        let scheduled = false;

        function setDimensions(width, height) {
            canvas.width = width;
            canvas.height = height;
            canvas.style.width = width + "px";
            canvas.style.height = height + "px";
        }

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
                setDimensions(msg.width, msg.height);
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
            const query = CHANNEL && CHANNEL !== "all" ? `?channel=${encodeURIComponent(CHANNEL)}` : "";
            const ws = new WebSocket(`${protocol}//${location.host}/obs/ws${query}`);
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


def obs_html(channel: str = "all") -> str:
    titles = {
        "chat": "Wingman AI HUD - Chat",
        "info": "Wingman AI HUD - Info",
    }
    title = titles.get(channel, "Wingman AI HUD")
    return OBS_HTML_TEMPLATE.replace("__TITLE__", title).replace("__CHANNEL__", channel)


OBS_HTML = obs_html("all")


def _window_channel(name: str) -> Optional[str]:
    """Which container channel a window belongs to ('chat', 'info', or None for general windows)."""
    if name in ("chat", "preview_chat") or name.endswith(f"_{GROUP_CHAT}") or name.startswith("chat_"):
        return "chat"
    if name in ("info", "preview_info") or name.endswith(f"_{GROUP_INFO}") or name.startswith("info_"):
        return "info"
    return None


def _pack_frame(header: dict, png: bytes) -> bytes:
    header_bytes = json.dumps(header).encode("utf-8")
    return struct.pack(">I", len(header_bytes)) + header_bytes + png


@dataclass
class _Window:
    canvas: Image.Image
    content_seq: int
    state_seq: int
    x: int
    y: int
    opacity: float


@dataclass
class _Container:
    x: int
    y: int
    width: int
    height: int


class _Client:
    """One Browser Source. Keeps only the newest message of each kind per
    window until it is sent: a client that stops reading costs one HUD's worth."""

    def __init__(self, ws: WebSocket, channel: str = "all") -> None:
        self.ws = ws
        self.channel = channel
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
        self._containers: Dict[str, _Container] = {
            "chat": _Container(x=20, y=20, width=400, height=500),
            "info": _Container(x=20, y=540, width=400, height=500),
        }
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

    def set_container(self, name: str, x: int, y: int, width: int, height: int) -> None:
        """Area of a shared HUD container on screen."""
        if name not in ("chat", "info"):
            return
        width = max(1, width)
        height = max(1, height)
        with self._cond:
            old = self._containers.get(name)
            if old and (old.x, old.y, old.width, old.height) == (x, y, width, height):
                return
            size_changed = old is None or (old.width, old.height) != (width, height)
            self._containers[name] = _Container(x, y, width, height)
            if size_changed:
                canvas_w = width + SHADOW.left + SHADOW.right
                canvas_h = height + SHADOW.top + SHADOW.bottom
                self._dispatch(
                    ("resize", name),
                    {name: {"type": "resize", "width": canvas_w, "height": canvas_h, "channel": name}},
                )

    def set_dimensions(self, width: int, height: int) -> None:
        with self._cond:
            if width <= 0 or height <= 0 or (width, height) == (self._width, self._height):
                return
            self._width, self._height = width, height
            # Under the lock: a client connecting now gets this or an init with the new size
            self._dispatch(
                ("resize", "all"),
                {"all": {"type": "resize", "width": width, "height": height, "channel": "all"}},
            )

    # ─────────────────────────── from the overlay ─────────────────────────── #

    def show_window(self, name: str, canvas: Image.Image, x: int, y: int, opacity: float) -> None:
        """A window shows a new picture. The canvas must not change afterwards."""
        with self._cond:
            self._seq += 1
            self._windows[name] = _Window(canvas, self._seq, self._seq, x, y, opacity)
            chan = _window_channel(name)
            if any(c.channel in ("all", chan) for c in self._clients):
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
            msg_all = {"type": "state", "id": name, "seq": self._seq, "x": x, "y": y, "opacity": opacity}
            data_by_chan = {"all": msg_all}
            chan = _window_channel(name)
            if chan in ("chat", "info"):
                c = self._containers[chan]
                x0, y0 = c.x - SHADOW.left, c.y - SHADOW.top
                data_by_chan[chan] = {
                    "type": "state", "id": name, "seq": self._seq,
                    "x": x - x0, "y": y - y0, "opacity": opacity,
                }
        self._dispatch(("state", name), data_by_chan)

    def hide_window(self, name: str) -> None:
        with self._cond:
            if self._windows.pop(name, None) is None:
                return
            self._pending.discard(name)
            self._seq += 1
            msg = {"type": "hide", "id": name, "seq": self._seq}
            data_by_chan = {"all": msg}
            chan = _window_channel(name)
            if chan in ("chat", "info"):
                data_by_chan[chan] = msg
        self._dispatch(("hide", name), data_by_chan)

    def clear(self) -> None:
        """The overlay stopped: no windows anymore."""
        with self._cond:
            self._windows.clear()
            self._pending.clear()
            self._seq += 1
            msg = {"type": "clear", "seq": self._seq}
            data_by_chan = {"all": msg, "chat": msg, "info": msg}
        self._dispatch(("clear",), data_by_chan)

    # ─────────────────────────── from the server ─────────────────────────── #

    async def connect(self, ws: WebSocket, channel: str = "all") -> None:
        """Size the client's canvas, then send it every window matching its channel."""
        self._loop = asyncio.get_running_loop()
        channel = channel if channel in ("chat", "info") else "all"
        client = _Client(ws, channel=channel)
        with self._cond:
            if channel == "all":
                init = {
                    "type": "init", "width": self._width, "height": self._height,
                    "fps": self._framerate, "channel": "all",
                }
            else:
                c = self._containers[channel]
                init = {
                    "type": "init",
                    "width": c.width + SHADOW.left + SHADOW.right,
                    "height": c.height + SHADOW.top + SHADOW.bottom,
                    "fps": self._framerate,
                    "channel": channel,
                }
            client.put(("init",), json.dumps(init))
            self._clients = self._clients | {client}
            if self._worker is None:
                self._worker_stop = threading.Event()
                self._worker = threading.Thread(
                    target=self._encode_loop, args=(self._worker_stop,), name=THREAD_NAME_OBS_ENCODER, daemon=True
                )
                self._worker.start()
            matching = [
                name for name in self._windows
                if channel == "all" or _window_channel(name) == channel
            ]
            self._pending.update(matching)
            self._cond.notify()
        client.task = asyncio.create_task(client.run(self.disconnect))

    def disconnect(self, ws: WebSocket) -> None:
        """On the event loop."""
        with self._cond:
            gone = {client for client in self._clients if client.ws is ws}
            self._clients = self._clients - gone
        for client in gone:
            if client.task is not None and client.task is not asyncio.current_task():
                client.task.cancel()

    def snapshot(self, channel: str = "all") -> bytes:
        """All visible windows matching channel on one transparent PNG."""
        channel = channel if channel in ("chat", "info") else "all"
        with self._cond:
            windows = [replace(win) for name, win in self._windows.items()
                       if channel == "all" or _window_channel(name) == channel]
            if channel in ("chat", "info"):
                c = self._containers[channel]
                size = (c.width + SHADOW.left + SHADOW.right, c.height + SHADOW.top + SHADOW.bottom)
                x0, y0 = c.x - SHADOW.left, c.y - SHADOW.top
            else:
                size = (self._width, self._height)
                x0, y0 = 0, 0
        frame = Image.new("RGBA", size, (0, 0, 0, 0))
        for win in windows:
            if win.opacity <= 0:
                continue
            image = win.canvas
            if win.opacity < 1:
                image = image.copy()
                image.putalpha(image.getchannel("A").point(lambda a: round(a * win.opacity)))
            # Part of a window may lie off screen (its shadow at the edge)
            wx, wy = win.x - x0, win.y - y0
            left, top = max(0, -wx), max(0, -wy)
            if left < image.width and top < image.height:
                frame.alpha_composite(image, (wx + left, wy + top), (left, top))
        return _png(frame)

    def get_status(self) -> Dict[str, Any]:
        with self._cond:
            shown = len(self._windows)
            chat_c = self._containers["chat"]
            info_c = self._containers["info"]
        return {
            "subscribers": len(self._clients),
            "width": self._width,
            "height": self._height,
            "fps": self._framerate,
            "windows": shown,
            "chat": {
                "width": chat_c.width + SHADOW.left + SHADOW.right,
                "height": chat_c.height + SHADOW.top + SHADOW.bottom,
            },
            "info": {
                "width": info_c.width + SHADOW.left + SHADOW.right,
                "height": info_c.height + SHADOW.top + SHADOW.bottom,
            },
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
                    chan = _window_channel(name)
                    header_all = {
                        "id": name, "seq": content_seq, "state": win.state_seq,
                        "x": win.x, "y": win.y, "opacity": win.opacity,
                    }
                    data_by_chan = {"all": _pack_frame(header_all, png)}
                    if chan in ("chat", "info"):
                        c = self._containers[chan]
                        x0, y0 = c.x - SHADOW.left, c.y - SHADOW.top
                        header_chan = {
                            "id": name, "seq": content_seq, "state": win.state_seq,
                            "x": win.x - x0, "y": win.y - y0, "opacity": win.opacity,
                        }
                        data_by_chan[chan] = _pack_frame(header_chan, png)
                self._dispatch(("picture", name), data_by_chan)

    def _dispatch(self, key: tuple, data_by_channel: Dict[str, Any]) -> None:
        """Queue for every matching client, from any thread."""
        loop = self._loop
        if not self._clients or loop is None or loop.is_closed():
            return
        prepared = {
            chan: val if isinstance(val, bytes) else json.dumps(val)
            for chan, val in data_by_channel.items()
        }
        try:
            loop.call_soon_threadsafe(self._deliver, key, prepared)
        except RuntimeError:
            pass  # The loop closed in between

    def _deliver(self, key: tuple, prepared_by_channel: Dict[str, Any]) -> None:
        for client in self._clients:
            data = prepared_by_channel.get(client.channel)
            if data is not None:
                client.put(key, data)


def same_origin(headers) -> bool:
    """Whether a request comes from an /obs page or no web page at all. The
    API allows every origin, but no other site may watch the HUD. The host
    must be an IP or localhost: a site whose name was rebound to this PC
    sends its own name as both origin and host."""
    host = headers.get("host") or ""
    if not _is_address(urlsplit(f"//{host}").hostname):
        return False
    origin = headers.get("origin")
    return origin is None or urlsplit(origin).netloc == host


def _is_address(hostname: Optional[str]) -> bool:
    if hostname == "localhost":
        return True
    try:
        ipaddress.ip_address(hostname or "")
        return True
    except ValueError:
        return False


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    # Fastest zlib level: sent over localhost, a smaller PNG saves nothing
    image.save(buffer, format="PNG", compress_level=1)
    return buffer.getvalue()
