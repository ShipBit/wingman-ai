"""
HUD Server - Integrated HTTP server for HUD overlay control.

This server provides a REST API to control HUD overlays from any client.
It runs independently and can be used by multiple applications simultaneously.

Included modules:
- server.py: FastAPI HTTP server
- hud_manager.py: State management for HUD groups
- http_client.py: HTTP client for skills to use
- overlay/overlay.py: PIL-based overlay renderer (Windows)
- rendering/markdown.py: Markdown rendering
- platform/win32.py: Win32 API definitions
- hud_types.py: Type definitions for HUD elements
"""

from hud_server.server import HudServer
from hud_server.http_client import HudHttpClient, HudHttpClientSync
from hud_server.models import (
    HudServerSettings,
    GroupState,
    MessageRequest,
    ChatMessageRequest,
    ProgressRequest,
    TimerRequest,
    ItemRequest,
    StateRestoreRequest,
    HealthResponse,
    GroupStateResponse,
)

__all__ = [
    "HudServer",
    "HudHttpClient",
    "HudHttpClientSync",
    "HudServerSettings",
    "GroupState",
    "MessageRequest",
    "ChatMessageRequest",
    "ProgressRequest",
    "TimerRequest",
    "ItemRequest",
    "StateRestoreRequest",
    "HealthResponse",
    "GroupStateResponse",
]

