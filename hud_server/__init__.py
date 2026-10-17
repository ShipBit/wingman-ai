"""
HUD Server - Integrated HTTP server for HUD overlay control.

This server provides a REST API to control HUD overlays from any client.
It runs independently and can be used by multiple applications simultaneously.

Included modules:
- server.py: FastAPI HTTP server
- hud_manager.py: State management for HUD groups
- http_client.py: HTTP client for skills to use
- types.py: Type definitions (enums, property classes) for HUD elements
- overlay/overlay.py: PIL-based overlay renderer (any OS)
- rendering/markdown.py: Markdown rendering
- platform/: the bridge to the OS, one window backend per OS (Windows for now)

Type-Safe Usage:
    from hud_server import HudHttpClient, Anchor, HudColor, FontFamily, WindowType
    from hud_server.types import message_props, chat_window_props

    async with HudHttpClient() as client:
        # Create group with typed props
        props = message_props(
            anchor=Anchor.TOP_RIGHT,
            accent_color=HudColor.WARNING,
            font_family=FontFamily.CONSOLAS
        )
        await client.create_group("alerts", WindowType.MESSAGE, props=props)

        # Use enums directly in method calls
        await client.show_message(
            "alerts",
            WindowType.MESSAGE,
            "Warning",
            "Low fuel!",
            color=HudColor.WARNING
        )
"""

from hud_server.server import HudServer
from hud_server.http_client import HudHttpClient, HudHttpClientSync
from hud_server.models import (
    MessageRequest,
    ChatMessageRequest,
    ProgressRequest,
    TimerRequest,
    ItemRequest,
    HealthResponse,
)
from hud_server.types import (
    # Enums
    Anchor,
    LayoutMode,
    FontFamily,
    HudColor,
    WindowType,
    FadeState,
    # Property classes
    BaseProps,
    MessageProps,
    PersistentProps,
    ChatWindowProps,
    ProgressProps,
    TimerProps,
    # Helper functions
    color,
    rgb,
    # Convenience constructors
    message_props,
    chat_window_props,
    persistent_props,
    # Defaults
    Defaults,
)

__all__ = [
    # Server and clients
    "HudServer",
    "HudHttpClient",
    "HudHttpClientSync",
    # Models
    "MessageRequest",
    "ChatMessageRequest",
    "ProgressRequest",
    "TimerRequest",
    "ItemRequest",
    "HealthResponse",
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

