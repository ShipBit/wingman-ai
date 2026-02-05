"""
Pydantic Models for HUD Server API.

Defines all request/response models and configuration schemas for the HUD Server.
"""

from typing import Optional, Any
from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────── Configuration ─────────────────────────────── #


class HudServerSettings(BaseModel):
    """HUD Server settings for global configuration."""

    enabled: bool = False
    """Whether the HUD server should auto-start with Wingman AI Core."""

    host: str = Field(default="127.0.0.1", pattern=r"^(\d{1,3}\.){3}\d{1,3}$|^localhost$|^0\.0\.0\.0$")
    """The interface to listen on. Use '127.0.0.1' for local only, '0.0.0.0' for LAN access."""

    port: int = Field(default=7862, ge=1024, le=65535)
    """The port to listen on. Must be between 1024 and 65535."""

    framerate: int = Field(default=60, ge=1, le=240)
    """HUD overlay rendering framerate. Between 1 and 240 FPS."""

    layout_margin: int = Field(default=20, ge=0, le=200)
    """Margin from screen edges in pixels for HUD elements. Between 0 and 200."""

    layout_spacing: int = Field(default=15, ge=0, le=100)
    """Spacing between stacked HUD windows in pixels. Between 0 and 100."""

    @field_validator('host')
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Validate host is a valid IP address or hostname."""
        if v not in ['localhost', '0.0.0.0'] and not all(0 <= int(part) <= 255 for part in v.split('.')):
            raise ValueError('Invalid IP address format')
        return v


# ─────────────────────────────── Group Properties ─────────────────────────────── #


class HudGroupProps(BaseModel):
    """Properties for a HUD group. All properties are optional when updating."""

    # Position & Size
    x: int = Field(default=20, ge=-5000, le=10000)
    y: int = Field(default=20, ge=-5000, le=10000)
    width: int = Field(default=400, ge=100, le=3840)
    max_height: int = Field(default=600, ge=100, le=2160)

    # Colors (hex format)
    bg_color: str = Field(default="#1e212b", pattern=r"^#[0-9a-fA-F]{6}$")
    text_color: str = Field(default="#f0f0f0", pattern=r"^#[0-9a-fA-F]{6}$")
    accent_color: str = Field(default="#00aaff", pattern=r"^#[0-9a-fA-F]{6}$")
    title_color: Optional[str] = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")

    # Visual
    opacity: float = Field(default=0.85, ge=0.0, le=1.0)
    border_radius: int = Field(default=12, ge=0, le=50)
    font_size: int = Field(default=16, ge=8, le=72)
    font_family: str = "Segoe UI"
    content_padding: int = Field(default=16, ge=0, le=100)

    # Behavior
    typewriter_effect: bool = True
    typewriter_speed: int = Field(default=200, ge=1, le=1000)
    show_loader: bool = True
    auto_fade: bool = True
    fade_delay: float = Field(default=8.0, ge=0.0, le=300.0)
    fade_duration: float = Field(default=0.5, ge=0.1, le=10.0)

    # Rendering
    z_order: int = Field(default=0, ge=-1000, le=1000)

    # Layout Management
    layout_mode: str = Field(default="auto", pattern=r"^(auto|manual|hybrid)$")
    """Layout mode: 'auto' (automatic stacking), 'manual' (fixed x,y), 'hybrid' (auto with offset)."""

    anchor: str = Field(default="top_left", pattern=r"^(top_left|top_right|bottom_left|bottom_right|center)$")
    """Screen anchor for auto layout: 'top_left', 'top_right', 'bottom_left', 'bottom_right', 'center'."""

    priority: int = Field(default=10, ge=0, le=100)
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

    group_name: str = Field(..., min_length=1, max_length=100)
    """Name of the HUD group."""

    title: str = Field(..., min_length=1, max_length=200)
    """Message title."""

    content: str = Field(..., max_length=50000)
    """Message content (supports Markdown)."""

    color: Optional[str] = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    """Optional title/accent color override."""

    tools: Optional[list[dict[str, Any]]] = None
    """Optional tool information for display."""

    props: Optional[dict[str, Any]] = None
    """Optional property overrides for this message."""

    duration: Optional[float] = Field(default=None, ge=0.1, le=3600.0)
    """Optional duration in seconds before auto-hide (0.1 to 3600)."""


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

