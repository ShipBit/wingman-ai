"""
HeadsUp Overlay - PIL-based implementation with sophisticated Markdown rendering

This implementation uses ONLY:
- PIL (Pillow) for rendering (text, shapes, images)
- Win32 API for window management
"""

import os
import sys
import json
import threading
import time
import queue
import math
import re
import ctypes
from typing import Tuple, Dict, Optional
import traceback

# PIL for rendering
try:
    from PIL import Image, ImageDraw, ImageFont, ImageChops

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None
    ImageDraw = None
    ImageFont = None
    ImageChops = None

from hud_server.rendering.markdown import MarkdownRenderer

if sys.platform != "win32":
    raise ImportError("hud_server.overlay is only available on Windows")

from hud_server.platform.win32 import (
    user32,
    gdi32,
    kernel32,
    BITMAPINFOHEADER,
    BITMAPINFO,
    MSG,
    WS_POPUP,
    WS_EX_LAYERED,
    WS_EX_TRANSPARENT,
    WS_EX_TOPMOST,
    WS_EX_TOOLWINDOW,
    WS_EX_NOACTIVATE,
    LWA_ALPHA,
    LWA_COLORKEY,
    SWP_SHOWWINDOW,
    SWP_NOACTIVATE,
    SWP_NOMOVE,
    SWP_NOSIZE,
    SRCCOPY,
    DIB_RGB_COLORS,
    BI_RGB,
    SW_SHOWNOACTIVATE,
    HWND_TOPMOST,
    PM_REMOVE,
    _ensure_window_class,
    _class_name,
    force_on_top,
    WINEVENTPROC,
    EVENT_SYSTEM_FOREGROUND,
    WINEVENT_OUTOFCONTEXT,
    WINEVENT_SKIPOWNPROCESS,
    get_monitor_dimensions,
)
from hud_server.layout import LayoutManager, Anchor, LayoutMode
from hud_server.constants import (
    MAX_PROGRESS_TRACK_CACHE_SIZE,
    MAX_PROGRESS_GRADIENT_CACHE_SIZE,
    MAX_CORNER_CACHE_SIZE,
    MAX_LOADING_BAR_CACHE_SIZE,
)


class HeadsUpOverlay:
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
    ):
        self.running = True
        self.msg_queue = command_queue if command_queue else queue.Queue()
        self.error_queue = error_queue
        self._next_heartbeat = time.time() + 1.0
        self.use_stdin = command_queue is None
        self.dt = 0.0
        self.last_update_time = 0.0
        self._global_framerate = max(1, framerate)
        self._layout_margin = layout_margin
        self._layout_spacing = layout_spacing
        self._screen = screen

        # Reactive foreground management
        self._foreground_changed = threading.Event()
        self._win_event_hook = None
        self._win_event_proc = None  # prevent GC of the callback

        # =====================================================================
        # UNIFIED WINDOW SYSTEM
        # =====================================================================
        # All windows are stored in this dictionary, keyed by unique window name.
        # Window name format: "{type}_{group}" e.g. "message_ATC", "persistent_Computer"
        #
        # Each window state contains:
        # - 'type': str - 'message', 'persistent', or 'chat'
        # - 'group': str - the group name this window belongs to
        # - 'props': dict - display properties (x, y, width, colors, etc.)
        # - 'hwnd': window handle
        # - 'window_dc': device context
        # - 'mem_dc': memory device context
        # - 'canvas': PIL Image
        # - 'canvas_dirty': bool
        # - 'dib_bitmap', 'dib_bits', 'old_bitmap', 'dib_width', 'dib_height': DIB resources
        # - 'fade_state': 0=hidden, 1=fade_in, 2=visible, 3=fade_out
        # - 'opacity': current opacity (0-255)
        # - 'target_opacity': target opacity (0-255)
        # - 'last_render_state': for caching
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
        #
        # Chat windows:
        # - 'messages': list of chat messages
        # - 'last_message_time': float
        # - 'visible': bool
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
            # Persistent window defaults
            "persistent_x": 20,
            "persistent_y": 300,
        }

        # Per-group props storage (set via create_group/update_group)
        self._group_props: Dict[str, Dict] = {}

        # Progress animation transition duration
        self._progress_transition_duration = 0.5

        # =====================================================================
        # SHARED RESOURCES (used by unified window system)
        # =====================================================================
        self.fonts = {}
        self.image_cache = {}
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

        # Rounded rectangle corner cache: stores pre-rendered corners at various radii
        # Key: (radius, scale, bg_color) -> cached corner images
        self._corner_cache: Dict[tuple, Dict[str, Image.Image]] = {}
        # Max cache entries for corners
        self._max_corner_cache = MAX_CORNER_CACHE_SIZE

        # Loading bar element cache: stores pre-rendered loading bar elements
        # Key: (bar_width, max_height, color) -> cached bar surface
        self._loading_bar_cache: Dict[tuple, Image.Image] = {}
        # Max cache entries for loading bars
        self._max_loading_bar_cache = MAX_LOADING_BAR_CACHE_SIZE

        # Render statistics for monitoring (optional debugging)
        self._render_stats = {
            "track_cache_hits": 0,
            "track_cache_misses": 0,
            "gradient_cache_hits": 0,
            "gradient_cache_misses": 0,
            "corner_cache_hits": 0,
            "corner_cache_misses": 0,
            "loading_cache_hits": 0,
            "loading_cache_misses": 0,
        }

        # =====================================================================
        # LAYOUT MANAGER
        # =====================================================================
        # Automatic positioning and stacking to prevent window overlap
        # Get screen dimensions and offset based on selected monitor
        screen_width, screen_height, screen_offset_x, screen_offset_y = (
            get_monitor_dimensions(self._screen)
        )
        self._layout_manager = LayoutManager(
            screen_width=screen_width,
            screen_height=screen_height,
            screen_offset_x=screen_offset_x,
            screen_offset_y=screen_offset_y,
            default_margin=self._layout_margin,
            default_spacing=self._layout_spacing,
        )

    # =========================================================================
    # RENDER CACHE MANAGEMENT
    # =========================================================================

    def get_render_cache_stats(self) -> Dict[str, int]:
        """Get render cache statistics for monitoring performance.

        Returns a dictionary with cache hit/miss counts for each cache type.
        Useful for debugging and performance monitoring.
        """
        return dict(self._render_stats)

    def clear_render_caches(self):
        """Clear all render caches.

        Call this when memory pressure is high or when visual styles change
        significantly. Normally caches auto-evict when full.
        """
        self._progress_track_cache.clear()
        self._progress_gradient_cache.clear()
        self._corner_cache.clear()
        self._loading_bar_cache.clear()

        # Reset statistics
        for key in self._render_stats:
            self._render_stats[key] = 0

    def get_render_cache_sizes(self) -> Dict[str, int]:
        """Get current sizes of render caches.

        Returns a dictionary with the number of entries in each cache.
        """
        return {
            "progress_track_cache": len(self._progress_track_cache),
            "progress_gradient_cache": len(self._progress_gradient_cache),
            "corner_cache": len(self._corner_cache),
            "loading_bar_cache": len(self._loading_bar_cache),
        }

    # =========================================================================
    # UNIFIED WINDOW MANAGEMENT
    # =========================================================================

    def _get_window_name(self, window_type: str, group: str) -> str:
        """Generate a unique window name from type and group."""
        return f"{window_type}_{group}"

    def _get_default_window_props(self, window_type: str, group: str) -> dict:
        """Get default properties for a new window, merging group props if available."""
        props = dict(self._default_props)

        # Apply group-specific props if available
        if group in self._group_props:
            props.update(self._group_props[group])

        # Adjust defaults based on window type
        if window_type == self.WINDOW_TYPE_PERSISTENT:
            # Use persistent_* props for position
            props["x"] = props.get("x", 20)
            props["y"] = props.get("y", 300)
            props["width"] = props.get("width", 300)

        return props

    def _create_window_state(
        self, window_type: str, group: str, props: dict = None
    ) -> Dict:
        """Create a new window state dictionary."""
        merged_props = self._get_default_window_props(window_type, group)
        if props:
            merged_props.update(props)

        state = {
            "type": window_type,
            "group": group,
            "props": merged_props,
            "hwnd": None,
            "window_dc": None,
            "mem_dc": None,
            "canvas": None,
            "canvas_dirty": False,
            "dib_bitmap": None,
            "dib_bits": None,
            "old_bitmap": None,
            "dib_width": 0,
            "dib_height": 0,
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
                    "loading_color": (0, 170, 255),
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

            # Create the actual Win32 window
            window_props = state["props"]
            w = int(window_props.get("width", 400))
            h = 100  # Initial height, will be adjusted during rendering

            # Register with layout manager
            layout_mode_str = window_props.get("layout_mode", "auto")
            anchor_str = window_props.get("anchor", "top_left")
            priority = int(window_props.get("priority", 10))
            margin = int(window_props.get("margin", 20))
            spacing = int(window_props.get("spacing", 10))

            # Map string to enum
            try:
                anchor = Anchor(anchor_str)
            except ValueError:
                anchor = Anchor.TOP_LEFT

            try:
                layout_mode = LayoutMode(layout_mode_str)
            except ValueError:
                layout_mode = LayoutMode.AUTO

            # Adjust priority for persistent windows (lower so they stack below messages)
            if window_type == self.WINDOW_TYPE_PERSISTENT:
                priority = max(0, priority - 5)

            self._layout_manager.register_window(
                name=name,
                anchor=anchor,
                mode=layout_mode,
                priority=priority,
                width=w,
                height=h,
                margin_x=margin,
                margin_y=margin,
                spacing=spacing,
                group=group,
                manual_x=(
                    int(window_props.get("x", 20))
                    if layout_mode == LayoutMode.MANUAL
                    else None
                ),
                manual_y=(
                    int(window_props.get("y", 20))
                    if layout_mode == LayoutMode.MANUAL
                    else None
                ),
            )

            # Get initial position from layout manager
            pos = self._layout_manager.get_position(name)
            if pos:
                x, y = pos
            else:
                x = int(window_props.get("x", 20))
                y = int(window_props.get("y", 20))

            hwnd = self._create_overlay_window(f"HUD_{name}", x, y, w, h)
            if hwnd:
                window_dc, mem_dc = self._init_gdi(hwnd)
                state["hwnd"] = hwnd
                state["window_dc"] = window_dc
                state["mem_dc"] = mem_dc
        elif props:
            # Update existing window props
            self._windows[name]["props"].update(props)
            self._windows[name]["target_opacity"] = int(
                self._windows[name]["props"].get("opacity", 0.85) * 255
            )

            # Update layout manager if layout props changed
            window_props = self._windows[name]["props"]
            layout_mode_str = window_props.get("layout_mode", "auto")
            anchor_str = window_props.get("anchor", "top_left")

            try:
                anchor = Anchor(anchor_str)
            except ValueError:
                anchor = Anchor.TOP_LEFT

            try:
                layout_mode = LayoutMode(layout_mode_str)
            except ValueError:
                layout_mode = LayoutMode.AUTO

            self._layout_manager.update_window(
                name,
                anchor=anchor,
                mode=layout_mode,
                priority=int(window_props.get("priority", 10)),
            )

        return self._windows[name]

    def _get_window(self, window_type: str, group: str) -> Dict:
        """Get a window state, or None if it doesn't exist."""
        name = self._get_window_name(window_type, group)
        return self._windows.get(name)

    def _destroy_window(self, name: str):
        """Destroy a window and clean up its resources."""
        if name not in self._windows:
            return

        state = self._windows[name]

        # Cleanup DIB
        if state.get("old_bitmap") and state.get("mem_dc"):
            try:
                gdi32.SelectObject(state["mem_dc"], state["old_bitmap"])
            except:
                pass
        if state.get("dib_bitmap"):
            try:
                gdi32.DeleteObject(state["dib_bitmap"])
            except:
                pass

        # Cleanup DCs
        if state.get("mem_dc"):
            try:
                gdi32.DeleteDC(state["mem_dc"])
            except:
                pass
        if state.get("window_dc") and state.get("hwnd"):
            try:
                user32.ReleaseDC(state["hwnd"], state["window_dc"])
            except:
                pass

        # Destroy window
        if state.get("hwnd"):
            try:
                user32.DestroyWindow(state["hwnd"])
            except:
                pass

        # Unregister from layout manager
        self._layout_manager.unregister_window(name)

        del self._windows[name]

    def _destroy_group_windows(self, group: str):
        """Destroy all windows for a group."""
        # Handle all unified windows (message, persistent, chat)
        # Chat windows use the group name as the chat name
        names_to_destroy = [
            name for name in self._windows if self._windows[name].get("group") == group
        ]
        for name in names_to_destroy:
            self._destroy_window(name)

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
                # Check if window is manually hidden
                is_hidden = win.get("hidden", False)

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
                is_hidden = pers_win.get("hidden", False)
                # Only blit if not hidden
                if not is_hidden:
                    msg_win = message_windows.get(group)
                    collision = self._check_window_collision(msg_win, pers_win)
                    self._update_persistent_fade(pers_win, collision)
                    self._blit_window(
                        self._get_window_name(self.WINDOW_TYPE_PERSISTENT, group),
                        pers_win,
                    )
            except Exception as e:
                self._report_exception(f"persistent_collision_{group}", e)

        # Third pass: Update ALL window positions from layout manager
        # This ensures windows reposition when others hide/show/resize
        self._update_all_window_positions()

    def _update_all_window_positions(self):
        """Update positions of all windows based on layout manager calculations."""
        # Force recompute positions
        positions = self._layout_manager.compute_positions(force=True)

        for name, win in self._windows.items():
            hwnd = win.get("hwnd")
            if not hwnd:
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
                    user32.MoveWindow(hwnd, x, y, w, h, True)  # True = repaint
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

        # Fade logic
        self._update_window_fade(win, has_content=bool(items))

    def _update_window_fade(self, win: Dict, has_content: bool):
        """Update fade animation for a window."""
        hwnd = win.get("hwnd")
        if not hwnd:
            return

        # If manually hidden, force has_content to False so fade out completes
        if win.get("hidden", False):
            has_content = False

        key = 0x00FF00FF
        fade_amount = int(1080 * self.dt)
        if fade_amount < 1:
            fade_amount = 1

        target = win.get("target_opacity", 216)
        old_fade_state = win["fade_state"]

        # Determine target state
        if has_content and win["fade_state"] in (0, 3):
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
            user32.SetLayeredWindowAttributes(
                hwnd, key, win["opacity"], LWA_ALPHA | LWA_COLORKEY
            )
            if win["opacity"] >= target:
                win["fade_state"] = 2

        elif win["fade_state"] == 3:  # Fade out
            win["opacity"] = max(0, win.get("opacity", 0) - fade_amount)
            user32.SetLayeredWindowAttributes(
                hwnd, key, win["opacity"], LWA_ALPHA | LWA_COLORKEY
            )
            if win["opacity"] <= 0:
                win["fade_state"] = 0
                # Update layout visibility when fully hidden
                self._layout_manager.set_window_visible(window_name, False)
                if win["type"] == self.WINDOW_TYPE_MESSAGE:
                    win["current_message"] = None

        elif win["fade_state"] == 2:  # Visible - maintain target opacity
            if win["opacity"] != target:
                if win["opacity"] < target:
                    win["opacity"] = min(target, win["opacity"] + fade_amount)
                else:
                    win["opacity"] = max(target, win["opacity"] - fade_amount)
                user32.SetLayeredWindowAttributes(
                    hwnd, key, win["opacity"], LWA_ALPHA | LWA_COLORKEY
                )

    def _draw_message_window(self, name: str, win: Dict):
        """Draw content for a message window."""
        current_message = win.get("current_message")
        is_loading = win.get("is_loading", False)

        if not current_message and not is_loading:
            # Clear render state and canvas when there's no content
            # This ensures old content doesn't persist
            if win.get("last_render_state") is not None:
                win["last_render_state"] = None
                win["canvas"] = None
                win["canvas_dirty"] = False
            return

        props = win.get("props", {})
        bg_rgba = self._parse_hex_color_with_alpha(props.get("bg_color", "#1e212b"))
        bg = bg_rgba[:3]  # RGB portion for compatibility
        bg_alpha = bg_rgba[3]  # Alpha channel from hex color
        text_color = self._hex_to_rgb(props.get("text_color", "#f0f0f0"))
        accent = self._hex_to_rgb(props.get("accent_color", "#00aaff"))

        width = int(props.get("width", 400))
        max_height = int(props.get("max_height", 600))
        radius = int(props.get("border_radius", 12))
        padding = int(props.get("content_padding", 16))

        # Build state hash for caching
        # Force repaint every frame while loading (animation needs continuous updates)
        if is_loading:
            # Use time-based state to force repaint each frame
            current_state = ("loading", time.time())
        else:
            try:
                # Include tools in state hash
                tools = current_message.get("tools", []) if current_message else []
                tools_hash = (
                    tuple((t.get("source", ""), t.get("name", "")) for t in tools)
                    if tools
                    else ()
                )

                msg_state = (
                    current_message.get("message", "") if current_message else "",
                    current_message.get("title", "") if current_message else "",
                    int(win.get("typewriter_char_count", 0)),
                    tools_hash,
                )
            except:
                msg_state = str(current_message)

            # Include visual props in state hash for real-time config updates
            visual_props_hash = (
                width,
                max_height,
                radius,
                padding,
                bg,
                text_color,
                accent,
                props.get("opacity", 0.85),
                props.get("font_size", 16),
                props.get("font_family", ""),
            )
            current_state = (msg_state, win.get("opacity", 0), visual_props_hash)

        if win.get("last_render_state") == current_state and win.get("canvas"):
            return

        win["last_render_state"] = current_state
        win["canvas_dirty"] = True

        # Ensure fonts for this window's font_family are loaded
        font_size = int(props.get("font_size", 16))
        font_family = props.get("font_family", "Segoe UI")
        window_fonts = self._load_fonts_for_size_and_family(font_size, font_family)

        # Always ensure renderer uses window's correct fonts (each window may have different font settings)
        colors = {"text": text_color, "accent": accent, "bg": bg}
        self.fonts = window_fonts  # Update global fonts to match window
        self.md_renderer = MarkdownRenderer(
            window_fonts, colors, props.get("color_emojis", True)
        )

        # Update renderer colors
        self.md_renderer.set_colors(text_color, accent, bg)

        # Create temp canvas
        temp_h = max_height + 500
        temp = Image.new("RGBA", (width, temp_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(temp)

        y = padding

        # Title
        if current_message:
            title = current_message.get("title", "")
            if title:
                title = self._strip_emotions(title)
                font_bold = self.fonts.get(
                    "bold", self.fonts.get("normal", self.fonts.get("regular"))
                )
                if font_bold:
                    # Use emoji-aware rendering for title
                    self._render_text_with_emoji(
                        draw,
                        title,
                        padding,
                        y,
                        accent + (255,),
                        font_bold,
                        emoji_y_offset=3,
                    )
                    try:
                        bbox = font_bold.getbbox(title)
                        y += bbox[3] - bbox[1] + 12
                    except:
                        y += 24

            # Message content with typewriter
            message = current_message.get("message", "")
            if message:
                message = self._strip_emotions(message)

                # Use max_chars for typewriter effect (don't truncate message directly)
                typewriter_active = win.get("typewriter_active", False)
                max_chars = (
                    int(win.get("typewriter_char_count", 0))
                    if typewriter_active
                    else None
                )

                # Use cached blocks if available and message hasn't changed
                cached = win.get("current_blocks")
                if cached is None or cached.get("msg") != message:
                    win["current_blocks"] = {
                        "msg": message,
                        "blocks": self.md_renderer.parse_blocks(message),
                    }
                    cached = win["current_blocks"]

                if self.md_renderer:
                    y = self.md_renderer.render(
                        draw,
                        temp,
                        message,
                        padding,
                        y,
                        width - padding * 2,
                        max_chars,
                        pre_parsed_blocks=cached["blocks"],
                    )

        # Tool chips - display skill/tool information
        if current_message:
            tools = current_message.get("tools", [])
            if tools:
                y += 10
                tx = padding
                th = 30

                # Group tools by source (skill/mcp name)
                counts = {}
                for t in tools:
                    key = (t.get("source", "System"), t.get("icon"))
                    counts[key] = counts.get(key, 0) + 1

                for (src, icon), cnt in counts.items():
                    font = self.fonts.get(
                        "code", self.fonts.get("normal", self.fonts.get("regular"))
                    )
                    sw, sh = self._get_text_size(src, font)
                    icon_w = 24 if icon and os.path.exists(str(icon)) else 0
                    badge_w = 26 if cnt > 1 else 0
                    chip_w = sw + icon_w + badge_w + 26

                    if tx + chip_w > width - padding:
                        tx = padding
                        y += th + 10

                    # Modern chip with subtle background
                    chip_bg = (42, 48, 60, 235)
                    draw.rounded_rectangle(
                        [tx, y, tx + chip_w, y + th],
                        radius=th // 2,
                        fill=chip_bg,
                        outline=accent,
                    )

                    ix = tx + 12
                    if icon and os.path.exists(str(icon)):
                        try:
                            if icon not in self.image_cache:
                                img = (
                                    Image.open(icon)
                                    .convert("RGBA")
                                    .resize((18, 18), Image.Resampling.LANCZOS)
                                )
                                self.image_cache[icon] = img
                            temp.paste(
                                self.image_cache[icon],
                                (ix, y + 6),
                                self.image_cache[icon],
                            )
                            ix += 22
                        except:
                            pass

                    draw.text((ix, y + (th - sh) // 2), src, fill=text_color, font=font)

                    # Badge for multiple tool calls from same source
                    if cnt > 1:
                        bw, bh = self._get_text_size(str(cnt), font)
                        bx = tx + chip_w - bw - 16
                        draw.ellipse(
                            [bx - 4, y + 5, bx + bw + 8, y + th - 5], fill=accent
                        )
                        draw.text((bx + 2, y + 7), str(cnt), fill=bg, font=font)

                    tx += chip_w + 10

                y += th + 10

        # Loading animation
        if win.get("is_loading"):
            y += 6
            loading_color = win.get("loading_color", (0, 170, 255))
            self._draw_loading(
                draw, temp, padding, y, width - padding * 2, loading_color
            )
            y += 24

        # Loading animation - reserve 30px at bottom when loading
        loader_space = 30 if win.get("is_loading") else 0

        # Calculate final height - use fixed height if specified
        fixed_height = props.get("height")
        bottom_padding = padding - 4
        if fixed_height is not None:
            final_h = int(fixed_height)
        else:
            # Calculate content height without loader space reservation
            # (loader is already included in y, we just need to cap at max_height)
            final_h = min(max(60, y + bottom_padding), max_height)

        # Determine if content is clipped (overflows the final window height)
        content_clipped = y > final_h

        # Create final canvas - ALWAYS create fresh to prevent ghosting
        old_canvas = win.get("canvas")
        if (
            old_canvas is None
            or old_canvas.width != width
            or old_canvas.height != final_h
        ):
            canvas = Image.new("RGBA", (width, final_h), (255, 0, 255, 255))
            win["canvas"] = canvas
        else:
            canvas = old_canvas
            # Completely clear the canvas with magenta (transparency key)
            # Use a new image to ensure complete overwrite
            canvas.paste(
                Image.new("RGBA", (width, final_h), (255, 0, 255, 255)), (0, 0)
            )

        final_draw = ImageDraw.Draw(canvas)
        # Draw solid background first (covers everything)
        final_draw.rectangle([0, 0, width, final_h], fill=(255, 0, 255, 255))
        # Then draw the rounded rectangle on top with user-specified alpha
        final_draw.rounded_rectangle(
            [0, 0, width - 1, final_h - 1],
            radius=radius,
            fill=bg + (bg_alpha,),
            outline=(55, 62, 74),
        )

        # Crop content - show bottom portion when clipped (newest content), top when fits
        if content_clipped:
            # Content overflows - crop from bottom to show newest content
            # Account for loader space: ensure loader is within visible area
            crop_top = max(0, y - final_h)
            crop = temp.crop((0, crop_top, width, crop_top + final_h))
        else:
            # Content fits - crop from top
            crop = temp.crop((0, 0, width, min(final_h, temp.height)))

        # Composite the text onto the background properly
        # Use Image.alpha_composite to blend correctly without leaving ghost pixels
        # First, create a version of the canvas portion and composite
        canvas_region = canvas.crop((0, 0, width, final_h))
        composited = Image.alpha_composite(canvas_region, crop)
        canvas.paste(composited, (0, 0))

        # Apply fade gradient at top when content is clipped to indicate more content above
        if content_clipped:
            fade_height = int(props.get("scroll_fade_height", 40))
            if fade_height > 0:
                # Fade at top to indicate more content above
                top_region = canvas.crop((0, 0, width, fade_height))

                # Create a mask identifying magenta (color key) pixels to preserve rounded corners
                top_data = top_region.load()
                corner_mask = Image.new("L", (width, fade_height), 0)
                corner_mask_data = corner_mask.load()
                for py in range(fade_height):
                    for px in range(width):
                        r, g, b, a = top_data[px, py]
                        # Check if pixel is magenta (color key for transparency)
                        if r == 255 and g == 0 and b == 255:
                            corner_mask_data[px, py] = 255  # Mark as corner pixel

                # Create a gradient mask that fades from opaque bg at top to transparent at bottom
                gradient = Image.new("L", (width, fade_height), 0)
                for fade_y in range(fade_height):
                    # Fade: 255 (full bg) at top, 0 (no bg) at bottom
                    alpha = int(255 * (1.0 - fade_y / fade_height))
                    ImageDraw.Draw(gradient).line(
                        [(0, fade_y), (width, fade_y)], fill=alpha
                    )

                # Create background layer for fade
                bg_layer = Image.new("RGBA", (width, fade_height), bg + (255,))

                # Apply gradient as alpha to bg layer
                bg_layer.putalpha(gradient)

                # Composite fade over content
                faded_top = Image.alpha_composite(top_region, bg_layer)

                # Restore magenta pixels for corners (color key transparency)
                faded_data = faded_top.load()
                for py in range(fade_height):
                    for px in range(width):
                        if corner_mask_data[px, py] == 255:
                            faded_data[px, py] = (255, 0, 255, 255)

                canvas.paste(faded_top, (0, 0))

        # Update layout manager with new height and get position
        self._layout_manager.update_window_height(name, final_h)

        # Get position from layout manager
        pos = self._layout_manager.get_position(name)

        hwnd = win.get("hwnd")
        if hwnd:
            if pos:
                x, y_pos = pos
            else:
                # Fallback to props
                x = int(props.get("x", 20))
                y_pos = int(props.get("y", 20))
            user32.MoveWindow(hwnd, x, y_pos, width, final_h, True)

    def _draw_persistent_window(self, name: str, win: Dict):
        """Draw content for a persistent window."""
        items = win.get("items", {})
        if not items:
            # Clear render state and canvas when there are no items
            # This ensures old content doesn't persist
            if win.get("last_render_state") is not None:
                win["last_render_state"] = None
                win["canvas"] = None
                win["canvas_dirty"] = False
            return

        props = win.get("props", {})
        bg_rgba = self._parse_hex_color_with_alpha(props.get("bg_color", "#1e212b"))
        bg = bg_rgba[:3]  # RGB portion for compatibility
        bg_alpha = bg_rgba[3]  # Alpha channel from hex color
        text_color = self._hex_to_rgb(props.get("text_color", "#f0f0f0"))
        accent = self._hex_to_rgb(props.get("accent_color", "#00aaff"))

        width = int(props.get("width", 300))
        max_height = int(props.get("max_height", 600))
        radius = int(props.get("border_radius", 12))
        padding = int(props.get("content_padding", 16))

        # State hash for caching - include visual props so config changes trigger re-render
        now = time.time()
        progress_anims = win.get("progress_animations", {})

        items_state = []
        for title, info in sorted(items.items()):
            if title in progress_anims:
                items_state.append((title, progress_anims[title].get("current", 0)))
            else:
                items_state.append((title, info.get("description", "")))

        # Include visual props in state hash for real-time config updates
        visual_props_hash = (
            width,
            max_height,
            radius,
            padding,
            bg,
            bg_alpha,
            text_color,
            accent,
            props.get("opacity", 0.85),
            props.get("font_size", 16),
            props.get("font_family", ""),
        )
        current_state = (tuple(items_state), int(now), visual_props_hash)

        last_state = win.get("last_render_state")
        cache_hit = last_state == current_state and win.get("canvas")

        if cache_hit:
            return

        win["last_render_state"] = current_state
        win["canvas_dirty"] = True

        # Ensure fonts for this window's font_family are loaded
        font_size = int(props.get("font_size", 16))
        font_family = props.get("font_family", "Segoe UI")
        window_fonts = self._load_fonts_for_size_and_family(font_size, font_family)

        # Always ensure renderer uses window's correct fonts (each window may have different font settings)
        colors = {"text": text_color, "accent": accent, "bg": bg}
        self.fonts = window_fonts  # Update global fonts to match window
        self.md_renderer = MarkdownRenderer(
            window_fonts, colors, props.get("color_emojis", True)
        )

        self.md_renderer.set_colors(text_color, accent, bg)

        # Create temp canvas
        temp = Image.new("RGBA", (width, 2000), (0, 0, 0, 0))
        draw = ImageDraw.Draw(temp)

        y = padding
        font_bold = self.fonts.get(
            "bold", self.fonts.get("normal", self.fonts.get("regular"))
        )
        font_normal = self.fonts.get("normal", self.fonts.get("regular"))
        now = time.time()

        for title, info in sorted(items.items(), key=lambda x: x[1].get("added_at", 0)):
            # Check expiry but don't delete (logic does that)
            if info.get("expiry") and now > info["expiry"]:
                continue

            # Calculate timer width/draw timer for expiry OR progress timer
            timer_w = 0
            timer_text = None

            # For progress items with timer, calculate remaining time
            if info.get("is_progress") and info.get("is_timer"):
                timer_start = info.get("timer_start", now)
                timer_duration = info.get("timer_duration", 0)
                elapsed_time = now - timer_start
                remaining_seconds = max(0, timer_duration - elapsed_time)
                remaining = int(remaining_seconds + 0.999)

                r = remaining
                d = r // 86400
                r %= 86400
                h = r // 3600
                r %= 3600
                m = r // 60
                s = r % 60

                parts = []
                if d > 0:
                    parts.append(f"{d}d")
                if h > 0:
                    parts.append(f"{h}h")
                if m > 0:
                    parts.append(f"{m}m")
                parts.append(f"{s}s")

                timer_text = " ".join(parts)
            elif info.get("expiry"):
                remaining = max(0, int(info["expiry"] - now + 0.999))
                r = remaining
                d = r // 86400
                r %= 86400
                h = r // 3600
                r %= 3600
                m = r // 60
                s = r % 60

                parts = []
                if d > 0:
                    parts.append(f"{d}d")
                if h > 0:
                    parts.append(f"{h}h")
                if m > 0:
                    parts.append(f"{m}m")
                parts.append(f"{s}s")

                timer_text = " ".join(parts)

            # Draw timer text on the right side
            if timer_text and font_bold:
                timer_w, _ = self._get_text_size(timer_text, font_bold)
                draw.text(
                    (width - padding - timer_w, y),
                    timer_text,
                    fill=text_color + (255,),
                    font=font_bold,
                )
                timer_w += 10

            # Title - render with emoji support (account for timer width)
            title_text = info.get("title", title)
            max_title_w = width - (padding * 2) - timer_w
            if font_bold:
                self._render_text_with_emoji(
                    draw,
                    title_text,
                    padding,
                    y,
                    accent + (255,),
                    font_bold,
                    emoji_y_offset=3,
                )
                # Calculate proper spacing based on font height instead of hardcoded value
                try:
                    bbox = font_bold.getbbox(title_text)
                    title_h = bbox[3] - bbox[1]
                except:
                    title_h = font_size
                # Add spacing: title height + padding (0.625x of title height for adequate breathing room)
                y += title_h + max(10, int(title_h * 0.625))
            else:
                y += 22  # Fallback if no font

            # Progress bar
            if info.get("is_progress"):
                progress_max = float(info.get("progress_maximum", 100))
                if title in progress_anims:
                    progress_current = progress_anims[title].get("current", 0)
                else:
                    progress_current = float(info.get("progress_current", 0))

                if progress_max <= 0:
                    progress_max = 100
                percentage = min(100, max(0, (progress_current / progress_max) * 100))

                progress_color = accent
                if info.get("progress_color"):
                    progress_color = self._hex_to_rgb(info["progress_color"])

                bar_width = width - padding * 2
                bar_height = 16
                y += 4

                # Draw progress bar using existing method
                y = self._draw_progress_bar(
                    draw,
                    temp,
                    padding,
                    y,
                    bar_width,
                    bar_height,
                    percentage,
                    bg,
                    progress_color,
                    text_color,
                )

                # Percentage text
                if font_normal:
                    pct_text = f"{percentage:.0f}%"
                    try:
                        bbox = font_normal.getbbox(pct_text)
                        pct_w = bbox[2] - bbox[0]
                        pct_h = bbox[3] - bbox[1]
                    except:
                        pct_w = len(pct_text) * 7
                        pct_h = font_size
                    pct_x = padding + (bar_width - pct_w) // 2
                    draw.text(
                        (pct_x, y), pct_text, fill=text_color + (200,), font=font_normal
                    )
                    # Scale spacing based on font size (1.25x for spacing) plus small additional padding
                    y += int(pct_h * 1.25) + 4

            # Description
            desc = info.get("description", "")
            if desc:
                desc = self._strip_emotions(desc)
                if self.md_renderer:
                    y = self.md_renderer.render(
                        draw, temp, desc, padding, y, width - padding * 2
                    )

            y += 8

        # Finalize canvas
        bottom_padding = padding - 4
        # Calculate final height - constrain to max_height if content exceeds it
        calculated_height = max(60, y + bottom_padding)
        final_h = min(calculated_height, max_height)

        # Determine if content is clipped (overflows the final window height)
        content_clipped = y > final_h

        # Create final canvas - ALWAYS create fresh to prevent ghosting
        old_canvas = win.get("canvas")
        if (
            old_canvas is None
            or old_canvas.width != width
            or old_canvas.height != final_h
        ):
            canvas = Image.new("RGBA", (width, final_h), (255, 0, 255, 255))
            win["canvas"] = canvas
        else:
            canvas = old_canvas
            # Completely clear the canvas with magenta (transparency key)
            canvas.paste(
                Image.new("RGBA", (width, final_h), (255, 0, 255, 255)), (0, 0)
            )

        final_draw = ImageDraw.Draw(canvas)
        # Draw solid background first (covers everything)
        final_draw.rectangle([0, 0, width, final_h], fill=(255, 0, 255, 255))
        # Then draw the rounded rectangle on top with user-specified alpha
        final_draw.rounded_rectangle(
            [0, 0, width - 1, final_h - 1],
            radius=radius,
            fill=bg + (bg_alpha,),
            outline=(55, 62, 74),
        )

        crop = temp.crop((0, 0, width, final_h))
        # Composite the content onto the background properly
        canvas_region = canvas.crop((0, 0, width, final_h))
        composited = Image.alpha_composite(canvas_region, crop)
        canvas.paste(composited, (0, 0))

        # Apply fade gradient at top when content is clipped to indicate more content above
        if content_clipped:
            fade_height = int(props.get("scroll_fade_height", 40))
            if fade_height > 0:
                # Get the top portion of the canvas before applying fade
                top_region = canvas.crop((0, 0, width, fade_height))

                # Create a mask identifying magenta (color key) pixels to preserve rounded corners
                # Magenta = (255, 0, 255) is used as transparency color key
                top_data = top_region.load()
                corner_mask = Image.new("L", (width, fade_height), 0)
                corner_mask_data = corner_mask.load()
                for py in range(fade_height):
                    for px in range(width):
                        r, g, b, a = top_data[px, py]
                        # Check if pixel is magenta (color key for transparency)
                        if r == 255 and g == 0 and b == 255:
                            corner_mask_data[px, py] = 255  # Mark as corner pixel

                # Create a gradient mask that fades from opaque bg at top to transparent at bottom
                gradient = Image.new("L", (width, fade_height), 0)
                for fade_y in range(fade_height):
                    # Fade: 255 (full bg) at top, 0 (no bg) at bottom
                    alpha = int(255 * (1.0 - fade_y / fade_height))
                    ImageDraw.Draw(gradient).line(
                        [(0, fade_y), (width, fade_y)], fill=alpha
                    )

                # Create background layer for fade
                bg_layer = Image.new("RGBA", (width, fade_height), bg + (255,))

                # Apply gradient as alpha to bg layer
                bg_layer.putalpha(gradient)

                # Composite fade over content
                faded_top = Image.alpha_composite(top_region, bg_layer)

                # Restore magenta pixels for corners (color key transparency)
                faded_data = faded_top.load()
                for py in range(fade_height):
                    for px in range(width):
                        if corner_mask_data[px, py] == 255:
                            faded_data[px, py] = (255, 0, 255, 255)

                canvas.paste(faded_top, (0, 0))

        # Apply fade gradient at bottom when content is clipped to indicate more content below
        if content_clipped:
            fade_height = int(props.get("scroll_fade_height", 40))
            if fade_height > 0:
                # Get the bottom portion of the canvas
                fade_y = max(0, final_h - fade_height)
                fade_actual = min(fade_height, final_h - fade_y)
                if fade_actual > 0:
                    bottom_region = canvas.crop(
                        (0, fade_y, width, fade_y + fade_actual)
                    )

                    # Create a mask identifying magenta (color key) pixels to preserve rounded corners
                    bottom_data = bottom_region.load()
                    corner_mask = Image.new("L", (width, fade_actual), 0)
                    corner_mask_data = corner_mask.load()
                    for py in range(fade_actual):
                        for px in range(width):
                            r, g, b, a = bottom_data[px, py]
                            # Check if pixel is magenta (color key for transparency)
                            if r == 255 and g == 0 and b == 255:
                                corner_mask_data[px, py] = 255  # Mark as corner pixel

                    # Create a gradient mask that fades from transparent at bottom to opaque at top
                    gradient = Image.new("L", (width, fade_actual), 0)
                    for fade_y_idx in range(fade_actual):
                        # Fade: 0 (transparent) at bottom, 255 (opaque) at top of fade region
                        alpha = int(255 * fade_y_idx / fade_actual)
                        ImageDraw.Draw(gradient).line(
                            [(0, fade_y_idx), (width, fade_y_idx)], fill=alpha
                        )

                    # Create background layer for fade
                    bg_layer = Image.new("RGBA", (width, fade_actual), bg + (255,))

                    # Apply gradient as alpha to bg layer
                    bg_layer.putalpha(gradient)

                    # Composite fade over content
                    faded_bottom = Image.alpha_composite(bottom_region, bg_layer)

                    # Restore magenta pixels for corners (color key transparency)
                    faded_data = faded_bottom.load()
                    for py in range(fade_actual):
                        for px in range(width):
                            if corner_mask_data[px, py] == 255:
                                faded_data[px, py] = (255, 0, 255, 255)

                    canvas.paste(faded_bottom, (0, fade_y))

        # Update layout manager with new height and get position
        self._layout_manager.update_window_height(name, final_h)

        # Get position from layout manager
        pos = self._layout_manager.get_position(name)

        hwnd = win.get("hwnd")
        if hwnd:
            if pos:
                x, y_pos = pos
            else:
                # Fallback to props
                x = int(props.get("x", 20))
                y_pos = int(props.get("y", 20))
            user32.MoveWindow(hwnd, x, y_pos, width, final_h, True)

    def _update_chat_window(self, name: str, win: Dict):
        """Update chat window state (fade logic and auto-hide)."""
        now = time.time()
        props = win.get("props", {})
        auto_hide = props.get("auto_hide", False)
        auto_hide_delay = props.get("auto_hide_delay", 10.0)

        # Check auto-hide
        if auto_hide and win.get("messages") and win["fade_state"] == 2:
            if now - win.get("last_message_time", 0) > auto_hide_delay:
                win["fade_state"] = 3  # Start fade out

        # Use common fade logic with messages as content indicator
        has_content = bool(win.get("messages")) or win.get("visible", False)
        self._update_window_fade(win, has_content=has_content)

    def _draw_chat_window(self, name: str, win: Dict):
        """Draw content for a chat window."""
        messages = win.get("messages", [])
        if not messages:
            # Clear render state and canvas when there are no messages
            if win.get("last_render_state") is not None:
                win["last_render_state"] = None
                win["canvas"] = None
                win["canvas_dirty"] = False
            return

        props = win.get("props", {})
        bg_rgba = self._parse_hex_color_with_alpha(props.get("bg_color", "#1e212b"))
        bg = bg_rgba[:3]  # RGB portion for compatibility
        bg_alpha = bg_rgba[3]  # Alpha channel from hex color
        text_color = self._hex_to_rgb(props.get("text_color", "#f0f0f0"))
        accent = self._hex_to_rgb(props.get("accent_color", "#00aaff"))

        width = int(props.get("width", 400))
        max_height = int(props.get("max_height", 400))
        radius = int(props.get("border_radius", 12))
        padding = int(props.get("content_padding", 12))
        message_spacing = int(props.get("message_spacing", 8))
        fade_old = props.get("fade_old_messages", True)
        sender_colors = props.get("sender_colors", {})
        scroll_fade_height = int(props.get("scroll_fade_height", 40))
        color_emojis = props.get("color_emojis", True)

        # Build state hash for caching
        msg_state = tuple(
            (m["sender"], m["text"], m.get("color")) for m in messages[-50:]
        )
        props_hash = (
            width,
            max_height,
            radius,
            padding,
            bg,
            bg_alpha,
            text_color,
            accent,
            props.get("opacity", 0.85),
            props.get("font_size", 14),
            message_spacing,
            fade_old,
            scroll_fade_height,
            color_emojis,
        )
        current_state = (msg_state, win.get("opacity", 0), props_hash)

        if win.get("last_render_state") == current_state and win.get("canvas"):
            return

        win["last_render_state"] = current_state
        win["canvas_dirty"] = True

        # Ensure fonts for this window's font_family are loaded
        font_size = int(props.get("font_size", 14))
        font_family = props.get("font_family", "Segoe UI")
        window_fonts = self._load_fonts_for_size_and_family(font_size, font_family)

        # Always ensure renderer uses window's correct fonts
        colors = {"text": text_color, "accent": accent, "bg": bg}
        self.fonts = window_fonts  # Update global fonts to match window
        self.md_renderer = MarkdownRenderer(window_fonts, colors, color_emojis)

        # Get fonts
        font_bold = self.fonts.get(
            "bold", self.fonts.get("normal", self.fonts.get("regular"))
        )
        font_normal = self.fonts.get("normal", self.fonts.get("regular"))

        # Render messages to temp canvas
        temp_h = max(2000, max_height * 3)
        temp = Image.new("RGBA", (width, temp_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(temp)

        content_width = width - (padding * 2)
        y = padding

        # Render each message
        for i, msg in enumerate(messages):
            # Apply fade to older messages
            if fade_old and i < len(messages) - 3:
                # Fade factor: older = more faded
                position_from_end = len(messages) - i
                fade_factor = max(0.3, 1.0 - (position_from_end * 0.05))
                msg_alpha = int(255 * fade_factor)
            else:
                msg_alpha = 255

            sender = msg.get("sender", "")
            text = msg.get("text", "")
            msg_color = msg.get("color")

            # Determine sender color
            if msg_color:
                sender_color = (
                    self._hex_to_rgb(msg_color)
                    if isinstance(msg_color, str)
                    else msg_color
                )
            elif sender in sender_colors:
                sender_color = (
                    self._hex_to_rgb(sender_colors[sender])
                    if isinstance(sender_colors[sender], str)
                    else sender_colors[sender]
                )
            else:
                sender_color = accent

            # Draw sender name with emoji support
            if sender:
                if font_bold:
                    sender_text = sender + ":"
                    if color_emojis and self.md_renderer:
                        # Use emoji-aware rendering for proper emoji display
                        self._render_text_with_emoji(
                            draw,
                            sender_text,
                            padding,
                            y,
                            sender_color + (msg_alpha,),
                            font_bold,
                            emoji_y_offset=0,
                        )
                    else:
                        draw.text(
                            (padding, y),
                            sender_text,
                            fill=sender_color + (msg_alpha,),
                            font=font_bold,
                        )
                    try:
                        bbox = font_bold.getbbox(sender_text)
                        y += bbox[3] - bbox[1] + 4
                    except:
                        y += 20

            # Draw message text with markdown
            if text and self.md_renderer:
                y = self.md_renderer.render(
                    draw, temp, text, padding, y, content_width, max_chars=None
                )
            elif text and font_normal:
                # Fallback simple text rendering with emoji support
                if color_emojis and self.md_renderer:
                    self._render_text_with_emoji(
                        draw,
                        text,
                        padding,
                        y,
                        text_color + (msg_alpha,),
                        font_normal,
                        emoji_y_offset=0,
                    )
                else:
                    draw.text(
                        (padding, y),
                        text,
                        fill=text_color + (msg_alpha,),
                        font=font_normal,
                    )
                try:
                    lines = text.split("\n")
                    for line in lines:
                        bbox = font_normal.getbbox(line)
                        y += bbox[3] - bbox[1] + 4
                except:
                    y += len(text.split("\n")) * 20

            y += message_spacing

        # Calculate final height
        bottom_padding = padding - 4
        total_content_height = y + bottom_padding
        final_h = min(max(60, total_content_height), max_height)

        # Determine if content is clipped (needs scroll)
        content_clipped = total_content_height > max_height

        # Create final canvas
        old_canvas = win.get("canvas")
        if (
            old_canvas is None
            or old_canvas.width != width
            or old_canvas.height != final_h
        ):
            canvas = Image.new("RGBA", (width, final_h), (255, 0, 255, 255))
            win["canvas"] = canvas
        else:
            canvas = old_canvas
            canvas.paste(
                Image.new("RGBA", (width, final_h), (255, 0, 255, 255)), (0, 0)
            )

        final_draw = ImageDraw.Draw(canvas)
        final_draw.rectangle([0, 0, width, final_h], fill=(255, 0, 255, 255))
        final_draw.rounded_rectangle(
            [0, 0, width - 1, final_h - 1],
            radius=radius,
            fill=bg + (bg_alpha,),
            outline=(55, 62, 74),
        )

        # Composite content - scroll to bottom (show newest messages)
        if content_clipped:
            # Content is taller than max_height, crop from bottom to show newest messages
            crop_top = total_content_height - final_h
            crop = temp.crop((0, crop_top, width, crop_top + final_h))
        else:
            # Content fits, crop from top
            crop = temp.crop((0, 0, width, min(final_h, temp.height)))

        canvas_region = canvas.crop((0, 0, width, min(final_h, canvas.height)))
        composited = Image.alpha_composite(canvas_region, crop)
        canvas.paste(composited, (0, 0))

        # Apply fade gradient at top when content is clipped to indicate more content above
        if content_clipped:
            fade_height = int(props.get("scroll_fade_height", 40))
            if fade_height > 0:
                # Get the top portion of the canvas before applying fade
                top_region = canvas.crop((0, 0, width, fade_height))

                # Create a mask identifying magenta (color key) pixels to preserve rounded corners
                # Magenta = (255, 0, 255) is used as transparency color key
                top_data = top_region.load()
                corner_mask = Image.new("L", (width, fade_height), 0)
                corner_mask_data = corner_mask.load()
                for py in range(fade_height):
                    for px in range(width):
                        r, g, b, a = top_data[px, py]
                        # Check if pixel is magenta (color key for transparency)
                        if r == 255 and g == 0 and b == 255:
                            corner_mask_data[px, py] = 255  # Mark as corner pixel

                # Create a gradient mask that fades from opaque bg at top to transparent at bottom
                gradient = Image.new("L", (width, fade_height), 0)
                for fade_y in range(fade_height):
                    # Fade: 255 (full bg) at top, 0 (no bg) at bottom
                    alpha = int(255 * (1.0 - fade_y / fade_height))
                    ImageDraw.Draw(gradient).line(
                        [(0, fade_y), (width, fade_y)], fill=alpha
                    )

                # Create background layer for fade
                bg_layer = Image.new("RGBA", (width, fade_height), bg + (255,))

                # Apply gradient as alpha to bg layer
                bg_layer.putalpha(gradient)

                # Composite fade over content
                faded_top = Image.alpha_composite(top_region, bg_layer)

                # Restore magenta pixels for corners (color key transparency)
                faded_data = faded_top.load()
                for py in range(fade_height):
                    for px in range(width):
                        if corner_mask_data[px, py] == 255:
                            faded_data[px, py] = (255, 0, 255, 255)

                canvas.paste(faded_top, (0, 0))

        # Update layout manager and position
        self._layout_manager.update_window_height(name, final_h)
        pos = self._layout_manager.get_position(name)

        hwnd = win.get("hwnd")
        if hwnd:
            if pos:
                x, y_pos = pos
            else:
                x = int(props.get("x", 20))
                y_pos = int(props.get("y", 20))
            user32.MoveWindow(hwnd, x, y_pos, width, final_h, True)

    def _blit_window(self, name: str, win: Dict):
        """Blit a window's canvas to its Win32 window."""
        if win.get("opacity", 0) <= 0:
            return
        if not win.get("canvas_dirty", False):
            return

        canvas = win.get("canvas")
        hwnd = win.get("hwnd")
        window_dc = win.get("window_dc")
        mem_dc = win.get("mem_dc")

        if not all([canvas, hwnd, window_dc, mem_dc]):
            return

        w, h = canvas.size

        # Check if DIB needs resize
        if w != win.get("dib_width", 0) or h != win.get("dib_height", 0):
            # Cleanup old DIB
            if win.get("old_bitmap"):
                gdi32.SelectObject(mem_dc, win["old_bitmap"])
            if win.get("dib_bitmap"):
                gdi32.DeleteObject(win["dib_bitmap"])

            # Create new DIB
            win["dib_width"] = w
            win["dib_height"] = h
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = w
            bmi.bmiHeader.biHeight = -h  # Top-down
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = BI_RGB

            dib_bits = ctypes.c_void_p()
            dib_bitmap = gdi32.CreateDIBSection(
                mem_dc,
                ctypes.byref(bmi),
                DIB_RGB_COLORS,
                ctypes.byref(dib_bits),
                None,
                0,
            )
            if dib_bitmap:
                win["old_bitmap"] = gdi32.SelectObject(mem_dc, dib_bitmap)
                win["dib_bitmap"] = dib_bitmap
                win["dib_bits"] = dib_bits

        dib_bits = win.get("dib_bits")
        if not dib_bits:
            return

        try:
            rgba = canvas.tobytes("raw", "BGRA")
            # Clear the entire DIB buffer first to prevent any ghosting
            buffer_size = w * h * 4
            # Overwrite entire buffer with new content
            ctypes.memmove(dib_bits, rgba, buffer_size)
            gdi32.BitBlt(window_dc, 0, 0, w, h, mem_dc, 0, 0, SRCCOPY)
            win["canvas_dirty"] = False
        except Exception as e:
            pass

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

        # Map font family names to Windows font files
        font_map = {
            "segoe ui": {
                "normal": "segoeuisl.ttf",
                "bold": "segoeuib.ttf",
                "italic": "segoeuii.ttf",
                "bold_italic": "segoeuiz.ttf",
            },
            "arial": {
                "normal": "arial.ttf",
                "bold": "arialbd.ttf",
                "italic": "ariali.ttf",
                "bold_italic": "arialbi.ttf",
            },
            "verdana": {
                "normal": "verdana.ttf",
                "bold": "verdanab.ttf",
                "italic": "verdanai.ttf",
                "bold_italic": "verdanaz.ttf",
            },
            "tahoma": {
                "normal": "tahoma.ttf",
                "bold": "tahomabd.ttf",
                "italic": "tahoma.ttf",
                "bold_italic": "tahomabd.ttf",
            },
            "trebuchet ms": {
                "normal": "trebuc.ttf",
                "bold": "trebucbd.ttf",
                "italic": "trebucit.ttf",
                "bold_italic": "trebucbi.ttf",
            },
            "calibri": {
                "normal": "calibri.ttf",
                "bold": "calibrib.ttf",
                "italic": "calibrii.ttf",
                "bold_italic": "calibriz.ttf",
            },
            "consolas": {
                "normal": "consola.ttf",
                "bold": "consolab.ttf",
                "italic": "consolai.ttf",
                "bold_italic": "consolaz.ttf",
            },
            "courier new": {
                "normal": "cour.ttf",
                "bold": "courbd.ttf",
                "italic": "couri.ttf",
                "bold_italic": "courbi.ttf",
            },
        }

        family_lower = family.lower()
        font_files = font_map.get(family_lower, font_map["segoe ui"])
        fonts_dir = "C:/Windows/Fonts/"

        pil_size = size
        pil_code_size = max(1, size - 1)  # Code font slightly smaller, but at least 1

        # Load emoji fonts
        emoji_font = None
        emoji_font_paths = [
            fonts_dir + "seguiemj.ttf",
            fonts_dir + "seguisym.ttf",
        ]
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

        # Try to load fonts from Windows fonts directory
        try:
            fonts_dict = {
                "normal": ImageFont.truetype(
                    fonts_dir + font_files["normal"], pil_size
                ),
                "bold": ImageFont.truetype(fonts_dir + font_files["bold"], pil_size),
                "italic": ImageFont.truetype(
                    fonts_dir + font_files["italic"], pil_size
                ),
                "bold_italic": ImageFont.truetype(
                    fonts_dir + font_files["bold_italic"], pil_size
                ),
                "code": ImageFont.truetype(fonts_dir + "consola.ttf", pil_code_size),
                "h1": ImageFont.truetype(fonts_dir + font_files["bold"], pil_size + 10),
                "h2": ImageFont.truetype(fonts_dir + font_files["bold"], pil_size + 6),
                "h3": ImageFont.truetype(fonts_dir + font_files["bold"], pil_size + 3),
                "h4": ImageFont.truetype(fonts_dir + font_files["bold"], pil_size + 1),
                "h5": ImageFont.truetype(fonts_dir + font_files["bold"], pil_size),
                "h6": ImageFont.truetype(
                    fonts_dir + font_files["bold_italic"], pil_size - 1
                ),
                "header": ImageFont.truetype(
                    fonts_dir + font_files["bold"], pil_size + 4
                ),
                "emoji": (
                    emoji_font
                    if emoji_font
                    else ImageFont.truetype(fonts_dir + font_files["normal"], pil_size)
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

    def _init_fonts(self, font_size: int = None, font_family: str = None):
        """Initialize fonts for rendering.

        Args:
            font_size: Font size in pixels. Defaults to value from _default_props (16).
            font_family: Font family name. Defaults to value from _default_props ('Segoe UI').
        """
        size = (
            font_size
            if font_size is not None
            else int(self._default_props.get("font_size", 16))
        )
        family = (
            font_family
            if font_family is not None
            else self._default_props.get("font_family", "Segoe UI")
        )

        # Load fonts using the cache
        self.fonts = self._load_fonts_for_size_and_family(size, family)

        colors = {
            "text": self._hex_to_rgb(self._default_props.get("text_color", "#f0f0f0")),
            "accent": self._hex_to_rgb(
                self._default_props.get("accent_color", "#00aaff")
            ),
            "bg": self._hex_to_rgb(self._default_props.get("bg_color", "#1e212b")),
        }
        color_emojis = self._default_props.get("color_emojis", True)
        self.md_renderer = MarkdownRenderer(self.fonts, colors, color_emojis)

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
            self._render_stats["loading_cache_hits"] += 1
            return self._loading_bar_cache[cache_key]

        self._render_stats["loading_cache_misses"] += 1

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

    def _cleanup_chat_window(self, chat_name: str):
        """Clean up resources for a specific chat window."""
        window_name = f"chat_{chat_name}"

        # Unregister from layout manager
        self._layout_manager.unregister_window(window_name)

        # Clean up unified window if it exists
        if window_name in self._windows:
            self._destroy_window(window_name)

    def _safe_report(self, payload):
        if not self.error_queue:
            return
        try:
            self.error_queue.put_nowait(payload)
        except Exception:
            pass

    def _emit_heartbeat(self):
        now = time.time()
        if now >= self._next_heartbeat:
            self._next_heartbeat = now + 1.0
            self._safe_report({"type": "heartbeat", "ts": now})

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

        # Get message window rect
        msg_props = msg_win.get("props", {})
        msg_x = int(msg_props.get("x", 20))
        msg_y = int(msg_props.get("y", 20))
        msg_w = int(msg_props.get("width", 400))
        msg_canvas = msg_win.get("canvas")
        msg_h = msg_canvas.height if msg_canvas else 200

        # Get persistent window rect
        pers_props = pers_win.get("props", {})
        pers_x = int(pers_props.get("x", pers_props.get("x", 20)))
        pers_y = int(pers_props.get("y", pers_props.get("y", 300)))
        pers_w = int(pers_props.get("width", pers_props.get("width", 400)))
        pers_canvas = pers_win.get("canvas")
        pers_h = pers_canvas.height if pers_canvas else 200

        # Check intersection (AABB test)
        return not (
            msg_x + msg_w <= pers_x
            or pers_x + pers_w <= msg_x
            or msg_y + msg_h <= pers_y
            or pers_y + pers_h <= msg_y
        )

    def _update_persistent_fade(self, win: Dict, collision_detected: bool = False):
        """Update persistent window fade based on content and collision."""
        items = win.get("items", {})
        has_content = bool(items)

        # If collision detected, force hide
        should_show = has_content and not collision_detected

        fade_state = win.get("fade_state", 0)

        if should_show and fade_state in (0, 3):
            win["fade_state"] = 1  # Start fade in
        elif not should_show and fade_state in (1, 2):
            win["fade_state"] = 3  # Start fade out

    def run(self):
        try:
            if not PIL_AVAILABLE:
                self._report_exception("init", ImportError("PIL not available"))
                return

            if self.use_stdin:
                threading.Thread(target=self._read_stdin, daemon=True).start()

            if not _ensure_window_class():
                self._report_exception(
                    "init", RuntimeError("Failed to register window class")
                )
                return

            self._init_fonts()

            self.last_update_time = time.time()

            # Install WinEvent hook for reactive foreground monitoring.
            # The callback fires only when a different window becomes the foreground
            # window, so we re-apply topmost to all HUD windows only when needed.
            self._install_foreground_hook()

            # Signal successful start
            self._emit_heartbeat()

            while self.running:
                try:
                    start = time.time()
                    self.dt = start - self.last_update_time
                    self.last_update_time = start

                    # Pump the Win32 message queue (handles both windows)
                    msg = MSG()
                    while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                        user32.TranslateMessage(ctypes.byref(msg))
                        user32.DispatchMessageW(ctypes.byref(msg))

                    target_fps = self._global_framerate
                    frame_time = 1.0 / target_fps

                    try:
                        while True:
                            msg = self.msg_queue.get_nowait()
                            msg_type = (
                                msg.get("type", "unknown")
                                if isinstance(msg, dict)
                                else "non-dict"
                            )
                            msg_group = (
                                msg.get("group", "unknown")
                                if isinstance(msg, dict)
                                else "n/a"
                            )
                            self._handle_message(msg)
                    except queue.Empty:
                        pass

                    # =========================================================
                    # UPDATE AND RENDER ALL UNIFIED WINDOWS (includes chat windows now)
                    # =========================================================
                    self._update_all_windows()

                    # Re-apply topmost to all HUD windows when the foreground
                    # window changed (event-driven, not polled).
                    if self._foreground_changed.is_set():
                        self._foreground_changed.clear()
                        self._reapply_topmost()

                    self._emit_heartbeat()

                    elapsed = time.time() - start
                    if elapsed < frame_time:
                        time.sleep(frame_time - elapsed)

                except Exception as e:
                    self._report_exception("run_loop", e)
                    time.sleep(0.05)

        except Exception as e:
            self._report_exception("run_crash", e)
        finally:
            self._uninstall_foreground_hook()
            # Cleanup unified windows (including chat windows)
            for name in list(self._windows.keys()):
                self._destroy_window(name)

    def _install_foreground_hook(self):
        """Install a WinEvent hook to detect foreground window changes.

        Uses EVENT_SYSTEM_FOREGROUND which fires whenever a different window
        becomes the foreground window. WINEVENT_OUTOFCONTEXT means the callback
        runs in our own process/thread context (no DLL injection needed).
        WINEVENT_SKIPOWNPROCESS avoids firing for our own HUD windows.
        """

        def _on_foreground_change(
            hook, event, hwnd, id_object, id_child, event_thread, event_time
        ):
            self._foreground_changed.set()

        # Must keep a reference to prevent garbage collection of the ctypes callback
        self._win_event_proc = WINEVENTPROC(_on_foreground_change)
        self._win_event_hook = user32.SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND,  # eventMin
            EVENT_SYSTEM_FOREGROUND,  # eventMax
            None,  # hmodWinEventProc (None for out-of-context)
            self._win_event_proc,  # callback
            0,  # idProcess (0 = all processes)
            0,  # idThread (0 = all threads)
            WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
        )

    def _uninstall_foreground_hook(self):
        """Remove the WinEvent hook on shutdown."""
        if self._win_event_hook:
            try:
                user32.UnhookWinEvent(self._win_event_hook)
            except Exception:
                pass
            self._win_event_hook = None
            self._win_event_proc = None

    def _reapply_topmost(self):
        """Re-apply topmost z-order to all visible HUD windows."""
        for win in self._windows.values():
            hwnd = win.get("hwnd")
            if not hwnd:
                continue
            # Only re-apply to windows that are visible or fading in
            if win.get("fade_state", 0) in (1, 2, 3):
                force_on_top(hwnd)

    def _handle_message(self, msg):
        try:
            t = msg.get("type")

            # Normalize command type names (support both modern and legacy names)
            type_aliases = {
                # Modern name -> handled as
                "show_message": "draw",
                "hide_message": "hide",
                "set_loader": "loading",
                "add_item": "add_persistent_info",
                "update_item": "update_persistent_info",
                "remove_item": "remove_persistent_info",
                "clear_items": "clear_all_persistent_info",
                "show_timer": "show_progress_timer",
            }
            t = type_aliases.get(t, t)

            # Normalize field names (support both 'content' and 'message', 'show' and 'state')
            if "content" in msg and "message" not in msg:
                msg["message"] = msg["content"]
            if "show" in msg and "state" not in msg:
                msg["state"] = msg["show"]
            if (
                "color" in msg
                and "progress_color" not in msg
                and t in ("show_progress", "show_progress_timer")
            ):
                msg["progress_color"] = msg["color"]

            # Extract group name (default to 'default' for backward compatibility)
            group = msg.get("group", "default")

            # =====================================================================
            # GROUP MANAGEMENT COMMANDS
            # =====================================================================
            if t == "create_group":
                props = msg.get("props", {})
                if group not in self._group_props:
                    self._group_props[group] = {}
                self._group_props[group].update(props)
                return

            elif t == "update_group":
                props = msg.get("props", {})
                if group not in self._group_props:
                    self._group_props[group] = {}
                self._group_props[group].update(props)

                # Update existing windows for this group and force re-render
                matched_count = 0
                for name, state in self._windows.items():
                    if state.get("group") == group:
                        matched_count += 1
                        old_width = state["props"].get("width")
                        state["props"].update(props)
                        new_width = state["props"].get("width")
                        state["target_opacity"] = int(
                            state["props"].get("opacity", 0.85) * 255
                        )
                        # Invalidate render cache to force re-render with new props
                        state["last_render_state"] = None
                        state["canvas_dirty"] = True
                        # Clear cached canvas if width changed (forces new canvas creation)
                        if "width" in props:
                            state["canvas"] = None
                        # Update layout manager with new layout properties
                        layout_kwargs = {}
                        if "width" in props:
                            layout_kwargs["width"] = int(props["width"])
                        if "anchor" in props:
                            try:
                                layout_kwargs["anchor"] = Anchor(props["anchor"])
                            except ValueError:
                                pass
                        if "priority" in props:
                            layout_kwargs["priority"] = int(props["priority"])
                        if layout_kwargs:
                            self._layout_manager.update_window(name, **layout_kwargs)

                # Re-init fonts in case font properties changed
                old_size = self.fonts.get("_font_size") if self.fonts else None
                old_family = self.fonts.get("_font_family") if self.fonts else None
                new_size = props.get("font_size")
                new_family = props.get("font_family")
                if (new_size is not None and new_size != old_size) or (
                    new_family is not None and new_family != old_family
                ):
                    font_size = int(new_size) if new_size is not None else old_size
                    font_family = new_family if new_family is not None else old_family
                    self._init_fonts(font_size, font_family)
                    # Rebuild markdown renderer with new fonts
                    text_color = self._hex_to_rgb(props.get("text_color", "#f0f0f0"))
                    accent_color = self._hex_to_rgb(
                        props.get("accent_color", "#00aaff")
                    )
                    bg_color = self._hex_to_rgb(props.get("bg_color", "#1e212b"))
                    colors = {
                        "text": text_color,
                        "accent": accent_color,
                        "bg": bg_color,
                    }
                    color_emojis = props.get("color_emojis", True)
                    self.md_renderer = MarkdownRenderer(
                        self.fonts, colors, color_emojis
                    )
                return

            elif t == "delete_group":
                self._group_props.pop(group, None)
                self._destroy_group_windows(group)
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
            elif t == "hide":
                # Hide message window for this group
                win = self._get_window(self.WINDOW_TYPE_MESSAGE, group)
                if win:
                    win["fade_state"] = 3
                    win["current_message"] = None
                    win["is_loading"] = False
                    # Note: Don't release layout slot yet - window still visible during fade-out
                    # Layout slot will be released when fade completes (opacity reaches 0)

            elif t == "draw":
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

                if props:
                    # Check for font changes
                    old_size = win["props"].get("font_size")
                    old_family = win["props"].get("font_family")

                    # Update window props (excluding persistent_* keys)
                    msg_props = {
                        k: v
                        for k, v in props.items()
                        if not k.startswith("persistent_")
                    }
                    win["props"].update(msg_props)
                    win["target_opacity"] = int(win["props"].get("opacity", 0.85) * 255)

                    new_size = win["props"].get("font_size")
                    new_family = win["props"].get("font_family")

                    # Re-init fonts if size or family changed
                    if old_size != new_size or old_family != new_family:
                        font_size = (
                            int(new_size)
                            if new_size is not None
                            else int(old_size) if old_size is not None else 16
                        )
                        font_family = (
                            new_family
                            if new_family is not None
                            else old_family if old_family is not None else "Segoe UI"
                        )
                        self._init_fonts(font_size, font_family)
                        colors = {
                            "text": self._hex_to_rgb(
                                win["props"].get("text_color", "#f0f0f0")
                            ),
                            "accent": self._hex_to_rgb(
                                win["props"].get("accent_color", "#00aaff")
                            ),
                            "bg": self._hex_to_rgb(
                                win["props"].get("bg_color", "#1e212b")
                            ),
                        }
                        color_emojis = win["props"].get("color_emojis", True)
                        self.md_renderer = MarkdownRenderer(
                            self.fonts, colors, color_emojis
                        )
                        win["current_blocks"] = None
                        win["last_render_state"] = None

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
                    win["fade_state"] = 1
                    # Immediately notify layout manager that this window is now visible
                    window_name = self._get_window_name(self.WINDOW_TYPE_MESSAGE, group)
                    self._layout_manager.set_window_visible(window_name, True)

                win["min_display_time"] = time.time() + win["props"].get(
                    "duration", 8.0
                )

            elif t == "loading":
                # Get or create message window for this group (loader can work without message)
                win = self._ensure_window(
                    self.WINDOW_TYPE_MESSAGE, group, msg.get("props", {})
                )
                win["is_loading"] = msg.get("state", False)
                if msg.get("color"):
                    win["loading_color"] = self._hex_to_rgb(msg["color"])
                # If showing loader, ensure window is visible
                if win["is_loading"] and win["fade_state"] in (0, 3):
                    win["fade_state"] = 1
                    # Immediately notify layout manager that this window is now visible
                    window_name = self._get_window_name(self.WINDOW_TYPE_MESSAGE, group)
                    self._layout_manager.set_window_visible(window_name, True)

            # =====================================================================
            # PERSISTENT WINDOW COMMANDS
            # =====================================================================
            elif t == "add_persistent_info":
                title = msg.get("title")
                if title:
                    props = msg.get("props", {})
                    win = self._ensure_window(self.WINDOW_TYPE_PERSISTENT, group, props)

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

            elif t == "update_persistent_info":
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
                    props = msg.get("props", {})
                    win = self._ensure_window(self.WINDOW_TYPE_PERSISTENT, group, props)

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

            elif t == "show_progress_timer":
                title = msg.get("title")
                if title:
                    props = msg.get("props", {})
                    win = self._ensure_window(self.WINDOW_TYPE_PERSISTENT, group, props)

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

            elif t == "update_progress":
                title = msg.get("title")
                if title:
                    win = self._get_window(self.WINDOW_TYPE_PERSISTENT, group)
                    if win and title in win["items"]:
                        info = win["items"][title]
                        if info.get("is_progress"):
                            now = time.time()
                            target_current = float(
                                msg.get("current", info.get("progress_current", 0))
                            )

                            if title in win["progress_animations"]:
                                anim = win["progress_animations"][title]
                                anim["start_value"] = anim["current"]
                                anim["target"] = target_current
                                anim["start_time"] = now

                            info["progress_current"] = target_current
                            if msg.get("maximum") is not None:
                                info["progress_maximum"] = float(msg["maximum"])
                            if msg.get("description") is not None:
                                info["description"] = msg["description"]

            elif t == "remove_persistent_info":
                title = msg.get("title")
                if title:
                    win = self._get_window(self.WINDOW_TYPE_PERSISTENT, group)
                    if win and title in win["items"]:
                        del win["items"][title]
                        if title in win["progress_animations"]:
                            del win["progress_animations"][title]

            elif t == "clear_all_persistent_info":
                win = self._get_window(self.WINDOW_TYPE_PERSISTENT, group)
                if win:
                    win["items"].clear()
                    win["progress_animations"].clear()

            # =====================================================================
            # Chat Window Commands
            # =====================================================================
            elif t == "create_chat_window":
                chat_name = msg.get("name")
                if chat_name:
                    props = msg.get("props", {})
                    # Set default chat window props
                    default_props = {
                        "width": 400,
                        "max_height": 400,
                        "bg_color": "#1e212b",
                        "text_color": "#f0f0f0",
                        "accent_color": "#00aaff",
                        "opacity": 0.85,
                        "border_radius": 12,
                        "content_padding": 12,
                        "font_size": 14,
                        "auto_hide": False,
                        "auto_hide_delay": 10.0,
                        "max_messages": 50,
                        "sender_colors": {},
                        "show_timestamps": False,
                        "message_spacing": 8,
                        "fade_old_messages": True,
                        "scroll_fade_height": 40,  # Height of fade gradient at top when scrolled
                        "is_chat_window": True,
                        # Layout manager props (margin/spacing now global)
                        "anchor": "top_left",
                        "priority": 5,  # Lower than messages by default
                        "layout_mode": "auto",
                    }
                    default_props.update(props)
                    # Also merge top-level msg properties for backwards compatibility
                    for key in [
                        "x",
                        "y",
                        "width",
                        "max_height",
                        "auto_hide",
                        "auto_hide_delay",
                        "max_messages",
                        "sender_colors",
                        "fade_old_messages",
                        "scroll_fade_height",
                        "anchor",
                        "priority",
                        "layout_mode",
                    ]:
                        if key in msg and msg[key] is not None:
                            default_props[key] = msg[key]

                    # Create unified window for chat
                    window_name = f"chat_{chat_name}"
                    self._windows[window_name] = {
                        "type": self.WINDOW_TYPE_CHAT,
                        "group": chat_name,  # Chat window name is also the group name
                        "props": default_props,
                        "messages": [],
                        "last_message_time": 0,
                        "visible": True,
                        "opacity": 0,
                        "target_opacity": int(default_props.get("opacity", 0.85) * 255),
                        "fade_state": 0,  # 0=hidden, 1=fade_in, 2=visible, 3=fade_out
                        "canvas_dirty": True,
                        "hwnd": None,
                        "window_dc": None,
                        "mem_dc": None,
                        "canvas": None,
                        "dib_bitmap": None,
                        "dib_bits": None,
                        "old_bitmap": None,
                        "dib_width": 0,
                        "dib_height": 0,
                        "last_render_state": None,
                    }

                    # Register with layout manager using same name as other windows
                    layout_name = window_name
                    anchor = default_props.get("anchor", "top_left")
                    priority = default_props.get("priority", 5)
                    layout_mode = default_props.get("layout_mode", "auto")
                    self._layout_manager.register_window(
                        layout_name, anchor, priority, layout_mode
                    )

                    # Create window for this chat
                    w = int(default_props.get("width", 400))
                    h = int(default_props.get("max_height", 400))

                    # Register with layout manager
                    layout_mode = default_props.get("layout_mode", "auto")
                    if layout_mode == "auto":
                        anchor_str = default_props.get("anchor", "top_left")
                        priority = int(default_props.get("priority", 5))

                        # Convert string anchor to Anchor enum
                        anchor_map = {
                            "top_left": Anchor.TOP_LEFT,
                            "top_center": Anchor.TOP_CENTER,
                            "top_right": Anchor.TOP_RIGHT,
                            "left_center": Anchor.LEFT_CENTER,
                            "center": Anchor.CENTER,
                            "right_center": Anchor.RIGHT_CENTER,
                            "bottom_left": Anchor.BOTTOM_LEFT,
                            "bottom_center": Anchor.BOTTOM_CENTER,
                            "bottom_right": Anchor.BOTTOM_RIGHT,
                        }
                        anchor_enum = anchor_map.get(anchor_str, Anchor.TOP_LEFT)

                        # Register with layout manager (uses global margin/spacing defaults)
                        self._layout_manager.register_window(
                            name=f"chat_{chat_name}",
                            anchor=anchor_enum,
                            mode=LayoutMode.AUTO,
                            priority=priority,
                            width=w,
                            height=h,
                        )
                        # Get initial position from layout manager
                        pos = self._layout_manager.get_position(f"chat_{chat_name}")
                        x = pos[0] if pos else int(default_props.get("x", 20))
                        y = pos[1] if pos else int(default_props.get("y", 20))
                    else:
                        # Manual mode - use x/y directly
                        x = int(default_props.get("x", 20))
                        y = int(default_props.get("y", 20))

                    hwnd = self._create_overlay_window(
                        f"HeadsUpChat_{chat_name}", x, y, w, h
                    )
                    if hwnd:
                        # Store hwnd in the unified window state
                        self._windows[window_name]["hwnd"] = hwnd
                        window_dc, mem_dc = self._init_gdi(hwnd)
                        self._windows[window_name]["window_dc"] = window_dc
                        self._windows[window_name]["mem_dc"] = mem_dc

            elif t == "update_chat_window":
                chat_name = msg.get("name")
                window_name = f"chat_{chat_name}"
                if chat_name and window_name in self._windows:
                    win = self._windows[window_name]
                    props = msg.get("props", {})
                    win["props"].update(props)
                    win["canvas_dirty"] = True

                    # Update window position if changed
                    if (
                        "x" in props
                        or "y" in props
                        or "width" in props
                        or "max_height" in props
                    ):
                        hwnd = win.get("hwnd")
                        if hwnd:
                            chat_props = win["props"]
                            x = int(chat_props.get("x", 20))
                            y = int(chat_props.get("y", 20))
                            w = int(chat_props.get("width", 400))
                            h = int(chat_props.get("max_height", 400))
                            user32.SetWindowPos(
                                hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE
                            )

            elif t == "delete_chat_window":
                chat_name = msg.get("name")
                if chat_name:
                    window_name = f"chat_{chat_name}"
                    if window_name in self._windows:
                        self._destroy_window(window_name)

            elif t == "chat_message":
                chat_name = msg.get("name")
                window_name = f"chat_{chat_name}"
                if chat_name and window_name in self._windows:
                    now = time.time()
                    win = self._windows[window_name]
                    sender = msg.get("sender", "")
                    message_id = msg.get("id", "")

                    # Append to last message if same sender
                    if win["messages"] and win["messages"][-1]["sender"] == sender:
                        win["messages"][-1]["text"] += " " + msg.get("text", "")
                        win["messages"][-1]["timestamp"] = now
                    else:
                        message = {
                            "id": message_id,
                            "sender": sender,
                            "text": msg.get("text", ""),
                            "color": msg.get("color"),
                            "timestamp": now,
                        }
                        win["messages"].append(message)

                    win["last_message_time"] = now

                    # Trim old messages if over limit
                    max_messages = win["props"].get("max_messages", 50)
                    if len(win["messages"]) > max_messages:
                        win["messages"] = win["messages"][-max_messages:]

                    # Show window if auto-hide was triggered
                    if win["fade_state"] == 0 or win["fade_state"] == 3:
                        win["fade_state"] = 1  # fade in
                        win["visible"] = True
                        # Immediately notify layout manager
                        self._layout_manager.set_window_visible(window_name, True)

                    win["canvas_dirty"] = True

            elif t == "update_chat_message":
                chat_name = msg.get("name")
                window_name = f"chat_{chat_name}"
                if chat_name and window_name in self._windows:
                    win = self._windows[window_name]
                    message_id = msg.get("id", "")
                    new_text = msg.get("text", "")
                    for m in win["messages"]:
                        if m.get("id") == message_id:
                            m["text"] = new_text
                            win["canvas_dirty"] = True
                            break

            elif t == "clear_chat_window":
                chat_name = msg.get("name")
                window_name = f"chat_{chat_name}"
                if chat_name and window_name in self._windows:
                    self._windows[window_name]["messages"] = []
                    self._windows[window_name]["canvas_dirty"] = True

            elif t == "show_chat_window":
                chat_name = msg.get("name")
                window_name = f"chat_{chat_name}"
                if chat_name and window_name in self._windows:
                    win = self._windows[window_name]
                    win["visible"] = True
                    win["fade_state"] = 1  # fade in
                    # Immediately notify layout manager
                    self._layout_manager.set_window_visible(window_name, True)
                    win["canvas_dirty"] = True

            elif t == "hide_chat_window":
                chat_name = msg.get("name")
                window_name = f"chat_{chat_name}"
                if chat_name and window_name in self._windows:
                    win = self._windows[window_name]
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
                    screen_width, screen_height, screen_offset_x, screen_offset_y = (
                        get_monitor_dimensions(self._screen)
                    )
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
        """Re-register all windows with the layout manager after screen change.

        This ensures windows are repositioned to the new screen's coordinates.
        """
        # Use current margin/spacing values when re-registering
        current_margin = self._layout_margin
        current_spacing = self._layout_spacing

        for name, win in self._windows.items():
            props = win.get("props", {})

            # Get anchor and layout mode from props or defaults
            anchor_str = props.get("anchor", "top_left")
            layout_mode_str = props.get("layout_mode", "auto")

            try:
                anchor = Anchor(anchor_str)
            except ValueError:
                anchor = Anchor.TOP_LEFT

            try:
                layout_mode = (
                    LayoutMode(layout_mode_str)
                    if layout_mode_str == "manual"
                    else LayoutMode.AUTO
                )
            except ValueError:
                layout_mode = LayoutMode.AUTO

            # Get dimensions
            width = props.get("width", 400)
            height = win.get("canvas", {}).size[1] if win.get("canvas") else 200
            priority = props.get("priority", 10)

            # Re-register with layout manager, using CURRENT margin/spacing values
            self._layout_manager.register_window(
                name=name,
                anchor=anchor,
                mode=layout_mode,
                priority=priority,
                width=width,
                height=height,
                margin_x=current_margin,
                margin_y=current_margin,
                spacing=current_spacing,
            )

        # Force position recalculation and window repositioning
        self._update_all_window_positions()

    def _create_overlay_window(self, name, x, y, w, h):
        ex = (
            WS_EX_LAYERED
            | WS_EX_TRANSPARENT
            | WS_EX_TOPMOST
            | WS_EX_TOOLWINDOW
            | WS_EX_NOACTIVATE
        )
        hwnd = user32.CreateWindowExW(
            ex,
            _class_name,
            name,
            WS_POPUP,
            x,
            y,
            w,
            h,
            None,
            None,
            kernel32.GetModuleHandleW(None),
            None,
        )
        if hwnd:
            user32.SetLayeredWindowAttributes(
                hwnd, 0x00FF00FF, 0, LWA_ALPHA | LWA_COLORKEY
            )
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            user32.SetWindowPos(
                hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW
            )
        return hwnd

    def _init_gdi(self, hwnd):
        if not hwnd:
            return None, None
        window_dc = user32.GetDC(hwnd)
        mem_dc = gdi32.CreateCompatibleDC(window_dc)
        return window_dc, mem_dc

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
            self._render_stats["track_cache_hits"] += 1
            # Copy required: callers draw the progress fill onto this image
            return self._progress_track_cache[cache_key].copy()

        self._render_stats["track_cache_misses"] += 1

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
            self._render_stats["gradient_cache_hits"] += 1
            # Copy required: gradient is composited onto the progress bar buffer
            return self._progress_gradient_cache[cache_key].copy()

        self._render_stats["gradient_cache_misses"] += 1

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

    def _read_stdin(self):
        while self.running:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                    self.msg_queue.put(msg)
                except:
                    pass
            except:
                break


def run_overlay_in_subprocess(command_queue, error_queue=None):
    """Entry point for running the overlay in a subprocess.

    Args:
        command_queue: A multiprocessing.Queue for receiving commands.
        error_queue: Optional queue for reporting errors back to the parent process.
    """
    try:
        overlay = HeadsUpOverlay(command_queue=command_queue, error_queue=error_queue)
        overlay.run()
    except Exception as e:
        if error_queue:
            import traceback

            error_queue.put(
                f"Subprocess crashed: {type(e).__name__}: {e}\n{traceback.format_exc()}"
            )
        raise


if __name__ == "__main__":
    # Allow running standalone for testing
    overlay = HeadsUpOverlay()
    overlay.run()
