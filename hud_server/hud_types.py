"""
HeadsUp HUD - Generalized HUD overlay system with named groups.

Each HUD group has its own:
- Position (x, y)
- Size (width, max_height)
- Visual properties (colors, opacity, fonts)
- Behavior (typewriter effect, loader, auto-fade)

Props can be:
- Set when creating a group
- Updated at any time via update_group()
- Overridden per-message/item

This allows multiple independent HUD areas on screen with full flexibility.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List


@dataclass
class HUDGroupProps:
    """
    Properties for a HUD group.

    All properties are optional when updating - only provided values will be changed.
    When creating a new group, defaults will be used for any unspecified properties.
    """
    # Position & Size
    x: int = 20
    y: int = 20
    width: int = 400
    max_height: int = 600

    # Colors
    bg_color: str = "#1e212b"
    text_color: str = "#f0f0f0"
    accent_color: str = "#00aaff"
    title_color: Optional[str] = None  # If None, uses accent_color

    # Visual
    opacity: float = 0.85
    border_radius: int = 12
    font_size: int = 16
    font_family: str = "Segoe UI"
    content_padding: int = 16

    # Behavior
    typewriter_effect: bool = True
    typewriter_speed: int = 200  # chars per second
    show_loader: bool = True
    auto_fade: bool = True
    fade_delay: float = 8.0  # seconds before fade starts
    fade_duration: float = 0.5  # fade animation duration

    # Rendering
    z_order: int = 0  # Higher = rendered on top

    # Layout Management
    layout_mode: str = "auto"  # 'auto', 'manual', or 'hybrid'
    anchor: str = "top_left"  # 'top_left', 'top_right', 'bottom_left', 'bottom_right', 'center'
    priority: int = 10  # Stacking priority (higher = closer to anchor)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, resolving defaults."""
        return {
            'x': self.x,
            'y': self.y,
            'width': self.width,
            'max_height': self.max_height,
            'bg_color': self.bg_color,
            'text_color': self.text_color,
            'accent_color': self.accent_color,
            'title_color': self.title_color or self.accent_color,
            'opacity': self.opacity,
            'border_radius': self.border_radius,
            'font_size': self.font_size,
            'font_family': self.font_family,
            'content_padding': self.content_padding,
            'typewriter_effect': self.typewriter_effect,
            'typewriter_speed': self.typewriter_speed,
            'show_loader': self.show_loader,
            'auto_fade': self.auto_fade,
            'fade_delay': self.fade_delay,
            'fade_duration': self.fade_duration,
            'z_order': self.z_order,
            'layout_mode': self.layout_mode,
            'anchor': self.anchor,
            'priority': self.priority,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HUDGroupProps":
        """Create from dictionary, ignoring unknown keys."""
        import dataclasses
        valid_fields = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid_fields})

    def merge_with(self, overrides: Dict[str, Any]) -> "HUDGroupProps":
        """Create a new HUDGroupProps with overrides applied."""
        base = self.to_dict()
        base.update({k: v for k, v in overrides.items() if v is not None})
        return HUDGroupProps.from_dict(base)


@dataclass
class HUDMessage:
    """A message to display in a HUD group."""
    title: str = ""
    content: str = ""
    color: Optional[str] = None  # Override title/accent color for this message
    tools: List[Dict[str, Any]] = field(default_factory=list)
    id: Optional[str] = None  # For tracking/updating specific messages

    # Per-message prop overrides (optional)
    props: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'title': self.title,
            'content': self.content,
            'color': self.color,
            'tools': self.tools,
            'id': self.id,
        }
        if self.props:
            result['props'] = self.props
        return result


@dataclass
class HUDItem:
    """A persistent item in a HUD group."""
    title: str
    description: str = ""
    color: Optional[str] = None
    duration: Optional[float] = None  # Auto-remove after duration (seconds)

    # Progress bar support
    is_progress: bool = False
    progress_current: float = 0
    progress_maximum: float = 100
    progress_color: Optional[str] = None

    # Timer support
    is_timer: bool = False
    timer_duration: float = 0
    auto_close: bool = True

    # Per-item prop overrides (optional)
    props: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'title': self.title,
            'description': self.description,
            'color': self.color,
            'duration': self.duration,
            'is_progress': self.is_progress,
            'progress_current': self.progress_current,
            'progress_maximum': self.progress_maximum,
            'progress_color': self.progress_color,
            'is_timer': self.is_timer,
            'timer_duration': self.timer_duration,
            'auto_close': self.auto_close,
        }
        if self.props:
            result['props'] = self.props
        return result


@dataclass
class ChatMessage:
    """A single chat message for the chat window."""
    sender: str
    text: str
    color: Optional[str] = None  # Override sender color
    timestamp: Optional[float] = None  # When the message was added

    def to_dict(self) -> Dict[str, Any]:
        return {
            'sender': self.sender,
            'text': self.text,
            'color': self.color,
            'timestamp': self.timestamp,
        }


@dataclass
class ChatWindowProps(HUDGroupProps):
    """
    Properties for a Chat Window HUD group.

    Extends HUDGroupProps with chat-specific settings.
    """
    # Chat-specific settings
    auto_hide: bool = False  # Hide window after auto_hide_delay seconds
    auto_hide_delay: float = 10.0  # Seconds after last message before hiding
    max_messages: int = 50  # Maximum messages to keep in history
    sender_colors: Optional[Dict[str, str]] = None  # Map sender names to colors
    show_timestamps: bool = False  # Show timestamp next to messages
    message_spacing: int = 8  # Vertical spacing between messages
    fade_old_messages: bool = True  # Fade out messages that overflow at top

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, including chat-specific props."""
        base = super().to_dict()
        base.update({
            'auto_hide': self.auto_hide,
            'auto_hide_delay': self.auto_hide_delay,
            'max_messages': self.max_messages,
            'sender_colors': self.sender_colors or {},
            'show_timestamps': self.show_timestamps,
            'message_spacing': self.message_spacing,
            'fade_old_messages': self.fade_old_messages,
            'is_chat_window': True,  # Flag to identify chat windows
        })
        return base

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatWindowProps":
        """Create from dictionary, ignoring unknown keys."""
        import dataclasses
        valid_fields = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid_fields})


