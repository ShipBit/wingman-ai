"""
Preview of the shared HUD containers (chat and info panel).

Each container is drawn with sample content in its real style, always filling
its whole area. In interactive mode the preview windows take the mouse: drag
the middle to move a container, an edge or corner to resize it. Every change
is reported through the overlay's event callback as a `preview_changed` event.

Mixed into HeadsUpOverlay; runs on the overlay thread.
"""

import time
from typing import Dict, Optional

from PIL import Image, ImageDraw

from hud_server.constants import GROUP_CHAT, GROUP_INFO
from hud_server.platform.win32 import (
    IDC_ARROW,
    IDC_SIZEALL,
    IDC_SIZENESW,
    IDC_SIZENS,
    IDC_SIZENWSE,
    IDC_SIZEWE,
    MA_NOACTIVATE,
    WM_CAPTURECHANGED,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_MOUSEACTIVATE,
    WM_MOUSEMOVE,
    WM_SETCURSOR,
    get_cursor_pos,
    set_click_through,
    set_cursor,
    set_message_handler,
    user32,
)

PREVIEW_CONTAINERS = {"chat": "message", "info": "persistent"}
SHARED_GROUPS = (GROUP_CHAT, GROUP_INFO)

GRAB = 10  # px from the border that resize instead of move
MIN_WIDTH = 120
MIN_HEIGHT = 60
EVENT_INTERVAL = 0.1  # seconds between live events while dragging
BASE_ALPHA = 3  # invisible, but keeps every pixel of the area clickable

_CURSORS = {
    "move": IDC_SIZEALL,
    "n": IDC_SIZENS,
    "s": IDC_SIZENS,
    "w": IDC_SIZEWE,
    "e": IDC_SIZEWE,
    "nw": IDC_SIZENWSE,
    "se": IDC_SIZENWSE,
    "ne": IDC_SIZENESW,
    "sw": IDC_SIZENESW,
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
            dragging = self._drag and self._drag["container"] == container
            if dragging:
                # The rect being dragged is ours; only take the style
                props = {k: v for k, v in props.items() if k not in ("x", "y", "width", "max_height")}
            self._ensure_preview_window(container, window_type, props)

        self._preview_active = bool(self._preview_windows)
        self._preview_interactive = interactive
        for win in self._preview_windows.values():
            set_click_through(win["hwnd"], not interactive)

    def _clear_preview(self) -> None:
        if self._drag:
            user32.ReleaseCapture()
            self._drag = None
        for container in list(self._preview_windows):
            self._destroy_preview_window(container)
        self._preview_active = False
        self._hover = {}

    def _is_suppressed(self, win: Dict) -> bool:
        """The real shared containers step aside while their preview is shown."""
        return self._preview_active and win.get("group") in SHARED_GROUPS

    # ─────────────────────────────── windows ─────────────────────────────── #

    def _preview_props(self, props: dict) -> dict:
        preview = {
            **props,
            "layout_mode": "manual",
            "align": "top",
            "typewriter_effect": False,
        }
        # Always as tall as the area; a style-only update keeps the height it has
        if "max_height" in props:
            preview["height"] = int(props["max_height"])
        return preview

    def _ensure_preview_window(self, container: str, window_type: str, props: dict) -> None:
        name = f"preview_{container}"
        win = self._preview_windows.get(container)
        if win is None:
            win = self._create_window_state(window_type, f"__preview_{container}", self._preview_props(props))
            win["preview_container"] = container
            self._fill_sample(container, win)
            self._preview_windows[container] = win
            self._register_layout(name, win, int(win["props"].get("max_height", 600)))
            x, y = self._layout_manager.get_position(name) or (0, 0)
            hwnd = self._create_overlay_window(f"HUD_{name}", x, y, int(win["props"].get("width", 400)), 100)
            if hwnd:
                win["window_dc"], win["mem_dc"] = self._init_gdi(hwnd)
                win["hwnd"] = hwnd
                set_message_handler(
                    hwnd, lambda m, w, l, c=container: self._on_preview_mouse(c, m, w, l)
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
        set_message_handler(win.get("hwnd"), None)
        # _destroy_window works on self._windows; borrow the slot
        name = f"preview_{container}"
        self._windows[name] = win
        self._destroy_window(name)

    def _fill_sample(self, container: str, win: Dict) -> None:
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
        mx, my = self._screen_to_monitor(*get_cursor_pos())
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
        w, h = canvas.size

        # Bake the profile's opacity into the pixels (the window itself stays opaque)
        opacity = max(0.0, min(1.0, float(props.get("opacity", 0.85))))
        r, g, b, a = canvas.split()
        a = a.point(lambda v: int(v * opacity))
        content = Image.merge("RGBA", (r, g, b, a))

        base = Image.new("RGBA", (w, h), (0, 0, 0, BASE_ALPHA))
        decorated = Image.alpha_composite(base, content)

        accent = self._hex_to_rgb(props.get("accent_color", "#00aaff"))
        active = self._hover.get(container) is not None or (
            self._drag is not None and self._drag["container"] == container
        )
        draw = ImageDraw.Draw(decorated)
        self._dashed_rect(draw, w, h, accent + (255 if active else 170,), solid=active)

        if self._preview_interactive:
            for gx, gy in ((0, 0), (w // 2, 0), (w - 1, 0), (0, h // 2), (w - 1, h // 2),
                           (0, h - 1), (w // 2, h - 1), (w - 1, h - 1)):
                draw.rectangle([gx - 4, gy - 4, gx + 4, gy + 4], fill=accent + (230,))

        font = self.fonts.get("code", self.fonts.get("normal"))
        label = f"{_LABELS[container]}  {w}×{h}"
        if font:
            tw, th = self._get_text_size(label, font)
            lx, ly = w - tw - 14, h - th - 12
            draw.rounded_rectangle([lx - 6, ly - 3, lx + tw + 6, ly + th + 5], radius=6, fill=accent + (220,))
            draw.text((lx, ly), label, fill=(20, 22, 28, 255), font=font)

        canvas.paste(decorated, (0, 0))

    @staticmethod
    def _dashed_rect(draw, w, h, color, solid=False, dash=10, gap=6, width=2):
        if solid:
            draw.rectangle([1, 1, w - 2, h - 2], outline=color, width=width)
            return
        for x in range(0, w, dash + gap):
            draw.line([(x, 1), (min(x + dash, w - 1), 1)], fill=color, width=width)
            draw.line([(x, h - 2), (min(x + dash, w - 1), h - 2)], fill=color, width=width)
        for y in range(0, h, dash + gap):
            draw.line([(1, y), (1, min(y + dash, h - 1))], fill=color, width=width)
            draw.line([(w - 2, y), (w - 2, min(y + dash, h - 1))], fill=color, width=width)

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

    def _on_preview_mouse(self, container: str, msg: int, wparam, lparam):
        if container not in self._preview_windows or not self._preview_interactive:
            return None

        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE

        mx, my = self._screen_to_monitor(*get_cursor_pos())

        if msg == WM_SETCURSOR:
            zone = self._drag["zone"] if self._drag else self._hit_zone(container, mx, my)
            set_cursor(_CURSORS.get(zone, IDC_ARROW))
            return 1

        if msg == WM_LBUTTONDOWN:
            self._drag = {
                "container": container,
                "zone": self._hit_zone(container, mx, my),
                "start": (mx, my),
                "rect": self._preview_rect(container),
            }
            user32.SetCapture(self._preview_windows[container]["hwnd"])
            self._invalidate_preview(container)
            return 0

        if msg == WM_MOUSEMOVE:
            if self._drag and self._drag["container"] == container:
                set_cursor(_CURSORS.get(self._drag["zone"], IDC_ARROW))
                self._drag_to(mx, my)
            else:
                zone = self._hit_zone(container, mx, my)
                if self._hover.get(container) != zone:
                    self._hover[container] = zone
                    self._invalidate_preview(container)
            return 0

        if msg == WM_LBUTTONUP:
            if self._drag and self._drag["container"] == container:
                self._drag_to(mx, my)
                self._end_drag()
                user32.ReleaseCapture()
            return 0

        if msg == WM_CAPTURECHANGED:
            if self._drag and self._drag["container"] == container:
                self._end_drag()
            return 0

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
