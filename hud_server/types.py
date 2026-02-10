# -*- coding: utf-8 -*-
"""
HUD Server Types - Comprehensive type definitions for the HUD HTTP Client.

This module provides strongly-typed enums and property classes for all HUD
server interactions. Use these types to ensure correct values when configuring
HUD elements.

Usage:
    from hud_server.types import (
        Anchor, LayoutMode, HudColor, FontFamily,
        MessageProps, ChatWindowProps, GroupProps
    )

    # Create props with type safety and autocompletion
    props = MessageProps(
        anchor=Anchor.TOP_RIGHT,
        accent_color=HudColor.CYAN,
        font_family=FontFamily.SEGOE_UI,
        opacity=0.9
    )

    # Use with HTTP client
    await client.create_group("my_group", props=props.to_dict())
"""

from enum import Enum
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any

from hud_server.constants import (
    ANCHOR_TOP_LEFT,
    ANCHOR_TOP_CENTER,
    ANCHOR_TOP_RIGHT,
    ANCHOR_LEFT_CENTER,
    ANCHOR_RIGHT_CENTER,
    ANCHOR_BOTTOM_LEFT,
    ANCHOR_BOTTOM_CENTER,
    ANCHOR_BOTTOM_RIGHT,
    ANCHOR_CENTER
)


# =============================================================================
# ENUMS - Predefined values for restricted properties
# =============================================================================


class Anchor(str, Enum):
    """Screen anchor points for window positioning.

    Determines where on the screen a HUD window will be anchored.
    Windows stack automatically from their anchor point.
    """
    TOP_LEFT = ANCHOR_TOP_LEFT
    """Anchor to top-left corner. Windows stack downward."""

    TOP_CENTER = ANCHOR_TOP_CENTER
    """Anchor to top-center. Windows stack downward."""

    TOP_RIGHT = ANCHOR_TOP_RIGHT
    """Anchor to top-right corner. Windows stack downward."""

    LEFT_CENTER = ANCHOR_LEFT_CENTER
    """Anchor to left edge, vertically centered. Windows stack toward center."""

    CENTER = ANCHOR_CENTER
    """Anchor to screen center. Fixed position, no automatic stacking."""

    RIGHT_CENTER = ANCHOR_RIGHT_CENTER
    """Anchor to right edge, vertically centered. Windows stack toward center."""

    BOTTOM_LEFT = ANCHOR_BOTTOM_LEFT
    """Anchor to bottom-left corner. Windows stack upward."""

    BOTTOM_CENTER = ANCHOR_BOTTOM_CENTER
    """Anchor to bottom-center. Windows stack upward."""

    BOTTOM_RIGHT = ANCHOR_BOTTOM_RIGHT
    """Anchor to bottom-right corner. Windows stack upward."""


class LayoutMode(str, Enum):
    """Layout modes for window positioning."""

    AUTO = "auto"
    """Automatic stacking based on anchor point. Recommended for most cases."""

    MANUAL = "manual"
    """User-specified x, y coordinates. No automatic adjustment."""

    HYBRID = "hybrid"
    """Automatic positioning with user-defined offsets. Reserved for future use."""


class FontFamily(str, Enum):
    """Commonly available font families for HUD text.

    These fonts are commonly available on Windows systems.
    The HUD will fall back to a default if the specified font is not found.
    """
    # Sans-serif fonts (clean, modern look)
    SEGOE_UI = "Segoe UI"
    """Default Windows font. Clean and readable. Recommended."""

    ARIAL = "Arial"
    """Classic sans-serif. Widely available."""

    VERDANA = "Verdana"
    """Wide, readable sans-serif designed for screens."""

    TAHOMA = "Tahoma"
    """Compact sans-serif, good for small sizes."""

    TREBUCHET_MS = "Trebuchet MS"
    """Humanist sans-serif with personality."""

    CALIBRI = "Calibri"
    """Modern sans-serif, default in Office."""

    CONSOLAS = "Consolas"
    """Modern monospace. Excellent for code. Recommended for technical data."""

    COURIER_NEW = "Courier New"
    """Classic monospace typewriter font."""


class HudColor(str, Enum):
    """Predefined colors for HUD elements.

    Use these predefined colors or specify custom hex values (#RRGGBB or #RRGGBBAA).
    The alpha channel (AA) in hex codes controls transparency (00=transparent, FF=opaque).
    """
    # Primary colors
    WHITE = "#ffffff"
    BLACK = "#000000"
    RED = "#ff0000"
    GREEN = "#00ff00"
    BLUE = "#0000ff"
    YELLOW = "#ffff00"
    CYAN = "#00ffff"
    MAGENTA = "#ff00ff"

    # Grayscale
    GRAY_LIGHT = "#d0d0d0"
    GRAY = "#808080"
    GRAY_DARK = "#404040"

    # Theme colors (recommended for HUD)
    ACCENT_BLUE = "#00aaff"
    """Default accent color. Bright, noticeable."""

    ACCENT_ORANGE = "#ff8800"
    """Warm accent. Good for warnings or highlights."""

    ACCENT_GREEN = "#00ff88"
    """Success/positive indicator."""

    ACCENT_PURPLE = "#aa00ff"
    """Alternative accent color."""

    ACCENT_PINK = "#ff0088"
    """Vibrant pink accent."""

    # Status colors
    SUCCESS = "#22c55e"
    """Green success indicator."""

    WARNING = "#f59e0b"
    """Orange/amber warning indicator."""

    ERROR = "#ef4444"
    """Red error indicator."""

    INFO = "#3b82f6"
    """Blue informational indicator."""

    # Background colors
    BG_DARK = "#1e212b"
    """Default dark background. Recommended."""

    BG_DARKER = "#13151a"
    """Very dark background."""

    BG_MEDIUM = "#2d3142"
    """Medium dark background."""

    BG_LIGHT = "#3d4157"
    """Lighter background."""

    # Text colors
    TEXT_PRIMARY = "#f0f0f0"
    """Default text color. High contrast on dark backgrounds."""

    TEXT_SECONDARY = "#a0a0a0"
    """Subdued text for secondary information."""

    TEXT_MUTED = "#606060"
    """Very subdued text."""

    # Semi-transparent variants (with alpha channel)
    WHITE_50 = "#ffffff80"
    """50% transparent white."""

    BLACK_50 = "#00000080"
    """50% transparent black."""

    BG_DARK_90 = "#1e212be6"
    """90% opaque dark background."""

    BG_DARK_75 = "#1e212bbf"
    """75% opaque dark background."""

    BG_DARK_50 = "#1e212b80"
    """50% opaque dark background."""

    # Game-themed colors
    SHIELD = "#00aaff"
    """Shield/energy color."""

    HEALTH = "#22c55e"
    """Health/life color."""

    ARMOR = "#f59e0b"
    """Armor/protection color."""

    DANGER = "#ef4444"
    """Danger/damage color."""

    QUANTUM = "#aa00ff"
    """Quantum/warp color."""

    FUEL = "#ffcc00"
    """Fuel/energy resource color."""


class WindowType(str, Enum):
    """Types of HUD windows."""

    MESSAGE = "message"
    """Temporary message window. Fades out after display duration."""

    PERSISTENT = "persistent"
    """Persistent information window. Stays visible until explicitly hidden."""

    CHAT = "chat"
    """Chat window for message streams."""


class FadeState(int, Enum):
    """Window fade animation states."""

    HIDDEN = 0
    """Window is fully hidden."""

    FADE_IN = 1
    """Window is fading in (appearing)."""

    VISIBLE = 2
    """Window is fully visible."""

    FADE_OUT = 3
    """Window is fading out (disappearing)."""


# =============================================================================
# PROPERTY CLASSES - Typed property containers for each window type
# =============================================================================


@dataclass
class BaseProps:
    """Base properties shared by all HUD elements."""

    # Position & Layout
    x: Optional[int] = None
    """X position in pixels. Used in MANUAL layout mode."""

    y: Optional[int] = None
    """Y position in pixels. Used in MANUAL layout mode."""

    width: Optional[int] = None
    """Window width in pixels. Range: 100-3840."""

    max_height: Optional[int] = None
    """Maximum window height in pixels. Range: 100-2160."""

    layout_mode: Optional[str] = None
    """Layout mode: 'auto', 'manual', or 'hybrid'. Use LayoutMode enum."""

    anchor: Optional[str] = None
    """Screen anchor point. Use Anchor enum."""

    priority: Optional[int] = None
    """Stacking priority within anchor zone. Higher = closer to anchor. Range: 0-100."""

    z_order: Optional[int] = None
    """Z-order for layering. Higher = on top. Range: -1000 to 1000."""

    # Colors
    bg_color: Optional[str] = None
    """Background color in hex format (#RRGGBB or #RRGGBBAA). Use HudColor enum."""

    text_color: Optional[str] = None
    """Text color in hex format. Use HudColor enum."""

    accent_color: Optional[str] = None
    """Accent color for titles and highlights. Use HudColor enum."""

    title_color: Optional[str] = None
    """Override color for title text. Use HudColor enum."""

    # Visual styling
    opacity: Optional[float] = None
    """Window opacity. Range: 0.0 (transparent) to 1.0 (opaque)."""

    border_radius: Optional[int] = None
    """Corner radius in pixels. Range: 0-50."""

    content_padding: Optional[int] = None
    """Padding inside the window in pixels. Range: 0-100."""

    # Typography
    font_size: Optional[int] = None
    """Font size in pixels. Range: 8-72."""

    font_family: Optional[str] = None
    """Font family name. Use FontFamily enum."""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class MessageProps(BaseProps):
    """Properties for message windows (temporary notifications).

    Message windows display temporary content that fades out after a duration.
    Supports markdown content and typewriter animation.
    """

    # Behavior
    typewriter_effect: Optional[bool] = None
    """Enable typewriter animation for text. Default: True."""

    typewriter_speed: Optional[int] = None
    """Characters per second for typewriter effect. Range: 1-1000."""

    auto_fade: Optional[bool] = None
    """Automatically fade out after display. Default: True."""

    fade_delay: Optional[float] = None
    """Seconds before starting fade out. Range: 0.0-300.0."""

    fade_duration: Optional[float] = None
    """Duration of fade animation in seconds. Range: 0.1-10.0."""

    show_loader: Optional[bool] = None
    """Show loading animation while waiting for content."""


@dataclass
class PersistentProps(BaseProps):
    """Properties for persistent windows (information panels).

    Persistent windows display items that remain visible until removed.
    Good for status indicators, tracked information, etc.
    """
    pass  # Uses base props. Items are added/removed via add_item/remove_item


@dataclass
class ChatWindowProps(BaseProps):
    """Properties for chat windows (message streams).

    Chat windows display a scrolling list of messages from multiple senders.
    """

    # Size
    max_height: Optional[int] = None
    """Maximum height before scrolling. Range: 100-2160."""

    # Behavior
    auto_hide: Optional[bool] = None
    """Automatically hide after inactivity. Default: False."""

    auto_hide_delay: Optional[float] = None
    """Seconds of inactivity before auto-hide. Default: 10.0."""

    max_messages: Optional[int] = None
    """Maximum messages to keep in history. Default: 50."""

    fade_old_messages: Optional[bool] = None
    """Fade older messages for visual distinction. Default: True."""

    show_timestamps: Optional[bool] = None
    """Show timestamps on messages. Default: False."""

    message_spacing: Optional[int] = None
    """Vertical spacing between messages in pixels. Default: 8."""

    sender_colors: Optional[Dict[str, str]] = None
    """Map of sender names to colors. E.g., {'User': '#00ff00', 'AI': '#00aaff'}."""


@dataclass
class ProgressProps(BaseProps):
    """Properties for progress bar displays."""

    auto_close: Optional[bool] = None
    """Automatically close when progress reaches maximum. Default: False."""


@dataclass
class TimerProps(BaseProps):
    """Properties for timer/countdown displays."""

    auto_close: Optional[bool] = None
    """Automatically close when timer completes. Default: True."""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def color(hex_value: str) -> str:
    """Validate and return a hex color value.

    Args:
        hex_value: Color in hex format (#RGB, #RRGGBB, or #RRGGBBAA)

    Returns:
        The validated hex color string

    Raises:
        ValueError: If the color format is invalid

    Example:
        color("#ff0000")  # Red
        color("#ff000080")  # Semi-transparent red
    """
    if not isinstance(hex_value, str):
        raise ValueError(f"Color must be a string, got {type(hex_value)}")

    if not hex_value.startswith('#'):
        raise ValueError(f"Color must start with '#', got '{hex_value}'")

    hex_part = hex_value[1:]
    if len(hex_part) not in (3, 6, 8):
        raise ValueError(
            f"Color must be #RGB, #RRGGBB, or #RRGGBBAA format, got '{hex_value}'"
        )

    try:
        int(hex_part, 16)
    except ValueError:
        raise ValueError(f"Invalid hex color: '{hex_value}'")

    return hex_value


def rgb(r: int, g: int, b: int, a: Optional[int] = None) -> str:
    """Create a hex color from RGB(A) values.

    Args:
        r: Red component (0-255)
        g: Green component (0-255)
        b: Blue component (0-255)
        a: Optional alpha component (0-255). 0=transparent, 255=opaque.

    Returns:
        Hex color string (#RRGGBB or #RRGGBBAA)

    Example:
        rgb(255, 0, 0)  # "#ff0000" - Red
        rgb(255, 0, 0, 128)  # "#ff000080" - Semi-transparent red
    """
    for val, name in [(r, 'r'), (g, 'g'), (b, 'b')]:
        if not 0 <= val <= 255:
            raise ValueError(f"{name} must be 0-255, got {val}")

    if a is not None:
        if not 0 <= a <= 255:
            raise ValueError(f"a must be 0-255, got {a}")
        return f"#{r:02x}{g:02x}{b:02x}{a:02x}"

    return f"#{r:02x}{g:02x}{b:02x}"


# =============================================================================
# DEFAULTS - Easy access to default values
# =============================================================================


class Defaults:
    """Default values for HUD properties.

    Use these constants when you want to explicitly set the default value.
    """

    # Layout
    ANCHOR = Anchor.TOP_LEFT
    LAYOUT_MODE = LayoutMode.AUTO
    PRIORITY = 10
    Z_ORDER = 0

    # Position (for manual mode)
    X = 20
    Y = 20

    # Size
    WIDTH = 400
    MAX_HEIGHT = 600

    # Colors
    BG_COLOR = HudColor.BG_DARK
    TEXT_COLOR = HudColor.TEXT_PRIMARY
    ACCENT_COLOR = HudColor.ACCENT_BLUE

    # Visual
    OPACITY = 0.85
    BORDER_RADIUS = 12
    CONTENT_PADDING = 16

    # Typography
    FONT_SIZE = 16
    FONT_FAMILY = FontFamily.SEGOE_UI

    # Behavior
    TYPEWRITER_EFFECT = True
    TYPEWRITER_SPEED = 200
    AUTO_FADE = True
    FADE_DELAY = 8.0
    FADE_DURATION = 0.5
    SHOW_LOADER = True

    # Chat specific
    AUTO_HIDE = False
    AUTO_HIDE_DELAY = 10.0
    MAX_MESSAGES = 50
    MESSAGE_SPACING = 8
    FADE_OLD_MESSAGES = True
    SHOW_TIMESTAMPS = False


# =============================================================================
# CONVENIENCE CONSTRUCTORS
# =============================================================================


def message_props(
    *,
    anchor: Anchor = None,
    priority: int = None,
    width: int = None,
    max_height: int = None,
    bg_color: str = None,
    text_color: str = None,
    accent_color: str = None,
    opacity: float = None,
    border_radius: int = None,
    font_size: int = None,
    font_family: str = None,
    typewriter_effect: bool = None,
    typewriter_speed: int = None,
    fade_delay: float = None,
    **kwargs
) -> Dict[str, Any]:
    """Create a props dictionary for message windows.

    All parameters are optional - only provided values will be included.

    Returns:
        Dictionary of properties ready to pass to create_group or show_message.

    Example:
        props = message_props(
            anchor=Anchor.TOP_RIGHT,
            accent_color=HudColor.ACCENT_ORANGE,
            opacity=0.9
        )
        await client.create_group("notifications", props=props)
    """
    props = MessageProps(
        anchor=anchor.value if anchor else None,
        priority=priority,
        width=width,
        max_height=max_height,
        bg_color=bg_color.value if isinstance(bg_color, HudColor) else bg_color,
        text_color=text_color.value if isinstance(text_color, HudColor) else text_color,
        accent_color=accent_color.value if isinstance(accent_color, HudColor) else accent_color,
        opacity=opacity,
        border_radius=border_radius,
        font_size=font_size,
        font_family=font_family.value if isinstance(font_family, FontFamily) else font_family,
        typewriter_effect=typewriter_effect,
        typewriter_speed=typewriter_speed,
        fade_delay=fade_delay,
        **kwargs
    )
    return props.to_dict()


def chat_window_props(
    *,
    anchor: Anchor = None,
    priority: int = None,
    width: int = None,
    max_height: int = None,
    bg_color: str = None,
    text_color: str = None,
    accent_color: str = None,
    opacity: float = None,
    border_radius: int = None,
    font_size: int = None,
    font_family: str = None,
    auto_hide: bool = None,
    auto_hide_delay: float = None,
    max_messages: int = None,
    fade_old_messages: bool = None,
    sender_colors: Dict[str, str] = None,
    **kwargs
) -> Dict[str, Any]:
    """Create a props dictionary for chat windows.

    All parameters are optional - only provided values will be included.

    Returns:
        Dictionary of properties ready to pass to create_chat_window.

    Example:
        props = chat_window_props(
            anchor=Anchor.BOTTOM_LEFT,
            max_messages=100,
            sender_colors={
                "User": HudColor.ACCENT_GREEN.value,
                "AI": HudColor.ACCENT_BLUE.value
            }
        )
        await client.create_chat_window("chat", **props)
    """
    props = ChatWindowProps(
        anchor=anchor.value if anchor else None,
        priority=priority,
        width=width,
        max_height=max_height,
        bg_color=bg_color.value if isinstance(bg_color, HudColor) else bg_color,
        text_color=text_color.value if isinstance(text_color, HudColor) else text_color,
        accent_color=accent_color.value if isinstance(accent_color, HudColor) else accent_color,
        opacity=opacity,
        border_radius=border_radius,
        font_size=font_size,
        font_family=font_family.value if isinstance(font_family, FontFamily) else font_family,
        auto_hide=auto_hide,
        auto_hide_delay=auto_hide_delay,
        max_messages=max_messages,
        fade_old_messages=fade_old_messages,
        sender_colors=sender_colors,
        **kwargs
    )
    return props.to_dict()


def persistent_props(
    *,
    anchor: Anchor = None,
    priority: int = None,
    width: int = None,
    max_height: int = None,
    bg_color: str = None,
    text_color: str = None,
    accent_color: str = None,
    opacity: float = None,
    border_radius: int = None,
    font_size: int = None,
    font_family: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Create a props dictionary for persistent windows (info panels).

    All parameters are optional - only provided values will be included.

    Returns:
        Dictionary of properties ready to pass to create_group.

    Example:
        props = persistent_props(
            anchor=Anchor.TOP_RIGHT,
            width=300,
            accent_color=HudColor.ACCENT_GREEN
        )
        await client.create_group("status_panel", props=props)
    """
    props = PersistentProps(
        anchor=anchor.value if anchor else None,
        priority=priority,
        width=width,
        max_height=max_height,
        bg_color=bg_color.value if isinstance(bg_color, HudColor) else bg_color,
        text_color=text_color.value if isinstance(text_color, HudColor) else text_color,
        accent_color=accent_color.value if isinstance(accent_color, HudColor) else accent_color,
        opacity=opacity,
        border_radius=border_radius,
        font_size=font_size,
        font_family=font_family.value if isinstance(font_family, FontFamily) else font_family,
        **kwargs
    )
    return props.to_dict()


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    "Anchor",
    "LayoutMode",
    "FontFamily",
    "HudColor",
    "WindowType",
    "FadeState",
    # Property classes
    "BaseProps",
    "MessageProps",
    "PersistentProps",
    "ChatWindowProps",
    "ProgressProps",
    "TimerProps",
    # Helper functions
    "color",
    "rgb",
    # Convenience constructors
    "message_props",
    "chat_window_props",
    "persistent_props",
    # Defaults
    "Defaults",
]


