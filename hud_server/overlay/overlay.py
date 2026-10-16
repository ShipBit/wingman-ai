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
import math
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

from hud_server.rendering.markdown import MarkdownRenderer
from hud_server.rendering.layers import Piece, PieceCache, compose, lay_out, render_piece

from hud_server.platform import HudBackend, create_backend
from hud_server.layout import LayoutManager, Anchor, LayoutMode, Align
from hud_server.overlay.preview import PreviewMixin
from hud_server.constants import (
    MAX_PROGRESS_TRACK_CACHE_SIZE,
    MAX_PROGRESS_GRADIENT_CACHE_SIZE,
    MAX_LOADING_BAR_CACHE_SIZE,
    DEFAULT_BORDER_COLOR,
)


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

        # =====================================================================
        # RENDER CACHING SYSTEM
        # =====================================================================
        # Cache for pre-rendered components to reduce CPU load
        # Each cache entry contains: {'image': PIL.Image, 'params': tuple}
        #
        # Progress bar track cache: stores empty progress bar backgrounds
        # Key: (width, height, bg_color) -> cached track image
        self._progress_track_cache: Dict[tuple, Image.Image] = {}
        # Max cache entries for progress tracks
        self._max_progress_track_cache = MAX_PROGRESS_TRACK_CACHE_SIZE

        # Progress bar fill gradient cache: stores gradient overlays
        # Key: (width, height, fill_color) -> cached gradient overlay
        self._progress_gradient_cache: Dict[tuple, Image.Image] = {}
        # Max cache entries for gradients
        self._max_progress_gradient_cache = MAX_PROGRESS_GRADIENT_CACHE_SIZE

        # Loading bar element cache: stores pre-rendered loading bar elements
        # Key: (bar_width, max_height, color) -> cached bar surface
        self._loading_bar_cache: Dict[tuple, Image.Image] = {}
        # Max cache entries for loading bars
        self._max_loading_bar_cache = MAX_LOADING_BAR_CACHE_SIZE

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
            handle = win.get("handle")
            if handle is None:
                continue

            # Skip windows that are manually hidden
            if win.get("hidden", False):
                continue

            # Skip windows that are completely hidden (fade_state 0 AND opacity 0)
            fade_state = win.get("fade_state", 0)
            opacity = win.get("opacity", 0)
            if fade_state == 0 and opacity == 0:
                continue

            canvas = win.get("canvas")
            if not canvas:
                continue

            # Get position from layout - windows should be repositioned even when fading out
            # so that layout updates are immediate when other windows change size
            pos = positions.get(name)
            if pos:
                x, y = pos
                w, h = canvas.size

                # Check if position actually changed
                old_x = win.get("_last_x", -1)
                old_y = win.get("_last_y", -1)

                if x != old_x or y != old_y:
                    # Position changed - move window and mark for reblit
                    self._backend.move_window(handle, x, y, w, h)
                    win["_last_x"] = x
                    win["_last_y"] = y
                    win["canvas_dirty"] = True  # Force reblit after move

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

    LOADER_SPACE = 30

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
        self.md_renderer = renderer
        return renderer

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
        """Lay out the pieces in view, put the window together when that
        changed, and draw the loader, the one thing that moves every frame."""
        bg_rgba = self._parse_hex_color_with_alpha(props.get("bg_color", "#1e212b"))
        width = max(1, int(props.get("width", 400)))
        padding = int(props.get("content_padding", 16))
        radius = int(props.get("border_radius", 12))
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
            tail=self.LOADER_SPACE if loading else 0,
            min_height=60,
            fixed_height=fixed_height,
        )
        cache.end_frame()

        signature = (layout.signature, width, tuple(bg_rgba), radius, fade_height)
        changed = win.get("static_signature") != signature or win.get("static_canvas") is None
        if changed:
            win["static_canvas"] = compose(
                layout, width, tuple(bg_rgba), (*DEFAULT_BORDER_COLOR, bg_rgba[3]),
                radius, fade_height,
            )
            win["static_signature"] = signature
        elif not loading and win.get("canvas") is not None and win.get("last_render_state") == signature:
            return

        # A copy: whoever gets the picture may draw on it (the preview does)
        canvas = win["static_canvas"].copy()
        if loading:
            self._draw_loading(
                ImageDraw.Draw(canvas), canvas, padding, layout.tail_y + 6,
                width - padding * 2, loader_color,
            )
        win["last_render_state"] = signature
        self._present(name, win, canvas)

    def _present(self, name: str, win: Dict, canvas: Image.Image):
        """Hand the new picture to the window and fit the window to it."""
        win["canvas"] = canvas
        win["canvas_dirty"] = True
        self._layout_manager.update_window_height(name, canvas.height)
        pos = self._layout_manager.get_position(name)
        handle = win.get("handle")
        if handle is not None:
            props = win.get("props", {})
            if pos:
                x, y = pos
            else:
                x, y = int(props.get("x", 20)), int(props.get("y", 20))
            self._backend.move_window(handle, x, y, canvas.width, canvas.height)

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
        """The picture as a circle. Without one, a circle with the name's
        initial when `initial`, else None."""
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
        key = ("initial", letter, size, tuple(color))
        avatar = self.image_cache.get(key)
        if avatar is None:
            avatar = round_avatar(Image.new("RGBA", (size, size), tuple(color) + (70,)), size)
            font = self.fonts.get("bold", self.fonts.get("normal"))
            if font:
                try:
                    ImageDraw.Draw(avatar).text(
                        (size / 2, size / 2), letter, fill=tuple(color) + (255,), font=font, anchor="mm"
                    )
                except Exception:
                    pass
            self.image_cache[key] = avatar
        return avatar

    def _sender_piece(
        self, name: str, icon: Optional[str], x: int, color: Tuple, size: int,
        style: tuple, initial: bool = False, alpha: float = 1.0,
    ) -> Piece:
        """A sender's round picture with the name beside it, centred on it."""
        key = ("sender", name, icon, x, tuple(color), size, initial, style)

        def draw(d, image, _top):
            avatar = self._avatar(icon, name, size, color, initial)
            text_x, height = x, 0
            if avatar is not None:
                image.alpha_composite(avatar, (x, 0))
                text_x, height = x + size + 10, size
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
                    return text_h + 12
            return height + 4

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

        def draw(d, image, _top):
            y = 10
            tx = x
            th = 30
            font = self.fonts.get("code", self.fonts.get("normal", self.fonts.get("regular")))
            for src, (icon, cnt) in chips.items():
                has_icon = bool(icon and os.path.exists(str(icon)))
                icon_w = 24 if has_icon else 0
                badge_w = 26 if cnt > 1 else 0
                # A chip never wider than the window
                src = self._fit_text(src, font, right - x - icon_w - badge_w - 26) or "…"
                sw, sh = self._get_text_size(src, font)
                chip_w = sw + icon_w + badge_w + 26

                if tx + chip_w > right and tx > x:
                    tx = x
                    y += th + 10

                d.rounded_rectangle(
                    [tx, y, tx + chip_w, y + th], radius=th // 2,
                    fill=(42, 48, 60, 235), outline=accent,
                )
                ix = tx + 12
                if has_icon:
                    try:
                        if icon not in self.image_cache:
                            with Image.open(icon) as source:
                                self.image_cache[icon] = source.convert("RGBA").resize(
                                    (18, 18), Image.Resampling.LANCZOS
                                )
                        chip_icon = self.image_cache[icon]
                        image.paste(chip_icon, (ix, y + 6), chip_icon)
                        ix += 22
                    except Exception:
                        pass
                d.text((ix, y + (th - sh) // 2), src, fill=text_color, font=font)

                # Badge for multiple tool calls from the same source
                if cnt > 1:
                    bw, bh = self._get_text_size(str(cnt), font)
                    bx = tx + chip_w - bw - 16
                    d.ellipse([bx - 4, y + 5, bx + bw + 8, y + th - 5], fill=accent)
                    d.text((bx + 2, y + 7), str(cnt), fill=bg, font=font)

                tx += chip_w + 10
            return y + th + 10

        return Piece(key, draw, alpha=alpha)

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
                pieces.append(self._sender_piece(title, icon, padding, accent, size, style))

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
        r = int(seconds + 0.999)
        d, r = divmod(r, 86400)
        h, r = divmod(r, 3600)
        m, s = divmod(r, 60)
        parts = []
        if d > 0:
            parts.append(f"{d}d")
        if h > 0:
            parts.append(f"{h}h")
        if m > 0:
            parts.append(f"{m}m")
        parts.append(f"{s}s")
        return " ".join(parts)

    def _info_item_piece(
        self, title: str, info: Dict, anim: Optional[Dict], now: float, props: Dict,
        style: tuple, text_color, accent, bg,
    ) -> Piece:
        """One info panel item. Its key holds what is shown, not the time: a
        running timer draws again once a second, a moving bar once a pixel."""
        width = int(props.get("width", 300))
        padding = int(props.get("content_padding", 16))
        font_size = int(props.get("font_size", 16))
        renderer = self.md_renderer

        timer_text = None
        if info.get("is_progress") and info.get("is_timer"):
            elapsed = now - info.get("timer_start", now)
            timer_text = self._format_remaining(max(0.0, info.get("timer_duration", 0) - elapsed))
        elif info.get("expiry"):
            timer_text = self._format_remaining(max(0.0, info["expiry"] - now))

        progress = None
        if info.get("is_progress"):
            progress_max = float(info.get("progress_maximum", 100))
            current = anim.get("current", 0) if anim else float(info.get("progress_current", 0))
            if progress_max <= 0:
                progress_max = 100
            percentage = min(100, max(0, (current / progress_max) * 100))
            bar_width = width - padding * 2
            # What the bar shows: its filled pixels (2x supersampled) and the label
            fill = int((bar_width * 2 - 4) * percentage / 100)
            progress = (percentage, fill, f"{percentage:.0f}%")

        title_text = info.get("title", title)
        desc = self._strip_emotions(info.get("description", "") or "")
        progress_color = info.get("progress_color")
        images = renderer.image_version if "![" in desc else 0
        key = (
            "info", title_text, desc, timer_text,
            progress[1:] if progress else None, progress_color,
            width, padding, style, images,
        )

        def draw(d, image, _top):
            y = 0
            font_bold = self.fonts.get("bold", self.fonts.get("normal", self.fonts.get("regular")))
            font_normal = self.fonts.get("normal", self.fonts.get("regular"))

            timer_w = 0
            if timer_text and font_bold:
                timer_w, _ = self._get_text_size(timer_text, font_bold)
                d.text((width - padding - timer_w, y), timer_text, fill=text_color + (255,), font=font_bold)
                timer_w += 10

            if font_bold:
                shown_title = self._fit_text(title_text, font_bold, width - padding * 2 - timer_w)
                self._render_text_with_emoji(
                    d, shown_title, padding, y, accent + (255,), font_bold, emoji_y_offset=3
                )
                try:
                    bbox = font_bold.getbbox(shown_title or title_text)
                    title_h = bbox[3] - bbox[1]
                except Exception:
                    title_h = font_size
                y += title_h + max(10, int(title_h * 0.625))
            else:
                y += 22

            if progress:
                percentage, _fill, pct_text = progress
                color = self._hex_to_rgb(progress_color) if progress_color else accent
                bar_width = width - padding * 2
                y += 4
                y = self._draw_progress_bar(
                    d, image, padding, y, bar_width, 16, percentage, bg, color, text_color
                )
                if font_normal:
                    try:
                        bbox = font_normal.getbbox(pct_text)
                        pct_w = bbox[2] - bbox[0]
                        pct_h = bbox[3] - bbox[1]
                    except Exception:
                        pct_w = len(pct_text) * 7
                        pct_h = font_size
                    d.text(
                        (padding + (bar_width - pct_w) // 2, y), pct_text,
                        fill=text_color + (200,), font=font_normal,
                    )
                    y += int(pct_h * 1.25) + 4

            if desc:
                y = renderer.render(d, image, desc, padding, y, width - padding * 2)
            return y

        return Piece(key, draw, gap=8)

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

        def newest_first():
            for title, info in reversed(shown):
                yield self._info_item_piece(
                    title, info, anims.get(title), now, props, style, text_color, accent, bg_rgba[:3]
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
        the name above it, like in a messenger."""
        sender = message.get("sender", "")
        text = message.get("text", "")
        renderer = self.md_renderer
        images = renderer.image_version if "![" in text else 0
        key = ("own", sender, text, x, width, tuple(color), radius, style, images)

        def draw(d, image, _top):
            right = x + width
            y = 0
            font_bold = self.fonts.get("bold", self.fonts.get("normal", self.fonts.get("regular")))
            name = self._fit_text(sender, font_bold, width) if font_bold else ""
            if name:
                name_w, _ = self._get_text_size(name, font_bold)
                try:
                    _, top, _, bottom = font_bold.getbbox(name)
                except Exception:
                    top, bottom = 0, 20
                self._render_text_with_emoji(
                    d, name, right - name_w, 0, tuple(color) + (255,), font_bold, emoji_y_offset=3
                )
                y = bottom - top + 10

            # Drawn at the widest a bubble may be, then cut to what the text
            # covers: bold, emoji, links and line breaks all measure right
            pad_x, pad_y = 12, 8
            max_inner = max(40, int(width * 0.85) - 2 * pad_x)
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
            d.rounded_rectangle(
                [bx, y, right - 1, y + bubble_h], radius=max(4, min(radius, 14)),
                fill=renderer.accent_tint(0.4),
                outline=renderer.accent_tint(0.7),
            )
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
        spacing = int(props.get("message_spacing", 8))
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
        """Remove emotion tags like [happy], [sad], [breathe] but preserve markdown links and checkboxes."""
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

    def _get_cached_loading_bar(
        self, bar_w: int, bar_h: int, color: Tuple
    ) -> Image.Image:
        """Get or create a cached loading bar element.

        Caches pre-rendered loading bar pill shapes to avoid recreating
        them every frame for each bar in the loading animation.

        Note: bar_h is already guaranteed >= 1 by the caller.
        """
        # Ensure color is just RGB for cache key (ignore alpha variations)
        color_key = color[:3]
        cache_key = (bar_w, bar_h, color_key)

        if cache_key in self._loading_bar_cache:
            return self._loading_bar_cache[cache_key]


        # Create the bar surface (bar_h >= 1 guaranteed by caller)
        bar_surf = Image.new("RGBA", (bar_w, bar_h), (0, 0, 0, 0))
        bar_draw = ImageDraw.Draw(bar_surf)

        radius = min(bar_w // 2, bar_h // 2)
        if radius < 1:
            radius = 1

        bar_color = color_key + (255,)
        bar_draw.rounded_rectangle(
            [0, 0, bar_w - 1, bar_h - 1], radius=radius, fill=bar_color
        )

        # Limit cache size
        if len(self._loading_bar_cache) >= self._max_loading_bar_cache:
            oldest_key = next(iter(self._loading_bar_cache))
            del self._loading_bar_cache[oldest_key]

        self._loading_bar_cache[cache_key] = bar_surf
        return bar_surf

    def _draw_loading(self, draw, canvas, x: int, y: int, width: int, color: Tuple):
        """Modern animated loading bars with full width wave.

        OPTIMIZED: Uses caching for bar element surfaces.
        """
        # Initialize loading phase if not exists
        if not hasattr(self, "_loading_phase"):
            self._loading_phase = 0.0

        # Update phase based on time (approx 9.0 rad/s matches original 0.15/frame at 60fps)
        self._loading_phase += 9.0 * self.dt

        # Use full available width (padding already handled by caller)
        available_w = width

        bar_w = 4
        spacing = 4
        num_bars = int(available_w // (bar_w + spacing))

        # Center the array of bars within the given area
        total_bars_w = num_bars * (bar_w + spacing) - spacing
        start_x = x + (width - total_bars_w) // 2

        max_h = 14
        min_h = 2

        center_y = y + 15

        for i in range(num_bars):
            # Create a gentle wave using two sine waves for organic feel
            wave1 = math.sin(self._loading_phase + (i * 0.2))
            wave2 = math.sin((self._loading_phase * 0.5) - (i * 0.1))

            normalized = (wave1 + wave2 + 2) / 4  # Normalize to 0-1

            # Sharpen the peak
            normalized = normalized**2

            h = int(min_h + (normalized * (max_h - min_h)))
            if h < 1:
                h = 1

            bar_x = start_x + i * (bar_w + spacing)
            bar_y = int(center_y - (h / 2))

            # Get cached bar surface (or create if height not cached)
            bar_surf = self._get_cached_loading_bar(bar_w, h, color)
            canvas.paste(bar_surf, (bar_x, bar_y), bar_surf)

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
        msg_canvas = msg_win.get("canvas")
        msg_h = msg_canvas.height if msg_canvas else msg_info.height

        pers_x, pers_y = pers_info.computed_x, pers_info.computed_y
        pers_w = pers_info.width
        pers_canvas = pers_win.get("canvas")
        pers_h = pers_canvas.height if pers_canvas else pers_info.height

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
            canvas = win.get("canvas")
            height = canvas.size[1] if canvas else 200
            self._register_layout(name, win, height)
            if win.get("fade_state", 0) == 0:
                self._layout_manager.set_window_visible(name, False)
        self._reregister_preview_windows()

        # Force position recalculation and window repositioning
        self._update_all_window_positions()

    def _get_cached_progress_track(
        self, width: int, height: int, bg_color: Tuple[int, int, int], scale: int = 2
    ) -> Image.Image:
        """Get or create a cached progress bar background track.

        Caches the empty progress bar background to avoid recreating it every frame.
        The track includes the rounded rectangle with antialiasing.

        Note: Returns a copy because callers modify the returned image (draw fill on it).
        """
        cache_key = (width, height, bg_color, scale)

        if cache_key in self._progress_track_cache:
            # Copy required: callers draw the progress fill onto this image
            return self._progress_track_cache[cache_key].copy()


        # Create the track at scaled resolution
        scaled_width = width * scale
        scaled_height = height * scale
        radius = scaled_height // 2

        track = Image.new("RGBA", (scaled_width, scaled_height), (0, 0, 0, 0))
        track_draw = ImageDraw.Draw(track)

        track_color = tuple(max(0, c - 30) for c in bg_color)
        outline_color = tuple(max(0, c - 50) for c in bg_color) + (150,)
        track_draw.rounded_rectangle(
            [0, 0, scaled_width - 1, scaled_height - 1],
            radius=radius,
            fill=track_color + (255,),
            outline=outline_color,
        )

        # Limit cache size using simple FIFO eviction
        if len(self._progress_track_cache) >= self._max_progress_track_cache:
            oldest_key = next(iter(self._progress_track_cache))
            del self._progress_track_cache[oldest_key]

        self._progress_track_cache[cache_key] = track
        return track.copy()

    def _get_cached_gradient_overlay(
        self,
        fill_width: int,
        fill_height: int,
        highlight_height: int,
        shadow_height: int,
    ) -> Image.Image:
        """Get or create a cached gradient overlay for progress bar fills.

        The gradient provides the depth effect (top highlight, bottom shadow).
        Cached because the gradient pattern is the same for same dimensions.

        Note: Returns a copy because gradient is pasted/composited onto other images.
        """
        cache_key = (fill_width, fill_height, highlight_height, shadow_height)

        if cache_key in self._progress_gradient_cache:
            # Copy required: gradient is composited onto the progress bar buffer
            return self._progress_gradient_cache[cache_key].copy()


        gradient = Image.new("RGBA", (fill_width + 1, fill_height + 1), (0, 0, 0, 0))
        gradient_draw = ImageDraw.Draw(gradient)

        # Top highlight (lighter)
        for i in range(highlight_height):
            alpha = int(60 * (1 - i / highlight_height))
            gradient_draw.line([(0, i), (fill_width, i)], fill=(255, 255, 255, alpha))

        # Bottom shadow (darker)
        for i in range(shadow_height):
            alpha = int(40 * (i / shadow_height))
            gradient_draw.line(
                [
                    (0, fill_height - shadow_height + i),
                    (fill_width, fill_height - shadow_height + i),
                ],
                fill=(0, 0, 0, alpha),
            )

        # Limit cache size
        if len(self._progress_gradient_cache) >= self._max_progress_gradient_cache:
            oldest_key = next(iter(self._progress_gradient_cache))
            del self._progress_gradient_cache[oldest_key]

        self._progress_gradient_cache[cache_key] = gradient
        return gradient.copy()

    def _draw_progress_bar(
        self,
        draw: ImageDraw.Draw,
        img: Image.Image,
        x: int,
        y: int,
        width: int,
        height: int,
        percentage: float,
        bg_color: Tuple[int, int, int],
        fill_color: Tuple[int, int, int],
        text_color: Tuple[int, int, int],
    ) -> int:
        """
        Draw a modern, sleek progress bar with antialiasing via supersampling.

        Uses 2x supersampling for smooth edges on rounded corners.
        OPTIMIZED: Uses caching for track backgrounds and gradient overlays.

        Args:
            draw: ImageDraw object
            img: The PIL Image to draw on (for advanced effects)
            x: X position
            y: Y position
            width: Width of the progress bar
            height: Height of the progress bar
            percentage: Progress percentage (0-100)
            bg_color: Background track color
            fill_color: Progress fill color (accent color)
            text_color: Text color for percentage

        Returns:
            The Y position after the progress bar (for layout)
        """
        percentage = max(0, min(100, percentage))

        # Supersampling scale factor for antialiasing
        scale = 2
        scaled_height = height * scale
        scaled_width = width * scale
        radius = scaled_height // 2

        # Get cached track background (or create if not cached)
        bar_buffer = self._get_cached_progress_track(width, height, bg_color, scale)

        # Calculate fill width at scaled size
        fill_width = int((scaled_width - 2 * scale) * percentage / 100)

        if fill_width > radius:  # Only draw if there's meaningful progress
            bar_draw = ImageDraw.Draw(bar_buffer)
            fill_x = scale
            fill_y = scale
            fill_h = scaled_height - 2 * scale
            inner_radius = max(1, radius - scale)

            # Draw the main fill
            bar_draw.rounded_rectangle(
                [fill_x, fill_y, fill_x + fill_width, fill_y + fill_h],
                radius=inner_radius,
                fill=fill_color + (255,),
            )

            # Get cached gradient overlay
            highlight_height = fill_h // 3
            shadow_height = fill_h // 4
            gradient_overlay = self._get_cached_gradient_overlay(
                fill_width, fill_h, highlight_height, shadow_height
            )

            # Create a mask from the fill shape to apply gradient only within the bar
            mask = Image.new("L", (scaled_width, scaled_height), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle(
                [fill_x, fill_y, fill_x + fill_width, fill_y + fill_h],
                radius=inner_radius,
                fill=255,
            )

            # Composite the gradient onto the bar buffer
            gradient_full = Image.new(
                "RGBA", (scaled_width, scaled_height), (0, 0, 0, 0)
            )
            gradient_full.paste(gradient_overlay, (fill_x, fill_y))
            bar_buffer = Image.composite(
                Image.alpha_composite(bar_buffer, gradient_full), bar_buffer, mask
            )

            # Add a subtle inner glow/shine at the top edge
            shine_buffer = Image.new(
                "RGBA", (scaled_width, scaled_height), (0, 0, 0, 0)
            )
            shine_draw = ImageDraw.Draw(shine_buffer)

            # Draw a thin highlight line at the top of the fill
            shine_y = fill_y + scale
            shine_start = fill_x + inner_radius
            shine_end = fill_x + fill_width - inner_radius
            if shine_end > shine_start:
                shine_color = tuple(min(255, c + 80) for c in fill_color) + (120,)
                shine_draw.line(
                    [(shine_start, shine_y), (shine_end, shine_y)],
                    fill=shine_color,
                    width=scale,
                )
                shine_draw.line(
                    [(shine_start, shine_y + scale), (shine_end, shine_y + scale)],
                    fill=tuple(min(255, c + 40) for c in fill_color) + (60,),
                    width=scale,
                )

            bar_buffer = Image.alpha_composite(bar_buffer, shine_buffer)

        # Downsample with high-quality resampling (antialiasing)
        bar_final = bar_buffer.resize((width, height), Image.Resampling.LANCZOS)

        # Paste the antialiased progress bar onto the main image
        img.paste(bar_final, (x, y), bar_final)

        return y + height + 2  # Return next Y position with minimal spacing
