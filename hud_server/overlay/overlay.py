"""
HeadsUp Overlay - PIL-based implementation with sophisticated Markdown rendering

This implementation uses ONLY:
- PIL (Pillow) for rendering (text, shapes, images)
- a platform backend (hud_server/platform) for the OS's windows, so the
  renderer itself runs on every OS
"""

import os
import time
import queue
import re
from typing import Tuple, Dict, Optional
import traceback

# PIL for rendering
try:
    from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None
    ImageDraw = None
    ImageFont = None
    ImageChops = None
    ImageOps = None

from services.markdown import display_text
from hud_server.rendering import glass
from hud_server.rendering.markdown import MarkdownRenderer
from hud_server.rendering.layers import Piece, PieceCache, compose, lay_out, render_piece

from hud_server.platform import HudBackend, create_backend
from hud_server.layout import LayoutManager, Anchor, LayoutMode, Align
from hud_server.overlay.preview import PreviewMixin


def round_avatar(image: "Image.Image", size: int) -> "Image.Image":
    """The picture's center as a circle `size` wide, with a smooth edge."""
    avatar = ImageOps.fit(image.convert("RGBA"), (size, size), Image.Resampling.LANCZOS)
    # Drawn 4x larger and scaled down, so the edge is anti-aliased
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size * 4 - 1, size * 4 - 1], fill=255)
    mask = mask.resize((size, size), Image.Resampling.LANCZOS)
    avatar.putalpha(ImageChops.multiply(avatar.getchannel("A"), mask))
    return avatar


class HeadsUpOverlay(PreviewMixin):
    """HUD Overlay with sophisticated Markdown rendering.

    Architecture (Rework v2):
    - All HUD elements are managed through a unified window system
    - Each group (wingman) can have its own message window and persistent window
    - Windows are created on-demand and identified by unique names
    - Window types: 'message', 'persistent', 'chat'
    """

    # Window type constants
    WINDOW_TYPE_MESSAGE = "message"
    WINDOW_TYPE_PERSISTENT = "persistent"
    WINDOW_TYPE_CHAT = "chat"

    def __init__(
        self,
        command_queue=None,
        error_queue=None,
        framerate: int = 60,
        layout_margin: int = 20,
        layout_spacing: int = 15,
        screen: int = 1,
        event_callback=None,
        backend: Optional[HudBackend] = None,
    ):
        self.running = True
        self.msg_queue = command_queue if command_queue else queue.Queue()
        self.error_queue = error_queue
        self.dt = 0.0
        self.last_update_time = 0.0
        self._global_framerate = max(1, framerate)
        self._layout_margin = layout_margin
        self._layout_spacing = layout_spacing
        self._screen = screen

        # The OS's windows (hud_server/platform)
        self._backend = backend or create_backend()

        # =====================================================================
        # UNIFIED WINDOW SYSTEM
        # =====================================================================
        # All windows are stored in this dictionary, keyed by unique window name.
        # Window name format: "{type}_{group}" e.g. "message_ATC", "persistent_Computer"
        #
        # Each window state contains:
        # - 'type': str - 'message', 'persistent', or 'chat'
        # - 'group': str - the group name this window belongs to
        # - 'explicit_props': dict - props sent with commands for this window
        # - 'props': dict - resolved display properties (x, y, width, colors, etc.)
        # - 'handle': the backend's window (None until created)
        # - 'canvas': PIL Image - the picture last handed to the backend
        # - 'canvas_dirty': bool - the backend has not got the picture yet
        # - 'pieces', 'static_canvas', 'static_signature': the cached drawing (_draw_stack)
        # - 'fade_state': 0=hidden, 1=fade_in, 2=visible, 3=fade_out
        # - 'opacity': current opacity (0-255)
        # - 'target_opacity': target opacity (0-255)
        # - 'last_render_state': the layout last presented
        # - 'hidden': bool - hidden by hide_element
        # - 'show_on_present': bool - show the OS window with the next picture
        # - 'present_failed': bool - the backend could not draw the last picture
        #
        # Type-specific fields:
        # Message windows:
        # - 'current_message': dict or None
        # - 'is_loading': bool
        # - 'loading_color': tuple
        # - 'typewriter_active': bool
        # - 'typewriter_char_count': float
        # - 'last_typewriter_update': float
        # - 'min_display_time': float
        # - 'current_blocks': parsed markdown blocks
        #
        # Persistent windows:
        # - 'items': dict[title -> item_info]
        # - 'progress_animations': dict[title -> animation_state]
        # - 'collides': bool - its group's message window covers it
        #
        # Chat windows:
        # - 'messages': list of chat messages
        # - 'last_message_time': float
        # - 'visible': bool
        # - 'is_loading', 'loading_color': the loader
        # - 'typing': the reply being typed (id, chars, last)
        self._windows: Dict[str, Dict] = {}

        # Default properties for new windows
        self._default_props = {
            "width": 400,
            "x": 20,
            "y": 20,
            "bg_color": "#1e212b",
            "text_color": "#f0f0f0",
            "accent_color": "#00aaff",
            "opacity": 0.85,
            "duration": 8.0,
            "border_radius": 12,
            "content_padding": 16,
            "max_height": 600,
            "font_size": 16,
            "font_family": "Segoe UI",
            "color_emojis": True,
            "typewriter_effect": True,
        }

        # Server defaults (set_defaults): for every group, and per group name
        self._server_defaults: Dict = {}
        self._group_defaults: Dict[str, Dict] = {}

        # Explicit group props (create_group/update_group), keyed by window name
        self._group_props: Dict[str, Dict] = {}

        # Progress animation transition duration
        self._progress_transition_duration = 0.5

        # =====================================================================
        # SHARED RESOURCES (used by unified window system)
        # =====================================================================
        self.fonts = {}
        self.image_cache = {}
        # One markdown renderer per font, kept across frames (see _window_renderer)
        self._md_renderers: Dict[tuple, MarkdownRenderer] = {}
        self._bubble_refs: Dict[int, tuple] = {}
        self.md_renderer = None

        # Font cache: stores font sets by (family, size) to avoid reloading
        # Key: (family, size) -> {font_dict with font objects}
        self._font_cache: Dict[tuple, Dict] = {}
        # The window's smaller font: names above bubbles, tool chips
        self.small_fonts = {}

        # =====================================================================
        # LAYOUT MANAGER
        # =====================================================================
        # Automatic positioning and stacking to prevent window overlap
        # Get screen dimensions and offset based on selected monitor
        monitor = self._backend.monitor(self._screen)
        self._layout_manager = LayoutManager(
            screen_width=monitor.width,
            screen_height=monitor.height,
            screen_offset_x=monitor.x,
            screen_offset_y=monitor.y,
            default_margin=self._layout_margin,
            default_spacing=self._layout_spacing,
        )

        # Preview of the shared containers (see preview.py)
        self._init_preview(event_callback)

    # =========================================================================
    # UNIFIED WINDOW MANAGEMENT
    # =========================================================================

    def _get_window_name(self, window_type: str, group: str) -> str:
        """Generate a unique window name from type and group."""
        return f"{window_type}_{group}"

    def _resolve_window_props(
        self, window_type: str, group: str, explicit: dict = None
    ) -> dict:
        """Built-in values, then server defaults, then group defaults, then the
        group's own props, then the props sent with commands for this window."""
        props = dict(self._default_props)
        props.update(self._server_defaults)
        props.update(self._group_defaults.get(group, {}))
        props.update(self._group_props.get(self._get_window_name(window_type, group), {}))
        if explicit:
            props.update(explicit)
        return props

    def _layout_params(self, win: Dict) -> dict:
        """Layout manager arguments for a window, taken from its resolved props."""
        props = win["props"]
        try:
            anchor = Anchor(props.get("anchor", "top_left"))
        except ValueError:
            anchor = Anchor.TOP_LEFT
        try:
            mode = LayoutMode(props.get("layout_mode", "auto"))
        except ValueError:
            mode = LayoutMode.AUTO
        try:
            align = Align(props.get("align", "top"))
        except ValueError:
            align = Align.TOP

        priority = int(props.get("priority", 10))
        # Persistent windows stack below the message window of the same priority
        if win.get("type") == self.WINDOW_TYPE_PERSISTENT:
            priority = max(0, priority - 5)

        manual = mode == LayoutMode.MANUAL
        return {
            "anchor": anchor,
            "mode": mode,
            "priority": priority,
            "width": int(props.get("width", 400)),
            "manual_x": int(props.get("x", 20)) if manual else None,
            "manual_y": int(props.get("y", 20)) if manual else None,
            "align": align,
            "area_height": int(props.get("max_height", 600)) if manual else None,
            "margin": int(props.get("margin", self._layout_margin)),
            "spacing": int(props.get("spacing", self._layout_spacing)),
        }

    def _register_layout(self, name: str, win: Dict, height: int):
        params = self._layout_params(win)
        margin = params.pop("margin")
        self._layout_manager.register_window(
            name=name,
            height=height,
            margin_x=margin,
            margin_y=margin,
            **params,
        )

    def _refresh_window(self, name: str, win: Dict):
        """Re-resolve a window's props after defaults or group props changed."""
        new_props = self._resolve_window_props(
            win["type"], win["group"], win.get("explicit_props")
        )
        old_props = win.get("props", {})
        if new_props == old_props:
            return

        win["props"] = new_props
        win["target_opacity"] = int(new_props.get("opacity", 0.85) * 255)
        win["last_render_state"] = None
        win["canvas_dirty"] = True
        if old_props.get("width") != new_props.get("width"):
            win["canvas"] = None
        if old_props.get("font_size") != new_props.get("font_size") or old_props.get(
            "font_family"
        ) != new_props.get("font_family"):
            win["current_blocks"] = None

        self._layout_manager.update_window(name, **self._layout_params(win))

    def _refresh_windows(self):
        """Re-resolve every window, after the defaults changed."""
        for name, win in list(self._windows.items()):
            self._refresh_window(name, win)

    def _create_window_state(
        self, window_type: str, group: str, props: dict = None
    ) -> Dict:
        """Create a new window state dictionary."""
        explicit_props = dict(props or {})
        merged_props = self._resolve_window_props(window_type, group, explicit_props)

        state = {
            "type": window_type,
            "group": group,
            "explicit_props": explicit_props,
            "props": merged_props,
            "handle": None,
            "canvas": None,
            "canvas_dirty": False,
            "fade_state": 0,  # hidden
            "opacity": 0,
            "target_opacity": int(merged_props.get("opacity", 0.85) * 255),
            "last_render_state": None,
            "hidden": False,  # manually hidden flag
        }

        # Type-specific initialization
        if window_type == self.WINDOW_TYPE_MESSAGE:
            state.update(
                {
                    "current_message": None,
                    "is_loading": False,
                    "loading_color": None,  # None: the accent color
                    "typewriter_active": False,
                    "typewriter_char_count": 0,
                    "last_typewriter_update": 0,
                    "min_display_time": 0,
                    "current_blocks": None,
                }
            )
        elif window_type == self.WINDOW_TYPE_PERSISTENT:
            state.update(
                {
                    "items": {},
                    "progress_animations": {},
                }
            )
        elif window_type == self.WINDOW_TYPE_CHAT:
            state.update(
                {
                    "messages": [],
                    "last_message_time": 0,
                    "visible": True,
                    "is_loading": False,
                    "loading_color": None,  # None: the accent color
                }
            )

        return state

    def _ensure_window(self, window_type: str, group: str, props: dict = None) -> Dict:
        """Get or create a window for the given type and group."""
        name = self._get_window_name(window_type, group)

        if name not in self._windows:
            # Create new window state
            state = self._create_window_state(window_type, group, props)
            self._windows[name] = state

            # Create the OS window
            window_props = state["props"]
            w = int(window_props.get("width", 400))
            h = 100  # Initial height, will be adjusted during rendering

            self._register_layout(name, state, h)

            # Get initial position from layout manager
            pos = self._layout_manager.get_position(name)
            if pos:
                x, y = pos
            else:
                x = int(window_props.get("x", 20))
                y = int(window_props.get("y", 20))

            state["handle"] = self._backend.create_window(f"HUD_{name}", x, y, w, h)
        elif props:
            win = self._windows[name]
            win.setdefault("explicit_props", {}).update(props)
            self._refresh_window(name, win)

        return self._windows[name]

    def _command_window_types(self, msg: dict) -> list:
        """The element a group command targets, or every type if it names none."""
        element = msg.get("element")
        if element:
            return [element]
        return [
            self.WINDOW_TYPE_MESSAGE,
            self.WINDOW_TYPE_PERSISTENT,
            self.WINDOW_TYPE_CHAT,
        ]

    def _get_window(self, window_type: str, group: str) -> Dict:
        """Get a window state, or None if it doesn't exist."""
        name = self._get_window_name(window_type, group)
        return self._windows.get(name)

    def _destroy_window(self, name: str):
        """Destroy a window and clean up its resources."""
        if name not in self._windows:
            return

        state = self._windows[name]

        if state.get("handle") is not None:
            try:
                self._backend.destroy_window(state["handle"])
            except Exception:
                pass
            state["handle"] = None

        # Unregister from layout manager
        self._layout_manager.unregister_window(name)

        del self._windows[name]

    # =========================================================================
    # UNIFIED WINDOW UPDATE AND RENDER LOOP
    # =========================================================================

    def _update_all_windows(self):
        """Update and render all windows in the unified system."""
        # First pass: update and draw all windows
        message_windows = {}
        persistent_windows = {}

        for name, win in list(self._windows.items()):
            try:
                win_type = win.get("type")
                group = win.get("group", "default")
                # Check if window is manually hidden or steps aside for a preview
                is_hidden = win.get("hidden", False) or self._is_suppressed(win)

                if win_type == self.WINDOW_TYPE_MESSAGE:
                    message_windows[group] = win
                    self._update_message_window(name, win)
                    # Only draw and blit if not hidden
                    if not is_hidden:
                        self._draw_message_window(name, win)
                        self._blit_window(name, win)

                elif win_type == self.WINDOW_TYPE_PERSISTENT:
                    persistent_windows[group] = win
                    self._update_persistent_window(name, win)
                    # Only draw if not hidden (blit happens in second pass)
                    if not is_hidden:
                        self._draw_persistent_window(name, win)
                    # Don't blit yet - wait for collision check

                elif win_type == self.WINDOW_TYPE_CHAT:
                    self._update_chat_window(name, win)
                    # Only draw and blit if not hidden
                    if not is_hidden:
                        self._draw_chat_window(name, win)
                        self._blit_window(name, win)

            except Exception as e:
                self._report_exception(f"update_window_{name}", e)

        # Second pass: check collisions and update persistent windows
        for group, pers_win in persistent_windows.items():
            try:
                is_hidden = pers_win.get("hidden", False) or self._is_suppressed(pers_win)
                # Only blit if not hidden
                if not is_hidden:
                    msg_win = message_windows.get(group)
                    # Read by the next frame's fade (_update_persistent_window)
                    pers_win["collides"] = self._check_window_collision(msg_win, pers_win)
                    self._blit_window(
                        self._get_window_name(self.WINDOW_TYPE_PERSISTENT, group),
                        pers_win,
                    )
            except Exception as e:
                self._report_exception(f"persistent_collision_{group}", e)

        # Third pass: Update ALL window positions from layout manager
        # This ensures windows reposition when others hide/show/resize
        self._update_all_window_positions()

        if self._preview_windows:
            self._update_preview_windows()

    def _update_all_window_positions(self):
        """Update positions of all windows based on layout manager calculations."""
        # Force recompute positions
        positions = self._layout_manager.compute_positions(force=True)

        for name, win in self._windows.items():
            if win.get("handle") is None or win.get("hidden", False):
                continue
            # Skip windows that are completely hidden (fade_state 0 AND opacity 0)
            if win.get("fade_state", 0) == 0 and win.get("opacity", 0) == 0:
                continue
            # Repositioned even while fading out, so the layout follows other windows at once
            pos = positions.get(name)
            if pos and self._place(win, *pos):
                win["canvas_dirty"] = True  # Force reblit after move

    SLIDE = 8
    """How far a window rises into place while it fades in."""

    def _place(self, win: Dict, x: int, y: int) -> bool:
        """Put the window's body at (x, y): its picture starts the shadow's
        room further up and left, and it rises into place while it fades in.
        Returns whether the OS window moved."""
        canvas, handle = win.get("canvas"), win.get("handle")
        if canvas is None or handle is None:
            return False
        lift = 0
        target = win.get("target_opacity", 0)
        if win.get("fade_state") == 1 and target > 0:
            lift = round(self.SLIDE * (1 - min(1.0, win.get("opacity", 0) / target)) ** 2)
        rect = (x - glass.SHADOW.left, y - glass.SHADOW.top + lift, canvas.width, canvas.height)
        if rect == win.get("_rect"):
            return False
        self._backend.move_window(handle, *rect)
        win["_rect"] = rect
        return True

    def _update_message_window(self, name: str, win: Dict):
        """Update message window state (typewriter, fade, etc.)."""
        # Typewriter progression
        if win.get("typewriter_active") and win.get("current_message"):
            now = time.time()
            chars = (now - win.get("last_typewriter_update", now)) * 200
            if chars > 0:
                win["typewriter_char_count"] = (
                    win.get("typewriter_char_count", 0) + chars
                )
                win["last_typewriter_update"] = now
                msg_len = len(win["current_message"].get("message", ""))
                if win["typewriter_char_count"] >= msg_len:
                    win["typewriter_active"] = False
                    win["typewriter_char_count"] = float(msg_len)

        # Fade logic
        self._update_window_fade(
            win, has_content=bool(win.get("current_message") or win.get("is_loading"))
        )

        # Auto-hide check
        if win["fade_state"] == 2:  # visible
            should_fade = True
            if win.get("is_loading"):
                should_fade = False
            elif win.get("current_message"):
                if time.time() <= win.get("min_display_time", 0):
                    should_fade = False
            if should_fade:
                win["fade_state"] = 3
                # Clear message so has_content becomes False and fade-out can proceed
                win["current_message"] = None
                # Note: Don't release layout slot yet - window still visible during fade-out
                # Layout slot will be released when fade completes (opacity reaches 0)

    def _update_persistent_window(self, name: str, win: Dict):
        """Update persistent window state (progress animations, expiry, etc.)."""
        now = time.time()
        items = win.get("items", {})
        progress_anims = win.get("progress_animations", {})

        # Check for expired items
        expired = [
            title
            for title, info in items.items()
            if info.get("expiry") and now > info["expiry"]
        ]
        for title in expired:
            del items[title]
            if title in progress_anims:
                del progress_anims[title]

        # Update progress animations
        items_to_remove = []
        for title, info in list(items.items()):
            if title not in progress_anims:
                continue

            anim = progress_anims[title]

            if anim.get("is_timer"):
                # Timer-based progress
                timer_elapsed = now - anim.get("timer_start", now)
                timer_duration = anim.get("timer_duration", 1)
                timer_progress = min(100, (timer_elapsed / timer_duration) * 100)
                anim["current"] = timer_progress
                info["progress_current"] = timer_progress

                if (
                    timer_elapsed >= timer_duration
                    and info.get("auto_close")
                    and not info.get("auto_close_triggered")
                ):
                    info["auto_close_triggered"] = True
                    info["auto_close_time"] = now + 2.0
            else:
                # Regular progress animation
                elapsed = now - anim.get("start_time", now)
                duration = self._progress_transition_duration

                if duration > 0 and elapsed < duration:
                    t = elapsed / duration
                    t = 1 - (1 - t) ** 3  # ease-out cubic
                    anim["current"] = (
                        anim.get("start_value", 0)
                        + (anim.get("target", 0) - anim.get("start_value", 0)) * t
                    )
                else:
                    anim["current"] = anim.get("target", 0)

                # Check for auto-close at 100%
                percentage = (anim["current"] / info.get("progress_maximum", 100)) * 100
                if (
                    percentage >= 100
                    and info.get("auto_close")
                    and not info.get("auto_close_triggered")
                ):
                    info["auto_close_triggered"] = True
                    info["auto_close_time"] = now + 2.0

            # Handle auto-close removal
            if info.get("auto_close_triggered") and info.get("auto_close_time"):
                if now >= info["auto_close_time"]:
                    items_to_remove.append(title)

        for title in items_to_remove:
            if title in items:
                del items[title]
            if title in progress_anims:
                del progress_anims[title]

        # Fade logic: away while its group's message window covers it
        self._update_window_fade(win, has_content=bool(items) and not win.get("collides", False))

    def _show_window_if_hidden(self, win: Dict):
        """Re-show a window that was hidden when it faded out (fade_state==0).

        Several code paths set fade_state to 1 directly (bypassing _update_window_fade)
        as a fast path when new content arrives - each of those must call this first
        (before overwriting fade_state) or the window stays invisible forever, since
        a hidden window stays hidden whatever opacity it is drawn with.
        """
        handle = win.get("handle")
        if handle is not None and win.get("fade_state") == 0:
            # Until its next picture arrives, the OS window still holds the
            # last one: it is shown with the new picture (_blit_window)
            win["show_on_present"] = True

    def _update_window_fade(self, win: Dict, has_content: bool):
        """Update fade animation for a window."""
        handle = win.get("handle")
        if handle is None:
            return

        # If manually hidden, force has_content to False so fade out completes
        if win.get("hidden", False) or self._is_suppressed(win):
            has_content = False

        fade_amount = int(1080 * self.dt)
        if fade_amount < 1:
            fade_amount = 1

        target = win.get("target_opacity", 216)
        old_fade_state = win["fade_state"]

        # Determine target state
        if has_content and win["fade_state"] in (0, 3):
            self._show_window_if_hidden(win)
            win["fade_state"] = 1  # start fade in
        elif not has_content and win["fade_state"] in (1, 2):
            win["fade_state"] = 3  # start fade out

        # Update layout manager visibility when fade state changes
        window_name = self._get_window_name(
            win.get("type", "message"), win.get("group", "default")
        )
        if old_fade_state != win["fade_state"]:
            # Window is visible for layout purposes when fading in (1), fully visible (2), OR fading out (3)
            # This prevents new windows from taking a slot while fade-out animation is in progress
            # Slot is only released when fully hidden (0)
            is_visible = win["fade_state"] in (1, 2, 3)
            self._layout_manager.set_window_visible(window_name, is_visible)

        if win["fade_state"] == 1:  # Fade in
            win["opacity"] = min(target, win.get("opacity", 0) + fade_amount)
            # Opacity is applied when the canvas is presented (_blit_window) - force a re-blit.
            win["canvas_dirty"] = True
            if win["opacity"] >= target:
                win["fade_state"] = 2

        elif win["fade_state"] == 3:  # Fade out
            win["opacity"] = max(0, win.get("opacity", 0) - fade_amount)
            win["canvas_dirty"] = True
            if win["opacity"] <= 0:
                win["fade_state"] = 0
                # Update layout visibility when fully hidden
                self._layout_manager.set_window_visible(window_name, False)
                if win["type"] == self.WINDOW_TYPE_MESSAGE:
                    win["current_message"] = None
                win.pop("show_on_present", None)
                # Explicitly hide the window rather than relying on a final
                # alpha=0 blit: the draw function clears the canvas as soon as
                # there's no content, so that final blit is never guaranteed to
                # run on this exact frame. Without this, the window would be
                # stuck showing its last visible frame forever.
                self._backend.hide_window(handle)

        elif win["fade_state"] == 2:  # Visible - maintain target opacity
            if win["opacity"] != target:
                if win["opacity"] < target:
                    win["opacity"] = min(target, win["opacity"] + fade_amount)
                else:
                    win["opacity"] = max(target, win["opacity"] - fade_amount)
                win["canvas_dirty"] = True

    # =========================================================================
    # DRAWING: every window is a stack of cached pieces (rendering/layers.py)
    # =========================================================================

    LOADER_FPS = 30
    """A frame in which only the loader moves comes this often, not at the HUD's frame rate."""

    def _window_renderer(self, props: Dict, text_color, accent, bg_rgba) -> MarkdownRenderer:
        """The window's fonts and markdown renderer. One renderer per font, kept,
        so what it caches (downloaded images, wrapped lines) outlives a frame."""
        font_size = int(props.get("font_size", 16))
        font_family = props.get("font_family", "Segoe UI")
        color_emojis = props.get("color_emojis", True)
        fonts = self._load_fonts_for_size_and_family(font_size, font_family)
        key = (font_size, font_family, color_emojis)
        renderer = self._md_renderers.get(key)
        if renderer is None:
            renderer = MarkdownRenderer(fonts, {"text": text_color, "accent": accent}, color_emojis)
            self._md_renderers[key] = renderer
        renderer.set_colors(text_color, accent, tuple(bg_rgba[:3]), bg_rgba[3])
        self.fonts = fonts
        self.small_fonts = self._load_fonts_for_size_and_family(max(9, round(font_size * 0.8)), font_family)
        self.md_renderer = renderer
        return renderer

    def _muted(self, color) -> Tuple[int, int, int]:
        """A colour pulled towards the panel: for names and labels next to the text."""
        return glass.mix(color, self.md_renderer.colors["bg"], 0.35)

    GLOW_FADE = 0.4
    """Seconds the loader's glow takes to come and to go."""

    def _glow_level(self, win: Dict, loading: bool) -> float:
        """How far the loader's glow has come in (1) or gone (0): it eases
        in when the loader starts and out when it stops, frame by frame."""
        level = win.get("glow_level", 0.0)
        step = max(0.0, self.dt) / self.GLOW_FADE
        level = min(1.0, level + step) if loading else max(0.0, level - step)
        win["glow_level"] = level
        return level

    @staticmethod
    def _glow_under(width: int, height: int, radius: int, color, strength: float) -> Image.Image:
        """The light rising into the window from its bottom edge, at `strength`."""
        image = glass.bleed(width, min(glass.GLOW_HEIGHT, height), radius, tuple(color[:3]))
        if strength < 1:
            image = image.copy()
            image.putalpha(glass.scaled(image.getchannel("A"), round(255 * strength)))
        return image

    @staticmethod
    def _draw_glow_line(canvas: Image.Image, width: int, height: int, radius: int, color,
                        strength: float, spread: float):
        """The glowing line on the window's bottom edge, `spread` of its length,
        from the middle; its halo reaches into the shadow's room below."""
        length = max(2, width - 2 * radius)
        shown = max(2, round(length * spread))
        line = glass.edge_line(length, tuple(color[:3])).resize((shown, 1 + 2 * glass.LINE_PAD), Image.Resampling.BILINEAR)
        line.putalpha(glass.scaled(line.getchannel("A"), round(255 * strength)))
        x = glass.SHADOW.left + radius + (length - shown) // 2
        glass.put(canvas, line, (x, glass.SHADOW.top + height - 1 - glass.LINE_PAD))

    def _style_key(self, props: Dict) -> tuple:
        """Everything of a window's look that a piece's pixels depend on."""
        return (
            int(props.get("font_size", 16)),
            props.get("font_family", "Segoe UI"),
            props.get("color_emojis", True),
            props.get("text_color", "#f0f0f0"),
            props.get("accent_color", "#00aaff"),
            props.get("bg_color", "#1e212b"),
        )

    def _clear_drawing(self, win: Dict):
        """No content: drop the picture and every piece. While the window
        fades out, it keeps the last picture to fade."""
        if win.get("fade_state") == 3 and win.get("canvas") is not None:
            return
        if win.get("last_render_state") is not None:
            win["last_render_state"] = None
            win["canvas"] = None
            win["canvas_dirty"] = False
        win.pop("pieces", None)
        win.pop("static_canvas", None)
        win.pop("static_signature", None)
        win.pop("glow_level", None)
        win.pop("glow_shown", None)

    def _draw_stack(
        self,
        name: str,
        win: Dict,
        newest_first,
        *,
        props: Dict,
        loading: bool = False,
        loader_color: Tuple = (0, 170, 255),
    ):
        """Lay out the pieces in view and put the window together when that
        changed. The loader is a glow on the window's bottom edge, breathing:
        while it shows, the window is put together again for every breath."""
        bg_rgba = self._parse_hex_color_with_alpha(props.get("bg_color", "#1e212b"))
        width = max(1, int(props.get("width", 400)))
        padding = int(props.get("content_padding", 16))
        radius = max(0, int(props.get("border_radius", 12)))
        fade_height = int(props.get("scroll_fade_height", 40))
        fixed_height = props.get("height")
        if fixed_height is not None:
            fixed_height = max(1, int(fixed_height))

        cache = win.get("pieces")
        if cache is None:
            cache = win["pieces"] = PieceCache()
        layout = lay_out(
            cache,
            newest_first,
            width,
            max(1, int(props.get("max_height", 600))),
            top=padding,
            bottom=padding - 4,
            min_height=60,
            fixed_height=fixed_height,
        )
        cache.end_frame()

        signature = (layout.signature, width, tuple(bg_rgba), radius, fade_height)
        presented = win.get("canvas") is not None and win.get("last_render_state") == signature
        level = self._glow_level(win, loading)
        if level > 0:
            # Breathing: at LOADER_FPS, but every frame while it fades in or out.
            # Slack: at 60 Hz, two frames are 1/30 s apart give or take a rounding
            if presented and level >= 1 and time.time() - win.get("loader_drawn", 0) < 1 / self.LOADER_FPS - 0.004:
                return
            now = time.time()
            win["loader_drawn"] = now
            brightness, spread = glass.breath(now)
            fit = max(0, min(radius, layout.height // 2, width // 2))
            canvas = compose(
                layout, width, tuple(bg_rgba), radius, fade_height,
                under=self._glow_under(width, layout.height, fit, loader_color, brightness * level),
            )
            self._draw_glow_line(canvas, width, layout.height, fit, loader_color, brightness * level, spread)
            win["glow_shown"] = True
        else:
            if win.get("static_signature") != signature or win.get("static_canvas") is None:
                win["static_canvas"] = compose(layout, width, tuple(bg_rgba), radius, fade_height)
                win["static_signature"] = signature
            elif presented and not win.get("glow_shown"):
                return
            win["glow_shown"] = False
            # A copy: whoever gets the picture may draw on it (the preview does)
            canvas = win["static_canvas"].copy()
        win["last_render_state"] = signature
        self._present(name, win, canvas, layout.height)

    def _present(self, name: str, win: Dict, canvas: Image.Image, body_height: int):
        """Hand the new picture to the window and fit the window to it."""
        win["canvas"] = canvas
        win["body_height"] = body_height
        win["canvas_dirty"] = True
        self._layout_manager.update_window_height(name, body_height)
        pos = self._layout_manager.get_position(name)
        if pos is None:
            props = win.get("props", {})
            pos = (int(props.get("x", 20)), int(props.get("y", 20)))
        self._place(win, *pos)

    def _markdown_pieces(
        self, text: str, blocks: list, x: int, width: int, max_chars, style: tuple, alpha: float = 1.0
    ) -> list:
        """One piece per markdown block. While the typewriter runs, only the
        block it is typing changes; the ones above it are done and kept."""
        renderer = self.md_renderer
        pieces = []
        for block in blocks:
            start = block.get("start", 0)
            end = block.get("end", start)
            if max_chars is not None and start >= max_chars:
                break
            shown = None if max_chars is None or max_chars >= end else int(max_chars)
            # Its own text only: text appended later leaves the blocks above alone
            source = text[start:end]
            # A web image arrives later; its block is drawn again then
            images = renderer.image_version if "![" in source else 0
            key = ("md", start, source, shown, x, width, style, images)

            def draw(d, image, top, block=block, shown=shown):
                end_y = renderer.render(d, image, text, x, -top, width, shown, pre_parsed_blocks=[block])
                return end_y + top

            pieces.append(Piece(key, draw, alpha=alpha, slot=("md", start, x, width)))
        return pieces

    def _avatar(self, icon: Optional[str], name: str, size: int, color: Tuple, initial: bool):
        """The picture as a circle. Without one, a disc in a dark shade of
        `color` with the name's initial when `initial`, else None."""
        if icon and os.path.isfile(icon):
            key = (icon, size)
            avatar = self.image_cache.get(key)
            if avatar is None:
                try:
                    with Image.open(icon) as source:
                        avatar = round_avatar(source, size)
                    self.image_cache[key] = avatar
                except Exception:
                    avatar = None
            if avatar is not None:
                return avatar
        if not initial:
            return None
        letter = next((c for c in name if c.isalnum()), "?").upper()
        colors = self.md_renderer.colors
        text_color, bg = tuple(colors["text"][:3]), tuple(colors["bg"][:3])
        key = ("initial", letter, size, tuple(color), text_color, bg)
        avatar = self.image_cache.get(key)
        if avatar is None:
            avatar = glass.initial_disc(size, tuple(color[:3]), bg).copy()
            font = self.fonts.get("bold", self.fonts.get("normal"))
            if font:
                try:
                    ImageDraw.Draw(avatar).text(
                        (size / 2, size / 2), letter, fill=glass.lighter(text_color, 0.2) + (255,),
                        font=font, anchor="mm",
                    )
                except Exception:
                    pass
            self.image_cache[key] = avatar
        return avatar

    AVATAR_HALO = 4
    """Room around a round picture for its ring and glow."""

    def _sender_piece(
        self, name: str, icon: Optional[str], x: int, color: Tuple, size: int,
        style: tuple, initial: bool = False, alpha: float = 1.0, rule: bool = False,
    ) -> Piece:
        """A sender's round picture, ringed in their colour, with the name
        beside it. With `rule`, a fine line in their colour fades out below."""
        key = ("sender", name, icon, x, tuple(color), size, initial, style, rule)

        def draw(d, image, _top):
            halo = self.AVATAR_HALO
            avatar = self._avatar(icon, name, size, color, initial)
            text_x, height = x, 0
            if avatar is not None:
                image.alpha_composite(glass.avatar_halo(size, tuple(color[:3]), halo), (x - halo, 0))
                image.alpha_composite(avatar, (x, halo))
                text_x, height = x + size + 10, size + 2 * halo
            font = self.fonts.get("bold", self.fonts.get("normal", self.fonts.get("regular")))
            shown = self._fit_text(name, font, image.width - text_x - x) if font else ""
            if shown and font:
                try:
                    _, top, _, bottom = font.getbbox(shown)
                except Exception:
                    top, bottom = 0, 20
                text_h = bottom - top
                y = (height - text_h) // 2 - top if avatar is not None else 0
                self._render_text_with_emoji(
                    d, shown, text_x, y, tuple(color) + (255,), font, emoji_y_offset=3
                )
                if avatar is None:
                    height = text_h + 8
            if rule:
                line = glass.hairline(image.width - 2 * x, tuple(color[:3]) + (120,), peak=0.0, fade_in=False)
                glass.put(image, line, (x, height + 8))
                return height + 19
            return height + 2

        return Piece(key, draw, alpha=alpha)

    def _fit_text(self, text: str, font, max_width: int) -> str:
        """The text, cut with an ellipsis where it would run past `max_width`."""
        if not text or max_width <= 0:
            return ""
        if self._get_text_size(text, font)[0] <= max_width:
            return text
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if self._get_text_size(text[:mid].rstrip() + "…", font)[0] <= max_width:
                low = mid
            else:
                high = mid - 1
        return text[:low].rstrip() + "…" if low else ""

    def _tool_chips_piece(
        self, tools: list, x: int, right: int, style: tuple, text_color, accent, bg, alpha: float = 1.0
    ) -> Piece:
        """The tools a reply used: one chip per text it shows (the tool's name,
        or its skill's or server's), with the number of calls when more than one."""
        chips: dict[str, list] = {}  # label -> [icon, calls]
        for t in tools:
            label = str(t.get("source") or "System")
            chip = chips.setdefault(label, [None, 0])
            chip[0] = chip[0] or t.get("icon")
            chip[1] += 1
        key = ("tools", tuple((label, icon, calls) for label, (icon, calls) in chips.items()), x, right, style)
        renderer = self.md_renderer

        def draw(d, image, _top):
            font = self.small_fonts.get("normal") or self.fonts.get("normal", self.fonts.get("regular"))
            bold = self.small_fonts.get("bold") or font
            size = int(self.fonts.get("_font_size", 16))
            th = max(20, round(size * 1.55))
            mark = max(5, round(th * 0.24))
            pad = round(th * 0.4)
            y, tx = 8, x
            # Text laid over the chips at the end: drawn onto their see-through
            # tint, its anti-aliased edges would mix with it and show a rim
            labels = Image.new("RGBA", image.size, (0, 0, 0, 0))
            ld = ImageDraw.Draw(labels)
            for src, (icon, cnt) in chips.items():
                chip_icon = self._chip_icon(icon, th - 10)
                lead = chip_icon.width if chip_icon else mark
                count = str(cnt) if cnt > 1 else ""
                badge_w = max(th - 8, self._get_text_size(count, bold)[0] + 10) if count else 0
                fixed = pad + lead + 6 + (6 + badge_w + 4 if count else pad)
                # A chip never wider than the window
                src = self._fit_text(src, font, right - x - fixed) or "…"
                chip_w = fixed + self._get_text_size(src, font)[0]

                if tx + chip_w > right and tx > x:
                    tx = x
                    y += th + 6

                glass.paint(image, glass.rounded_mask(chip_w, th, th / 2), renderer.accent_tint(0.16), (tx, y))
                glass.paint(image, glass.ring_mask(chip_w, th, th / 2), renderer.accent_tint(0.45), (tx, y))
                if chip_icon:
                    image.alpha_composite(chip_icon, (tx + pad, y + (th - chip_icon.height) // 2))
                else:
                    sprite = glass.disc(mark, tuple(accent[:3]))
                    glass.put(image, sprite, (tx + pad + (mark - sprite.width) // 2, y + (th - sprite.height) // 2))
                label_x = tx + pad + lead + 6
                ld.text((label_x, y + th / 2), src, fill=tuple(text_color[:3]) + (255,), font=font, anchor="lm")

                # The number of calls, when more than one
                if count:
                    bx, bh = tx + chip_w - 4 - badge_w, th - 8
                    glass.paint(image, glass.rounded_mask(badge_w, bh, bh / 2), tuple(accent[:3]) + (255,), (bx, y + 4))
                    ink = (255, 255, 255) if glass.is_dark(accent) else (20, 22, 28)
                    ld.text((bx + badge_w / 2, y + th / 2), count, fill=ink + (255,), font=bold, anchor="mm")

                tx += chip_w + 8
            image.alpha_composite(labels)
            return y + th + 6

        return Piece(key, draw, alpha=alpha)

    def _chip_icon(self, icon: Optional[str], size: int) -> Optional[Image.Image]:
        """A tool's icon at chip size, or None without a readable one."""
        if not icon or not os.path.exists(str(icon)):
            return None
        key = ("chip", icon, size)
        image = self.image_cache.get(key)
        if image is None:
            try:
                with Image.open(icon) as source:
                    image = source.convert("RGBA")
                    image.thumbnail((size, size), Image.Resampling.LANCZOS)
            except Exception:
                return None
            self.image_cache[key] = image
        return image

    def _draw_message_window(self, name: str, win: Dict):
        """Draw content for a message window."""
        current_message = win.get("current_message")
        is_loading = win.get("is_loading", False)
        if not current_message and not is_loading:
            self._clear_drawing(win)
            return

        props = win.get("props", {})
        bg_rgba = self._parse_hex_color_with_alpha(props.get("bg_color", "#1e212b"))
        text_color = self._hex_to_rgb(props.get("text_color", "#f0f0f0"))
        accent = self._hex_to_rgb(props.get("accent_color", "#00aaff"))
        width = int(props.get("width", 400))
        padding = int(props.get("content_padding", 16))
        renderer = self._window_renderer(props, text_color, accent, bg_rgba)
        style = self._style_key(props)

        pieces = []
        if current_message:
            title = self._strip_emotions(current_message.get("title", "") or "")
            icon = current_message.get("title_icon")
            if title or icon:
                size = int(int(props.get("font_size", 16)) * 1.75)
                pieces.append(self._sender_piece(title, icon, padding, accent, size, style, rule=True))

            message = current_message.get("message", "")
            if message:
                message = self._strip_emotions(message)
                max_chars = (
                    int(win.get("typewriter_char_count", 0))
                    if win.get("typewriter_active", False)
                    else None
                )
                cached = win.get("current_blocks")
                if cached is None or cached.get("msg") != message:
                    cached = win["current_blocks"] = {
                        "msg": message,
                        "blocks": renderer.parse_blocks(message),
                    }
                pieces += self._markdown_pieces(
                    message, cached["blocks"], padding, width - padding * 2, max_chars, style
                )

            tools = current_message.get("tools") or []
            if tools:
                pieces.append(self._tool_chips_piece(
                    tools, padding, width - padding, style, text_color, accent, bg_rgba[:3]
                ))

        self._draw_stack(
            name, win, reversed(pieces), props=props, loading=is_loading,
            loader_color=win.get("loading_color") or accent,
        )

    @staticmethod
    def _format_remaining(seconds: float) -> str:
        """Time left as a clock: 0:42, 12:05, 1:02:03, 2d 3:04:05."""
        r = int(seconds + 0.999)
        d, r = divmod(r, 86400)
        h, r = divmod(r, 3600)
        m, s = divmod(r, 60)
        clock = f"{h}:{m:02d}:{s:02d}" if h or d else f"{m}:{s:02d}"
        return f"{d}d {clock}" if d else clock

    ITEM_SPACING = 14
    """Space above and below the line between two info panel items."""

    def _info_item_piece(
        self, title: str, info: Dict, anim: Optional[Dict], now: float, props: Dict,
        style: tuple, text_color, accent, bg_rgba, separator: bool,
    ) -> Piece:
        """One info panel item: an icon for its kind, the title, on the right
        the time left or how far it got, a slim bar for progress, the details.
        Its key holds what is shown, not the time: a running timer draws again
        once a second, a moving bar once a pixel."""
        width = int(props.get("width", 300))
        padding = int(props.get("content_padding", 16))
        font_size = int(props.get("font_size", 16))
        renderer = self.md_renderer
        bar_width = width - padding * 2

        timer_text = None
        if info.get("is_progress") and info.get("is_timer"):
            elapsed = now - info.get("timer_start", now)
            timer_text = self._format_remaining(max(0.0, info.get("timer_duration", 0) - elapsed))
        elif info.get("expiry"):
            timer_text = self._format_remaining(max(0.0, info["expiry"] - now))

        filled = None
        value = timer_text
        if info.get("is_progress"):
            progress_max = float(info.get("progress_maximum", 100))
            current = anim.get("current", 0) if anim else float(info.get("progress_current", 0))
            if progress_max <= 0:
                progress_max = 100
            percentage = min(100, max(0, (current / progress_max) * 100))
            filled = round(bar_width * percentage / 100)
            if not info.get("is_timer"):
                value = f"{percentage:.0f}%"
        kind = "timer" if info.get("is_timer") else "progress" if info.get("is_progress") else "note"

        title_text = info.get("title", title)
        desc = self._strip_emotions(info.get("description", "") or "")
        progress_color = info.get("progress_color")
        images = renderer.image_version if "![" in desc else 0
        key = (
            "info", title_text, desc, value, filled, progress_color,
            width, padding, style, images, separator,
        )

        def draw(d, image, _top):
            y = 0
            if separator:
                line = glass.hairline(bar_width, glass.edge_color(bg_rgba) + (round(0.1 * max(bg_rgba[3], 160)),))
                glass.put(image, line, (padding, 0))
                y = self.ITEM_SPACING + 1
            font_bold = self.fonts.get("bold", self.fonts.get("normal", self.fonts.get("regular")))
            font_normal = self.fonts.get("normal", self.fonts.get("regular"))
            color = self._hex_to_rgb(progress_color) if progress_color else tuple(accent[:3])
            try:
                _, line_top, _, line_bottom = font_bold.getbbox("Hg")
            except Exception:
                line_top, line_bottom = 0, font_size
            icon_px = max(12, font_size)
            # A blank title (a skill's own panel, like the mic's icon) gets
            # no icon and no title row; a time or percentage keeps its row
            titled = bool(title_text.strip())
            if titled or value:
                row_h = max(icon_px if titled else 0, line_bottom - line_top)
                middle = y + row_h / 2
                if titled:
                    image.alpha_composite(glass.icon(kind, icon_px, color), (padding, round(middle - icon_px / 2)))

                right = width - padding
                if value and font_bold:
                    timed_note = kind == "note"
                    value_font = font_normal if timed_note else font_bold
                    ink = self._muted(text_color) if timed_note else color
                    d.text((right, middle), value, fill=tuple(ink) + (255,), font=value_font, anchor="rm")
                    right -= self._get_text_size(value, value_font)[0] + 10

                title_x = padding + icon_px + 8
                if titled and font_bold:
                    shown = self._fit_text(title_text, font_bold, right - title_x)
                    self._render_text_with_emoji(
                        d, shown, title_x, round(middle - (line_bottom - line_top) / 2) - line_top,
                        tuple(text_color[:3]) + (255,), font_bold, emoji_y_offset=3,
                    )
                y += row_h

            if filled is not None:
                bar_h = max(4, round(font_size * 0.375))
                track = glass.edge_color(bg_rgba) + (round(0.1 * max(bg_rgba[3], 160)),)
                glass.put(image, glass.progress_bar(bar_width, bar_h, filled, color, track), (padding - 4, y + 6))
                y += 10 + bar_h + 2

            if desc:
                top = y + 8 if y else 0
                y = renderer.render(d, image, desc, padding, top, bar_width)
                # A last table or card leaves room for a block below it: end 4 px under its
                # ink, as text does (never lower, so text keeps its height)
                ink = image.crop((0, top, width, y)).getchannel("A").getbbox() if y <= image.height else None
                if ink:
                    y = min(y, top + ink[3] + 4)
            return y + 2

        return Piece(key, draw, gap=self.ITEM_SPACING)

    def _draw_persistent_window(self, name: str, win: Dict):
        """Draw content for a persistent window."""
        items = win.get("items", {})
        if not items:
            self._clear_drawing(win)
            return

        props = win.get("props", {})
        bg_rgba = self._parse_hex_color_with_alpha(props.get("bg_color", "#1e212b"))
        text_color = self._hex_to_rgb(props.get("text_color", "#f0f0f0"))
        accent = self._hex_to_rgb(props.get("accent_color", "#00aaff"))
        self._window_renderer(props, text_color, accent, bg_rgba)
        style = self._style_key(props)
        now = time.time()
        anims = win.get("progress_animations", {})

        shown = [
            (title, info)
            for title, info in sorted(items.items(), key=lambda x: x[1].get("added_at", 0))
            if not (info.get("expiry") and now > info["expiry"])
        ]
        if not shown:
            self._clear_drawing(win)
            return

        oldest = shown[0][0]

        def newest_first():
            for title, info in reversed(shown):
                yield self._info_item_piece(
                    title, info, anims.get(title), now, props, style, text_color, accent, bg_rgba,
                    separator=title != oldest,
                )

        self._draw_stack(name, win, newest_first(), props=props)

    def _update_chat_window(self, name: str, win: Dict):
        """Update chat window state (typewriter, fade logic and auto-hide)."""
        now = time.time()
        props = win.get("props", {})
        auto_hide = props.get("auto_hide", False)
        auto_hide_delay = props.get("auto_hide_delay", 10.0)

        typing = win.get("typing")
        if typing:
            message = next(
                (m for m in reversed(win.get("messages", [])) if m.get("id") == typing["id"]),
                None,
            )
            if message is None:
                win["typing"] = None
            else:
                typing["chars"] += (now - typing["last"]) * 200
                typing["last"] = now
                if typing["chars"] >= len(message.get("text", "")):
                    win["typing"] = None

        # Check auto-hide
        if auto_hide and win.get("messages") and win["fade_state"] == 2:
            if now - win.get("last_message_time", 0) > auto_hide_delay:
                win["visible"] = False

        has_content = win.get("visible", True) and bool(
            win.get("messages") or win.get("is_loading")
        )
        self._update_window_fade(win, has_content=has_content)

    def _own_message_piece(
        self, message: Dict, x: int, width: int, color: Tuple, radius: int,
        style: tuple, alpha: float = 1.0,
    ) -> Piece:
        """The user's own message: a bubble in the accent's tint on the right,
        its tail corner at the bottom right, the name above it."""
        sender = message.get("sender", "")
        text = message.get("text", "")
        renderer = self.md_renderer
        images = renderer.image_version if "![" in text else 0
        key = ("own", sender, text, x, width, tuple(color), radius, style, images)

        def draw(d, image, _top):
            right = x + width
            y = 0
            # The name as a Wingman's: bold, full size, in the sender's colour
            font = self.fonts.get("bold", self.fonts.get("normal", self.fonts.get("regular")))
            name = self._fit_text(sender, font, width) if font else ""
            if name:
                name_w, _ = self._get_text_size(name, font)
                try:
                    _, top, _, bottom = font.getbbox("Hg")
                except Exception:
                    top, bottom = 0, 20
                self._render_text_with_emoji(
                    d, name, right - name_w - 2, -top, tuple(color) + (255,), font, emoji_y_offset=3
                )
                y = bottom - top + 8

            # Drawn at the widest a bubble may be, then cut to what the text
            # covers: bold, emoji, links and line breaks all measure right
            pad_x, pad_y = 13, 8
            max_inner = max(40, int(width * 0.8) - 2 * pad_x)
            inner = render_piece(
                max_inner, lambda dd, im, top: renderer.render(dd, im, text, 0, -top, max_inner) + top
            )
            box = inner.getbbox()
            if box is None:
                return y
            # From cap height to baseline and descent, as for "Hg": every
            # one-line bubble is as high as the next, whatever its letters
            ref_top, ref_gap = self._bubble_lines(renderer)
            top = min(ref_top, box[1])
            bottom = max(inner.height - ref_gap, box[3], top + 1)
            inner = inner.crop((0, top, box[2], bottom))
            bubble_w = inner.width + 2 * pad_x
            bubble_h = inner.height + 2 * pad_y
            bx = right - bubble_w
            r = max(6, min(radius + 4, 16))
            corners = (r, r, min(4, r), r)
            fill = glass.vertical_gradient(bubble_w, bubble_h, renderer.accent_tint(0.34), renderer.accent_tint(0.2))
            fill.putalpha(ImageChops.multiply(fill.getchannel("A"), glass.rounded_mask(bubble_w, bubble_h, r, corners)))
            image.alpha_composite(fill, (bx, y))
            glass.paint(image, glass.ring_mask(bubble_w, bubble_h, r, 1, corners), renderer.accent_tint(0.5), (bx, y))
            image.alpha_composite(inner, (bx + pad_x, y + pad_y))
            return y + bubble_h + 1

        return Piece(key, draw, alpha=alpha)

    def _bubble_lines(self, renderer: MarkdownRenderer) -> tuple:
        """Where a line's letters start below its top, and how much of the
        rendered height lies below them: measured once per renderer on "Hg"."""
        lines = self._bubble_refs.get(id(renderer))
        if lines is None:
            ref = render_piece(200, lambda d, im, top: renderer.render(d, im, "Hg", 0, -top, 200) + top)
            box = ref.getbbox() or (0, 0, 0, ref.height)
            lines = self._bubble_refs[id(renderer)] = (box[1], ref.height - box[3])
        return lines

    def _chat_message_pieces(
        self, message: Dict, props: Dict, style: tuple, colors: tuple,
        max_chars, alpha: float, gap: int, sender_color=None, continues: bool = False,
    ) -> list:
        """A message's pieces, top to bottom. One that `continues` the same
        Wingman's entry above it has no picture and name of its own."""
        text_color, accent, bg = colors
        width = int(props.get("width", 400))
        padding = int(props.get("content_padding", 12))
        content_w = width - padding * 2
        sender = self._strip_emotions(message.get("sender", "") or "")
        color = message.get("color") or sender_color
        if isinstance(color, str):
            color = self._hex_to_rgb(color)
        color = tuple(color) if color else accent

        if message.get("own"):
            if not (message.get("text") or "").strip():
                return []
            radius = int(props.get("border_radius", 12))
            piece = self._own_message_piece(
                {**message, "sender": "" if continues else sender},
                padding, content_w, color, radius, style, alpha,
            )
            piece.gap = gap
            return [piece]

        size = int(int(props.get("font_size", 14)) * 1.75)
        indent = size + 10
        pieces = []
        if not continues:
            pieces.append(self._sender_piece(
                sender, message.get("icon"), padding, color, size, style, initial=True, alpha=alpha
            ))
        text = message.get("text", "")
        if text:
            blocks = message.get("_blocks")
            if blocks is None or blocks[0] != text:
                blocks = message["_blocks"] = (text, self.md_renderer.parse_blocks(text))
            pieces += self._markdown_pieces(
                text, blocks[1], padding + indent, content_w - indent, max_chars, style, alpha
            )
        if message.get("tools"):
            pieces.append(self._tool_chips_piece(
                message["tools"], padding + indent, width - padding, style,
                text_color, accent, bg, alpha,
            ))
        if pieces:
            pieces[-1].gap = gap
        return pieces

    def _draw_chat_window(self, name: str, win: Dict):
        """Draw content for a chat window."""
        messages = win.get("messages", [])
        is_loading = win.get("is_loading", False)
        if not messages and not is_loading:
            self._clear_drawing(win)
            return

        props = win.get("props", {})
        bg_rgba = self._parse_hex_color_with_alpha(props.get("bg_color", "#1e212b"))
        text_color = self._hex_to_rgb(props.get("text_color", "#f0f0f0"))
        accent = self._hex_to_rgb(props.get("accent_color", "#00aaff"))
        self._window_renderer(props, text_color, accent, bg_rgba)
        style = self._style_key(props)
        colors = (text_color, accent, bg_rgba[:3])
        spacing = int(props.get("message_spacing", 14))
        fade_old = props.get("fade_old_messages", True)
        sender_colors = props.get("sender_colors", {})
        typing = win.get("typing")
        count = len(messages)

        def newest_first():
            for i in range(count - 1, -1, -1):
                message = messages[i]
                from_end = count - i
                alpha = max(0.3, 1.0 - from_end * 0.05) if fade_old and from_end > 3 else 1.0
                max_chars = None
                if typing and typing["id"] == message.get("id") and not message.get("own"):
                    max_chars = int(typing["chars"])
                # A sender's next entry goes on under its name, shown once
                previous = messages[i - 1] if i > 0 else None
                continues = bool(
                    previous and bool(previous.get("own")) == bool(message.get("own"))
                    and previous.get("sender") == message.get("sender")
                )
                yield from reversed(self._chat_message_pieces(
                    message, props, style, colors, max_chars, alpha, spacing,
                    sender_colors.get(message.get("sender")), continues,
                ))

        self._draw_stack(
            name, win, newest_first(), props=props, loading=is_loading,
            loader_color=win.get("loading_color") or accent,
        )

    def _blit_window(self, name: str, win: Dict):
        """Hand a window's canvas to the backend, faded to the window's opacity."""
        if win.get("opacity", 0) <= 0:
            return
        if not win.get("canvas_dirty", False):
            return

        canvas = win.get("canvas")
        handle = win.get("handle")
        if canvas is None or handle is None:
            return

        try:
            self._backend.present(handle, canvas, max(0, min(255, int(win.get("opacity", 255)))))
        except Exception as e:
            # Still dirty: the next frame tries again; reported once per failure
            if not win.get("present_failed"):
                self._report_exception("blit_window", e)
            win["present_failed"] = True
            return
        win["present_failed"] = False
        win["canvas_dirty"] = False
        if win.pop("show_on_present", False):
            self._backend.show_window(handle)

    def _hex_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        """Parse hex color string to RGB tuple. Supports #RGB, #RRGGBB, #RRGGBBAA formats."""
        result = self._parse_hex_color_with_alpha(hex_color)
        return result[:3]  # Return only RGB portion

    def _parse_hex_color_with_alpha(self, color_str: str) -> Tuple[int, int, int, int]:
        """Parse hex color string to RGBA tuple. Alpha defaults to 255 if not specified.

        Supports formats: #RGB, #RRGGBB, #RRGGBBAA
        Returns: (red, green, blue, alpha) tuple with values 0-255
        """
        fallback_color = (0, 170, 255, 255)
        if not color_str or not isinstance(color_str, str):
            return fallback_color

        clean = color_str.strip().lstrip("#")
        char_count = len(clean)

        # Expand shorthand #RGB to #RRGGBB using same pattern as _hex_to_rgb
        if char_count == 3:
            clean = "".join([ch * 2 for ch in clean])
            char_count = 6

        # Validate length - must be 6 (RRGGBB) or 8 (RRGGBBAA)
        if char_count not in (6, 8):
            return fallback_color

        # Parse each component
        components = []
        for offset in range(0, char_count, 2):
            segment = clean[offset : offset + 2]
            try:
                val = int(segment, 16)
                components.append(val)
            except (ValueError, TypeError):
                return fallback_color

        # Ensure we always return exactly 4 components (RGBA)
        while len(components) < 4:
            components.append(255)  # Default alpha to full opacity

        # Return exactly 4 values as a tuple
        return (components[0], components[1], components[2], components[3])

    def _strip_emotions(self, text: str) -> str:
        """The text as it is read: without what only the voice needs (pauses,
        <verbatim>, [sigh], however the text arrived) and without emotion tags
        like [happy], [sad], [breathe]; markdown links and checkboxes stay."""
        text = display_text(text or "")
        # First, temporarily protect markdown links
        link_pattern = r"\[([^]]+)]\(([^)]+)\)"
        links = []

        def save_link(m):
            links.append(m.group(0))
            return f"__LINK_{len(links)-1}__"

        text = re.sub(link_pattern, save_link, text)

        # Temporarily protect checkboxes [ ], [x], [X]
        checkbox_pattern = r"\[[ xX]\]"
        checkboxes = []

        def save_checkbox(m):
            checkboxes.append(m.group(0))
            return f"__CHECKBOX_{len(checkboxes)-1}__"

        text = re.sub(checkbox_pattern, save_checkbox, text)

        # Remove emotion tags (single words in brackets, must be 2+ chars to avoid single letters)
        # This matches [word] where word is 2 or more letters/underscores
        text = re.sub(r"\[[a-zA-Z_]{2,}]\s*", "", text)

        # Restore checkboxes
        for i, checkbox in enumerate(checkboxes):
            text = text.replace(f"__CHECKBOX_{i}__", checkbox)

        # Restore links
        for i, link in enumerate(links):
            text = text.replace(f"__LINK_{i}__", link)

        # Clean up whitespace
        text = text.strip()
        # Remove leading newlines
        text = re.sub(r"^\n+", "", text)
        # Collapse multiple consecutive newlines into one (paragraph breaks become single empty lines)
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text

    def _load_fonts_for_size_and_family(self, size: int, family: str) -> Dict:
        """Load fonts for a specific size and family combination.

        Uses cache to avoid reloading the same font set multiple times.

        Args:
            size: Font size in pixels
            family: Font family name

        Returns:
            Dictionary of font objects for the given size and family
        """
        cache_key = (family.lower(), size)

        # Return cached fonts if available
        if cache_key in self._font_cache:
            return self._font_cache[cache_key]

        # The OS's font files for this family (hud_server/platform)
        font_set = self._backend.font_set(family)

        pil_size = size
        pil_code_size = max(1, size - 1)  # Code font slightly smaller, but at least 1

        # Load emoji fonts
        emoji_font = None
        emoji_font_paths = list(font_set.emoji) if font_set else []
        for emoji_path in emoji_font_paths:
            try:
                emoji_font = ImageFont.truetype(emoji_path, pil_size)
                break
            except:
                pass

        emoji_fonts = {"emoji": emoji_font}
        emoji_font_path = None
        for path in emoji_font_paths:
            try:
                ImageFont.truetype(path, pil_size)
                emoji_font_path = path
                break
            except:
                pass

        if emoji_font_path:
            try:
                emoji_fonts["emoji_h1"] = ImageFont.truetype(
                    emoji_font_path, pil_size + 10
                )
                emoji_fonts["emoji_h2"] = ImageFont.truetype(
                    emoji_font_path, pil_size + 6
                )
                emoji_fonts["emoji_h3"] = ImageFont.truetype(
                    emoji_font_path, pil_size + 3
                )
                emoji_fonts["emoji_h4"] = ImageFont.truetype(
                    emoji_font_path, pil_size + 1
                )
                emoji_fonts["emoji_h5"] = ImageFont.truetype(emoji_font_path, pil_size)
                emoji_fonts["emoji_h6"] = ImageFont.truetype(
                    emoji_font_path, pil_size - 1
                )
            except:
                pass

        try:
            if font_set is None:
                raise OSError(f"No font files for {family}")
            fonts_dict = {
                "normal": ImageFont.truetype(
                    font_set.normal, pil_size
                ),
                "bold": ImageFont.truetype(font_set.bold, pil_size),
                "italic": ImageFont.truetype(
                    font_set.italic, pil_size
                ),
                "bold_italic": ImageFont.truetype(
                    font_set.bold_italic, pil_size
                ),
                "code": ImageFont.truetype(font_set.code, pil_code_size),
                "h1": ImageFont.truetype(font_set.bold, pil_size + 10),
                "h2": ImageFont.truetype(font_set.bold, pil_size + 6),
                "h3": ImageFont.truetype(font_set.bold, pil_size + 3),
                "h4": ImageFont.truetype(font_set.bold, pil_size + 1),
                "h5": ImageFont.truetype(font_set.bold, pil_size),
                "h6": ImageFont.truetype(
                    font_set.bold_italic, pil_size - 1
                ),
                "header": ImageFont.truetype(
                    font_set.bold, pil_size + 4
                ),
                "emoji": (
                    emoji_font
                    if emoji_font
                    else ImageFont.truetype(font_set.normal, pil_size)
                ),
                "emoji_h1": emoji_fonts.get("emoji_h1", emoji_font),
                "emoji_h2": emoji_fonts.get("emoji_h2", emoji_font),
                "emoji_h3": emoji_fonts.get("emoji_h3", emoji_font),
                "emoji_h4": emoji_fonts.get("emoji_h4", emoji_font),
                "emoji_h5": emoji_fonts.get("emoji_h5", emoji_font),
                "emoji_h6": emoji_fonts.get("emoji_h6", emoji_font),
                "_font_size": size,
                "_font_family": family,
            }
        except Exception:
            # Fallback: try loading by family name directly
            try:
                fonts_dict = {
                    "normal": ImageFont.truetype(family, pil_size),
                    "bold": ImageFont.truetype(family, pil_size),
                    "italic": ImageFont.truetype(family, pil_size),
                    "bold_italic": ImageFont.truetype(family, pil_size),
                    "code": ImageFont.truetype("consola.ttf", pil_code_size),
                    "h1": ImageFont.truetype(family, pil_size + 10),
                    "h2": ImageFont.truetype(family, pil_size + 6),
                    "h3": ImageFont.truetype(family, pil_size + 3),
                    "h4": ImageFont.truetype(family, pil_size + 1),
                    "h5": ImageFont.truetype(family, pil_size),
                    "h6": ImageFont.truetype(family, pil_size - 1),
                    "header": ImageFont.truetype(family, pil_size + 4),
                    "emoji": (
                        emoji_font
                        if emoji_font
                        else ImageFont.truetype(family, pil_size)
                    ),
                    "_font_size": size,
                    "_font_family": family,
                }
            except:
                # Final fallback to default
                default = ImageFont.load_default()
                fonts_dict = {
                    k: default
                    for k in [
                        "normal",
                        "bold",
                        "italic",
                        "bold_italic",
                        "code",
                        "header",
                        "emoji",
                    ]
                }
                fonts_dict.update(
                    {
                        "h1": default,
                        "h2": default,
                        "h3": default,
                        "h4": default,
                        "h5": default,
                        "h6": default,
                    }
                )
                fonts_dict["_font_size"] = size
                fonts_dict["_font_family"] = family

        # Cache the fonts
        self._font_cache[cache_key] = fonts_dict
        return fonts_dict

    def _init_fonts(self):
        """Load the default fonts, so the first window does not wait for them."""
        self.fonts = self._load_fonts_for_size_and_family(
            int(self._default_props.get("font_size", 16)),
            self._default_props.get("font_family", "Segoe UI"),
        )

    def _get_text_size(self, text: str, font) -> Tuple[int, int]:
        try:
            bbox = font.getbbox(text)
            return int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])
        except:
            return len(text) * 8, 16

    def _render_text_with_emoji(
        self,
        draw,
        text: str,
        x: int,
        y: int,
        color: Tuple,
        font,
        emoji_y_offset: int = 5,
    ):
        """Render text with inline emoji support for titles and labels.

        Automatically adds a space after emojis if not already present.

        Args:
            draw: ImageDraw object
            text: Text to render (may contain emojis)
            x: X position
            y: Y position
            color: Text color (RGBA tuple)
            font: Font to use for text
            emoji_y_offset: Vertical offset for emojis (default 5 for bold titles)
        """
        if not text:
            return

        current_x = x
        i = 0
        emoji_font = self.fonts.get("emoji", font)
        space_w, _ = self._get_text_size(" ", font)

        while i < len(text):
            # Check for emoji at current position
            emoji_len = (
                self.md_renderer._get_emoji_length(text, i) if self.md_renderer else 0
            )
            if emoji_len > 0:
                # Render emoji with emoji font and color support
                emoji_text = text[i : i + emoji_len]
                if self.md_renderer and self.md_renderer.color_emojis:
                    draw.text(
                        (current_x, y + emoji_y_offset),
                        emoji_text,
                        fill=color,
                        font=emoji_font,
                        embedded_color=True,
                    )
                else:
                    draw.text(
                        (current_x, y + emoji_y_offset),
                        emoji_text,
                        fill=color,
                        font=emoji_font,
                    )
                emoji_w, _ = self._get_text_size(emoji_text, emoji_font)
                # Reduce emoji width - more aggressive for variation selector emojis
                has_variation_selector = "\ufe0f" in emoji_text
                if has_variation_selector:
                    current_x += int(emoji_w * 0.55)
                else:
                    current_x += int(emoji_w * 0.85)
                i += emoji_len

                # Add automatic space after emoji if next character is not a space or end of text
                if i < len(text) and text[i] != " ":
                    current_x += space_w
            else:
                # Find the next emoji or end of text
                text_start = i
                while i < len(text):
                    if (
                        self.md_renderer
                        and self.md_renderer._get_emoji_length(text, i) > 0
                    ):
                        break
                    i += 1
                # Render text segment
                text_segment = text[text_start:i]
                if text_segment:
                    draw.text((current_x, y), text_segment, fill=color, font=font)
                    text_w, _ = self._get_text_size(text_segment, font)
                    current_x += text_w

    def _safe_report(self, payload):
        if not self.error_queue:
            return
        try:
            self.error_queue.put_nowait(payload)
        except Exception:
            pass

    def _report_exception(self, context: str, exc: Exception):
        self._safe_report(
            {
                "type": "error",
                "context": context,
                "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(),
                "ts": time.time(),
            }
        )

    def _check_window_collision(self, msg_win: Optional[Dict], pers_win: Dict) -> bool:
        """Check if message window overlaps with persistent window (unified system)."""
        # No collision if no message window or message not visible
        if not msg_win:
            return False
        if not msg_win.get("current_message") and not msg_win.get("is_loading"):
            return False
        if msg_win.get("fade_state", 0) in (0, 3):  # Hidden or fading out
            return False

        # No collision if persistent window has no items
        if not pers_win.get("items"):
            return False

        msg_info = self._layout_manager.get_window(
            self._get_window_name(self.WINDOW_TYPE_MESSAGE, msg_win.get("group"))
        )
        pers_info = self._layout_manager.get_window(
            self._get_window_name(self.WINDOW_TYPE_PERSISTENT, pers_win.get("group"))
        )
        if not msg_info or not pers_info:
            return False

        msg_x, msg_y = msg_info.computed_x, msg_info.computed_y
        msg_w = msg_info.width
        msg_h = msg_win.get("body_height") or msg_info.height

        pers_x, pers_y = pers_info.computed_x, pers_info.computed_y
        pers_w = pers_info.width
        pers_h = pers_win.get("body_height") or pers_info.height

        # Check intersection (AABB test)
        return not (
            msg_x + msg_w <= pers_x
            or pers_x + pers_w <= msg_x
            or msg_y + msg_h <= pers_y
            or pers_y + pers_h <= msg_y
        )

    def run(self):
        try:
            if not PIL_AVAILABLE:
                self._report_exception("init", ImportError("PIL not available"))
                return

            try:
                self._backend.start()
            except Exception as e:
                self._report_exception("init", e)
                return

            self._init_fonts()

            self.last_update_time = time.time()

            while self.running:
                try:
                    start = time.time()
                    self.dt = start - self.last_update_time
                    self.last_update_time = start

                    # OS events: mouse input, keeping the HUD above other apps
                    self._backend.pump_events()

                    target_fps = self._global_framerate
                    frame_time = 1.0 / target_fps

                    try:
                        while True:
                            msg = self.msg_queue.get_nowait()
                            self._handle_message(msg)
                    except queue.Empty:
                        pass

                    # =========================================================
                    # UPDATE AND RENDER ALL UNIFIED WINDOWS (includes chat windows now)
                    # =========================================================
                    self._update_all_windows()

                    elapsed = time.time() - start
                    if elapsed < frame_time:
                        time.sleep(frame_time - elapsed)

                except Exception as e:
                    self._report_exception("run_loop", e)
                    time.sleep(0.05)

        except Exception as e:
            self._report_exception("run_crash", e)
        finally:
            self._clear_preview()
            # Cleanup unified windows (including chat windows)
            for name in list(self._windows.keys()):
                self._destroy_window(name)
            self._backend.stop()

    def _handle_message(self, msg):
        try:
            t = msg.get("type")

            # The HUD manager's field names, as the handlers below read them
            if "content" in msg and "message" not in msg:
                msg["message"] = msg["content"]
            if "show" in msg and "state" not in msg:
                msg["state"] = msg["show"]
            if (
                "color" in msg
                and "progress_color" not in msg
                and t in ("show_progress", "show_timer")
            ):
                msg["progress_color"] = msg["color"]

            # Extract group name (default to 'default' for backward compatibility)
            group = msg.get("group", "default")

            # =====================================================================
            # GROUP MANAGEMENT COMMANDS
            # =====================================================================
            if t == "create_group":
                for window_type in self._command_window_types(msg):
                    name = self._get_window_name(window_type, group)
                    self._group_props.setdefault(name, {}).update(msg.get("props") or {})
                    if name in self._windows:
                        self._refresh_window(name, self._windows[name])
                return

            elif t == "update_group":
                props = msg.get("props") or {}
                for window_type in self._command_window_types(msg):
                    name = self._get_window_name(window_type, group)
                    self._group_props.setdefault(name, {}).update(props)
                    win = self._windows.get(name)
                    if win:
                        # Props sent with earlier commands must not outvote the update
                        win.setdefault("explicit_props", {}).update(props)
                        self._refresh_window(name, win)
                return

            elif t == "delete_group":
                for window_type in self._command_window_types(msg):
                    name = self._get_window_name(window_type, group)
                    self._group_props.pop(name, None)
                    self._destroy_window(name)
                return

            elif t in ("set_preview", "clear_preview"):
                self._handle_preview_command(msg)
                return

            elif t == "set_defaults":
                self._server_defaults = dict(msg.get("props") or {})
                self._group_defaults = {
                    name: dict(p) for name, p in (msg.get("groups") or {}).items()
                }
                self._refresh_windows()
                return

            # =====================================================================
            # SYSTEM COMMANDS
            # =====================================================================
            if t == "quit":
                self.running = False
                return

            # =====================================================================
            # MESSAGE WINDOW COMMANDS
            # =====================================================================
            elif t == "hide_message":
                # Hide message window for this group
                win = self._get_window(self.WINDOW_TYPE_MESSAGE, group)
                if win:
                    win["fade_state"] = 3
                    win["current_message"] = None
                    win["is_loading"] = False
                    # Note: Don't release layout slot yet - window still visible during fade-out
                    # Layout slot will be released when fade completes (opacity reaches 0)

            elif t == "show_message":
                # Get or create message window for this group
                props = msg.get("props", {})
                win = self._ensure_window(self.WINDOW_TYPE_MESSAGE, group, props)

                new_msg = msg.get("message", "")
                old_msg = (
                    win["current_message"].get("message", "")
                    if win["current_message"]
                    else ""
                )
                is_append = (
                    win["current_message"] and old_msg and new_msg.startswith(old_msg)
                )

                win["current_message"] = msg

                if not is_append:
                    if win["props"].get("typewriter_effect", True):
                        win["typewriter_active"] = True
                        win["typewriter_char_count"] = 0
                        win["last_typewriter_update"] = time.time()
                    else:
                        win["typewriter_active"] = False
                        win["typewriter_char_count"] = len(new_msg)
                    # Clear cached blocks and render state for new message
                    win["current_blocks"] = None
                    win["last_render_state"] = None

                if win["fade_state"] != 2:
                    self._show_window_if_hidden(win)
                    win["fade_state"] = 1
                    # Immediately notify layout manager that this window is now visible
                    window_name = self._get_window_name(self.WINDOW_TYPE_MESSAGE, group)
                    self._layout_manager.set_window_visible(window_name, True)

                win["min_display_time"] = time.time() + win["props"].get(
                    "duration", 8.0
                )

            elif t == "set_loader" and msg.get("element") == self.WINDOW_TYPE_CHAT:
                win = self._ensure_window(self.WINDOW_TYPE_CHAT, group)
                win["is_loading"] = bool(msg.get("state", False))
                if msg.get("color"):
                    win["loading_color"] = self._hex_to_rgb(msg["color"])
                if win["is_loading"]:
                    win["visible"] = True
                win["canvas_dirty"] = True

            elif t == "set_loader":
                # Get or create message window for this group (loader can work without message)
                win = self._ensure_window(self.WINDOW_TYPE_MESSAGE, group)
                win["is_loading"] = msg.get("state", False)
                if msg.get("color"):
                    win["loading_color"] = self._hex_to_rgb(msg["color"])
                # If showing loader, ensure window is visible
                if win["is_loading"] and win["fade_state"] in (0, 3):
                    self._show_window_if_hidden(win)
                    win["fade_state"] = 1
                    # Immediately notify layout manager that this window is now visible
                    window_name = self._get_window_name(self.WINDOW_TYPE_MESSAGE, group)
                    self._layout_manager.set_window_visible(window_name, True)

            # =====================================================================
            # PERSISTENT WINDOW COMMANDS
            # =====================================================================
            elif t == "add_item":
                title = msg.get("title")
                if title:
                    win = self._ensure_window(self.WINDOW_TYPE_PERSISTENT, group)

                    now = time.time()
                    info = {
                        "title": title,
                        "description": msg.get("description", ""),
                        "added_at": win["items"].get(title, {}).get("added_at", now),
                        "_group": group,
                    }
                    if msg.get("duration"):
                        info["expiry"] = now + float(msg["duration"])
                    win["items"][title] = info

            elif t == "update_item":
                title = msg.get("title")
                if title:
                    win = self._get_window(self.WINDOW_TYPE_PERSISTENT, group)
                    if win and title in win["items"]:
                        info = win["items"][title]
                        if msg.get("description") is not None:
                            info["description"] = msg["description"]
                        if msg.get("duration") is not None:
                            info["expiry"] = time.time() + float(msg["duration"])

            elif t == "show_progress":
                title = msg.get("title")
                if title:
                    win = self._ensure_window(self.WINDOW_TYPE_PERSISTENT, group)

                    target_current = float(msg.get("current", 0))
                    target_maximum = float(msg.get("maximum", 100))
                    auto_close = msg.get("auto_close", False)
                    now = time.time()

                    # Initialize or update animation state
                    if title in win["progress_animations"]:
                        anim = win["progress_animations"][title]
                        anim["start_value"] = anim["current"]
                        anim["target"] = target_current
                        anim["start_time"] = now
                    else:
                        win["progress_animations"][title] = {
                            "current": 0.0,
                            "start_value": 0.0,
                            "target": target_current,
                            "start_time": now,
                        }

                    info = {
                        "title": title,
                        "description": msg.get("description", ""),
                        "added_at": win["items"].get(title, {}).get("added_at", now),
                        "is_progress": True,
                        "progress_current": target_current,
                        "progress_maximum": target_maximum,
                        "progress_color": msg.get("progress_color"),
                        "auto_close": auto_close,
                        "auto_close_triggered": False,
                        "_group": group,
                    }
                    win["items"][title] = info

            elif t == "show_timer":
                title = msg.get("title")
                if title:
                    win = self._ensure_window(self.WINDOW_TYPE_PERSISTENT, group)

                    duration = float(msg.get("duration", 10))
                    auto_close = msg.get("auto_close", True)
                    now = time.time()

                    initial_progress = float(msg.get("initial_progress", 0.0))
                    timer_start_time = now - initial_progress

                    start_percentage = 0.0
                    if initial_progress > 0 and duration > 0:
                        start_percentage = min(100, (initial_progress / duration) * 100)

                    win["progress_animations"][title] = {
                        "current": start_percentage,
                        "start_value": start_percentage,
                        "target": start_percentage,
                        "start_time": now,
                        "is_timer": True,
                        "timer_start": timer_start_time,
                        "timer_duration": duration,
                    }

                    info = {
                        "title": title,
                        "description": msg.get("description", ""),
                        "added_at": now,
                        "is_progress": True,
                        "is_timer": True,
                        "timer_start": timer_start_time,
                        "timer_duration": duration,
                        "progress_current": start_percentage,
                        "progress_maximum": 100,
                        "progress_color": msg.get("progress_color"),
                        "auto_close": auto_close,
                        "auto_close_triggered": False,
                        "_group": group,
                    }
                    win["items"][title] = info

            elif t == "remove_item":
                title = msg.get("title")
                if title:
                    win = self._get_window(self.WINDOW_TYPE_PERSISTENT, group)
                    if win and title in win["items"]:
                        del win["items"][title]
                        if title in win["progress_animations"]:
                            del win["progress_animations"][title]

            elif t == "clear_items":
                win = self._get_window(self.WINDOW_TYPE_PERSISTENT, group)
                if win:
                    win["items"].clear()
                    win["progress_animations"].clear()

            # =====================================================================
            # Chat Window Commands
            # =====================================================================
            elif t == "chat_message":
                chat_name = group
                window_name = f"chat_{chat_name}"
                if chat_name:
                    now = time.time()
                    win = self._ensure_window(self.WINDOW_TYPE_CHAT, chat_name)
                    restored = bool(msg.get("restored", False))
                    # History put back stays hidden until the next message shows it
                    win["visible"] = win.get("fade_state", 0) in (1, 2) if restored else True
                    sender = msg.get("sender", "")
                    message_id = msg.get("id", "")
                    own = bool(msg.get("own", False))
                    text = self._strip_emotions(msg.get("text", "") or "")
                    tools = list(msg.get("tools") or [])
                    last = win["messages"][-1] if win["messages"] else None

                    # The HUD manager decides what adds to the last entry: it sends its id
                    if last and message_id and last.get("id") == message_id:
                        typed_before = len(last["text"])
                        if text:
                            last["text"] = f"{last['text']} {text}" if last["text"] else text
                        last["tools"] = list(last.get("tools") or []) + tools
                        last["icon"] = msg.get("icon") or last.get("icon")
                        last["timestamp"] = now
                        message = last
                    else:
                        typed_before = 0
                        message = {
                            "id": message_id,
                            "sender": sender,
                            "text": text,
                            "color": msg.get("color"),
                            "icon": msg.get("icon"),
                            "own": own,
                            "tools": tools,
                            "timestamp": now,
                        }
                        win["messages"].append(message)

                    # A reply types itself out, like the message window
                    if not own and not restored and win["props"].get("typewriter_effect", True):
                        typing = win.get("typing")
                        if not typing or typing["id"] != message["id"]:
                            win["typing"] = {"id": message["id"], "chars": float(typed_before), "last": now}

                    win["last_message_time"] = now

                    # Trim old messages if over limit
                    max_messages = win["props"].get("max_messages", 50)
                    if len(win["messages"]) > max_messages:
                        win["messages"] = win["messages"][-max_messages:]

                    # Show window if auto-hide was triggered
                    if not restored and (win["fade_state"] == 0 or win["fade_state"] == 3):
                        self._show_window_if_hidden(win)
                        win["fade_state"] = 1  # fade in
                        win["visible"] = True
                        # Immediately notify layout manager
                        self._layout_manager.set_window_visible(window_name, True)

                    win["canvas_dirty"] = True

            elif t == "update_chat_message":
                chat_name = group
                window_name = f"chat_{chat_name}"
                if chat_name and window_name in self._windows:
                    win = self._windows[window_name]
                    message_id = msg.get("id", "")
                    new_text = msg.get("text", "")
                    for m in win["messages"]:
                        if m.get("id") == message_id:
                            m["text"] = self._strip_emotions(new_text or "")
                            win["canvas_dirty"] = True
                            break

            elif t == "clear_chat_window":
                chat_name = group
                window_name = f"chat_{chat_name}"
                if chat_name and window_name in self._windows:
                    self._windows[window_name]["messages"] = []
                    self._windows[window_name]["canvas_dirty"] = True

            elif t == "show_chat_window":
                chat_name = group
                window_name = f"chat_{chat_name}"
                if chat_name and window_name in self._windows:
                    win = self._windows[window_name]
                    win["visible"] = True
                    self._show_window_if_hidden(win)
                    win["fade_state"] = 1  # fade in
                    # Immediately notify layout manager
                    self._layout_manager.set_window_visible(window_name, True)
                    win["canvas_dirty"] = True

            elif t == "hide_chat_window":
                chat_name = group
                window_name = f"chat_{chat_name}"
                if chat_name and window_name in self._windows:
                    win = self._windows[window_name]
                    win["visible"] = False
                    win["is_loading"] = False
                    win["fade_state"] = 3  # fade out
                    # Note: Don't release layout slot yet - window still visible during fade-out
                    # Layout slot will be released when fade completes (opacity reaches 0)
                    win["canvas_dirty"] = True

            # =====================================================================
            # Element Visibility Commands
            # =====================================================================
            elif t == "show_element":
                group_name = msg.get("group")
                element = msg.get("element")
                if group_name and element:
                    window_name = self._get_window_name(element, group_name)
                    if window_name in self._windows:
                        win = self._windows[window_name]
                        win["hidden"] = False
                        self._show_window_if_hidden(win)
                        win["fade_state"] = 1  # fade in
                        self._layout_manager.set_window_visible(window_name, True)
                        win["canvas_dirty"] = True

            elif t == "hide_element":
                group_name = msg.get("group")
                element = msg.get("element")
                if group_name and element:
                    window_name = self._get_window_name(element, group_name)
                    if window_name in self._windows:
                        win = self._windows[window_name]
                        win["hidden"] = True
                        win["fade_state"] = 3  # fade out
                        win["canvas_dirty"] = True

            elif t == "update_settings":
                self._handle_settings_update(msg)

        except Exception as e:
            self._report_exception("handle_message", e)

    def _handle_settings_update(self, settings: dict):
        """Handle settings update message.

        Args:
            settings: Dict containing settings to update (framerate, layout_margin, layout_spacing, screen)
        """
        # Update framerate
        if "framerate" in settings:
            self._global_framerate = max(1, min(240, settings["framerate"]))

        # Update layout settings
        layout_changed = False
        if "layout_margin" in settings:
            self._layout_margin = settings["layout_margin"]
            layout_changed = True
        if "layout_spacing" in settings:
            self._layout_spacing = settings["layout_spacing"]
            layout_changed = True

        # If layout settings changed, reposition all windows
        if layout_changed:
            # Re-register all windows with new margin/spacing values
            self._reregister_all_windows()

        # Handle screen change - recreate LayoutManager and reposition
        if "screen" in settings:
            new_screen = settings["screen"]
            if new_screen != self._screen:
                self._screen = new_screen
                # Get new monitor dimensions
                try:
                    monitor = self._backend.monitor(self._screen)
                    screen_width, screen_height = monitor.width, monitor.height
                    screen_offset_x, screen_offset_y = monitor.x, monitor.y
                except Exception as e:
                    # Fall back to current dimensions
                    screen_width, screen_height = self._layout_manager.screen_size
                    screen_offset_x, screen_offset_y = (
                        self._layout_manager.screen_offset
                    )
                # Create new layout manager with new screen info
                self._layout_manager = LayoutManager(
                    screen_width=screen_width,
                    screen_height=screen_height,
                    screen_offset_x=screen_offset_x,
                    screen_offset_y=screen_offset_y,
                    default_margin=self._layout_margin,
                    default_spacing=self._layout_spacing,
                )
                # Re-register all windows with new layout manager
                self._reregister_all_windows()

    def _reregister_all_windows(self):
        """Re-register all windows with the layout manager after a screen or
        margin/spacing change, keeping manual placement."""
        for name, win in self._windows.items():
            self._register_layout(name, win, win.get("body_height") or 200)
            if win.get("fade_state", 0) == 0:
                self._layout_manager.set_window_visible(name, False)
        self._reregister_preview_windows()

        # Force position recalculation and window repositioning
        self._update_all_window_positions()
