"""
Pydantic Models for HUD Server API.

Defines all request/response models and configuration schemas for the HUD Server.
"""

from typing import Optional, Any
from pydantic import BaseModel, Field, field_validator
from hud_server.types import WindowType


# ─────────────────────────────── Configuration ─────────────────────────────── #


# ─────────────────────────────── Group Properties ─────────────────────────────── #


# ─────────────────────────────── State Management ─────────────────────────────── #


# ─────────────────────────────── API Requests ─────────────────────────────── #


class CreateGroupRequest(BaseModel):
    """Request to create a new HUD group."""

    group_name: str
    """Unique name for the group (e.g., wingman name)."""

    element: WindowType
    """The element type for this group (message, persistent, or chat)."""

    props: Optional[dict[str, Any]] = None
    """Optional properties for the group."""


class UpdateGroupRequest(BaseModel):
    """Request to update group properties. The path names the group and element."""

    group_name: Optional[str] = None
    """Name of the group to update (ignored, the path wins)."""

    element: Optional[WindowType] = None
    """The element type (ignored, the path wins)."""

    props: dict[str, Any]
    """Properties to update."""


class DefaultsRequest(BaseModel):
    """Values every group uses for the props its own calls leave out."""

    props: dict[str, Any] = {}
    """Defaults for every group (style)."""

    groups: dict[str, dict[str, Any]] = {}
    """Defaults per group name, applied on top of `props` (e.g. a container's area)."""


class PreviewRequest(BaseModel):
    """Show the shared containers as preview panels that fill their whole area."""

    containers: dict[str, dict[str, Any]]
    """"chat" and/or "info" mapped to fully resolved props (x, y, width, max_height, style)."""

    interactive: bool = False
    """Let the mouse move and resize the preview panels."""


class PreviewResponse(BaseModel):
    """The current preview, with the areas as the mouse left them."""

    active: bool
    interactive: bool = False
    containers: dict[str, dict[str, Any]] = {}


class MessageRequest(BaseModel):
    """Request to show a message in a group."""

    group_name: str = Field(..., min_length=1, max_length=100)
    """Name of the HUD group (e.g., wingman name)."""

    element: WindowType
    """The element type (message, persistent, or chat)."""

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

    title_icon: Optional[str] = None
    """Optional local file path to an icon shown in front of the title (e.g. an avatar)."""


class AppendMessageRequest(BaseModel):
    """Request to append content to current message (streaming)."""

    group_name: str
    element: WindowType
    content: str


class LoaderRequest(BaseModel):
    """Request to show/hide loader animation."""

    group_name: str
    element: WindowType
    show: bool = True
    color: Optional[str] = None


class ItemRequest(BaseModel):
    """Request to add/update a persistent item."""

    group_name: str
    """Name of the HUD group (e.g., wingman name)."""

    element: WindowType
    """The element type (must be persistent)."""

    title: str
    """Item title/identifier (unique within group)."""

    description: str = ""
    """Item description."""

    color: Optional[str] = None
    """Optional title color."""

    duration: Optional[float] = None
    """Auto-remove after this many seconds."""

    added_by: Optional[str] = None
    """Who adds it, e.g. a Wingman's name. Shown to whoever reads the panel."""


class UpdateItemRequest(BaseModel):
    """Request to update an existing item."""

    group_name: str
    element: WindowType
    title: str
    description: Optional[str] = None
    color: Optional[str] = None
    duration: Optional[float] = None


class ProgressRequest(BaseModel):
    """Request to show/update a progress bar."""

    group_name: str
    element: WindowType
    title: str
    current: float
    maximum: float = 100
    description: str = ""
    color: Optional[str] = None
    auto_close: bool = False
    added_by: Optional[str] = None
    """Who adds it, e.g. a Wingman's name. Shown to whoever reads the panel."""


class TimerRequest(BaseModel):
    """Request to show a timer-based progress bar."""

    group_name: str
    element: WindowType
    title: str
    duration: float
    description: str = ""
    color: Optional[str] = None
    auto_close: bool = True
    initial_progress: float = 0
    added_by: Optional[str] = None
    """Who adds it, e.g. a Wingman's name. Shown to whoever reads the panel."""


class ChatMessageRequest(BaseModel):
    """Request to send a chat message."""

    group_name: str
    """Name of the HUD group."""

    element: WindowType
    """The element type (must be chat)."""

    sender: str
    """Sender name."""

    text: str
    """Message text."""

    color: Optional[str] = None
    """Optional sender color override."""

    icon: Optional[str] = None
    """Path of the sender's picture, shown round next to the message."""

    own: bool = False
    """Written by the user: a bubble on the right, like in a messenger."""

    tools: Optional[list[dict[str, Any]]] = None
    """Tool chips under the message, as with a message window."""


class ChatMessageUpdateRequest(BaseModel):
    """Request to update an existing chat message."""

    group_name: str
    """Name of the HUD group."""

    element: WindowType
    """The element type."""

    message_id: str
    """ID of the message to update (returned by send_chat_message)."""

    text: str
    """New message text to replace the existing content."""


class CreateChatWindowRequest(BaseModel):
    """Request to create a chat window."""

    group_name: str
    """Name of the HUD group (e.g., wingman name)."""

    element: WindowType
    """The element type (must be chat)."""

    anchor: Optional[str] = "top_left"
    """Screen anchor point."""

    priority: int = 5
    """Stacking priority within anchor zone."""

    layout_mode: str = "auto"
    """Layout mode (auto or manual)."""

    x: int = 20
    y: int = 20
    width: int = 400
    max_height: int = 400
    bg_color: Optional[str] = None
    text_color: Optional[str] = None
    accent_color: Optional[str] = None
    opacity: Optional[float] = None
    font_size: Optional[int] = None
    font_family: Optional[str] = None
    border_radius: Optional[int] = None
    auto_hide: bool = False
    auto_hide_delay: float = 10.0
    max_messages: int = 50
    sender_colors: Optional[dict[str, str]] = None
    fade_old_messages: bool = True
    props: Optional[dict[str, Any]] = None


# ─────────────────────────────── API Responses ─────────────────────────────── #


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "healthy"
    groups: list[str] = []
    """List of active group names."""

    version: str = "1.0.0"


class OperationResponse(BaseModel):
    """Generic operation response."""

    status: str = "ok"
    message: Optional[str] = None


class ChatMessageResponse(BaseModel):
    """Response from sending a chat message, includes the message ID."""

    status: str = "ok"
    message_id: str
    """The unique ID of the message (new or merged)."""
