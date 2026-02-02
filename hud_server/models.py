"""
Pydantic Models for HUD Server API.
"""

from typing import Optional, Any
from pydantic import BaseModel


# ─────────────────────────────── Configuration ─────────────────────────────── #


class HudServerSettings(BaseModel):
    """HUD Server settings for global configuration."""

    enabled: bool = False
    """Whether the HUD server should auto-start with Wingman AI Core."""

    host: str = "127.0.0.1"
    """The interface to listen on. Use '127.0.0.1' for local only, '0.0.0.0' for LAN access."""

    port: int = 7862
    """The port to listen on."""

    framerate: int = 60
    """HUD overlay rendering framerate. Minimum 1."""

    layout_margin: int = 20
    """Margin from screen edges in pixels for HUD elements."""

    layout_spacing: int = 15
    """Spacing between stacked HUD windows in pixels."""


# ─────────────────────────────── Group Properties ─────────────────────────────── #


class HudGroupProps(BaseModel):
    """Properties for a HUD group. All properties are optional when updating."""

    # Position & Size
    x: int = 20
    y: int = 20
    width: int = 400
    max_height: int = 600

    # Colors
    bg_color: str = "#1e212b"
    text_color: str = "#f0f0f0"
    accent_color: str = "#00aaff"
    title_color: Optional[str] = None

    # Visual
    opacity: float = 0.85
    border_radius: int = 12
    font_size: int = 16
    font_family: str = "Segoe UI"
    content_padding: int = 16

    # Behavior
    typewriter_effect: bool = True
    typewriter_speed: int = 200
    show_loader: bool = True
    auto_fade: bool = True
    fade_delay: float = 8.0
    fade_duration: float = 0.5

    # Rendering
    z_order: int = 0

    # Layout Management
    layout_mode: str = "auto"
    """Layout mode: 'auto' (automatic stacking), 'manual' (fixed x,y), 'hybrid' (auto with offset)."""

    anchor: str = "top_left"
    """Screen anchor for auto layout: 'top_left', 'top_right', 'bottom_left', 'bottom_right', 'center'."""

    priority: int = 10
    """Stacking priority within anchor zone. Higher = closer to anchor point."""



class ChatWindowProps(HudGroupProps):
    """Extended properties for chat window groups."""

    auto_hide: bool = False
    auto_hide_delay: float = 10.0
    max_messages: int = 50
    sender_colors: Optional[dict[str, str]] = None
    show_timestamps: bool = False
    message_spacing: int = 8
    fade_old_messages: bool = True
    is_chat_window: bool = True


# ─────────────────────────────── State Management ─────────────────────────────── #


class GroupState(BaseModel):
    """State of a HUD group for persistence."""

    props: dict[str, Any] = {}
    """Group properties."""

    messages: list[dict[str, Any]] = []
    """Current messages in the group."""

    items: list[dict[str, Any]] = []
    """Persistent items in the group."""

    chat_messages: list[dict[str, Any]] = []
    """Chat messages (for chat windows)."""


# ─────────────────────────────── API Requests ─────────────────────────────── #


class CreateGroupRequest(BaseModel):
    """Request to create a new HUD group."""

    group_name: str
    """Unique name for this group."""

    props: Optional[dict[str, Any]] = None
    """Optional properties for the group."""


class UpdateGroupRequest(BaseModel):
    """Request to update group properties."""

    group_name: str
    """Name of the group to update."""

    props: dict[str, Any]
    """Properties to update."""


class MessageRequest(BaseModel):
    """Request to show a message in a group."""

    group_name: str
    """Name of the HUD group."""

    title: str
    """Message title."""

    content: str
    """Message content (supports Markdown)."""

    color: Optional[str] = None
    """Optional title/accent color override."""

    tools: Optional[list[dict[str, Any]]] = None
    """Optional tool information for display."""

    props: Optional[dict[str, Any]] = None
    """Optional property overrides for this message."""

    duration: Optional[float] = None
    """Optional duration in seconds before auto-hide."""


class AppendMessageRequest(BaseModel):
    """Request to append content to current message (streaming)."""

    group_name: str
    content: str


class LoaderRequest(BaseModel):
    """Request to show/hide loader animation."""

    group_name: str
    show: bool = True
    color: Optional[str] = None


class ItemRequest(BaseModel):
    """Request to add/update a persistent item."""

    group_name: str
    """Name of the HUD group."""

    title: str
    """Item title/identifier (unique within group)."""

    description: str = ""
    """Item description."""

    color: Optional[str] = None
    """Optional title color."""

    duration: Optional[float] = None
    """Auto-remove after this many seconds."""


class UpdateItemRequest(BaseModel):
    """Request to update an existing item."""

    group_name: str
    title: str
    description: Optional[str] = None
    color: Optional[str] = None
    duration: Optional[float] = None


class RemoveItemRequest(BaseModel):
    """Request to remove an item."""

    group_name: str
    title: str


class ProgressRequest(BaseModel):
    """Request to show/update a progress bar."""

    group_name: str
    title: str
    current: float
    maximum: float = 100
    description: str = ""
    color: Optional[str] = None
    auto_close: bool = False
    props: Optional[dict[str, Any]] = None


class TimerRequest(BaseModel):
    """Request to show a timer-based progress bar."""

    group_name: str
    title: str
    duration: float
    description: str = ""
    color: Optional[str] = None
    auto_close: bool = True
    initial_progress: float = 0
    props: Optional[dict[str, Any]] = None


class ChatMessageRequest(BaseModel):
    """Request to send a chat message."""

    window_name: str
    """Name of the chat window."""

    sender: str
    """Sender name."""

    text: str
    """Message text."""

    color: Optional[str] = None
    """Optional sender color override."""


class CreateChatWindowRequest(BaseModel):
    """Request to create a chat window."""

    name: str
    x: int = 20
    y: int = 20
    width: int = 400
    max_height: int = 400
    auto_hide: bool = False
    auto_hide_delay: float = 10.0
    max_messages: int = 50
    sender_colors: Optional[dict[str, str]] = None
    fade_old_messages: bool = True
    props: Optional[dict[str, Any]] = None


class StateRestoreRequest(BaseModel):
    """Request to restore group state."""

    group_name: str
    """Name of the group to restore."""

    state: dict[str, Any]
    """The state to restore (from get_state endpoint)."""


# ─────────────────────────────── API Responses ─────────────────────────────── #


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "healthy"
    groups: list[str] = []
    """List of active group names."""

    version: str = "1.0.0"


class GroupStateResponse(BaseModel):
    """Response containing group state."""

    group_name: str
    state: dict[str, Any]


class OperationResponse(BaseModel):
    """Generic operation response."""

    status: str = "ok"
    message: Optional[str] = None


class ErrorResponse(BaseModel):
    """Error response."""

    status: str = "error"
    message: str
    detail: Optional[str] = None

