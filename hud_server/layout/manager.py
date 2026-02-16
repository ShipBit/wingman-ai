"""
Layout Manager - Automatic positioning and stacking for HUD elements.

This module provides intelligent layout management to prevent HUD element overlap:

1. **Anchor System**: Elements anchor to screen corners and edges (9 anchor points)
2. **Automatic Stacking**: Elements at the same anchor stack vertically with configurable spacing
3. **Dynamic Reflow**: When element heights change, others reposition automatically
4. **Priority Ordering**: Elements can be ordered by priority within an anchor zone
5. **Visibility Awareness**: Hidden elements don't occupy space

For complete documentation including visual diagrams and examples, see:
    hud_server/README.md - Layout System section

Usage:
    from hud_server.layout import LayoutManager, Anchor

    # Create manager
    layout = LayoutManager(screen_width=1920, screen_height=1080)

    # Register windows with anchors
    layout.register_window("message_ATC", Anchor.TOP_LEFT, priority=10, margin=20)
    layout.register_window("persistent_ATC", Anchor.TOP_LEFT, priority=5, margin=20)
    layout.register_window("message_Computer", Anchor.TOP_RIGHT, priority=10, margin=20)

    # Update a window's content height
    layout.update_window_height("message_ATC", 200)

    # Get computed positions for all windows
    positions = layout.compute_positions()
    # Returns: {"message_ATC": (20, 20), "persistent_ATC": (20, 230), ...}
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple
import threading


class Anchor(Enum):
    """Screen anchor points for window positioning."""
    TOP_LEFT = "top_left"
    TOP_CENTER = "top_center"
    TOP_RIGHT = "top_right"
    RIGHT_CENTER = "right_center"
    BOTTOM_RIGHT = "bottom_right"
    BOTTOM_CENTER = "bottom_center"
    BOTTOM_LEFT = "bottom_left"
    LEFT_CENTER = "left_center"
    CENTER = "center"  # Fixed position, no stacking


class LayoutMode(Enum):
    """Layout modes for window positioning."""
    AUTO = "auto"        # Automatic stacking based on anchor
    MANUAL = "manual"    # User-specified x, y (no auto-adjustment)
    HYBRID = "hybrid"    # Reserved for future use (currently behaves like AUTO)


@dataclass
class WindowInfo:
    """
    Information about a window for layout calculations.

    Note: The 'group' field is reserved for future collision grouping features.
    """
    name: str
    anchor: Anchor = Anchor.TOP_LEFT
    mode: LayoutMode = LayoutMode.AUTO
    priority: int = 0  # Higher = rendered first (closer to anchor)
    width: int = 400
    height: int = 100
    margin_x: int = 20  # Margin from screen edge
    margin_y: int = 20
    spacing: int = 10  # Spacing between stacked windows
    visible: bool = True
    group: Optional[str] = None  # Reserved for future use

    # For manual/hybrid mode - user-specified offsets
    manual_x: Optional[int] = None
    manual_y: Optional[int] = None

    # Computed position (updated by layout manager)
    computed_x: int = 0
    computed_y: int = 0


class LayoutManager:
    """
    Manages automatic layout and positioning of HUD windows.

    Thread-safe for use from multiple contexts.
    """

    def __init__(
        self,
        screen_width: int = 1920,
        screen_height: int = 1080,
        screen_offset_x: int = 0,
        screen_offset_y: int = 0,
        default_margin: int = 20,
        default_spacing: int = 10
    ):
        self._lock = threading.RLock()
        self._screen_width = screen_width
        self._screen_height = screen_height
        self._screen_offset_x = screen_offset_x
        self._screen_offset_y = screen_offset_y
        self._default_margin = default_margin
        self._default_spacing = default_spacing

        # Window registry: name -> WindowInfo
        self._windows: Dict[str, WindowInfo] = {}

        # Cached positions - invalidated on changes
        self._position_cache: Optional[Dict[str, Tuple[int, int]]] = None
        self._cache_valid = False

    def set_screen_size(self, width: int, height: int):
        """Update screen dimensions and invalidate cache."""
        with self._lock:
            if self._screen_width != width or self._screen_height != height:
                self._screen_width = width
                self._screen_height = height
                self._invalidate_cache()

    def set_screen_offset(self, offset_x: int, offset_y: int):
        """Update screen offset and invalidate cache."""
        with self._lock:
            if self._screen_offset_x != offset_x or self._screen_offset_y != offset_y:
                self._screen_offset_x = offset_x
                self._screen_offset_y = offset_y
                self._invalidate_cache()

    @property
    def screen_size(self) -> Tuple[int, int]:
        """Get current screen dimensions."""
        return (self._screen_width, self._screen_height)

    @property
    def screen_offset(self) -> Tuple[int, int]:
        """Get current screen offset (position of monitor on desktop)."""
        return (self._screen_offset_x, self._screen_offset_y)

    def register_window(
        self,
        name: str,
        anchor: Anchor = Anchor.TOP_LEFT,
        mode: LayoutMode = LayoutMode.AUTO,
        priority: int = 0,
        width: int = 400,
        height: int = 100,
        margin_x: Optional[int] = None,
        margin_y: Optional[int] = None,
        spacing: Optional[int] = None,
        group: Optional[str] = None,
        manual_x: Optional[int] = None,
        manual_y: Optional[int] = None,
    ) -> WindowInfo:
        """
        Register a window for layout management.

        Args:
            name: Unique window identifier
            anchor: Screen anchor point for positioning
            mode: Layout mode (auto, manual, or hybrid)
            priority: Stacking priority (higher = closer to anchor)
            width: Window width in pixels
            height: Current window height in pixels
            margin_x: Horizontal margin from screen edge
            margin_y: Vertical margin from screen edge
            spacing: Vertical spacing between stacked windows
            group: Optional group name for related windows
            manual_x: Manual x position (for manual/hybrid mode)
            manual_y: Manual y position (for manual/hybrid mode)

        Returns:
            The WindowInfo object (can be modified directly, but call invalidate_cache after)
        """
        with self._lock:
            window = WindowInfo(
                name=name,
                anchor=anchor,
                mode=mode,
                priority=priority,
                width=width,
                height=height,
                margin_x=margin_x if margin_x is not None else self._default_margin,
                margin_y=margin_y if margin_y is not None else self._default_margin,
                spacing=spacing if spacing is not None else self._default_spacing,
                group=group,
                manual_x=manual_x,
                manual_y=manual_y,
            )
            self._windows[name] = window
            self._invalidate_cache()
            return window

    def unregister_window(self, name: str) -> bool:
        """Remove a window from layout management."""
        with self._lock:
            if name in self._windows:
                del self._windows[name]
                self._invalidate_cache()
                return True
            return False

    def get_window(self, name: str) -> Optional[WindowInfo]:
        """Get window info by name."""
        with self._lock:
            return self._windows.get(name)

    def update_window(
        self,
        name: str,
        height: Optional[int] = None,
        width: Optional[int] = None,
        visible: Optional[bool] = None,
        priority: Optional[int] = None,
        anchor: Optional[Anchor] = None,
        mode: Optional[LayoutMode] = None,
    ) -> bool:
        """
        Update window properties.

        Returns True if window exists and was updated.
        """
        with self._lock:
            window = self._windows.get(name)
            if not window:
                return False

            changed = False
            if height is not None and window.height != height:
                window.height = height
                changed = True
            if width is not None and window.width != width:
                window.width = width
                changed = True
            if visible is not None and window.visible != visible:
                window.visible = visible
                changed = True
            if priority is not None and window.priority != priority:
                window.priority = priority
                changed = True
            if anchor is not None and window.anchor != anchor:
                window.anchor = anchor
                changed = True
            if mode is not None and window.mode != mode:
                window.mode = mode
                changed = True

            if changed:
                self._invalidate_cache()

            return True

    def update_window_height(self, name: str, height: int) -> bool:
        """Convenience method to update just the height."""
        return self.update_window(name, height=height)

    def set_window_visible(self, name: str, visible: bool) -> bool:
        """Convenience method to set visibility."""
        return self.update_window(name, visible=visible)

    def _invalidate_cache(self):
        """Mark position cache as invalid."""
        self._cache_valid = False
        self._position_cache = None

    def compute_positions(self, force: bool = False) -> Dict[str, Tuple[int, int]]:
        """
        Compute positions for all windows.

        Returns a dict mapping window name to (x, y) position.
        Results are cached until windows change.
        """
        with self._lock:
            if self._cache_valid and self._position_cache and not force:
                return self._position_cache

            positions: Dict[str, Tuple[int, int]] = {}

            # Group windows by anchor
            by_anchor: Dict[Anchor, List[WindowInfo]] = {a: [] for a in Anchor}
            for window in self._windows.values():
                if window.visible:
                    by_anchor[window.anchor].append(window)

            # Process each anchor zone
            for anchor, windows in by_anchor.items():
                if not windows:
                    continue

                # Sort by priority (higher first, then by name for stability)
                windows.sort(key=lambda w: (-w.priority, w.name))

                # Calculate positions
                anchor_positions = self._compute_anchor_positions(anchor, windows)
                positions.update(anchor_positions)

            # Update computed positions in window objects
            for name, (x, y) in positions.items():
                if name in self._windows:
                    self._windows[name].computed_x = x
                    self._windows[name].computed_y = y

            # Add screen offset to all positions
            positions_with_offset = {
                name: (x + self._screen_offset_x, y + self._screen_offset_y)
                for name, (x, y) in positions.items()
            }

            self._position_cache = positions_with_offset
            self._cache_valid = True
            return positions_with_offset

    def _compute_anchor_positions(
        self,
        anchor: Anchor,
        windows: List[WindowInfo]
    ) -> Dict[str, Tuple[int, int]]:
        """Compute positions for windows at a specific anchor."""
        positions: Dict[str, Tuple[int, int]] = {}

        if anchor == Anchor.CENTER:
            # Center mode: each window is centered, no stacking
            for window in windows:
                if window.mode == LayoutMode.MANUAL and window.manual_x is not None and window.manual_y is not None:
                    x, y = window.manual_x, window.manual_y
                else:
                    x = self._screen_width // 2 - window.width // 2
                    y = self._screen_height // 2 - window.height // 2
                positions[window.name] = (x, y)
            return positions

        # Helper to handle manual positioning
        def get_position(window: WindowInfo, auto_x: int, auto_y: int) -> Tuple[int, int]:
            if window.mode == LayoutMode.MANUAL and window.manual_x is not None and window.manual_y is not None:
                return (window.manual_x, window.manual_y)
            return (auto_x, auto_y)

        # Calculate starting position based on anchor
        if anchor == Anchor.TOP_LEFT:
            # Stack downward from top-left
            current_y = windows[0].margin_y if windows else self._default_margin
            for window in windows:
                x = window.margin_x
                positions[window.name] = get_position(window, x, current_y)
                current_y += window.height + window.spacing

        elif anchor == Anchor.TOP_RIGHT:
            # Stack downward from top-right
            current_y = windows[0].margin_y if windows else self._default_margin
            for window in windows:
                x = self._screen_width - window.width - window.margin_x
                positions[window.name] = get_position(window, x, current_y)
                current_y += window.height + window.spacing

        elif anchor == Anchor.BOTTOM_LEFT:
            # Stack upward from bottom-left
            current_y = self._screen_height - windows[0].margin_y if windows else self._screen_height - self._default_margin
            for window in windows:
                x = window.margin_x
                y = current_y - window.height
                positions[window.name] = get_position(window, x, y)
                current_y = y - window.spacing

        elif anchor == Anchor.BOTTOM_RIGHT:
            # Stack upward from bottom-right
            current_y = self._screen_height - windows[0].margin_y if windows else self._screen_height - self._default_margin
            for window in windows:
                x = self._screen_width - window.width - window.margin_x
                y = current_y - window.height
                positions[window.name] = get_position(window, x, y)
                current_y = y - window.spacing

        elif anchor == Anchor.TOP_CENTER:
            # Stack downward from top-center
            current_y = windows[0].margin_y if windows else self._default_margin
            for window in windows:
                x = self._screen_width // 2 - window.width // 2
                positions[window.name] = get_position(window, x, current_y)
                current_y += window.height + window.spacing

        elif anchor == Anchor.BOTTOM_CENTER:
            # Stack upward from bottom-center
            current_y = self._screen_height - windows[0].margin_y if windows else self._screen_height - self._default_margin
            for window in windows:
                x = self._screen_width // 2 - window.width // 2
                y = current_y - window.height
                positions[window.name] = get_position(window, x, y)
                current_y = y - window.spacing

        elif anchor == Anchor.LEFT_CENTER:
            # Stack downward from left-center (starting at vertical middle)
            total_height = sum(w.height + w.spacing for w in windows) - (windows[-1].spacing if windows else 0)
            current_y = (self._screen_height - total_height) // 2
            for window in windows:
                x = window.margin_x
                positions[window.name] = get_position(window, x, current_y)
                current_y += window.height + window.spacing

        elif anchor == Anchor.RIGHT_CENTER:
            # Stack downward from right-center (starting at vertical middle)
            total_height = sum(w.height + w.spacing for w in windows) - (windows[-1].spacing if windows else 0)
            current_y = (self._screen_height - total_height) // 2
            for window in windows:
                x = self._screen_width - window.width - window.margin_x
                positions[window.name] = get_position(window, x, current_y)
                current_y += window.height + window.spacing

        return positions

    def get_position(self, name: str) -> Optional[Tuple[int, int]]:
        """Get the computed position for a window (offset already included via compute_positions)."""
        positions = self.compute_positions()
        return positions.get(name)

    def get_all_windows(self) -> Dict[str, WindowInfo]:
        """Get all registered windows."""
        with self._lock:
            return dict(self._windows)

    def get_windows_at_anchor(self, anchor: Anchor) -> List[WindowInfo]:
        """Get all windows at a specific anchor, sorted by priority."""
        with self._lock:
            windows = [w for w in self._windows.values() if w.anchor == anchor and w.visible]
            windows.sort(key=lambda w: (-w.priority, w.name))
            return windows

    def check_collision(self, name1: str, name2: str) -> bool:
        """Check if two windows overlap."""
        positions = self.compute_positions()

        if name1 not in positions or name2 not in positions:
            return False

        w1 = self._windows.get(name1)
        w2 = self._windows.get(name2)
        if not w1 or not w2:
            return False

        x1, y1 = positions[name1]
        x2, y2 = positions[name2]

        # AABB collision test
        return not (
            x1 + w1.width <= x2 or
            x2 + w2.width <= x1 or
            y1 + w1.height <= y2 or
            y2 + w2.height <= y1
        )

    def find_collisions(self) -> List[Tuple[str, str]]:
        """Find all pairs of overlapping windows."""
        collisions = []
        positions = self.compute_positions()
        names = list(positions.keys())

        for i, name1 in enumerate(names):
            for name2 in names[i + 1:]:
                if self.check_collision(name1, name2):
                    collisions.append((name1, name2))

        return collisions

    def to_dict(self) -> Dict[str, dict]:
        """Export layout state to dictionary."""
        with self._lock:
            positions = self.compute_positions()
            result = {}
            for name, window in self._windows.items():
                pos = positions.get(name, (0, 0))
                result[name] = {
                    "anchor": window.anchor.value,
                    "mode": window.mode.value,
                    "priority": window.priority,
                    "width": window.width,
                    "height": window.height,
                    "visible": window.visible,
                    "computed_x": pos[0],
                    "computed_y": pos[1],
                }
            return result

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, dict],
        screen_width: int = 1920,
        screen_height: int = 1080
    ) -> "LayoutManager":
        """Create layout manager from dictionary."""
        manager = cls(screen_width=screen_width, screen_height=screen_height)
        for name, window_data in data.items():
            manager.register_window(
                name=name,
                anchor=Anchor(window_data.get("anchor", "top_left")),
                mode=LayoutMode(window_data.get("mode", "auto")),
                priority=window_data.get("priority", 0),
                width=window_data.get("width", 400),
                height=window_data.get("height", 100),
            )
        return manager

    def debug_print(self):
        """Print layout state for debugging."""
        positions = self.compute_positions()
        print(f"Layout Manager - Screen: {self._screen_width}x{self._screen_height}")
        print("-" * 60)

        for anchor in Anchor:
            windows = self.get_windows_at_anchor(anchor)
            if windows:
                print(f"\n{anchor.value.upper()}:")
                for w in windows:
                    pos = positions.get(w.name, (0, 0))
                    print(f"  {w.name}: ({pos[0]}, {pos[1]}) "
                          f"size={w.width}x{w.height} "
                          f"priority={w.priority} "
                          f"visible={w.visible}")
