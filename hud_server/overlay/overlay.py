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
from ctypes import wintypes
from typing import Tuple, Dict, List, Optional
import traceback
import io
import urllib.request
import urllib.error

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
from hud_server.platform import win32
from hud_server.platform.win32 import (
    user32, gdi32, kernel32,
    WNDCLASSEXW, BITMAPINFOHEADER, BITMAPINFO, MSG, POINT,
    GWL_EXSTYLE, WS_POPUP, WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOPMOST, WS_EX_TOOLWINDOW,
    WS_EX_NOACTIVATE, LWA_ALPHA, LWA_COLORKEY, SWP_NOSIZE, SWP_NOMOVE, SWP_SHOWWINDOW,
    SWP_NOACTIVATE, SWP_ASYNCWINDOWPOS, SRCCOPY, DIB_RGB_COLORS, BI_RGB,
    SW_SHOWNOACTIVATE, HWND_TOPMOST, PM_REMOVE,
    _ensure_window_class, _class_name
)
from hud_server.layout import LayoutManager, Anchor, LayoutMode

class HeadsUpOverlay:
    """HUD Overlay with sophisticated Markdown rendering.

    Architecture (Rework v2):
    - All HUD elements are managed through a unified window system
    - Each group (wingman) can have its own message window and persistent window
    - Windows are created on-demand and identified by unique names
    - Window types: 'message', 'persistent', 'chat'
    """

    # Window type constants
    WINDOW_TYPE_MESSAGE = 'message'
    WINDOW_TYPE_PERSISTENT = 'persistent'
    WINDOW_TYPE_CHAT = 'chat'

    def __init__(self, command_queue=None, error_queue=None, framerate: int = 60,
                 layout_margin: int = 20, layout_spacing: int = 15):
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
            'width': 400, 'x': 20, 'y': 20,
            'bg_color': '#1e212b', 'text_color': '#f0f0f0', 'accent_color': '#00aaff',
            'opacity': 0.85, 'duration': 8.0, 'border_radius': 12, 'content_padding': 16,
            'max_height': 600, 'font_size': 16, 'color_emojis': True,
            'typewriter_effect': True,
            # Persistent window defaults
            'persistent_x': 20, 'persistent_y': 300, 'persistent_width': 300,
        }

        # Per-group props storage (set via create_group/update_group)
        self._group_props: Dict[str, Dict] = {}

        # Progress animation transition duration
        self._progress_transition_duration = 0.5

        # =====================================================================
        # LEGACY COMPATIBILITY LAYER
        # =====================================================================
        # These are kept for backward compatibility with code that doesn't use groups.
        # They point to the "_default" group windows.
        self.is_loading = False
        self.loading_color = (0, 170, 255)
        self.current_message = None
        self.display_props = dict(self._default_props)
        self.target_opacity = 216
        self.current_opacity = 0
        self.fade_state = 0
        self.min_display_time = 0
        self.typewriter_active = False
        self.typewriter_char_count = 0
        self.last_typewriter_update = 0

        # Legacy persistent infos (global, merged from all groups for backward compat)
        self.persistent_infos = {}
        self.persistent_fade_state = 0
        self.persistent_opacity = 0
        self._progress_animations = {}
        self._persistent_render_time = 0.0

        # Legacy Win32 resources (for _default group, created in run())
        self.hwnd = None
        self.window_dc = None
        self.mem_dc = None
        self.dib_bitmap = None
        self.dib_bits = None
        self.old_bitmap = None
        self.dib_width = 0
        self.dib_height = 0

        self.hwnd_persistent = None
        self.window_dc_persistent = None
        self.mem_dc_persistent = None
        self.dib_bitmap_persistent = None
        self.dib_bits_persistent = None
        self.old_bitmap_persistent = None
        self.dib_width_persistent = 0
        self.dib_height_persistent = 0

        # Legacy PIL resources
        self.canvas = None
        self.canvas_persistent = None
        self.temp_image = None
        self.temp_draw = None
        self.fonts = {}
        self.image_cache = {}
        self.md_renderer = None
        self.last_render_state = None
        self.last_render_state_persistent = None
        self.current_blocks = None
        self.canvas_dirty = False
        self.canvas_persistent_dirty = False

        # Legacy chat window state (will be migrated to unified system)
        self._chat_windows: Dict[str, Dict] = {}
        self._chat_window_dirty: Dict[str, bool] = {}
        self._chat_canvases: Dict[str, Image.Image] = {}
        self._chat_hwnds: Dict[str, int] = {}
        self._chat_window_dcs: Dict[str, tuple] = {}
        self._chat_last_render_state: Dict[str, tuple] = {}

        # =====================================================================
        # LAYOUT MANAGER
        # =====================================================================
        # Automatic positioning and stacking to prevent window overlap
        self._layout_manager = LayoutManager(
            screen_width=user32.GetSystemMetrics(0) if hasattr(user32, 'GetSystemMetrics') else 1920,
            screen_height=user32.GetSystemMetrics(1) if hasattr(user32, 'GetSystemMetrics') else 1080,
            default_margin=self._layout_margin,
            default_spacing=self._layout_spacing,
        )

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
            props['x'] = props.get('persistent_x', 20)
            props['y'] = props.get('persistent_y', 300)
            props['width'] = props.get('persistent_width', 300)

        return props

    def _create_window_state(self, window_type: str, group: str, props: dict = None) -> Dict:
        """Create a new window state dictionary."""
        merged_props = self._get_default_window_props(window_type, group)
        if props:
            merged_props.update(props)

        state = {
            'type': window_type,
            'group': group,
            'props': merged_props,
            'hwnd': None,
            'window_dc': None,
            'mem_dc': None,
            'canvas': None,
            'canvas_dirty': False,
            'dib_bitmap': None,
            'dib_bits': None,
            'old_bitmap': None,
            'dib_width': 0,
            'dib_height': 0,
            'fade_state': 0,  # hidden
            'opacity': 0,
            'target_opacity': int(merged_props.get('opacity', 0.85) * 255),
            'last_render_state': None,
        }

        # Type-specific initialization
        if window_type == self.WINDOW_TYPE_MESSAGE:
            state.update({
                'current_message': None,
                'is_loading': False,
                'loading_color': (0, 170, 255),
                'typewriter_active': False,
                'typewriter_char_count': 0,
                'last_typewriter_update': 0,
                'min_display_time': 0,
                'current_blocks': None,
            })
        elif window_type == self.WINDOW_TYPE_PERSISTENT:
            state.update({
                'items': {},
                'progress_animations': {},
            })
        elif window_type == self.WINDOW_TYPE_CHAT:
            state.update({
                'messages': [],
                'last_message_time': 0,
                'visible': True,
            })

        return state

    def _ensure_window(self, window_type: str, group: str, props: dict = None) -> Dict:
        """Get or create a window for the given type and group."""
        name = self._get_window_name(window_type, group)

        if name not in self._windows:
            # Create new window state
            state = self._create_window_state(window_type, group, props)
            self._windows[name] = state

            # Create the actual Win32 window
            window_props = state['props']
            w = int(window_props.get('width', 400))
            h = 100  # Initial height, will be adjusted during rendering

            # Register with layout manager
            layout_mode_str = window_props.get('layout_mode', 'auto')
            anchor_str = window_props.get('anchor', 'top_left')
            priority = int(window_props.get('priority', 10))
            margin = int(window_props.get('margin', 20))
            spacing = int(window_props.get('spacing', 10))

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
                manual_x=int(window_props.get('x', 20)) if layout_mode == LayoutMode.MANUAL else None,
                manual_y=int(window_props.get('y', 20)) if layout_mode == LayoutMode.MANUAL else None,
            )

            # Get initial position from layout manager
            pos = self._layout_manager.get_position(name)
            if pos:
                x, y = pos
            else:
                x = int(window_props.get('x', 20))
                y = int(window_props.get('y', 20))

            hwnd = self._create_overlay_window(f"HUD_{name}", x, y, w, h)
            if hwnd:
                window_dc, mem_dc = self._init_gdi(hwnd)
                state['hwnd'] = hwnd
                state['window_dc'] = window_dc
                state['mem_dc'] = mem_dc
        elif props:
            # Update existing window props
            self._windows[name]['props'].update(props)
            self._windows[name]['target_opacity'] = int(
                self._windows[name]['props'].get('opacity', 0.85) * 255
            )

            # Update layout manager if layout props changed
            window_props = self._windows[name]['props']
            layout_mode_str = window_props.get('layout_mode', 'auto')
            anchor_str = window_props.get('anchor', 'top_left')

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
                priority=int(window_props.get('priority', 10)),
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
        if state.get('old_bitmap') and state.get('mem_dc'):
            try:
                gdi32.SelectObject(state['mem_dc'], state['old_bitmap'])
            except:
                pass
        if state.get('dib_bitmap'):
            try:
                gdi32.DeleteObject(state['dib_bitmap'])
            except:
                pass

        # Cleanup DCs
        if state.get('mem_dc'):
            try:
                gdi32.DeleteDC(state['mem_dc'])
            except:
                pass
        if state.get('window_dc') and state.get('hwnd'):
            try:
                user32.ReleaseDC(state['hwnd'], state['window_dc'])
            except:
                pass

        # Destroy window
        if state.get('hwnd'):
            try:
                user32.DestroyWindow(state['hwnd'])
            except:
                pass

        # Unregister from layout manager
        self._layout_manager.unregister_window(name)

        del self._windows[name]

    def _destroy_group_windows(self, group: str):
        """Destroy all windows for a group."""
        names_to_destroy = [
            name for name in self._windows
            if self._windows[name].get('group') == group
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
                win_type = win.get('type')
                group = win.get('group', 'default')

                if win_type == self.WINDOW_TYPE_MESSAGE:
                    message_windows[group] = win
                    self._update_message_window(name, win)
                    self._draw_message_window(name, win)
                    self._blit_window(name, win)

                elif win_type == self.WINDOW_TYPE_PERSISTENT:
                    persistent_windows[group] = win
                    self._update_persistent_window(name, win)
                    self._draw_persistent_window(name, win)
                    # Don't blit yet - wait for collision check

                # Note: Chat windows use the legacy system for now

            except Exception as e:
                sys.stderr.write(f"[HUD] Window {name} update error: {e}\n")

        # Second pass: check collisions and update persistent windows
        for group, pers_win in persistent_windows.items():
            try:
                msg_win = message_windows.get(group)
                collision = self._check_window_collision(msg_win, pers_win)
                self._update_persistent_fade(pers_win, collision)
                self._blit_window(self._get_window_name(self.WINDOW_TYPE_PERSISTENT, group), pers_win)
            except Exception as e:
                sys.stderr.write(f"[HUD] Persistent window {group} collision error: {e}\n")

        # Third pass: Update ALL window positions from layout manager
        # This ensures windows reposition when others hide/show/resize
        self._update_all_window_positions()

    def _update_all_window_positions(self):
        """Update positions of all windows based on layout manager calculations."""
        # Force recompute positions
        positions = self._layout_manager.compute_positions(force=True)

        for name, win in self._windows.items():
            hwnd = win.get('hwnd')
            if not hwnd:
                continue

            # Skip windows that are completely hidden (fade_state 0 AND opacity 0)
            fade_state = win.get('fade_state', 0)
            opacity = win.get('opacity', 0)
            if fade_state == 0 and opacity == 0:
                continue

            canvas = win.get('canvas')
            if not canvas:
                continue

            # For windows that are visible or fading in, use layout position
            # For windows fading out (state 3), keep their current position (don't move during fade)
            if fade_state in (1, 2):  # Fading in or fully visible
                pos = positions.get(name)
                if pos:
                    x, y = pos
                    w, h = canvas.size

                    # Check if position actually changed
                    old_x = win.get('_last_x', -1)
                    old_y = win.get('_last_y', -1)

                    if x != old_x or y != old_y:
                        # Position changed - move window and mark for reblit
                        user32.MoveWindow(hwnd, x, y, w, h, True)  # True = repaint
                        win['_last_x'] = x
                        win['_last_y'] = y
                        win['canvas_dirty'] = True  # Force reblit after move

    def _update_message_window(self, name: str, win: Dict):
        """Update message window state (typewriter, fade, etc.)."""
        # Typewriter progression
        if win.get('typewriter_active') and win.get('current_message'):
            now = time.time()
            chars = (now - win.get('last_typewriter_update', now)) * 200
            if chars > 0:
                win['typewriter_char_count'] = win.get('typewriter_char_count', 0) + chars
                win['last_typewriter_update'] = now
                msg_len = len(win['current_message'].get('message', ''))
                if win['typewriter_char_count'] >= msg_len:
                    win['typewriter_active'] = False
                    win['typewriter_char_count'] = float(msg_len)

        # Fade logic
        self._update_window_fade(win, has_content=bool(win.get('current_message') or win.get('is_loading')))

        # Auto-hide check
        if win['fade_state'] == 2:  # visible
            should_fade = True
            if win.get('is_loading'):
                should_fade = False
            elif win.get('current_message'):
                if time.time() <= win.get('min_display_time', 0):
                    should_fade = False
            if should_fade:
                win['fade_state'] = 3
                # Clear message so has_content becomes False and fade-out can proceed
                win['current_message'] = None
                # Notify layout manager immediately
                window_name = self._get_window_name(self.WINDOW_TYPE_MESSAGE, win.get('group', 'default'))
                self._layout_manager.set_window_visible(window_name, False)

    def _update_persistent_window(self, name: str, win: Dict):
        """Update persistent window state (progress animations, expiry, etc.)."""
        now = time.time()
        items = win.get('items', {})
        progress_anims = win.get('progress_animations', {})

        # Check for expired items
        expired = [title for title, info in items.items()
                   if info.get('expiry') and now > info['expiry']]
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

            if anim.get('is_timer'):
                # Timer-based progress
                timer_elapsed = now - anim.get('timer_start', now)
                timer_duration = anim.get('timer_duration', 1)
                timer_progress = min(100, (timer_elapsed / timer_duration) * 100)
                anim['current'] = timer_progress
                info['progress_current'] = timer_progress

                if timer_elapsed >= timer_duration and info.get('auto_close') and not info.get('auto_close_triggered'):
                    info['auto_close_triggered'] = True
                    info['auto_close_time'] = now + 2.0
            else:
                # Regular progress animation
                elapsed = now - anim.get('start_time', now)
                duration = self._progress_transition_duration

                if duration > 0 and elapsed < duration:
                    t = elapsed / duration
                    t = 1 - (1 - t) ** 3  # ease-out cubic
                    anim['current'] = anim.get('start_value', 0) + (anim.get('target', 0) - anim.get('start_value', 0)) * t
                else:
                    anim['current'] = anim.get('target', 0)

                # Check for auto-close at 100%
                percentage = (anim['current'] / info.get('progress_maximum', 100)) * 100
                if percentage >= 100 and info.get('auto_close') and not info.get('auto_close_triggered'):
                    info['auto_close_triggered'] = True
                    info['auto_close_time'] = now + 2.0

            # Handle auto-close removal
            if info.get('auto_close_triggered') and info.get('auto_close_time'):
                if now >= info['auto_close_time']:
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
        hwnd = win.get('hwnd')
        if not hwnd:
            return

        key = 0x00FF00FF
        fade_amount = int(1080 * self.dt)
        if fade_amount < 1:
            fade_amount = 1

        target = win.get('target_opacity', 216)
        old_fade_state = win['fade_state']

        # Determine target state
        if has_content and win['fade_state'] in (0, 3):
            win['fade_state'] = 1  # start fade in
        elif not has_content and win['fade_state'] in (1, 2):
            win['fade_state'] = 3  # start fade out

        # Update layout manager visibility when fade state changes
        window_name = self._get_window_name(win.get('type', 'message'), win.get('group', 'default'))
        if old_fade_state != win['fade_state']:
            # Window is visible for layout purposes only when fading in (1) or fully visible (2)
            # When fading out (3) or hidden (0), it should NOT take up layout space
            is_visible = win['fade_state'] in (1, 2)
            self._layout_manager.set_window_visible(window_name, is_visible)

        if win['fade_state'] == 1:  # Fade in
            win['opacity'] = min(target, win.get('opacity', 0) + fade_amount)
            user32.SetLayeredWindowAttributes(hwnd, key, win['opacity'], LWA_ALPHA | LWA_COLORKEY)
            if win['opacity'] >= target:
                win['fade_state'] = 2

        elif win['fade_state'] == 3:  # Fade out
            win['opacity'] = max(0, win.get('opacity', 0) - fade_amount)
            user32.SetLayeredWindowAttributes(hwnd, key, win['opacity'], LWA_ALPHA | LWA_COLORKEY)
            if win['opacity'] <= 0:
                win['fade_state'] = 0
                # Update layout visibility when fully hidden
                self._layout_manager.set_window_visible(window_name, False)
                if win['type'] == self.WINDOW_TYPE_MESSAGE:
                    win['current_message'] = None

        elif win['fade_state'] == 2:  # Visible - maintain target opacity
            if win['opacity'] != target:
                if win['opacity'] < target:
                    win['opacity'] = min(target, win['opacity'] + fade_amount)
                else:
                    win['opacity'] = max(target, win['opacity'] - fade_amount)
                user32.SetLayeredWindowAttributes(hwnd, key, win['opacity'], LWA_ALPHA | LWA_COLORKEY)

    def _draw_message_window(self, name: str, win: Dict):
        """Draw content for a message window."""
        current_message = win.get('current_message')
        is_loading = win.get('is_loading', False)

        if not current_message and not is_loading:
            return

        props = win.get('props', {})
        bg = self._hex_to_rgb(props.get('bg_color', '#1e212b'))
        text_color = self._hex_to_rgb(props.get('text_color', '#f0f0f0'))
        accent = self._hex_to_rgb(props.get('accent_color', '#00aaff'))

        width = int(props.get('width', 400))
        max_height = int(props.get('max_height', 600))
        radius = int(props.get('border_radius', 12))
        padding = int(props.get('content_padding', 16))

        # Build state hash for caching
        # Force repaint every frame while loading (animation needs continuous updates)
        if is_loading:
            # Use time-based state to force repaint each frame
            current_state = ('loading', time.time())
        else:
            try:
                # Include tools in state hash
                tools = current_message.get('tools', []) if current_message else []
                tools_hash = tuple((t.get('source', ''), t.get('name', '')) for t in tools) if tools else ()

                msg_state = (
                    current_message.get('message', '') if current_message else '',
                    current_message.get('title', '') if current_message else '',
                    int(win.get('typewriter_char_count', 0)),
                    tools_hash,
                )
            except:
                msg_state = str(current_message)

            # Include visual props in state hash for real-time config updates
            visual_props_hash = (
                width, max_height, radius, padding,
                bg, text_color, accent,
                props.get('opacity', 0.85),
                props.get('font_size', 16),
                props.get('font_family', ''),
            )
            current_state = (msg_state, win.get('opacity', 0), visual_props_hash)

        if win.get('last_render_state') == current_state and win.get('canvas'):
            return

        win['last_render_state'] = current_state
        win['canvas_dirty'] = True

        # Ensure renderer exists
        if not self.md_renderer:
            self._init_fonts()
            colors = {'text': text_color, 'accent': accent, 'bg': bg}
            self.md_renderer = MarkdownRenderer(self.fonts, colors, props.get('color_emojis', True))

        # Update renderer colors
        self.md_renderer.set_colors(text_color, accent, bg)

        # Create temp canvas
        temp_h = max_height + 500
        temp = Image.new('RGBA', (width, temp_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(temp)

        y = padding

        # Title
        if current_message:
            title = current_message.get('title', '')
            if title:
                title = self._strip_emotions(title)
                font_bold = self.fonts.get('bold', self.fonts.get('normal', self.fonts.get('regular')))
                if font_bold:
                    draw.text((padding, y), title, fill=accent + (255,), font=font_bold)
                    try:
                        bbox = font_bold.getbbox(title)
                        y += bbox[3] - bbox[1] + 12
                    except:
                        y += 24

            # Message content with typewriter
            message = current_message.get('message', '')
            if message:
                message = self._strip_emotions(message)

                # Use max_chars for typewriter effect (don't truncate message directly)
                typewriter_active = win.get('typewriter_active', False)
                max_chars = int(win.get('typewriter_char_count', 0)) if typewriter_active else None

                # Use cached blocks if available and message hasn't changed
                cached = win.get('current_blocks')
                if cached is None or cached.get('msg') != message:
                    win['current_blocks'] = {
                        'msg': message,
                        'blocks': self.md_renderer.parse_blocks(message)
                    }
                    cached = win['current_blocks']

                if self.md_renderer:
                    y = self.md_renderer.render(
                        draw, temp, message, padding, y, width - padding * 2, max_chars,
                        pre_parsed_blocks=cached['blocks']
                    )

        # Tool chips - display skill/tool information
        if current_message:
            tools = current_message.get('tools', [])
            if tools:
                y += 10
                tx = padding
                th = 30

                # Group tools by source (skill/mcp name)
                counts = {}
                for t in tools:
                    key = (t.get('source', 'System'), t.get('icon'))
                    counts[key] = counts.get(key, 0) + 1

                for (src, icon), cnt in counts.items():
                    font = self.fonts.get('code', self.fonts.get('normal', self.fonts.get('regular')))
                    sw, sh = self._get_text_size(src, font)
                    icon_w = 24 if icon and os.path.exists(str(icon)) else 0
                    badge_w = 26 if cnt > 1 else 0
                    chip_w = sw + icon_w + badge_w + 26

                    if tx + chip_w > width - padding:
                        tx = padding
                        y += th + 10

                    # Modern chip with subtle background
                    chip_bg = (42, 48, 60, 235)
                    draw.rounded_rectangle([tx, y, tx + chip_w, y + th], radius=th//2,
                                          fill=chip_bg, outline=accent)

                    ix = tx + 12
                    if icon and os.path.exists(str(icon)):
                        try:
                            if icon not in self.image_cache:
                                img = Image.open(icon).convert('RGBA').resize((18, 18), Image.Resampling.LANCZOS)
                                self.image_cache[icon] = img
                            temp.paste(self.image_cache[icon], (ix, y + 6), self.image_cache[icon])
                            ix += 22
                        except:
                            pass

                    draw.text((ix, y + (th - sh) // 2), src, fill=text_color, font=font)

                    # Badge for multiple tool calls from same source
                    if cnt > 1:
                        bw, bh = self._get_text_size(str(cnt), font)
                        bx = tx + chip_w - bw - 16
                        draw.ellipse([bx - 4, y + 5, bx + bw + 8, y + th - 5], fill=accent)
                        draw.text((bx + 2, y + 7), str(cnt), fill=bg, font=font)

                    tx += chip_w + 10

                y += th + 10

        # Loading animation
        if win.get('is_loading'):
            y += 6
            loading_color = win.get('loading_color', (0, 170, 255))
            self._draw_loading(draw, temp, padding, y, width - padding * 2, loading_color)
            y += 24

        # Calculate final height
        bottom_padding = padding - 4
        final_h = min(max(60, y + bottom_padding), max_height)

        # Create final canvas - ALWAYS create fresh to prevent ghosting
        old_canvas = win.get('canvas')
        if old_canvas is None or old_canvas.width != width or old_canvas.height != final_h:
            canvas = Image.new('RGBA', (width, final_h), (255, 0, 255, 255))
            win['canvas'] = canvas
        else:
            canvas = old_canvas
            # Completely clear the canvas with magenta (transparency key)
            # Use a new image to ensure complete overwrite
            canvas.paste(Image.new('RGBA', (width, final_h), (255, 0, 255, 255)), (0, 0))

        final_draw = ImageDraw.Draw(canvas)
        # Draw solid background first (covers everything)
        final_draw.rectangle([0, 0, width, final_h], fill=(255, 0, 255, 255))
        # Then draw the rounded rectangle on top
        final_draw.rounded_rectangle([0, 0, width - 1, final_h - 1], radius=radius,
                                    fill=bg + (255,), outline=(55, 62, 74))

        crop_height = min(final_h, temp.height)
        crop = temp.crop((0, 0, width, crop_height))
        # Composite the text onto the background properly
        # Use Image.alpha_composite to blend correctly without leaving ghost pixels
        # First, create a version of the canvas portion and composite
        canvas_region = canvas.crop((0, 0, width, crop_height))
        composited = Image.alpha_composite(canvas_region, crop)
        canvas.paste(composited, (0, 0))

        # Update layout manager with new height and get position
        self._layout_manager.update_window_height(name, final_h)

        # Get position from layout manager
        pos = self._layout_manager.get_position(name)

        hwnd = win.get('hwnd')
        if hwnd:
            if pos:
                x, y_pos = pos
            else:
                # Fallback to props
                x = int(props.get('x', 20))
                y_pos = int(props.get('y', 20))
            user32.MoveWindow(hwnd, x, y_pos, width, final_h, True)

    def _draw_persistent_window(self, name: str, win: Dict):
        """Draw content for a persistent window."""
        items = win.get('items', {})
        if not items:
            return

        props = win.get('props', {})
        bg = self._hex_to_rgb(props.get('bg_color', '#1e212b'))
        text_color = self._hex_to_rgb(props.get('text_color', '#f0f0f0'))
        accent = self._hex_to_rgb(props.get('accent_color', '#00aaff'))

        width = int(props.get('width', 300))
        radius = int(props.get('border_radius', 12))
        padding = int(props.get('content_padding', 16))

        # State hash for caching - include visual props so config changes trigger re-render
        now = time.time()
        progress_anims = win.get('progress_animations', {})

        items_state = []
        for title, info in sorted(items.items()):
            if title in progress_anims:
                items_state.append((title, progress_anims[title].get('current', 0)))
            else:
                items_state.append((title, info.get('description', '')))

        # Include visual props in state hash for real-time config updates
        visual_props_hash = (
            width, radius, padding,
            bg, text_color, accent,
            props.get('opacity', 0.85),
            props.get('font_size', 16),
            props.get('font_family', ''),
        )
        current_state = (tuple(items_state), int(now), visual_props_hash)

        last_state = win.get('last_render_state')
        cache_hit = (last_state == current_state and win.get('canvas'))

        if cache_hit:
            return

        win['last_render_state'] = current_state
        win['canvas_dirty'] = True

        # Ensure renderer
        if not self.md_renderer:
            self._init_fonts()
            colors = {'text': text_color, 'accent': accent, 'bg': bg}
            self.md_renderer = MarkdownRenderer(self.fonts, colors, props.get('color_emojis', True))

        self.md_renderer.set_colors(text_color, accent, bg)

        # Create temp canvas
        temp = Image.new('RGBA', (width, 2000), (0, 0, 0, 0))
        draw = ImageDraw.Draw(temp)

        y = padding
        font_bold = self.fonts.get('bold', self.fonts.get('normal', self.fonts.get('regular')))
        font_normal = self.fonts.get('normal', self.fonts.get('regular'))
        now = time.time()

        for title, info in sorted(items.items(), key=lambda x: x[1].get('added_at', 0)):
            # Check expiry but don't delete (logic does that)
            if info.get('expiry') and now > info['expiry']:
                continue

            # Calculate timer width/draw timer for expiry OR progress timer
            timer_w = 0
            timer_text = None

            # For progress items with timer, calculate remaining time
            if info.get('is_progress') and info.get('is_timer'):
                timer_start = info.get('timer_start', now)
                timer_duration = info.get('timer_duration', 0)
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
                if d > 0: parts.append(f"{d}d")
                if h > 0: parts.append(f"{h}h")
                if m > 0: parts.append(f"{m}m")
                parts.append(f"{s}s")

                timer_text = " ".join(parts)
            elif info.get('expiry'):
                remaining = max(0, int(info['expiry'] - now + 0.999))
                r = remaining
                d = r // 86400
                r %= 86400
                h = r // 3600
                r %= 3600
                m = r // 60
                s = r % 60

                parts = []
                if d > 0: parts.append(f"{d}d")
                if h > 0: parts.append(f"{h}h")
                if m > 0: parts.append(f"{m}m")
                parts.append(f"{s}s")

                timer_text = " ".join(parts)

            # Draw timer text on the right side
            if timer_text and font_bold:
                timer_w, _ = self._get_text_size(timer_text, font_bold)
                draw.text((width - padding - timer_w, y), timer_text, fill=text_color + (255,), font=font_bold)
                timer_w += 10

            # Title - render with emoji support (account for timer width)
            title_text = info.get('title', title)
            max_title_w = width - (padding * 2) - timer_w
            if font_bold:
                self._render_text_with_emoji(draw, title_text, padding, y, accent + (255,), font_bold)
            y += 22

            # Progress bar
            if info.get('is_progress'):
                progress_max = float(info.get('progress_maximum', 100))
                if title in progress_anims:
                    progress_current = progress_anims[title].get('current', 0)
                else:
                    progress_current = float(info.get('progress_current', 0))

                if progress_max <= 0:
                    progress_max = 100
                percentage = min(100, max(0, (progress_current / progress_max) * 100))

                progress_color = accent
                if info.get('progress_color'):
                    progress_color = self._hex_to_rgb(info['progress_color'])

                bar_width = width - padding * 2
                bar_height = 16
                y += 4

                # Draw progress bar using existing method
                y = self._draw_progress_bar(draw, temp, padding, y, bar_width, bar_height,
                                           percentage, bg, progress_color, text_color)

                # Percentage text
                if font_normal:
                    pct_text = f"{percentage:.0f}%"
                    try:
                        bbox = font_normal.getbbox(pct_text)
                        pct_w = bbox[2] - bbox[0]
                    except:
                        pct_w = len(pct_text) * 7
                    pct_x = padding + (bar_width - pct_w) // 2
                    draw.text((pct_x, y), pct_text, fill=text_color + (200,), font=font_normal)
                y += 18

            # Description
            desc = info.get('description', '')
            if desc:
                desc = self._strip_emotions(desc)
                if self.md_renderer:
                    y = self.md_renderer.render(draw, temp, desc, padding, y, width - padding * 2)

            y += 8

        # Finalize canvas
        bottom_padding = padding - 4
        final_h = max(60, y + bottom_padding)

        # Create final canvas - ALWAYS create fresh to prevent ghosting
        old_canvas = win.get('canvas')
        if old_canvas is None or old_canvas.width != width or old_canvas.height != final_h:
            canvas = Image.new('RGBA', (width, final_h), (255, 0, 255, 255))
            win['canvas'] = canvas
        else:
            canvas = old_canvas
            # Completely clear the canvas with magenta (transparency key)
            canvas.paste(Image.new('RGBA', (width, final_h), (255, 0, 255, 255)), (0, 0))

        final_draw = ImageDraw.Draw(canvas)
        # Draw solid background first (covers everything)
        final_draw.rectangle([0, 0, width, final_h], fill=(255, 0, 255, 255))
        # Then draw the rounded rectangle on top
        final_draw.rounded_rectangle([0, 0, width - 1, final_h - 1], radius=radius,
                                    fill=bg + (255,), outline=(55, 62, 74))

        crop = temp.crop((0, 0, width, final_h))
        # Composite the content onto the background properly
        canvas_region = canvas.crop((0, 0, width, final_h))
        composited = Image.alpha_composite(canvas_region, crop)
        canvas.paste(composited, (0, 0))

        # Update layout manager with new height and get position
        self._layout_manager.update_window_height(name, final_h)

        # Get position from layout manager
        pos = self._layout_manager.get_position(name)

        hwnd = win.get('hwnd')
        if hwnd:
            if pos:
                x, y_pos = pos
            else:
                # Fallback to props
                x = int(props.get('x', 20))
                y_pos = int(props.get('y', 20))
            user32.MoveWindow(hwnd, x, y_pos, width, final_h, True)

    def _blit_window(self, name: str, win: Dict):
        """Blit a window's canvas to its Win32 window."""
        if win.get('opacity', 0) <= 0:
            return
        if not win.get('canvas_dirty', False):
            return

        canvas = win.get('canvas')
        hwnd = win.get('hwnd')
        window_dc = win.get('window_dc')
        mem_dc = win.get('mem_dc')

        if not all([canvas, hwnd, window_dc, mem_dc]):
            return

        w, h = canvas.size

        # Check if DIB needs resize
        if w != win.get('dib_width', 0) or h != win.get('dib_height', 0):
            # Cleanup old DIB
            if win.get('old_bitmap'):
                gdi32.SelectObject(mem_dc, win['old_bitmap'])
            if win.get('dib_bitmap'):
                gdi32.DeleteObject(win['dib_bitmap'])

            # Create new DIB
            win['dib_width'] = w
            win['dib_height'] = h
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = w
            bmi.bmiHeader.biHeight = -h  # Top-down
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = BI_RGB

            dib_bits = ctypes.c_void_p()
            dib_bitmap = gdi32.CreateDIBSection(mem_dc, ctypes.byref(bmi), DIB_RGB_COLORS,
                                                ctypes.byref(dib_bits), None, 0)
            if dib_bitmap:
                win['old_bitmap'] = gdi32.SelectObject(mem_dc, dib_bitmap)
                win['dib_bitmap'] = dib_bitmap
                win['dib_bits'] = dib_bits

        dib_bits = win.get('dib_bits')
        if not dib_bits:
            return

        try:
            rgba = canvas.tobytes('raw', 'BGRA')
            # Clear the entire DIB buffer first to prevent any ghosting
            buffer_size = w * h * 4
            # Overwrite entire buffer with new content
            ctypes.memmove(dib_bits, rgba, buffer_size)
            gdi32.BitBlt(window_dc, 0, 0, w, h, mem_dc, 0, 0, SRCCOPY)
            win['canvas_dirty'] = False
        except Exception as e:
            pass

    def _hex_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        try:
            hex_color = hex_color.lstrip('#')
            if len(hex_color) == 3:
                hex_color = ''.join([c*2 for c in hex_color])
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        except:
            return (0, 170, 255)

    def _strip_emotions(self, text: str) -> str:
        """Remove emotion tags like [happy], [sad], [breathe] but preserve markdown links and checkboxes."""
        # First, temporarily protect markdown links
        link_pattern = r'\[([^]]+)]\(([^)]+)\)'
        links = []
        def save_link(m):
            links.append(m.group(0))
            return f'__LINK_{len(links)-1}__'

        text = re.sub(link_pattern, save_link, text)

        # Temporarily protect checkboxes [ ], [x], [X]
        checkbox_pattern = r'\[[ xX]\]'
        checkboxes = []
        def save_checkbox(m):
            checkboxes.append(m.group(0))
            return f'__CHECKBOX_{len(checkboxes)-1}__'

        text = re.sub(checkbox_pattern, save_checkbox, text)

        # Remove emotion tags (single words in brackets, must be 2+ chars to avoid single letters)
        # This matches [word] where word is 2 or more letters/underscores
        text = re.sub(r'\[[a-zA-Z_]{2,}]\s*', '', text)

        # Restore checkboxes
        for i, checkbox in enumerate(checkboxes):
            text = text.replace(f'__CHECKBOX_{i}__', checkbox)

        # Restore links
        for i, link in enumerate(links):
            text = text.replace(f'__LINK_{i}__', link)

        # Restore links
        for i, link in enumerate(links):
            text = text.replace(f'__LINK_{i}__', link)

        # Clean up whitespace
        text = text.strip()
        # Remove leading newlines
        text = re.sub(r'^\n+', '', text)
        # Collapse multiple consecutive newlines into one (paragraph breaks become single empty lines)
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text

    def _init_fonts(self):
        size = int(self.display_props.get('font_size', 16))
        font_family = self.display_props.get('font_family', 'Segoe UI')

        # Map font family names to Windows font files
        font_map = {
            'segoe ui': {'normal': 'segoeuisl.ttf', 'bold': 'segoeuib.ttf', 'italic': 'segoeuii.ttf', 'bold_italic': 'segoeuiz.ttf'},
            'arial': {'normal': 'arial.ttf', 'bold': 'arialbd.ttf', 'italic': 'ariali.ttf', 'bold_italic': 'arialbi.ttf'},
            'verdana': {'normal': 'verdana.ttf', 'bold': 'verdanab.ttf', 'italic': 'verdanai.ttf', 'bold_italic': 'verdanaz.ttf'},
            'tahoma': {'normal': 'tahoma.ttf', 'bold': 'tahomabd.ttf', 'italic': 'tahoma.ttf', 'bold_italic': 'tahomabd.ttf'},
            'trebuchet ms': {'normal': 'trebuc.ttf', 'bold': 'trebucbd.ttf', 'italic': 'trebucit.ttf', 'bold_italic': 'trebucbi.ttf'},
            'calibri': {'normal': 'calibri.ttf', 'bold': 'calibrib.ttf', 'italic': 'calibrii.ttf', 'bold_italic': 'calibriz.ttf'},
            'consolas': {'normal': 'consola.ttf', 'bold': 'consolab.ttf', 'italic': 'consolai.ttf', 'bold_italic': 'consolaz.ttf'},
            'courier new': {'normal': 'cour.ttf', 'bold': 'courbd.ttf', 'italic': 'couri.ttf', 'bold_italic': 'courbi.ttf'},
            'roboto': {'normal': 'Roboto-Regular.ttf', 'bold': 'Roboto-Bold.ttf', 'italic': 'Roboto-Italic.ttf', 'bold_italic': 'Roboto-BoldItalic.ttf'},
        }

        # Get font files for the specified family (case-insensitive)
        family_lower = font_family.lower()
        font_files = font_map.get(family_lower, font_map['segoe ui'])

        fonts_dir = "C:/Windows/Fonts/"

        # Use configured font size directly
        pil_size = size
        pil_code_size = size - 1  # Code font slightly smaller

        # Load emoji font separately (may fail on some systems)
        emoji_font = None
        emoji_font_paths = [
            fonts_dir + "seguiemj.ttf",  # Windows 10/11 Segoe UI Emoji
            fonts_dir + "seguisym.ttf",  # Fallback to Segoe UI Symbol
        ]
        for emoji_path in emoji_font_paths:
            try:
                emoji_font = ImageFont.truetype(emoji_path, pil_size)
                break
            except:
                pass

        # Load emoji fonts at different sizes for headers
        emoji_fonts = {'emoji': emoji_font}
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
                emoji_fonts['emoji_h1'] = ImageFont.truetype(emoji_font_path, pil_size + 10)
                emoji_fonts['emoji_h2'] = ImageFont.truetype(emoji_font_path, pil_size + 6)
                emoji_fonts['emoji_h3'] = ImageFont.truetype(emoji_font_path, pil_size + 3)
                emoji_fonts['emoji_h4'] = ImageFont.truetype(emoji_font_path, pil_size + 1)
                emoji_fonts['emoji_h5'] = ImageFont.truetype(emoji_font_path, pil_size)
                emoji_fonts['emoji_h6'] = ImageFont.truetype(emoji_font_path, pil_size - 1)
            except:
                pass

        try:
            self.fonts = {
                'normal': ImageFont.truetype(fonts_dir + font_files['normal'], pil_size),
                'bold': ImageFont.truetype(fonts_dir + font_files['bold'], pil_size),
                'italic': ImageFont.truetype(fonts_dir + font_files['italic'], pil_size),
                'bold_italic': ImageFont.truetype(fonts_dir + font_files['bold_italic'], pil_size),
                'code': ImageFont.truetype(fonts_dir + "consola.ttf", pil_code_size),
                # Header fonts H1-H6 with decreasing sizes
                'h1': ImageFont.truetype(fonts_dir + font_files['bold'], pil_size + 10),  # Largest
                'h2': ImageFont.truetype(fonts_dir + font_files['bold'], pil_size + 6),
                'h3': ImageFont.truetype(fonts_dir + font_files['bold'], pil_size + 3),
                'h4': ImageFont.truetype(fonts_dir + font_files['bold'], pil_size + 1),
                'h5': ImageFont.truetype(fonts_dir + font_files['bold'], pil_size),
                'h6': ImageFont.truetype(fonts_dir + font_files['bold_italic'], pil_size - 1),  # Smallest, italic
                'header': ImageFont.truetype(fonts_dir + font_files['bold'], pil_size + 4),  # Legacy
                'emoji': emoji_font if emoji_font else ImageFont.truetype(fonts_dir + font_files['normal'], pil_size),
                # Emoji fonts for headers
                'emoji_h1': emoji_fonts.get('emoji_h1', emoji_font),
                'emoji_h2': emoji_fonts.get('emoji_h2', emoji_font),
                'emoji_h3': emoji_fonts.get('emoji_h3', emoji_font),
                'emoji_h4': emoji_fonts.get('emoji_h4', emoji_font),
                'emoji_h5': emoji_fonts.get('emoji_h5', emoji_font),
                'emoji_h6': emoji_fonts.get('emoji_h6', emoji_font),
            }
        except Exception as e:
            # Fallback: try loading font by name directly (for custom fonts)
            try:
                self.fonts = {
                    'normal': ImageFont.truetype(font_family, pil_size),
                    'bold': ImageFont.truetype(font_family, pil_size),
                    'italic': ImageFont.truetype(font_family, pil_size),
                    'bold_italic': ImageFont.truetype(font_family, pil_size),
                    'code': ImageFont.truetype("consola.ttf", pil_code_size),
                    'h1': ImageFont.truetype(font_family, pil_size + 10),
                    'h2': ImageFont.truetype(font_family, pil_size + 6),
                    'h3': ImageFont.truetype(font_family, pil_size + 3),
                    'h4': ImageFont.truetype(font_family, pil_size + 1),
                    'h5': ImageFont.truetype(font_family, pil_size),
                    'h6': ImageFont.truetype(font_family, pil_size - 1),
                    'header': ImageFont.truetype(font_family, pil_size + 4),
                    'emoji': emoji_font if emoji_font else ImageFont.truetype(font_family, pil_size),
                }
            except:
                # Final fallback to default
                default = ImageFont.load_default()
                self.fonts = {k: default for k in ['normal', 'bold', 'italic', 'bold_italic', 'code', 'header', 'emoji']}

        colors = {
            'text': self._hex_to_rgb(self.display_props.get('text_color', '#f0f0f0')),
            'accent': self._hex_to_rgb(self.display_props.get('accent_color', '#00aaff')),
            'bg': self._hex_to_rgb(self.display_props.get('bg_color', '#1e212b'))
        }
        color_emojis = self.display_props.get('color_emojis', True)
        self.md_renderer = MarkdownRenderer(self.fonts, colors, color_emojis)

    def _get_text_size(self, text: str, font) -> Tuple[int, int]:
        try:
            bbox = font.getbbox(text)
            return int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])
        except:
            return len(text) * 8, 16

    def _render_text_with_emoji(self, draw, text: str, x: int, y: int, color: Tuple, font, emoji_y_offset: int = 5):
        """Render text with inline emoji support for titles and labels.

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
        emoji_font = self.fonts.get('emoji', font)

        while i < len(text):
            # Check for emoji at current position
            emoji_len = self.md_renderer._get_emoji_length(text, i) if self.md_renderer else 0
            if emoji_len > 0:
                # Render emoji with emoji font and color support
                emoji_text = text[i:i+emoji_len]
                if self.md_renderer and self.md_renderer.color_emojis:
                    draw.text((current_x, y + emoji_y_offset), emoji_text, fill=color, font=emoji_font, embedded_color=True)
                else:
                    draw.text((current_x, y + emoji_y_offset), emoji_text, fill=color, font=emoji_font)
                emoji_w, _ = self._get_text_size(emoji_text, emoji_font)
                # Reduce emoji width - more aggressive for variation selector emojis
                has_variation_selector = '\ufe0f' in emoji_text
                if has_variation_selector:
                    current_x += int(emoji_w * 0.55)
                else:
                    current_x += int(emoji_w * 0.85)
                i += emoji_len
            else:
                # Find the next emoji or end of text
                text_start = i
                while i < len(text):
                    if self.md_renderer and self.md_renderer._get_emoji_length(text, i) > 0:
                        break
                    i += 1
                # Render text segment
                text_segment = text[text_start:i]
                if text_segment:
                    draw.text((current_x, y), text_segment, fill=color, font=font)
                    text_w, _ = self._get_text_size(text_segment, font)
                    current_x += text_w

    def _draw_loading(self, draw, canvas, x: int, y: int, width: int, color: Tuple):
        """Modern animated loading bars with full width wave."""
        # Initialize loading phase if not exists
        if not hasattr(self, '_loading_phase'):
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
            normalized = normalized ** 2

            h = int(min_h + (normalized * (max_h - min_h)))
            if h < 1:
                h = 1

            bar_x = start_x + i * (bar_w + spacing)
            bar_y = int(center_y - (h / 2))

            # Solid color without alpha
            bar_color = color[:3] + (255,)

            # Draw rounded bar (pill shape)
            radius = min(bar_w // 2, h // 2)
            if radius < 1:
                radius = 1

            # Create small surface for the bar
            bar_surf = Image.new('RGBA', (bar_w, max(1, h)), (0, 0, 0, 0))
            bar_draw = ImageDraw.Draw(bar_surf)
            bar_draw.rounded_rectangle([0, 0, bar_w - 1, h - 1], radius=radius, fill=bar_color)
            canvas.paste(bar_surf, (bar_x, bar_y), bar_surf)

    def _draw_main_frame(self):
        if not self.current_message and not self.is_loading:
            return

        # Check if redraw is needed
        # We include display_props in state because it affects rendering (colors, size) and window position
        # We convert display_props to a tuple of items for hashing
        try:
            props_hash = tuple(sorted((k, v) for k, v in self.display_props.items() if isinstance(v, (str, int, float, bool, tuple))))
        except:
            props_hash = str(self.display_props)

        current_msg_id = self.current_message.get('id') if self.current_message else None
        current_msg_content = self.current_message.get('message') if self.current_message else None

        # Quantize typewriter position to whole characters for state comparison
        # This prevents unnecessary redraws for sub-character movements
        typewriter_state = int(self.typewriter_char_count) if self.typewriter_active else -1

        # For loading animation, use current time to ensure redraw every frame
        # This keeps the animation smooth at configured FPS
        loading_frame = time.time() if self.is_loading else -1

        current_state = (
            current_msg_id,
            current_msg_content,
            typewriter_state,
            loading_frame,
            props_hash
        )

        # Skip render if state hasn't changed
        if self.last_render_state == current_state and self.canvas:
            return

        self.last_render_state = current_state
        self.canvas_dirty = True  # Mark canvas as needing blit

        props = self.display_props
        bg = self._hex_to_rgb(props.get('bg_color', '#1e212b'))
        text_color = self._hex_to_rgb(props.get('text_color', '#f0f0f0'))
        accent = self._hex_to_rgb(props.get('accent_color', '#00aaff'))
        width = int(props.get('width', 400))
        radius = int(props.get('border_radius', 12))
        padding = int(props.get('content_padding', 16))
        max_height = int(props.get('max_height', 600))

        # Update renderer colors
        if self.md_renderer:
            self.md_renderer.set_colors(text_color, accent, bg)

        # Reuse temp canvas if possible
        temp_h = 2000
        if self.temp_image is None or self.temp_image.width != width or self.temp_image.height < temp_h:
            self.temp_image = Image.new('RGBA', (width, temp_h), (0, 0, 0, 0))
            self.temp_draw = ImageDraw.Draw(self.temp_image)
        else:
            # Clear existing canvas
            self.temp_draw.rectangle([(0, 0), (width, temp_h)], fill=(0, 0, 0, 0))

        temp = self.temp_image
        draw = self.temp_draw

        y = padding

        # Determine if we should draw message components
        should_draw_message = self.current_message is not None

        # Title pill
        if should_draw_message:
            title = self.current_message.get('title', '')
            if title:
                title_color = self._hex_to_rgb(self.current_message.get('color', '#00aaff'))
                font = self.fonts.get('bold', self.fonts['normal'])

                # Get text bounding box for accurate sizing
                bbox = font.getbbox(title)
                tw = bbox[2] - bbox[0]  # width
                th = bbox[3] - bbox[1]  # height

                # Pill dimensions - fixed height for consistency
                pill_padding_x = 14
                pill_h = 28  # Fixed pill height for consistent look
                pill_w = tw + pill_padding_x * 2

                # Modern pill with subtle shadow
                shadow_offset = 2
                draw.rounded_rectangle([padding + shadow_offset, y + shadow_offset,
                                       padding + pill_w + shadow_offset, y + pill_h + shadow_offset],
                                      radius=pill_h//2, fill=(0, 0, 0, 40))
                draw.rounded_rectangle([padding, y, padding + pill_w, y + pill_h],
                                      radius=pill_h//2, fill=title_color)

                # Center text using anchor='mm' (middle-middle) for true centering
                center_x = padding + pill_w // 2
                center_y = y + pill_h // 2
                draw.text((center_x, center_y), title, fill=bg, font=font, anchor='mm')
                y += pill_h + 10  # Spacing after title pill

            # Message content with Markdown
            msg = self.current_message.get('message', '')
            if msg:
                msg = self._strip_emotions(msg)
                max_chars = self.typewriter_char_count if self.typewriter_active else None

                # Use cached blocks if available and message hasn't changed
                if self.current_blocks is None or self.current_blocks.get('msg') != msg:
                    self.current_blocks = {
                        'msg': msg,
                        'blocks': self.md_renderer.parse_blocks(msg)
                    }

                y = self.md_renderer.render(
                    draw, temp, msg, padding, y, width - padding * 2, max_chars,
                    pre_parsed_blocks=self.current_blocks['blocks']
                )

            # Tool chips
            tools = self.current_message.get('tools', [])
            if tools:
                y += 10
                tx = padding
                th = 30

                # Group by source
                counts = {}
                for t in tools:
                    key = (t.get('source', 'System'), t.get('icon'))
                    counts[key] = counts.get(key, 0) + 1

                for (src, icon), cnt in counts.items():
                    font = self.fonts.get('code', self.fonts['normal'])
                    sw, sh = self._get_text_size(src, font)
                    icon_w = 24 if icon and os.path.exists(str(icon)) else 0
                    badge_w = 26 if cnt > 1 else 0
                    chip_w = sw + icon_w + badge_w + 26

                    if tx + chip_w > width - padding:
                        tx = padding
                        y += th + 10

                    # Modern chip with gradient-like effect
                    chip_bg = (42, 48, 60, 235)
                    draw.rounded_rectangle([tx, y, tx + chip_w, y + th], radius=th//2,
                                          fill=chip_bg, outline=accent)

                    ix = tx + 12
                    if icon and os.path.exists(str(icon)):
                        try:
                            if icon not in self.image_cache:
                                img = Image.open(icon).convert('RGBA').resize((18, 18), Image.Resampling.LANCZOS)
                                self.image_cache[icon] = img
                            temp.paste(self.image_cache[icon], (ix, y + 6), self.image_cache[icon])
                            ix += 22
                        except:
                            pass

                    draw.text((ix, y + (th - sh) // 2), src, fill=text_color, font=font)

                    if cnt > 1:
                        bw, bh = self._get_text_size(str(cnt), font)
                        bx = tx + chip_w - bw - 16
                        draw.ellipse([bx - 4, y + 5, bx + bw + 8, y + th - 5], fill=accent)
                        draw.text((bx + 2, y + 7), str(cnt), fill=bg, font=font)

                    tx += chip_w + 10

                y += th + 10

        # Loading animation
        if self.is_loading:
            y += 6
            self._draw_loading(draw, temp, padding, y, width - padding * 2, self.loading_color)
            y += 24

        # Calculate final height with configured bottom padding
        # Add extra padding at bottom to match visual balance with top/sides
        bottom_padding = padding - 4
        final_h = min(max(60, y + bottom_padding), max_height)

        # Create final canvas with background (reuse if possible)
        if self.canvas is None or self.canvas.width != width or self.canvas.height != final_h:
            self.canvas = Image.new('RGBA', (width, final_h), (255, 0, 255, 255))
        else:
            # Clear canvas (fill with transparent or background color)
            # Actually we draw a full rounded rectangle over it so clearing might not be strictly needed
            # if the rounded rect covers everything, but for safety (corners):
             self.canvas.paste((255, 0, 255, 255), (0, 0, width, final_h))

        final_draw = ImageDraw.Draw(self.canvas)

        # Modern background with subtle gradient feel
        final_draw.rounded_rectangle([0, 0, width - 1, final_h - 1], radius=radius,
                                    fill=bg + (255,), outline=(55, 62, 74))

        # Composite content
        content_height = y + bottom_padding
        crop_height = min(final_h, temp.height)
        crop = temp.crop((0, 0, width, crop_height))

        # Apply fade out if content exceeds max height
        if content_height > max_height:
            fade_height = 60
            if crop_height > fade_height:
                # Create alpha mask
                mask = Image.new('L', (width, crop_height), 255)
                mask_draw = ImageDraw.Draw(mask)

                # Draw gradient at the bottom
                for i in range(fade_height):
                    alpha = int(255 * (1 - (i / fade_height)))
                    line_y = crop_height - fade_height + i
                    mask_draw.line([(0, line_y), (width, line_y)], fill=alpha)

                # Apply mask to crop's alpha channel
                r, g, b, a = crop.split()
                new_alpha = ImageChops.multiply(a, mask)
                crop.putalpha(new_alpha)

        self.canvas.paste(crop, (0, 0), crop)

        # Update window
        if self.hwnd:
            user32.MoveWindow(self.hwnd, int(props.get('x', 20)), int(props.get('y', 20)), width, final_h, True)
            user32.SetLayeredWindowAttributes(self.hwnd, 0x00FF00FF, self.current_opacity, LWA_ALPHA | LWA_COLORKEY)

    def _blit_to_window(self, hwnd, canvas, wdc, mdc, is_persistent=False):
        if not hwnd or not canvas or not wdc or not mdc:
            return

        w, h = canvas.size

        # Check if DIB needs resize
        if is_persistent:
            if w != self.dib_width_persistent or h != self.dib_height_persistent:
                # Cleanup old
                if self.old_bitmap_persistent: gdi32.SelectObject(mdc, self.old_bitmap_persistent)
                if self.dib_bitmap_persistent: gdi32.DeleteObject(self.dib_bitmap_persistent)
                # Create new
                self.dib_width_persistent = w
                self.dib_height_persistent = h
                bmi = BITMAPINFO(); bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
                bmi.bmiHeader.biWidth = w; bmi.bmiHeader.biHeight = -h
                bmi.bmiHeader.biPlanes = 1; bmi.bmiHeader.biBitCount = 32
                bmi.bmiHeader.biCompression = BI_RGB
                self.dib_bits_persistent = ctypes.c_void_p()
                self.dib_bitmap_persistent = gdi32.CreateDIBSection(mdc, ctypes.byref(bmi), DIB_RGB_COLORS,
                                                          ctypes.byref(self.dib_bits_persistent), None, 0)
                if self.dib_bitmap_persistent: self.old_bitmap_persistent = gdi32.SelectObject(mdc, self.dib_bitmap_persistent)

            dib_bits = self.dib_bits_persistent
        else:
            if w != self.dib_width or h != self.dib_height:
                if self.old_bitmap: gdi32.SelectObject(mdc, self.old_bitmap)
                if self.dib_bitmap: gdi32.DeleteObject(self.dib_bitmap)
                self.dib_width = w
                self.dib_height = h
                bmi = BITMAPINFO(); bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
                bmi.bmiHeader.biWidth = w; bmi.bmiHeader.biHeight = -h
                bmi.bmiHeader.biPlanes = 1; bmi.bmiHeader.biBitCount = 32
                bmi.bmiHeader.biCompression = BI_RGB
                self.dib_bits = ctypes.c_void_p()
                self.dib_bitmap = gdi32.CreateDIBSection(mdc, ctypes.byref(bmi), DIB_RGB_COLORS,
                                                          ctypes.byref(self.dib_bits), None, 0)
                if self.dib_bitmap: self.old_bitmap = gdi32.SelectObject(mdc, self.dib_bitmap)

            dib_bits = self.dib_bits

        if not dib_bits:
            return

        try:
            rgba = canvas.tobytes('raw', 'BGRA')
            ctypes.memmove(dib_bits, rgba, len(rgba))
            gdi32.BitBlt(wdc, 0, 0, w, h, mdc, 0, 0, SRCCOPY)
        except:
            pass

    def _create_dib(self, w, h):
        self.dib_width = w
        self.dib_height = h
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        self.dib_bits = ctypes.c_void_p()
        self.dib_bitmap = gdi32.CreateDIBSection(self.mem_dc, ctypes.byref(bmi), DIB_RGB_COLORS,
                                                  ctypes.byref(self.dib_bits), None, 0)
        if self.dib_bitmap:
            self.old_bitmap = gdi32.SelectObject(self.mem_dc, self.dib_bitmap)

    def _cleanup_dib(self):
        if self.old_bitmap:
            gdi32.SelectObject(self.mem_dc, self.old_bitmap)
            self.old_bitmap = None
        if self.dib_bitmap:
            gdi32.DeleteObject(self.dib_bitmap)
            self.dib_bitmap = None
        self.dib_bits = None
        self.dib_width = self.dib_height = 0

    def _cleanup_gdi(self):
        self._cleanup_dib()

        # Cleanup persistent DIB
        if self.old_bitmap_persistent and self.mem_dc_persistent:
            gdi32.SelectObject(self.mem_dc_persistent, self.old_bitmap_persistent)
            self.old_bitmap_persistent = None
        if self.dib_bitmap_persistent:
            gdi32.DeleteObject(self.dib_bitmap_persistent)
            self.dib_bitmap_persistent = None

        if self.mem_dc:
            gdi32.DeleteDC(self.mem_dc)
            self.mem_dc = None
        if self.mem_dc_persistent:
            gdi32.DeleteDC(self.mem_dc_persistent)
            self.mem_dc_persistent = None

        if self.window_dc and self.hwnd:
            user32.ReleaseDC(self.hwnd, self.window_dc)
            self.window_dc = None
        if self.window_dc_persistent and self.hwnd_persistent:
            user32.ReleaseDC(self.hwnd_persistent, self.window_dc_persistent)
            self.window_dc_persistent = None

        # Cleanup chat windows
        for chat_name in list(self._chat_windows.keys()):
            self._cleanup_chat_window(chat_name)

    def _cleanup_chat_window(self, chat_name: str):
        """Clean up resources for a specific chat window."""
        # Unregister from layout manager
        self._layout_manager.unregister_window(f"chat_{chat_name}")

        # Cleanup DCs
        if chat_name in self._chat_window_dcs:
            window_dc, mem_dc = self._chat_window_dcs[chat_name]
            hwnd = self._chat_hwnds.get(chat_name)
            if mem_dc:
                gdi32.DeleteDC(mem_dc)
            if window_dc and hwnd:
                user32.ReleaseDC(hwnd, window_dc)
            del self._chat_window_dcs[chat_name]

        # Destroy window
        if chat_name in self._chat_hwnds:
            hwnd = self._chat_hwnds[chat_name]
            if hwnd:
                user32.DestroyWindow(hwnd)
            del self._chat_hwnds[chat_name]

        # Clean up state
        self._chat_windows.pop(chat_name, None)
        self._chat_window_dirty.pop(chat_name, None)
        self._chat_canvases.pop(chat_name, None)
        self._chat_last_render_state.pop(chat_name, None)

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
        self._safe_report({
            "type": "error",
            "context": context,
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc(),
            "ts": time.time(),
        })

    def _update_logic_main(self):
        if not self.hwnd:
            return

        # Typewriter progression (only affects main message)
        if self.typewriter_active and self.current_message:
            now = time.time()
            chars = (now - self.last_typewriter_update) * 200
            if chars > 0:
                self.typewriter_char_count += chars
                self.last_typewriter_update = now
                msg_len = len(self.current_message.get('message', ''))
                if self.typewriter_char_count >= msg_len:
                    self.typewriter_active = False
                    self.typewriter_char_count = float(msg_len)

        key = 0x00FF00FF
        fade_amount = int(1080 * self.dt)
        if fade_amount < 1: fade_amount = 1

        # Fade logic for main window
        if self.fade_state == 1:  # Fade in
            self.current_opacity = min(self.target_opacity, self.current_opacity + fade_amount)
            user32.SetLayeredWindowAttributes(self.hwnd, key, self.current_opacity, LWA_ALPHA | LWA_COLORKEY)
            if self.current_opacity >= self.target_opacity:
                self.fade_state = 2

        elif self.fade_state == 3:  # Fade out
            self.current_opacity = max(0, self.current_opacity - fade_amount)
            user32.SetLayeredWindowAttributes(self.hwnd, key, self.current_opacity, LWA_ALPHA | LWA_COLORKEY)
            if self.current_opacity <= 0:
                self.fade_state = 0
                self.current_message = None

        if self.fade_state == 2:
            # Tracking opacity target
            if self.current_opacity != self.target_opacity:
                if self.current_opacity < self.target_opacity:
                    self.current_opacity = min(self.target_opacity, self.current_opacity + fade_amount)
                else:
                    self.current_opacity = max(self.target_opacity, self.current_opacity - fade_amount)
                user32.SetLayeredWindowAttributes(self.hwnd, key, self.current_opacity, LWA_ALPHA | LWA_COLORKEY)

            # Auto fade out check
            should_fade_out = True

            # Don't fade out if loading
            if self.is_loading:
                should_fade_out = False
            # Check if message duration has passed
            elif self.current_message:
                now = time.time()
                if now <= self.min_display_time:
                    should_fade_out = False
            else:
                # No message, no loading -> fade out
                should_fade_out = True

            if should_fade_out:
                self.fade_state = 3

    def _check_collision(self) -> bool:
        """Check if main window overlaps with persistent window."""
        if not self.current_message or not self.persistent_infos:
            return False

        # Get Main Window Rect
        main_x = int(self.display_props.get('x', 20))
        main_y = int(self.display_props.get('y', 20))
        main_w = int(self.display_props.get('width', 400))
        # Use existing canvas height if available, otherwise estimate or assume max
        # It's safer to rely on canvas if _draw_main_frame ran at least once for this content
        main_h = self.canvas.height if self.canvas else 200

        # Get Persistent Window Rect
        pers_x = int(self.display_props.get('persistent_x', 20))
        pers_y = int(self.display_props.get('persistent_y', 300))
        pers_w = int(self.display_props.get('persistent_width', 300))
        pers_h = self.canvas_persistent.height if self.canvas_persistent else 200

        # Check intersection
        # Rect1: (main_x, main_y, main_x + main_w, main_y + main_h)
        # Rect2: (pers_x, pers_y, pers_x + pers_w, pers_y + pers_h)

        return not (main_x + main_w <= pers_x or
                    pers_x + pers_w <= main_x or
                    main_y + main_h <= pers_y or
                    pers_y + pers_h <= main_y)

    def _update_logic_persistent(self, collision_detected=False):
        if not self.hwnd_persistent:
            return

        now = time.time()

        # Check expiry
        expired = [k for k, v in self.persistent_infos.items() if v.get('expiry') and now > v['expiry']]
        for k in expired:
            del self.persistent_infos[k]

        # Determine target state
        has_content = bool(self.persistent_infos)

        # If collision detected, force hide irrespective of content
        should_show = has_content and not collision_detected

        if should_show and self.persistent_fade_state in (0, 3):
            self.persistent_fade_state = 1 # Start Fade in
        elif not should_show and self.persistent_fade_state in (1, 2):
            self.persistent_fade_state = 3 # Start Fade out

        key = 0x00FF00FF
        fade_amount = int(1080 * self.dt)
        if fade_amount < 1: fade_amount = 1

        if self.persistent_fade_state == 1: # Fade in
            self.persistent_opacity = min(self.target_opacity, self.persistent_opacity + fade_amount)
            user32.SetLayeredWindowAttributes(self.hwnd_persistent, key, self.persistent_opacity, LWA_ALPHA | LWA_COLORKEY)
            if self.persistent_opacity >= self.target_opacity:
                self.persistent_fade_state = 2

        elif self.persistent_fade_state == 3: # Fade out
            self.persistent_opacity = max(0, self.persistent_opacity - fade_amount)
            user32.SetLayeredWindowAttributes(self.hwnd_persistent, key, self.persistent_opacity, LWA_ALPHA | LWA_COLORKEY)
            if self.persistent_opacity <= 0:
                self.persistent_fade_state = 0

        elif self.persistent_fade_state == 2: # Visible
             if self.persistent_opacity != self.target_opacity:
                if self.persistent_opacity < self.target_opacity:
                    self.persistent_opacity = min(self.target_opacity, self.persistent_opacity + fade_amount)
                else:
                    self.persistent_opacity = max(self.target_opacity, self.persistent_opacity - fade_amount)
                user32.SetLayeredWindowAttributes(self.hwnd_persistent, key, self.persistent_opacity, LWA_ALPHA | LWA_COLORKEY)

    def _check_window_collision(self, msg_win: Optional[Dict], pers_win: Dict) -> bool:
        """Check if message window overlaps with persistent window (unified system)."""
        # No collision if no message window or message not visible
        if not msg_win:
            return False
        if not msg_win.get('current_message') and not msg_win.get('is_loading'):
            return False
        if msg_win.get('fade_state', 0) in (0, 3):  # Hidden or fading out
            return False

        # No collision if persistent window has no items
        if not pers_win.get('items'):
            return False

        # Get message window rect
        msg_props = msg_win.get('props', {})
        msg_x = int(msg_props.get('x', 20))
        msg_y = int(msg_props.get('y', 20))
        msg_w = int(msg_props.get('width', 400))
        msg_canvas = msg_win.get('canvas')
        msg_h = msg_canvas.height if msg_canvas else 200

        # Get persistent window rect
        pers_props = pers_win.get('props', {})
        pers_x = int(pers_props.get('x', pers_props.get('persistent_x', 20)))
        pers_y = int(pers_props.get('y', pers_props.get('persistent_y', 300)))
        pers_w = int(pers_props.get('width', pers_props.get('persistent_width', 300)))
        pers_canvas = pers_win.get('canvas')
        pers_h = pers_canvas.height if pers_canvas else 200

        # Check intersection (AABB test)
        return not (msg_x + msg_w <= pers_x or
                    pers_x + pers_w <= msg_x or
                    msg_y + msg_h <= pers_y or
                    pers_y + pers_h <= msg_y)

    def _update_persistent_fade(self, win: Dict, collision_detected: bool = False):
        """Update persistent window fade based on content and collision."""
        items = win.get('items', {})
        has_content = bool(items)

        # If collision detected, force hide
        should_show = has_content and not collision_detected

        fade_state = win.get('fade_state', 0)

        if should_show and fade_state in (0, 3):
            win['fade_state'] = 1  # Start fade in
        elif not should_show and fade_state in (1, 2):
            win['fade_state'] = 3  # Start fade out

    def run(self):
        try:
            if not PIL_AVAILABLE:
                self._report_exception("init", ImportError("PIL not available"))
                return

            if self.use_stdin:
                threading.Thread(target=self._read_stdin, daemon=True).start()

            if not _ensure_window_class():
                self._report_exception("init", RuntimeError("Failed to register window class"))
                return

            # Initialize Main Window
            w = int(self.display_props.get('width', 400))
            h = 100
            x = int(self.display_props.get('x', 20))
            y = int(self.display_props.get('y', 20))

            self.hwnd = self._create_overlay_window("HeadsUp", x, y, w, h)
            if not self.hwnd:
                self._report_exception("init", RuntimeError("Failed to create main window"))
                return

            self.window_dc, self.mem_dc = self._init_gdi(self.hwnd)

            # Initialize Persistent Window
            pw = int(self.display_props.get('persistent_width', 300))
            ph = 100
            px = int(self.display_props.get('persistent_x', 20))
            py = int(self.display_props.get('persistent_y', 300))

            try:
                self.hwnd_persistent = self._create_overlay_window("HeadsUpPersistent", px, py, pw, ph)
                if self.hwnd_persistent:
                    self.window_dc_persistent, self.mem_dc_persistent = self._init_gdi(self.hwnd_persistent)
            except Exception as e:
                self._report_exception("init_persistent", e)
                # Continue without persistent window if it fails?
                pass

            self._init_fonts()

            last_z = time.time()
            self.last_update_time = time.time()

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
                            msg_type = msg.get('type', 'unknown') if isinstance(msg, dict) else 'non-dict'
                            msg_group = msg.get('group', 'unknown') if isinstance(msg, dict) else 'n/a'
                            self._handle_message(msg)
                    except queue.Empty:
                        pass

                    # =========================================================
                    # UPDATE AND RENDER ALL UNIFIED WINDOWS
                    # =========================================================
                    self._update_all_windows()

                    # Update and draw chat windows
                    if self._chat_windows:
                        try:
                            self._update_chat_windows()
                            self._draw_chat_windows()
                        except Exception as e:
                            sys.stderr.write(f"Draw chat windows error: {e}\n")

                    now = time.time()
                    if now - last_z > 0.1:
                        # Bring all windows to top
                        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS
                        # Unified windows
                        for win in self._windows.values():
                            if win.get('hwnd'):
                                user32.SetWindowPos(win['hwnd'], HWND_TOPMOST, 0, 0, 0, 0, flags)
                        # Chat windows
                        for chat_hwnd in self._chat_hwnds.values():
                            if chat_hwnd:
                                user32.SetWindowPos(chat_hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
                        last_z = now

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
            # Cleanup unified windows
            for name in list(self._windows.keys()):
                self._destroy_window(name)
            # Cleanup legacy windows
            self._cleanup_gdi()
            if self.hwnd:
                user32.DestroyWindow(self.hwnd)
            if self.hwnd_persistent:
                user32.DestroyWindow(self.hwnd_persistent)

    def _handle_message(self, msg):
        try:
            t = msg.get('type')

            # Normalize command type names (support both modern and legacy names)
            type_aliases = {
                # Modern name -> handled as
                'show_message': 'draw',
                'hide_message': 'hide',
                'set_loader': 'loading',
                'add_item': 'add_persistent_info',
                'update_item': 'update_persistent_info',
                'remove_item': 'remove_persistent_info',
                'clear_items': 'clear_all_persistent_info',
                'show_timer': 'show_progress_timer',
            }
            t = type_aliases.get(t, t)

            # Normalize field names (support both 'content' and 'message', 'show' and 'state')
            if 'content' in msg and 'message' not in msg:
                msg['message'] = msg['content']
            if 'show' in msg and 'state' not in msg:
                msg['state'] = msg['show']
            if 'color' in msg and 'progress_color' not in msg and t in ('show_progress', 'show_progress_timer'):
                msg['progress_color'] = msg['color']

            # Extract group name (default to 'default' for backward compatibility)
            group = msg.get('group', 'default')

            # =====================================================================
            # GROUP MANAGEMENT COMMANDS
            # =====================================================================
            if t == 'create_group':
                props = msg.get('props', {})
                if group not in self._group_props:
                    self._group_props[group] = {}
                self._group_props[group].update(props)
                return

            elif t == 'update_group':
                props = msg.get('props', {})
                if group not in self._group_props:
                    self._group_props[group] = {}
                self._group_props[group].update(props)

                # Update existing windows for this group and force re-render
                matched_count = 0
                for name, state in self._windows.items():
                    if state.get('group') == group:
                        matched_count += 1
                        old_width = state['props'].get('width')
                        state['props'].update(props)
                        new_width = state['props'].get('width')
                        state['target_opacity'] = int(state['props'].get('opacity', 0.85) * 255)
                        # Invalidate render cache to force re-render with new props
                        state['last_render_state'] = None
                        state['canvas_dirty'] = True
                        # Clear cached canvas if width changed (forces new canvas creation)
                        if 'width' in props:
                            state['canvas'] = None
                        # Update layout manager with new layout properties
                        layout_kwargs = {}
                        if 'width' in props:
                            layout_kwargs['width'] = int(props['width'])
                        if 'anchor' in props:
                            try:
                                layout_kwargs['anchor'] = Anchor(props['anchor'])
                            except ValueError:
                                pass
                        if 'priority' in props:
                            layout_kwargs['priority'] = int(props['priority'])
                        if layout_kwargs:
                            self._layout_manager.update_window(name, **layout_kwargs)

                # Re-init fonts in case font properties changed
                old_size = self.fonts.get('_font_size') if self.fonts else None
                old_family = self.fonts.get('_font_family') if self.fonts else None
                new_size = props.get('font_size')
                new_family = props.get('font_family')
                if (new_size is not None and new_size != old_size) or (new_family is not None and new_family != old_family):
                    self._init_fonts()
                    # Rebuild markdown renderer with new fonts
                    text_color = self._hex_to_rgb(props.get('text_color', '#f0f0f0'))
                    accent_color = self._hex_to_rgb(props.get('accent_color', '#00aaff'))
                    bg_color = self._hex_to_rgb(props.get('bg_color', '#1e212b'))
                    colors = {'text': text_color, 'accent': accent_color, 'bg': bg_color}
                    color_emojis = props.get('color_emojis', True)
                    self.md_renderer = MarkdownRenderer(self.fonts, colors, color_emojis)
                return

            elif t == 'delete_group':
                self._group_props.pop(group, None)
                self._destroy_group_windows(group)
                return

            # =====================================================================
            # SYSTEM COMMANDS
            # =====================================================================
            if t == 'quit':
                self.running = False
                return

            # =====================================================================
            # MESSAGE WINDOW COMMANDS
            # =====================================================================
            elif t == 'hide':
                # Hide message window for this group
                win = self._get_window(self.WINDOW_TYPE_MESSAGE, group)
                if win:
                    win['fade_state'] = 3
                    win['current_message'] = None
                    win['is_loading'] = False
                    # Immediately notify layout manager that this window is now hidden
                    window_name = self._get_window_name(self.WINDOW_TYPE_MESSAGE, group)
                    self._layout_manager.set_window_visible(window_name, False)

            elif t == 'draw':
                # Get or create message window for this group
                props = msg.get('props', {})
                win = self._ensure_window(self.WINDOW_TYPE_MESSAGE, group, props)

                new_msg = msg.get('message', '')
                old_msg = win['current_message'].get('message', '') if win['current_message'] else ''
                is_append = win['current_message'] and old_msg and new_msg.startswith(old_msg)

                if props:
                    # Check for font changes
                    old_size = win['props'].get('font_size')
                    old_family = win['props'].get('font_family')

                    # Update window props (excluding persistent_* keys)
                    msg_props = {k: v for k, v in props.items()
                                if not k.startswith('persistent_')}
                    win['props'].update(msg_props)
                    win['target_opacity'] = int(win['props'].get('opacity', 0.85) * 255)

                    new_size = win['props'].get('font_size')
                    new_family = win['props'].get('font_family')

                    # Re-init fonts if size or family changed
                    if old_size != new_size or old_family != new_family:
                        self._init_fonts()
                        colors = {
                            'text': self._hex_to_rgb(win['props'].get('text_color', '#f0f0f0')),
                            'accent': self._hex_to_rgb(win['props'].get('accent_color', '#00aaff')),
                            'bg': self._hex_to_rgb(win['props'].get('bg_color', '#1e212b'))
                        }
                        color_emojis = win['props'].get('color_emojis', True)
                        self.md_renderer = MarkdownRenderer(self.fonts, colors, color_emojis)
                        win['current_blocks'] = None
                        win['last_render_state'] = None

                win['current_message'] = msg

                if not is_append:
                    if win['props'].get('typewriter_effect', True):
                        win['typewriter_active'] = True
                        win['typewriter_char_count'] = 0
                        win['last_typewriter_update'] = time.time()
                    else:
                        win['typewriter_active'] = False
                        win['typewriter_char_count'] = len(new_msg)
                    # Clear cached blocks and render state for new message
                    win['current_blocks'] = None
                    win['last_render_state'] = None

                if win['fade_state'] != 2:
                    win['fade_state'] = 1
                    # Immediately notify layout manager that this window is now visible
                    window_name = self._get_window_name(self.WINDOW_TYPE_MESSAGE, group)
                    self._layout_manager.set_window_visible(window_name, True)

                win['min_display_time'] = time.time() + win['props'].get('duration', 8.0)

            elif t == 'loading':
                # Get or create message window for this group (loader can work without message)
                win = self._ensure_window(self.WINDOW_TYPE_MESSAGE, group, msg.get('props', {}))
                win['is_loading'] = msg.get('state', False)
                if msg.get('color'):
                    win['loading_color'] = self._hex_to_rgb(msg['color'])
                # If showing loader, ensure window is visible
                if win['is_loading'] and win['fade_state'] in (0, 3):
                    win['fade_state'] = 1
                    # Immediately notify layout manager that this window is now visible
                    window_name = self._get_window_name(self.WINDOW_TYPE_MESSAGE, group)
                    self._layout_manager.set_window_visible(window_name, True)

            # =====================================================================
            # PERSISTENT WINDOW COMMANDS
            # =====================================================================
            elif t == 'add_persistent_info':
                title = msg.get('title')
                if title:
                    props = msg.get('props', {})
                    win = self._ensure_window(self.WINDOW_TYPE_PERSISTENT, group, props)

                    now = time.time()
                    info = {
                        'title': title,
                        'description': msg.get('description', ''),
                        'added_at': win['items'].get(title, {}).get('added_at', now),
                        '_group': group,
                    }
                    if msg.get('duration'):
                        info['expiry'] = now + float(msg['duration'])
                    win['items'][title] = info


            elif t == 'update_persistent_info':
                title = msg.get('title')
                if title:
                    win = self._get_window(self.WINDOW_TYPE_PERSISTENT, group)
                    if win and title in win['items']:
                        info = win['items'][title]
                        if msg.get('description') is not None:
                            info['description'] = msg['description']
                        if msg.get('duration') is not None:
                            info['expiry'] = time.time() + float(msg['duration'])

            elif t == 'show_progress':
                title = msg.get('title')
                if title:
                    props = msg.get('props', {})
                    win = self._ensure_window(self.WINDOW_TYPE_PERSISTENT, group, props)

                    target_current = float(msg.get('current', 0))
                    target_maximum = float(msg.get('maximum', 100))
                    auto_close = msg.get('auto_close', False)
                    now = time.time()

                    # Initialize or update animation state
                    if title in win['progress_animations']:
                        anim = win['progress_animations'][title]
                        anim['start_value'] = anim['current']
                        anim['target'] = target_current
                        anim['start_time'] = now
                    else:
                        win['progress_animations'][title] = {
                            'current': 0.0,
                            'start_value': 0.0,
                            'target': target_current,
                            'start_time': now,
                        }

                    info = {
                        'title': title,
                        'description': msg.get('description', ''),
                        'added_at': win['items'].get(title, {}).get('added_at', now),
                        'is_progress': True,
                        'progress_current': target_current,
                        'progress_maximum': target_maximum,
                        'progress_color': msg.get('progress_color'),
                        'auto_close': auto_close,
                        'auto_close_triggered': False,
                        '_group': group,
                    }
                    win['items'][title] = info


            elif t == 'show_progress_timer':
                title = msg.get('title')
                if title:
                    props = msg.get('props', {})
                    win = self._ensure_window(self.WINDOW_TYPE_PERSISTENT, group, props)

                    duration = float(msg.get('duration', 10))
                    auto_close = msg.get('auto_close', True)
                    now = time.time()

                    initial_progress = float(msg.get('initial_progress', 0.0))
                    timer_start_time = now - initial_progress

                    start_percentage = 0.0
                    if initial_progress > 0 and duration > 0:
                        start_percentage = min(100, (initial_progress / duration) * 100)

                    win['progress_animations'][title] = {
                        'current': start_percentage,
                        'start_value': start_percentage,
                        'target': start_percentage,
                        'start_time': now,
                        'is_timer': True,
                        'timer_start': timer_start_time,
                        'timer_duration': duration,
                    }

                    info = {
                        'title': title,
                        'description': msg.get('description', ''),
                        'added_at': now,
                        'is_progress': True,
                        'is_timer': True,
                        'timer_start': timer_start_time,
                        'timer_duration': duration,
                        'progress_current': start_percentage,
                        'progress_maximum': 100,
                        'progress_color': msg.get('progress_color'),
                        'auto_close': auto_close,
                        'auto_close_triggered': False,
                        '_group': group,
                    }
                    win['items'][title] = info


            elif t == 'update_progress':
                title = msg.get('title')
                if title:
                    win = self._get_window(self.WINDOW_TYPE_PERSISTENT, group)
                    if win and title in win['items']:
                        info = win['items'][title]
                        if info.get('is_progress'):
                            now = time.time()
                            target_current = float(msg.get('current', info.get('progress_current', 0)))

                            if title in win['progress_animations']:
                                anim = win['progress_animations'][title]
                                anim['start_value'] = anim['current']
                                anim['target'] = target_current
                                anim['start_time'] = now

                            info['progress_current'] = target_current
                            if msg.get('maximum') is not None:
                                info['progress_maximum'] = float(msg['maximum'])
                            if msg.get('description') is not None:
                                info['description'] = msg['description']


            elif t == 'remove_persistent_info':
                title = msg.get('title')
                if title:
                    win = self._get_window(self.WINDOW_TYPE_PERSISTENT, group)
                    if win and title in win['items']:
                        del win['items'][title]
                        if title in win['progress_animations']:
                            del win['progress_animations'][title]

            elif t == 'clear_all_persistent_info':
                win = self._get_window(self.WINDOW_TYPE_PERSISTENT, group)
                if win:
                    win['items'].clear()
                    win['progress_animations'].clear()

            # =====================================================================
            # Chat Window Commands
            # =====================================================================
            elif t == 'create_chat_window':
                chat_name = msg.get('name')
                if chat_name:
                    props = msg.get('props', {})
                    # Set default chat window props
                    default_props = {
                        'width': 400, 'max_height': 400,
                        'bg_color': '#1e212b', 'text_color': '#f0f0f0',
                        'accent_color': '#00aaff', 'opacity': 0.85,
                        'border_radius': 12, 'content_padding': 12,
                        'font_size': 14, 'auto_hide': False,
                        'auto_hide_delay': 10.0, 'max_messages': 50,
                        'sender_colors': {}, 'show_timestamps': False,
                        'message_spacing': 8, 'fade_old_messages': True,
                        'is_chat_window': True,
                        # Layout manager props (margin/spacing now global)
                        'anchor': 'top_left',
                        'priority': 5,  # Lower than messages by default
                        'layout_mode': 'auto',
                    }
                    default_props.update(props)
                    # Also merge top-level msg properties for backwards compatibility
                    for key in ['x', 'y', 'width', 'max_height', 'auto_hide', 'auto_hide_delay',
                                'max_messages', 'sender_colors', 'fade_old_messages',
                                'anchor', 'priority', 'layout_mode']:
                        if key in msg and msg[key] is not None:
                            default_props[key] = msg[key]

                    self._chat_windows[chat_name] = {
                        'messages': [],
                        'props': default_props,
                        'last_message_time': 0,
                        'visible': True,
                        'opacity': 0,
                        'fade_state': 0,  # hidden
                    }
                    self._chat_window_dirty[chat_name] = True

                    # Create window for this chat
                    w = int(default_props.get('width', 400))
                    h = int(default_props.get('max_height', 400))

                    # Register with layout manager
                    layout_mode = default_props.get('layout_mode', 'auto')
                    if layout_mode == 'auto':
                        anchor_str = default_props.get('anchor', 'top_left')
                        priority = int(default_props.get('priority', 5))

                        # Convert string anchor to Anchor enum
                        anchor_map = {
                            'top_left': Anchor.TOP_LEFT,
                            'top_center': Anchor.TOP_CENTER,
                            'top_right': Anchor.TOP_RIGHT,
                            'left_center': Anchor.LEFT_CENTER,
                            'center': Anchor.CENTER,
                            'right_center': Anchor.RIGHT_CENTER,
                            'bottom_left': Anchor.BOTTOM_LEFT,
                            'bottom_center': Anchor.BOTTOM_CENTER,
                            'bottom_right': Anchor.BOTTOM_RIGHT,
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
                        x = pos[0] if pos else int(default_props.get('x', 20))
                        y = pos[1] if pos else int(default_props.get('y', 20))
                    else:
                        # Manual mode - use x/y directly
                        x = int(default_props.get('x', 20))
                        y = int(default_props.get('y', 20))

                    hwnd = self._create_overlay_window(f"HeadsUpChat_{chat_name}", x, y, w, h)
                    if hwnd:
                        self._chat_hwnds[chat_name] = hwnd
                        window_dc, mem_dc = self._init_gdi(hwnd)
                        self._chat_window_dcs[chat_name] = (window_dc, mem_dc)

            elif t == 'update_chat_window':
                chat_name = msg.get('name')
                if chat_name and chat_name in self._chat_windows:
                    props = msg.get('props', {})
                    self._chat_windows[chat_name]['props'].update(props)
                    self._chat_window_dirty[chat_name] = True

                    # Update window position if changed
                    if 'x' in props or 'y' in props or 'width' in props or 'max_height' in props:
                        hwnd = self._chat_hwnds.get(chat_name)
                        if hwnd:
                            chat_props = self._chat_windows[chat_name]['props']
                            x = int(chat_props.get('x', 20))
                            y = int(chat_props.get('y', 20))
                            w = int(chat_props.get('width', 400))
                            h = int(chat_props.get('max_height', 400))
                            user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE)

            elif t == 'delete_chat_window':
                chat_name = msg.get('name')
                if chat_name:
                    self._cleanup_chat_window(chat_name)

            elif t == 'chat_message':
                chat_name = msg.get('name')
                if chat_name and chat_name in self._chat_windows:
                    now = time.time()
                    message = {
                        'sender': msg.get('sender', ''),
                        'text': msg.get('text', ''),
                        'color': msg.get('color'),
                        'timestamp': now,
                    }
                    chat = self._chat_windows[chat_name]
                    chat['messages'].append(message)
                    chat['last_message_time'] = now

                    # Trim old messages if over limit
                    max_messages = chat['props'].get('max_messages', 50)
                    if len(chat['messages']) > max_messages:
                        chat['messages'] = chat['messages'][-max_messages:]

                    # Show window if auto-hide was triggered
                    if chat['fade_state'] == 0 or chat['fade_state'] == 3:
                        chat['fade_state'] = 1  # fade in
                        chat['visible'] = True
                        # Immediately notify layout manager
                        self._layout_manager.set_window_visible(f"chat_{chat_name}", True)

                    self._chat_window_dirty[chat_name] = True

            elif t == 'clear_chat_window':
                chat_name = msg.get('name')
                if chat_name and chat_name in self._chat_windows:
                    self._chat_windows[chat_name]['messages'] = []
                    self._chat_window_dirty[chat_name] = True

            elif t == 'show_chat_window':
                chat_name = msg.get('name')
                if chat_name and chat_name in self._chat_windows:
                    chat = self._chat_windows[chat_name]
                    chat['visible'] = True
                    chat['fade_state'] = 1  # fade in
                    # Immediately notify layout manager
                    self._layout_manager.set_window_visible(f"chat_{chat_name}", True)
                    self._chat_window_dirty[chat_name] = True

            elif t == 'hide_chat_window':
                chat_name = msg.get('name')
                if chat_name and chat_name in self._chat_windows:
                    chat = self._chat_windows[chat_name]
                    chat['fade_state'] = 3  # fade out
                    # Immediately notify layout manager
                    self._layout_manager.set_window_visible(f"chat_{chat_name}", False)
                    self._chat_window_dirty[chat_name] = True

        except Exception as e:
            self._report_exception("handle_message", e)

    def _create_overlay_window(self, name, x, y, w, h):
        ex = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        hwnd = user32.CreateWindowExW(ex, _class_name, name, WS_POPUP, x, y, w, h,
                                           None, None, kernel32.GetModuleHandleW(None), None)
        if hwnd:
            user32.SetLayeredWindowAttributes(hwnd, 0x00FF00FF, 0, LWA_ALPHA | LWA_COLORKEY)
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)
        return hwnd

    def _init_gdi(self, hwnd):
        if not hwnd: return None, None
        window_dc = user32.GetDC(hwnd)
        mem_dc = gdi32.CreateCompatibleDC(window_dc)
        return window_dc, mem_dc

    def _draw_progress_bar(self, draw: ImageDraw.Draw, img: Image.Image, x: int, y: int,
                          width: int, height: int, percentage: float,
                          bg_color: Tuple[int, int, int],
                          fill_color: Tuple[int, int, int],
                          text_color: Tuple[int, int, int]) -> int:
        """
        Draw a modern, sleek progress bar with antialiasing via supersampling.

        Uses 2x supersampling for smooth edges on rounded corners.

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

        # Create high-resolution buffer for the progress bar
        bar_buffer = Image.new('RGBA', (width * scale, height * scale), (0, 0, 0, 0))
        bar_draw = ImageDraw.Draw(bar_buffer)

        scaled_height = height * scale
        scaled_width = width * scale
        radius = scaled_height // 2  # Fully rounded ends at scaled size

        # Draw background track
        track_color = tuple(max(0, c - 30) for c in bg_color)
        bar_draw.rounded_rectangle(
            [0, 0, scaled_width - 1, scaled_height - 1],
            radius=radius,
            fill=track_color + (255,),
            outline=tuple(max(0, c - 50) for c in bg_color) + (150,)
        )

        # Calculate fill width at scaled size
        fill_width = int((scaled_width - 2 * scale) * percentage / 100)

        if fill_width > radius:  # Only draw if there's meaningful progress
            fill_x = scale
            fill_y = scale
            fill_h = scaled_height - 2 * scale
            inner_radius = max(1, radius - scale)

            # Draw the main fill
            bar_draw.rounded_rectangle(
                [fill_x, fill_y, fill_x + fill_width, fill_y + fill_h],
                radius=inner_radius,
                fill=fill_color + (255,)
            )

            # Create gradient overlay for depth effect
            gradient_overlay = Image.new('RGBA', (fill_width + 1, fill_h + 1), (0, 0, 0, 0))
            gradient_draw = ImageDraw.Draw(gradient_overlay)

            # Top highlight (lighter)
            highlight_height = fill_h // 3
            for i in range(highlight_height):
                alpha = int(60 * (1 - i / highlight_height))
                highlight_color = (255, 255, 255, alpha)
                gradient_draw.line([(0, i), (fill_width, i)], fill=highlight_color)

            # Bottom shadow (darker)
            shadow_height = fill_h // 4
            for i in range(shadow_height):
                alpha = int(40 * (i / shadow_height))
                shadow_color = (0, 0, 0, alpha)
                gradient_draw.line([(0, fill_h - shadow_height + i), (fill_width, fill_h - shadow_height + i)], fill=shadow_color)

            # Create a mask from the fill shape to apply gradient only within the bar
            mask = Image.new('L', (scaled_width, scaled_height), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle(
                [fill_x, fill_y, fill_x + fill_width, fill_y + fill_h],
                radius=inner_radius,
                fill=255
            )

            # Composite the gradient onto the bar buffer
            gradient_full = Image.new('RGBA', (scaled_width, scaled_height), (0, 0, 0, 0))
            gradient_full.paste(gradient_overlay, (fill_x, fill_y))
            bar_buffer = Image.composite(
                Image.alpha_composite(bar_buffer, gradient_full),
                bar_buffer,
                mask
            )

            # Add a subtle inner glow/shine at the top edge
            shine_buffer = Image.new('RGBA', (scaled_width, scaled_height), (0, 0, 0, 0))
            shine_draw = ImageDraw.Draw(shine_buffer)

            # Draw a thin highlight line at the top of the fill
            shine_y = fill_y + scale
            shine_start = fill_x + inner_radius
            shine_end = fill_x + fill_width - inner_radius
            if shine_end > shine_start:
                shine_color = tuple(min(255, c + 80) for c in fill_color) + (120,)
                shine_draw.line([(shine_start, shine_y), (shine_end, shine_y)], fill=shine_color, width=scale)
                shine_draw.line([(shine_start, shine_y + scale), (shine_end, shine_y + scale)],
                               fill=tuple(min(255, c + 40) for c in fill_color) + (60,), width=scale)

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

    def _draw_persistent_frame(self):
        if not self.persistent_infos:
            return

        # Check render state
        try:
            props_hash = tuple(sorted((k, v) for k, v in self.display_props.items() if isinstance(v, (str, int, float, bool, tuple))))
        except:
            props_hash = str(self.display_props)

        # Synchronize ALL timer updates to the same tick
        now = time.time()
        current_second = int(now)
        sync_time = float(current_second)
        self._persistent_render_time = sync_time

        # Update progress animations and check if any are active
        animations_active = False
        items_to_remove = []

        for title, anim in list(self._progress_animations.items()):
            if title not in self.persistent_infos:
                continue

            info = self.persistent_infos[title]

            # Handle timer-based progress bars
            if anim.get('is_timer'):
                timer_elapsed = now - anim['timer_start']
                timer_duration = anim['timer_duration']
                timer_progress = min(100, (timer_elapsed / timer_duration) * 100)

                # Update both animation current and target for timer
                anim['current'] = timer_progress
                anim['target'] = timer_progress
                info['progress_current'] = timer_progress

                if timer_elapsed < timer_duration:
                    # Optimization: For timers > 100s, changes are <1% per second
                    # No need for smooth animation, just update once per second
                    if timer_duration <= 100:
                        animations_active = True  # Short timers get smooth animation
                elif info.get('auto_close') and not info.get('auto_close_triggered'):
                    # Timer completed, schedule auto-close
                    info['auto_close_triggered'] = True
                    info['auto_close_time'] = now + 2.0  # 2 second delay
                    animations_active = True  # Keep animating for auto-close
            else:
                # Regular progress bar animation
                elapsed = now - anim.get('start_time', now)
                duration = self._progress_transition_duration

                if duration > 0 and elapsed < duration:
                    # Easing function (ease-out cubic)
                    t = elapsed / duration
                    t = 1 - (1 - t) ** 3
                    anim['current'] = anim['start_value'] + (anim['target'] - anim['start_value']) * t
                    animations_active = True
                else:
                    anim['current'] = anim['target']

                # Check for auto-close on 100%
                percentage = (anim['current'] / info.get('progress_maximum', 100)) * 100
                if percentage >= 100 and info.get('auto_close') and not info.get('auto_close_triggered'):
                    info['auto_close_triggered'] = True
                    info['auto_close_time'] = now + 2.0  # 2 second delay
                    animations_active = True

            # Handle auto-close removal
            if info.get('auto_close_triggered') and info.get('auto_close_time'):
                if now >= info['auto_close_time']:
                    items_to_remove.append(title)
                else:
                    animations_active = True

        # Remove items scheduled for auto-close
        for title in items_to_remove:
            if title in self.persistent_infos:
                del self.persistent_infos[title]
            if title in self._progress_animations:
                del self._progress_animations[title]

        persistent_state_list = []
        has_active_timers = False
        for k, v in sorted(self.persistent_infos.items()):
            if v.get('expiry'):
                rem = max(0, int(v['expiry'] - sync_time + 0.999))
            else:
                rem = -1
            progress_state = None
            if v.get('is_progress'):
                # Check if this is an active timer
                if v.get('is_timer'):
                    timer_elapsed = now - v.get('timer_start', now)
                    if timer_elapsed < v.get('timer_duration', 0):
                        has_active_timers = True
                # Use animated value for state hash if animating
                if k in self._progress_animations:
                    animated_value = self._progress_animations[k]['current']
                    progress_state = (animated_value, v.get('progress_maximum', 100))
                else:
                    progress_state = (v.get('progress_current', 0), v.get('progress_maximum', 100))
            persistent_state_list.append((k, v['description'], rem, progress_state))
        persistent_state = tuple(persistent_state_list)

        # Determine render frequency based on what's active:
        # - Smooth animations (progress bar transitions) need configured framerate
        # - Timers only need 1fps (once per second) since we show whole seconds only
        configured_fps = int(self.display_props.get('framerate', 60))
        if animations_active:
            # Smooth transitions need configured framerate
            anim_frame = int(now * configured_fps)
            needs_continuous_render = True
        elif has_active_timers:
            # Timers only need to update once per second (whole seconds display)
            anim_frame = current_second
            needs_continuous_render = True
        else:
            anim_frame = 0
            needs_continuous_render = False

        current_state = (persistent_state, props_hash, current_second, anim_frame)

        # Skip re-render if state unchanged
        if not needs_continuous_render and self.last_render_state_persistent == current_state and self.canvas_persistent:
            return

        self.last_render_state_persistent = current_state
        self.canvas_persistent_dirty = True

        props = self.display_props
        bg = self._hex_to_rgb(props.get('bg_color', '#1e212b'))
        text_color = self._hex_to_rgb(props.get('text_color', '#f0f0f0'))
        accent = self._hex_to_rgb(props.get('accent_color', '#00aaff'))

        width = int(props.get('persistent_width', 300))
        radius = int(props.get('border_radius', 12))
        padding = int(props.get('content_padding', 16))

        # Update renderer colors
        if self.md_renderer:
            self.md_renderer.set_colors(text_color, accent, bg)

        # We need a temp canvas
        temp_h = 2000
        temp = Image.new('RGBA', (width, temp_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(temp)

        y = padding
        font_bold = self.fonts.get('bold', self.fonts['normal'])
        font_normal = self.fonts['normal']

        for title, info in sorted(self.persistent_infos.items(), key=lambda x: x[1]['added_at']):
             # Check expiry but don't delete (logic does that)
             if info.get('expiry') and self._persistent_render_time > info['expiry']:
                 continue

             # Calculate timer width/draw timer for expiry OR progress timer
             timer_w = 0
             timer_text = None

             # For progress items with timer, calculate remaining time
             if info.get('is_progress') and info.get('is_timer'):
                 timer_start = info.get('timer_start', self._persistent_render_time)
                 timer_duration = info.get('timer_duration', 0)
                 elapsed_time = self._persistent_render_time - timer_start
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
                 if d > 0: parts.append(f"{d}d")
                 if h > 0: parts.append(f"{h}h")
                 if m > 0: parts.append(f"{m}m")
                 parts.append(f"{s}s")

                 timer_text = " ".join(parts)
             elif info.get('expiry'):
                 remaining = max(0, int(info['expiry'] - self._persistent_render_time + 0.999))
                 r = remaining
                 d = r // 86400
                 r %= 86400
                 h = r // 3600
                 r %= 3600
                 m = r // 60
                 s = r % 60

                 parts = []
                 if d > 0: parts.append(f"{d}d")
                 if h > 0: parts.append(f"{h}h")
                 if m > 0: parts.append(f"{m}m")
                 parts.append(f"{s}s")

                 timer_text = " ".join(parts)

             if timer_text:
                 timer_w, _ = self._get_text_size(timer_text, font_bold)
                 draw.text((width - padding - timer_w, y), timer_text, fill=text_color + (255,), font=font_bold)
                 timer_w += 10

             # Title Row - render with emoji support
             max_title_w = width - (padding * 2) - timer_w
             title_lines = title.split('\n')
             final_lines = []
             for line in title_lines:
                 if self.md_renderer:
                     wrapped = self.md_renderer._wrap_text(line, font_bold, max_title_w)
                     final_lines.extend(wrapped)
                 else:
                     final_lines.append(line)

             for i, line in enumerate(final_lines):
                 # Render title with emoji support
                 self._render_text_with_emoji(draw, line, padding, y, accent + (255,), font_bold)
                 y += 20

             if final_lines:
                 y += 8
             else:
                 y += 20

             # Check if this is a progress bar item
             if info.get('is_progress'):
                 progress_maximum = float(info.get('progress_maximum', 100))
                 if title in self._progress_animations:
                     progress_current = self._progress_animations[title]['current']
                 else:
                     progress_current = float(info.get('progress_current', 0))

                 if progress_maximum <= 0:
                     progress_maximum = 100

                 percentage = min(100, max(0, (progress_current / progress_maximum) * 100))
                 progress_color = accent
                 if info.get('progress_color'):
                     progress_color = self._hex_to_rgb(info['progress_color'])

                 bar_height = 16
                 bar_width = width - (padding * 2)

                 y += 4  # Margin above progress bar
                 y = self._draw_progress_bar(
                     draw, temp, padding, y, bar_width, bar_height,
                     percentage, bg, progress_color, text_color
                 )

                 # Draw percentage below progress bar
                 values_text = f"{percentage:.0f}%"

                 values_font = self.fonts.get('normal', font_normal)
                 try:
                     bbox = values_font.getbbox(values_text)
                     values_width = bbox[2] - bbox[0]
                 except:
                     values_width = len(values_text) * 7

                 values_x = padding + (bar_width - values_width) // 2
                 values_color = tuple(c - 40 if c > 40 else c for c in text_color) + (200,)
                 draw.text((values_x, y), values_text, fill=values_color, font=values_font)
                 y += 18

                 desc = info.get('description', '')
                 if desc:
                     desc = self._strip_emotions(desc)
                     y += 4
                     y = self.md_renderer.render(
                        draw, temp, desc, padding, y, width - padding * 2
                     )
             else:
                 desc = info.get('description', '')
                 if desc:
                     desc = self._strip_emotions(desc)
                     y = self.md_renderer.render(
                        draw, temp, desc, padding, y, width - padding * 2
                     )

             # Add spacing after item
             y += 8

        # Finish
        bottom_padding = padding - 4
        final_h = max(60, y + bottom_padding)

        if self.canvas_persistent is None or self.canvas_persistent.width != width or self.canvas_persistent.height != final_h:
            self.canvas_persistent = Image.new('RGBA', (width, final_h), (255, 0, 255, 255))
        else:
            self.canvas_persistent.paste((255, 0, 255, 255), (0, 0, width, final_h))

        final_draw = ImageDraw.Draw(self.canvas_persistent)
        final_draw.rounded_rectangle([0, 0, width - 1, final_h - 1], radius=radius,
                                    fill=bg + (255,), outline=(55, 62, 74))

        crop = temp.crop((0, 0, width, final_h))
        self.canvas_persistent.paste(crop, (0, 0), crop)

        if self.hwnd_persistent:
            user32.MoveWindow(self.hwnd_persistent,
                            int(props.get('persistent_x', 20)),
                            int(props.get('persistent_y', 300)),
                            width, final_h, True)
            user32.SetLayeredWindowAttributes(self.hwnd_persistent, 0x00FF00FF, self.persistent_opacity, LWA_ALPHA | LWA_COLORKEY)

    # =========================================================================
    # Chat Window Rendering
    # =========================================================================

    def _update_chat_windows(self):
        """Update all chat windows (fade logic and auto-hide)."""
        now = time.time()
        fade_speed = 600  # opacity units per second

        for chat_name, chat in list(self._chat_windows.items()):
            props = chat['props']
            auto_hide = props.get('auto_hide', False)
            auto_hide_delay = props.get('auto_hide_delay', 10.0)
            old_fade_state = chat['fade_state']

            # Check auto-hide
            if auto_hide and chat['messages'] and chat['fade_state'] == 2:
                if now - chat['last_message_time'] > auto_hide_delay:
                    chat['fade_state'] = 3  # Start fade out

            # Handle fade states
            if chat['fade_state'] == 1:  # Fade in
                chat['opacity'] = min(255, chat['opacity'] + fade_speed * self.dt)
                if chat['opacity'] >= 255:
                    chat['opacity'] = 255
                    chat['fade_state'] = 2  # Visible
                self._chat_window_dirty[chat_name] = True

            elif chat['fade_state'] == 3:  # Fade out
                chat['opacity'] = max(0, chat['opacity'] - fade_speed * self.dt)
                if chat['opacity'] <= 0:
                    chat['opacity'] = 0
                    chat['fade_state'] = 0  # Hidden
                    chat['visible'] = False
                self._chat_window_dirty[chat_name] = True

            # Update layout manager visibility when fade state changes
            if old_fade_state != chat['fade_state']:
                layout_name = f"chat_{chat_name}"
                is_visible = chat['fade_state'] in (1, 2)  # Visible when fading in or fully visible
                self._layout_manager.set_window_visible(layout_name, is_visible)

            # Update position from layout manager for visible windows
            if chat['fade_state'] in (1, 2):
                layout_mode = props.get('layout_mode', 'auto')
                if layout_mode == 'auto':
                    layout_name = f"chat_{chat_name}"
                    pos = self._layout_manager.get_position(layout_name)
                    if pos:
                        hwnd = self._chat_hwnds.get(chat_name)
                        if hwnd:
                            x, y = pos
                            w = int(props.get('width', 400))
                            h = int(props.get('max_height', 400))
                            # Check if position changed
                            old_x = chat.get('_last_x', -1)
                            old_y = chat.get('_last_y', -1)
                            if x != old_x or y != old_y:
                                user32.MoveWindow(hwnd, x, y, w, h, True)
                                chat['_last_x'] = x
                                chat['_last_y'] = y
                                self._chat_window_dirty[chat_name] = True

    def _draw_chat_windows(self):
        """Draw all visible chat windows."""
        for chat_name, chat in self._chat_windows.items():
            if chat['opacity'] <= 0:
                continue

            try:
                self._draw_chat_frame(chat_name, chat)
            except Exception as e:
                sys.stderr.write(f"Draw chat window error: {e}\n")

    def _draw_chat_frame(self, chat_name: str, chat: Dict):
        """Draw a single chat window frame with full markdown support."""
        props = chat['props']
        messages = chat['messages']

        # Build state hash for caching
        msg_state = tuple((m['sender'], m['text'], m.get('color')) for m in messages[-50:])
        props_hash = (
            props.get('width'), props.get('max_height'),
            props.get('bg_color'), props.get('text_color'),
            props.get('accent_color'), props.get('font_size'),
            props.get('message_spacing'), props.get('fade_old_messages'),
        )
        current_state = (msg_state, props_hash, int(chat['opacity']))

        # Skip redraw if unchanged
        if chat_name in self._chat_last_render_state:
            if self._chat_last_render_state[chat_name] == current_state:
                if chat_name in self._chat_canvases and not self._chat_window_dirty.get(chat_name, False):
                    # Just update opacity and position
                    hwnd = self._chat_hwnds.get(chat_name)
                    if hwnd:
                        user32.SetLayeredWindowAttributes(
                            hwnd, 0x00FF00FF, int(chat['opacity']), LWA_ALPHA | LWA_COLORKEY
                        )
                        # Also update position from layout manager
                        layout_mode = props.get('layout_mode', 'auto')
                        if layout_mode == 'auto':
                            layout_name = f"chat_{chat_name}"
                            pos = self._layout_manager.get_position(layout_name)
                            if pos:
                                canvas = self._chat_canvases[chat_name]
                                w, h = canvas.size
                                x, y = pos
                                old_x = chat.get('_last_x', -1)
                                old_y = chat.get('_last_y', -1)
                                if x != old_x or y != old_y:
                                    user32.MoveWindow(hwnd, x, y, w, h, True)
                                    chat['_last_x'] = x
                                    chat['_last_y'] = y
                    return

        self._chat_last_render_state[chat_name] = current_state
        self._chat_window_dirty[chat_name] = True

        # Extract props
        width = int(props.get('width', 400))
        max_height = int(props.get('max_height', 400))
        bg = self._hex_to_rgb(props.get('bg_color', '#1e212b'))
        text_color = self._hex_to_rgb(props.get('text_color', '#f0f0f0'))
        accent = self._hex_to_rgb(props.get('accent_color', '#00aaff'))
        radius = int(props.get('border_radius', 12))
        padding = int(props.get('content_padding', 12))
        message_spacing = int(props.get('message_spacing', 8))
        fade_old = props.get('fade_old_messages', True)
        sender_colors = props.get('sender_colors', {})

        # Get fonts
        font_bold = self.fonts.get('bold', self.fonts['normal'])
        font_normal = self.fonts['normal']

        # Update markdown renderer colors for this chat
        if self.md_renderer:
            self.md_renderer.set_colors(text_color, accent, bg)

        # Render messages to temp canvas
        temp_h = max(2000, max_height * 3)
        temp = Image.new('RGBA', (width, temp_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(temp)

        content_width = width - (padding * 2)
        y = padding

        for msg in messages:
            sender = msg.get('sender', '')
            text = msg.get('text', '')
            msg_color = msg.get('color')

            # Determine sender color
            if msg_color:
                sender_color = self._hex_to_rgb(msg_color)
            elif sender in sender_colors:
                sender_color = self._hex_to_rgb(sender_colors[sender])
            else:
                sender_color = accent

            # Draw sender name with emoji support
            sender_display = sender + ":"
            self._render_text_with_emoji(draw, sender_display, padding, y, sender_color + (255,), font_bold, emoji_y_offset=3)
            y += 20

            # Render message text with full markdown support
            if self.md_renderer and text.strip():
                # Use the markdown renderer for full formatting
                y = self.md_renderer.render(draw, temp, text, padding, y, content_width)
            else:
                # Fallback: simple text
                draw.text((padding, y), text, fill=text_color + (255,), font=font_normal)
                y += 20

            y += message_spacing

        # Calculate final height
        total_content_height = y + padding
        final_h = min(total_content_height, max_height)
        fade_zone = 60  # pixels at top that fade out

        # Create final canvas
        canvas = Image.new('RGBA', (width, final_h), (255, 0, 255, 255))
        canvas_draw = ImageDraw.Draw(canvas)

        # Draw background
        canvas_draw.rounded_rectangle(
            [0, 0, width - 1, final_h - 1],
            radius=radius,
            fill=bg + (255,),
            outline=(55, 62, 74)
        )

        # If content overflows, show from bottom (newest messages visible)
        if total_content_height > max_height:
            # Crop from bottom of temp
            crop_y = y + padding - final_h
            if crop_y < 0:
                crop_y = 0
            crop = temp.crop((0, crop_y, width, crop_y + final_h))

            # Apply fade gradient at top if enabled
            if fade_old and crop_y > 0:
                # Create gradient mask for fading old content at top
                gradient = Image.new('L', (width, final_h), 255)
                gradient_draw = ImageDraw.Draw(gradient)

                for gy in range(fade_zone):
                    alpha = int(255 * (gy / fade_zone))
                    gradient_draw.line([(0, gy), (width, gy)], fill=alpha)

                # Apply gradient to crop alpha
                crop_rgba = crop.split()
                if len(crop_rgba) == 4:
                    r, g, b, a = crop_rgba
                    # Multiply alpha by gradient
                    from PIL import ImageChops
                    new_alpha = ImageChops.multiply(a, gradient)
                    crop.putalpha(new_alpha)

            canvas.paste(crop, (0, 0), crop)
        else:
            # Content fits, just paste
            crop = temp.crop((0, 0, width, final_h))
            canvas.paste(crop, (0, 0), crop)

        self._chat_canvases[chat_name] = canvas

        # Update layout manager with actual rendered height
        layout_name = f"chat_{chat_name}"
        self._layout_manager.update_window_height(layout_name, final_h)

        # Blit to window
        hwnd = self._chat_hwnds.get(chat_name)
        if hwnd and chat_name in self._chat_window_dcs:
            window_dc, mem_dc = self._chat_window_dcs[chat_name]

            # Get position from layout manager if in auto mode
            layout_mode = props.get('layout_mode', 'auto')
            if layout_mode == 'auto':
                pos = self._layout_manager.get_position(layout_name)
                if pos:
                    x, y_pos = pos
                else:
                    x = int(props.get('x', 20))
                    y_pos = int(props.get('y', 20))
            else:
                x = int(props.get('x', 20))
                y_pos = int(props.get('y', 20))

            user32.MoveWindow(hwnd, x, y_pos, width, final_h, True)

            # Blit
            self._blit_to_window_chat(hwnd, canvas, window_dc, mem_dc, chat_name)

            # Set opacity
            user32.SetLayeredWindowAttributes(
                hwnd, 0x00FF00FF, int(chat['opacity']), LWA_ALPHA | LWA_COLORKEY
            )

        self._chat_window_dirty[chat_name] = False

    def _blit_to_window_chat(self, hwnd, canvas, window_dc, mem_dc, chat_name: str):
        """Blit a chat canvas to its window using DIB."""
        if not canvas or not hwnd:
            return

        w, h = canvas.size

        # Create DIB for this blit
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # Top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB

        dib_bits = ctypes.c_void_p()
        dib_bitmap = gdi32.CreateDIBSection(
            mem_dc, ctypes.byref(bmi), DIB_RGB_COLORS,
            ctypes.byref(dib_bits), None, 0
        )

        if not dib_bitmap or not dib_bits:
            return

        old_bitmap = gdi32.SelectObject(mem_dc, dib_bitmap)

        try:
            # Copy pixel data
            raw = canvas.tobytes("raw", "BGRA")
            ctypes.memmove(dib_bits, raw, len(raw))

            # Blit to window
            gdi32.BitBlt(window_dc, 0, 0, w, h, mem_dc, 0, 0, SRCCOPY)

        finally:
            gdi32.SelectObject(mem_dc, old_bitmap)
            gdi32.DeleteObject(dib_bitmap)


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
            error_queue.put(f"Subprocess crashed: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        raise


if __name__ == "__main__":
    # Allow running standalone for testing
    overlay = HeadsUpOverlay()
    overlay.run()

