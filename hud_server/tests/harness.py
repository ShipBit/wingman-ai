"""What every HUD demo runs on.

A demo drives the HUD server through its HTTP API, as any client does:

- live (the default): the HUD server already running on the port (Core's,
  when Core runs with the HUD on), or one started here. Its windows show on
  your screen, and the pauses give you time to look.
- headless: a server inside this process, reached without a port, drawing
  into windows that are never shown, with pauses of one frame. pytest runs
  every suite this way (tests/hud/test_demo_suites.py).

Every request the server refuses is recorded, and every error the overlay
reports when the server is ours; the runner lists them at the end. Demos use
their own groups (`demo_*`), never Core's chat and info panel, and the HUD is
left as it was found: those groups go, the defaults come back, no preview.
"""

import asyncio
import base64
import io
import os
import shutil
import tempfile
from types import SimpleNamespace
from typing import Optional

import httpx
from PIL import Image, ImageDraw, ImageFont

from hud_server.http_client import HudHttpClient
from hud_server.platform.base import HudBackend, Monitor

HERE = os.path.dirname(os.path.abspath(__file__))
WIDE_IMAGE = os.path.join(HERE, "test.png")
PHOTO = os.path.join(HERE, "test_abg.png")

MESSAGE = "demo_message"
CHAT = "demo_chat"
INFO = "demo_info"

# The look of a HUD profile as Core sends it (bg_opacity folded into bg_color)
STYLE = {
    "font_family": "Segoe UI",
    "font_size": 16,
    "accent_color": "#d84f4f",
    "bg_color": "#202227d9",
    "text_color": "#cccccc",
    "border_radius": 12,
    "content_padding": 16,
    "opacity": 0.9,
    "typewriter_effect": True,
}


def area(x1: int, y1: int, x2: int, y2: int, align: str = "top") -> dict:
    """A container's area, as Core turns a profile's x1/y1/x2/y2 into props."""
    return {"layout_mode": "manual", "x": x1, "y": y1, "width": x2 - x1, "max_height": y2 - y1, "align": align}


class HeadlessBackend(HudBackend):
    """Windows that are never shown. The fonts come from this OS's backend,
    so text is measured and drawn as it would be on screen."""

    def __init__(self):
        from hud_server.platform import create_backend

        self._os_backend = create_backend()
        self.windows: list = []
        self.presented = 0
        """Pictures drawn: proof the overlay drew what the demos sent."""

    def start(self):
        pass

    def stop(self):
        self.windows.clear()

    def pump_events(self):
        pass

    def create_window(self, title, x, y, width, height):
        window = SimpleNamespace(title=title, rect=(x, y, width, height), image=None, shown=True)
        self.windows.append(window)
        return window

    def destroy_window(self, window):
        if window in self.windows:
            self.windows.remove(window)

    def move_window(self, window, x, y, width, height):
        window.rect = (x, y, width, height)

    def raise_window(self, window):
        pass

    def show_window(self, window):
        window.shown = True

    def hide_window(self, window):
        window.shown = False

    def present(self, window, image, opacity):
        window.image = image
        self.presented += 1

    def set_click_through(self, window, click_through):
        pass

    def set_pointer_handler(self, window, handler):
        pass

    def capture_pointer(self, window):
        pass

    def release_pointer(self):
        pass

    def cursor_position(self):
        return 0, 0

    def monitors(self):
        return [Monitor(0, 0, 1920, 1080, True)]

    def font_set(self, family):
        return self._os_backend.font_set(family)


class _Recording(httpx.AsyncBaseTransport):
    """Notes every answer the server gives with an error status."""

    def __init__(self, inner: httpx.AsyncBaseTransport, demo: "Demo"):
        self._inner = inner
        self._demo = demo

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        if response.status_code >= 400:
            await response.aread()
            self._demo.fail(f"{request.method} {request.url.path} -> {response.status_code}: {response.text[:300]}")
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


class _Client(HudHttpClient):
    """The HUD client, noting the groups a demo uses and requests that got no answer."""

    def __init__(self, demo: "Demo", base_url: str, transport: httpx.AsyncBaseTransport):
        super().__init__(base_url, transport=_Recording(transport, demo))
        self._demo = demo

    async def _request(self, method, path, json=None):
        if json and json.get("group_name") and json.get("element"):
            self._demo.used.add((json["group_name"], json["element"]))
        failures = len(self._demo.failures)
        result = await super()._request(method, path, json)
        if result is None and len(self._demo.failures) == failures:
            self._demo.fail(f"{method} {path} -> no answer")
        return result


class Demo:
    """One run of demos: the server, a client for it, what went wrong."""

    def __init__(self, *, headless: bool = False, speed: Optional[float] = None, host: str = "127.0.0.1",
                 port: int = 7862, screen: int = 1, web: bool = True):
        self.headless = headless
        self.speed = speed if speed is not None else (0.0 if headless else 1.0)
        self.web = web and not headless
        self.host, self.port, self.screen = host, port, screen
        self.failures: list[str] = []
        self.overlay_errors: list[str] = []
        self.used: set[tuple] = set()
        self.server = None
        """Ours, when this run started one; None when it uses Core's."""
        self.backend: Optional[HeadlessBackend] = None
        """Headless: the windows the overlay drew into."""
        self.client: Optional[_Client] = None
        self._lifespan = None
        self._quiet = False
        self._found_defaults: Optional[dict] = None
        self._files = tempfile.mkdtemp(prefix="hud_demo_")

    # ─────────────────────────────── lifecycle ─────────────────────────────── #

    async def __aenter__(self) -> "Demo":
        from hud_server.server import HudServer

        if self.headless:
            self.backend = HeadlessBackend()
            self.server = HudServer(backend=self.backend)
            self.server.add_event_listener(self._on_event)
            # The app's startup (it starts the overlay), as uvicorn would run it
            self._lifespan = self.server.app.router.lifespan_context(self.server.app)
            await self._lifespan.__aenter__()
            self.client = _Client(self, "http://hud.headless", httpx.ASGITransport(app=self.server.app))
            if not await self.client.connect():
                raise RuntimeError("The headless HUD server did not answer")
        else:
            url = f"http://{self.host}:{self.port}"
            self.client = _Client(self, url, httpx.AsyncHTTPTransport())
            if await self.client.connect(timeout=2.0):
                print(f"Using the HUD server running on {url} (Core's?); its overlay errors go to its log.")
            else:
                self.server = HudServer()
                self.server.add_event_listener(self._on_event)
                if not self.server.start(host=self.host, port=self.port, screen=self.screen):
                    raise RuntimeError(f"Could not start a HUD server on {url}")
                if not await self.client.connect():
                    raise RuntimeError(f"The HUD server on {url} does not answer")
                print(f"Started a HUD server on {url}.")
        self._found_defaults = await self.client.get_defaults()
        return self

    async def __aexit__(self, *exc) -> None:
        try:
            await self.clean_up()
            await self.settle()
        finally:
            await self.client.disconnect()
            if self._lifespan is not None:
                await self._lifespan.__aexit__(None, None, None)
            elif self.server is not None:
                await self.server.stop()
            shutil.rmtree(self._files, ignore_errors=True)

    async def clean_up(self) -> None:
        """Put the HUD back as found: no preview, the demo groups gone, the
        defaults it had. A group the server no longer has is no failure."""
        self._quiet = True
        try:
            await self.client.clear_preview()
            for group, element in sorted(self.used):
                await self.client.delete_group(group, element)
            self.used.clear()
        finally:
            self._quiet = False
        if self._found_defaults is not None:
            await self.client.set_defaults(self._found_defaults.get("props"), self._found_defaults.get("groups"))

    def _on_event(self, event: dict) -> None:
        if event.get("type") == "overlay_error":
            self.overlay_errors.append(f"{event.get('context')}: {event.get('error')}")

    # ─────────────────────────────── pacing ─────────────────────────────── #

    async def pause(self, seconds: float) -> None:
        """Time to look. Headless, one frame: enough for the overlay to draw
        the step, so a step that breaks the drawing is caught."""
        await asyncio.sleep(seconds / self.speed if self.speed > 0 else 1 / 60)

    async def settle(self) -> None:
        """Let the overlay draw everything sent so far."""
        await asyncio.sleep(0.3)

    def scene(self, title: str, look_for: str = "") -> None:
        print(f"\n-- {title}")
        if look_for and not self.headless:
            print(f"   Look for: {look_for}")

    def fail(self, what: str) -> None:
        if self._quiet:
            return
        self.failures.append(what)
        print(f"   FAILED: {what}")

    def new_client(self) -> HudHttpClient:
        """Another client of the same server, as a second app would be."""
        if self.headless:
            return _Client(self, "http://hud.headless", httpx.ASGITransport(app=self.server.app))
        return _Client(self, f"http://{self.host}:{self.port}", httpx.AsyncHTTPTransport())

    @property
    def own_server(self) -> bool:
        """This run started the server (or runs headless): its settings may change."""
        return self.server is not None

    def check(self, ok, what: str) -> None:
        """Record `what` as a failure unless `ok`."""
        if not ok:
            self.fail(what)

    # ─────────────────────────────── pictures ─────────────────────────────── #

    def picture(self, name: str, color: str) -> str:
        """A round profile picture with the name's initial, as a file."""
        path = os.path.join(self._files, f"picture_{name}_{color.strip('#')}.png")
        if not os.path.exists(path):
            size = 128
            r, g, b = (int(color.strip("#")[i:i + 2], 16) for i in (0, 2, 4))
            image = Image.new("RGBA", (size, size))
            draw = ImageDraw.Draw(image)
            for y in range(size):
                t = y / size
                draw.line([(0, y), (size, y)], fill=(int(r * (1 - t * 0.6)), int(g * (1 - t * 0.6)), int(b * (1 - t * 0.6)), 255))
            draw.text((size / 2, size / 2), name[:1].upper(), fill=(255, 255, 255, 255),
                      font=ImageFont.load_default(size=72), anchor="mm")
            image.save(path)
        return path

    def icon(self, name: str, color: str) -> str:
        """A small square icon, as a skill's or MCP server's icon file."""
        path = os.path.join(self._files, f"icon_{name}_{color.strip('#')}.png")
        if not os.path.exists(path):
            image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle([4, 4, 59, 59], radius=14, fill=color)
            draw.text((32, 33), name[:1].upper(), fill=(255, 255, 255, 255),
                      font=ImageFont.load_default(size=36), anchor="mm")
            image.save(path)
        return path

    @staticmethod
    def data_uri(path: str, width: int = 240, photo: bool = False) -> str:
        """A picture as a base64 data URI, as a tool may hand one back: a
        photo as JPEG (a message takes at most 50,000 characters), else PNG."""
        with Image.open(path) as image:
            image = image.convert("RGB" if photo else "RGBA")
            image.thumbnail((width, width))
            buffer = io.BytesIO()
            image.save(buffer, "JPEG" if photo else "PNG", quality=80)
        kind = "jpeg" if photo else "png"
        return f"data:image/{kind};base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
