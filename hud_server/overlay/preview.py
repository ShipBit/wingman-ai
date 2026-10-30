"""
Preview of the shared HUD containers (chat and info panel).

Each container is drawn with sample content in its real style and height,
inside a frame of its whole area: at the frame's top, middle or bottom, as the
container's alignment puts a short message. In interactive mode the preview windows take the mouse: drag
the middle to move a container, an edge or corner to resize it. Every change
is reported through the overlay's event callback as a `preview_changed` event.

Mixed into HeadsUpOverlay; runs on the overlay thread.
"""

import time
from typing import Dict, Optional

from PIL import Image, ImageDraw

from hud_server.constants import GROUP_CHAT, GROUP_INFO
from hud_server.platform import Cursor, Pointer
from hud_server.rendering.glass import SHADOW

PREVIEW_CONTAINERS = {"chat": "message", "info": "persistent"}
SHARED_GROUPS = (GROUP_CHAT, GROUP_INFO)

GRAB = 10  # px from the border that resize instead of move
MIN_WIDTH = 120
MIN_HEIGHT = 60
EVENT_INTERVAL = 0.1  # seconds between live events while dragging
BASE_ALPHA = 3  # invisible, but keeps every pixel of the area clickable

_CURSORS = {
    "move": Cursor.MOVE,
    "n": Cursor.RESIZE_NS,
    "s": Cursor.RESIZE_NS,
    "w": Cursor.RESIZE_WE,
    "e": Cursor.RESIZE_WE,
    "nw": Cursor.RESIZE_NWSE,
    "se": Cursor.RESIZE_NWSE,
    "ne": Cursor.RESIZE_NESW,
    "sw": Cursor.RESIZE_NESW,
}

_LABELS = {"chat": "Chat", "info": "Info Panel"}


class PreviewMixin:
    def _init_preview(self, event_callback=None):
        self._preview_active = False
        self._preview_interactive = False
        self._preview_windows: Dict[str, Dict] = {}
        self._drag: Optional[Dict] = None
        self._hover: Dict[str, Optional[str]] = {}
        self._last_preview_event = 0.0
        self._event_callback = event_callback

    # ─────────────────────────────── commands ─────────────────────────────── #

    def _handle_preview_command(self, msg: dict) -> None:
        if msg.get("type") == "clear_preview":
            self._clear_preview()
            return

        containers = msg.get("containers") or {}
        interactive = bool(msg.get("interactive", False))
        for container, window_type in PREVIEW_CONTAINERS.items():
            props = containers.get(container)
            if props is None:
                self._destroy_preview_window(container)
                continue
            if container == "chat" and props.get("chat_flow"):
                window_type = self.WINDOW_TYPE_CHAT
            dragging = self._drag and self._drag["container"] == container
            if dragging:
                # The rect being dragged is ours; only take the style
                props = {k: v for k, v in props.items() if k not in ("x", "y", "width", "max_height")}
            self._ensure_preview_window(container, window_type, props)

        self._preview_active = bool(self._preview_windows)
        self._preview_interactive = interactive
        for win in self._preview_windows.values():
            if win.get("handle") is not None:
                self._backend.set_click_through(win["handle"], not interactive)
        self._update_obs_containers()

    def _clear_preview(self) -> None:
        if self._drag:
            self._backend.release_pointer()
            self._drag = None
        for container in list(self._preview_windows):
            self._destroy_preview_window(container)
        self._preview_active = False
        self._hover = {}
        self._update_obs_containers()

    def _is_suppressed(self, win: Dict) -> bool:
        """The real shared containers step aside while their preview is shown."""
        return self._preview_active and win.get("group") in SHARED_GROUPS

    # ─────────────────────────────── windows ─────────────────────────────── #

    def _preview_props(self, props: dict) -> dict:
        preview = {
            **props,
            "layout_mode": "manual",
            # The window covers the whole area from its top; the content sits
            # in it where the alignment puts it (_decorate_preview)
            "align": "top",
            "typewriter_effect": False,
        }
        if "align" in props:
            preview["preview_align"] = props["align"]
        return preview

    def _ensure_preview_window(self, container: str, window_type: str, props: dict) -> None:
        name = f"preview_{container}"
        win = self._preview_windows.get(container)
        if win is not None and win["type"] != window_type:
            # The chat flow was switched while previewing: the other sample
            self._destroy_preview_window(container)
            win = None
        if win is None:
            win = self._create_window_state(window_type, f"__preview_{container}", self._preview_props(props))
            win["preview_container"] = container
            self._fill_sample(container, win)
            self._preview_windows[container] = win
            self._register_layout(name, win, int(win["props"].get("max_height", 600)))
            x, y = self._layout_manager.get_position(name) or (0, 0)
            handle = self._backend.create_window(f"HUD_{name}", x, y, int(win["props"].get("width", 400)), 100)
            win["handle"] = handle
            if handle is not None:
                self._backend.set_pointer_handler(
                    handle, lambda event, px, py, c=container: self._on_preview_pointer(c, event, px, py)
                )
        else:
            win["explicit_props"].update(self._preview_props(props))
            self._refresh_window(name, win)

        # Shown at full strength; the profile's opacity is baked into the pixels
        win["fade_state"] = 2
        win["opacity"] = 255
        win["target_opacity"] = 255
        win["last_render_state"] = None

    def _destroy_preview_window(self, container: str) -> None:
        win = self._preview_windows.pop(container, None)
        if not win:
            return
        if win.get("handle") is not None:
            self._backend.set_pointer_handler(win["handle"], None)
        # _destroy_window works on self._windows; borrow the slot
        name = f"preview_{container}"
        self._windows[name] = win
        self._destroy_window(name)

    def _fill_sample(self, container: str, win: Dict) -> None:
        if win["type"] == self.WINDOW_TYPE_CHAT:
            win["messages"] = [
                {
                    "id": "sample-user", "sender": win["props"].get("sample_user") or "User",
                    "text": "How does the chat flow look?", "own": True,
                    "color": win["props"].get("text_color"), "icon": None, "tools": [],
                },
                {
                    "id": "sample-reply", "sender": "Wingman",
                    "text": (
                        "Like a messenger: your messages on the right, ours with our picture.\n\n"
                        "Drag the **middle** to move this container, an **edge** or "
                        "**corner** to resize it."
                    ),
                    "own": False, "color": None, "icon": None,
                    "tools": [{"name": "hud_set_info", "source": "Info Panel", "icon": None}],
                },
            ]
            return

        if container == "chat":
            win["current_message"] = {
                "title": "Wingman",
                "message": (
                    "This is how answers look on your HUD.\n\n"
                    "Drag the **middle** to move this container, an **edge** or "
                    "**corner** to resize it."
                ),
                "tools": [{"name": "hud_set_info", "source": "Info Panel", "icon": None}],
            }
            win["typewriter_active"] = False
            return

        now = time.time()
        win["items"] = {
            "Info Panel": {
                "title": "Info Panel",
                "description": "Your Wingmen and skills pin **information** here.",
                "added_at": now,
            },
            "Progress": {
                "title": "Progress",
                "description": "",
                "added_at": now + 1,
                "is_progress": True,
                "progress_current": 65,
                "progress_maximum": 100,
            },
        }
        win["progress_animations"] = {"Progress": {"current": 65, "target": 65, "start_time": now}}

    # ─────────────────────────────── frame ─────────────────────────────── #

    def _reregister_preview_windows(self) -> None:
        """A new layout manager (another screen) needs the preview windows too."""
        for container, win in self._preview_windows.items():
            self._register_layout(f"preview_{container}", win, int(win["props"].get("max_height", 600)))
            self._invalidate_preview(container)

    def _forget_hover(self) -> None:
        """No mouse-leave message arrives; drop the highlight once the pointer is elsewhere."""
        if self._drag or not any(self._hover.values()):
            return
        mx, my = self._screen_to_monitor(*self._backend.cursor_position())
        for container, zone in list(self._hover.items()):
            if zone is None or container not in self._preview_windows:
                continue
            x1, y1, x2, y2 = self._preview_rect(container)
            if not (x1 <= mx < x2 and y1 <= my < y2):
                self._hover[container] = None
                self._invalidate_preview(container)

    def _update_preview_windows(self) -> None:
        if self._preview_interactive:
            self._forget_hover()
        for container, win in list(self._preview_windows.items()):
            try:
                name = f"preview_{container}"
                if win["type"] == self.WINDOW_TYPE_MESSAGE:
                    self._draw_message_window(name, win)
                elif win["type"] == self.WINDOW_TYPE_CHAT:
                    self._draw_chat_window(name, win)
                else:
                    self._draw_persistent_window(name, win)

                if win.get("canvas") is not None and win.get("_decorated_for") is not win.get(
                    "last_render_state"
                ):
                    self._decorate_preview(container, win)
                    win["_decorated_for"] = win.get("last_render_state")
                    win["canvas_dirty"] = True

                self._blit_window(name, win)
            except Exception as e:
                self._report_exception(f"preview_{container}", e)

    def _decorate_preview(self, container: str, win: Dict) -> None:
        canvas = win["canvas"]
        props = win["props"]
        # The area is the window's body; its shadow's room lies around it
        left, top = SHADOW.left, SHADOW.top
        w = canvas.width - SHADOW.left - SHADOW.right
        body = win.get("body_height") or canvas.height - SHADOW.top - SHADOW.bottom
        h = max(body, int(props.get("max_height", body)))

        # The content at its own height, where the alignment puts it in the area
        align = props.get("preview_align", "top")
        offset = {"center": (h - body) // 2, "bottom": h - body}.get(align, 0)
        framed = Image.new("RGBA", (canvas.width, SHADOW.top + h + SHADOW.bottom), (0, 0, 0, 0))
        framed.paste(canvas, (0, offset))

        # Bake the profile's opacity into the pixels (the window itself stays opaque)
        opacity = max(0.0, min(1.0, float(props.get("opacity", 0.85))))
        r, g, b, a = framed.split()
        a = a.point(lambda v: int(v * opacity))
        content = Image.merge("RGBA", (r, g, b, a))

        base = Image.new("RGBA", framed.size, (0, 0, 0, 0))
        base.paste((0, 0, 0, BASE_ALPHA), (left, top, left + w, top + h))
        decorated = Image.alpha_composite(base, content)

        accent = self._hex_to_rgb(props.get("accent_color", "#00aaff"))
        active = self._hover.get(container) is not None or (
            self._drag is not None and self._drag["container"] == container
        )
        draw = ImageDraw.Draw(decorated)
        self._dashed_rect(draw, left, top, w, h, accent + (255 if active else 170,), solid=active)

        if self._preview_interactive:
            for gx, gy in ((0, 0), (w // 2, 0), (w - 1, 0), (0, h // 2), (w - 1, h // 2),
                           (0, h - 1), (w // 2, h - 1), (w - 1, h - 1)):
                draw.rectangle([left + gx - 4, top + gy - 4, left + gx + 4, top + gy + 4], fill=accent + (230,))

        font = self.fonts.get("code", self.fonts.get("normal"))
        label = f"{_LABELS[container]}  {w}×{h}"
        if font:
            tw, th = self._get_text_size(label, font)
            lx, ly = left + w - tw - 14, top + h - th - 12
            draw.rounded_rectangle([lx - 6, ly - 3, lx + tw + 6, ly + th + 5], radius=6, fill=accent + (220,))
            draw.text((lx, ly), label, fill=(20, 22, 28, 255), font=font)

        # The window grows to the whole area
        win["canvas"] = decorated
        position = self._layout_manager.get_position(f"preview_{container}")
        if position is not None:
            self._place(win, *position)

    @staticmethod
    def _dashed_rect(draw, left, top, w, h, color, solid=False, dash=10, gap=6, width=2):
        right, bottom = left + w - 2, top + h - 2
        if solid:
            draw.rectangle([left + 1, top + 1, right, bottom], outline=color, width=width)
            return
        for x in range(left, left + w, dash + gap):
            draw.line([(x, top + 1), (min(x + dash, left + w - 1), top + 1)], fill=color, width=width)
            draw.line([(x, bottom), (min(x + dash, left + w - 1), bottom)], fill=color, width=width)
        for y in range(top, top + h, dash + gap):
            draw.line([(left + 1, y), (left + 1, min(y + dash, top + h - 1))], fill=color, width=width)
            draw.line([(right, y), (right, min(y + dash, top + h - 1))], fill=color, width=width)

    # ─────────────────────────────── mouse ─────────────────────────────── #

    def _preview_rect(self, container: str) -> tuple:
        """The container's area, relative to the HUD monitor."""
        props = self._preview_windows[container]["props"]
        x1, y1 = int(props.get("x", 20)), int(props.get("y", 20))
        return x1, y1, x1 + int(props.get("width", 400)), y1 + int(props.get("max_height", 600))

    def _screen_to_monitor(self, x: int, y: int) -> tuple:
        ox, oy = self._layout_manager.screen_offset
        return x - ox, y - oy

    def _hit_zone(self, container: str, mx: int, my: int) -> str:
        x1, y1, x2, y2 = self._preview_rect(container)
        zone = ""
        if my - y1 < GRAB:
            zone += "n"
        elif y2 - my < GRAB:
            zone += "s"
        if mx - x1 < GRAB:
            zone += "w"
        elif x2 - mx < GRAB:
            zone += "e"
        return zone or "move"

    def _on_preview_pointer(self, container: str, event: Pointer, x: int, y: int) -> Optional[Cursor]:
        """The mouse over a preview window (screen coordinates); answers with the cursor to show."""
        if container not in self._preview_windows or not self._preview_interactive:
            return None

        mx, my = self._screen_to_monitor(x, y)

        if event == Pointer.HOVER:
            zone = self._drag["zone"] if self._drag else self._hit_zone(container, mx, my)
            return _CURSORS.get(zone, Cursor.ARROW)

        if event == Pointer.PRESS:
            self._drag = {
                "container": container,
                "zone": self._hit_zone(container, mx, my),
                "start": (mx, my),
                "rect": self._preview_rect(container),
            }
            self._backend.capture_pointer(self._preview_windows[container]["handle"])
            self._invalidate_preview(container)
            return None

        if event == Pointer.MOVE:
            if self._drag and self._drag["container"] == container:
                self._drag_to(mx, my)
                return _CURSORS.get(self._drag["zone"], Cursor.ARROW)
            zone = self._hit_zone(container, mx, my)
            if self._hover.get(container) != zone:
                self._hover[container] = zone
                self._invalidate_preview(container)
            return None

        if event == Pointer.RELEASE:
            if self._drag and self._drag["container"] == container:
                self._drag_to(mx, my)
                self._end_drag()
                self._backend.release_pointer()
            return None

        if event == Pointer.LOST:
            if self._drag and self._drag["container"] == container:
                self._end_drag()
        return None

    def _drag_to(self, mx: int, my: int) -> None:
        drag = self._drag
        container, zone = drag["container"], drag["zone"]
        x1, y1, x2, y2 = drag["rect"]
        dx, dy = mx - drag["start"][0], my - drag["start"][1]
        screen_w, screen_h = self._layout_manager.screen_size

        if zone == "move":
            w, h = x2 - x1, y2 - y1
            x1 = max(0, min(x1 + dx, screen_w - w))
            y1 = max(0, min(y1 + dy, screen_h - h))
            x2, y2 = x1 + w, y1 + h
        else:
            if "w" in zone:
                x1 = max(0, min(x1 + dx, x2 - MIN_WIDTH))
            if "e" in zone:
                x2 = min(screen_w, max(x2 + dx, x1 + MIN_WIDTH))
            if "n" in zone:
                y1 = max(0, min(y1 + dy, y2 - MIN_HEIGHT))
            if "s" in zone:
                y2 = min(screen_h, max(y2 + dy, y1 + MIN_HEIGHT))

        if (x1, y1, x2, y2) == self._preview_rect(container):
            return
        win = self._preview_windows[container]
        win["explicit_props"].update(
            self._preview_props({"x": x1, "y": y1, "width": x2 - x1, "max_height": y2 - y1})
        )
        self._refresh_window(f"preview_{container}", win)
        self._invalidate_preview(container)

        now = time.time()
        if now - self._last_preview_event >= EVENT_INTERVAL:
            self._last_preview_event = now
            self._emit_preview_event(container, final=False)

    def _end_drag(self) -> None:
        container = self._drag["container"]
        self._drag = None
        self._invalidate_preview(container)
        self._emit_preview_event(container, final=True)

    def _invalidate_preview(self, container: str) -> None:
        win = self._preview_windows.get(container)
        if win:
            win["last_render_state"] = None

    def _emit_preview_event(self, container: str, final: bool) -> None:
        self._update_obs_containers()
        if not self._event_callback:
            return
        x1, y1, x2, y2 = self._preview_rect(container)
        try:
            self._event_callback({
                "type": "preview_changed",
                "container": container,
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "final": final,
            })
        except Exception as e:
            self._report_exception("preview_event", e)
