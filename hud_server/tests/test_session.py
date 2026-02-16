"""
Test Session - HTTP-based test infrastructure for HUD Server testing.

Provides the TestSession class that uses the HTTP API to send commands
to the HUD server and overlay.
"""

import httpx
from typing import Optional, Any

from hud_server.http_client import HudHttpClient
from hud_server.types import (
    Anchor, LayoutMode, HudColor, FontFamily,
    MessageProps, PersistentProps, ChatWindowProps, WindowType
)


# =============================================================================
# SESSION CONFIGURATIONS
# =============================================================================

SESSION_CONFIGS = {
    1: {
        "name": "Atlas",
        # Layout (anchor-based)
        "anchor": Anchor.TOP_LEFT,
        "priority": 20,
        "persistent_anchor": Anchor.TOP_LEFT,
        "persistent_priority": 10,
        "layout_mode": LayoutMode.AUTO,
        # Sizes
        "hud_width": 450,
        "persistent_width": 350,
        "hud_max_height": 500,
        # Visual
        "bg_color": HudColor.BG_DARK,
        "text_color": HudColor.TEXT_PRIMARY,
        "accent_color": HudColor.ACCENT_BLUE,
        "user_color": HudColor.SUCCESS,
        "opacity": 0.9,
        "border_radius": 12,
        "font_size": 16,
        "content_padding": 16,
        "typewriter_effect": True,
    },
    2: {
        "name": "Nova",
        # Layout (anchor-based)
        "anchor": Anchor.TOP_RIGHT,
        "priority": 20,
        "persistent_anchor": Anchor.TOP_RIGHT,
        "persistent_priority": 10,
        "layout_mode": LayoutMode.AUTO,
        # Sizes
        "hud_width": 400,
        "persistent_width": 320,
        "hud_max_height": 450,
        # Visual
        "bg_color": "#1a1f2e",
        "text_color": "#e8e8e8",
        "accent_color": HudColor.ACCENT_ORANGE,
        "user_color": "#ffd700",
        "opacity": 0.85,
        "border_radius": 8,
        "font_size": 14,
        "content_padding": 14,
        "typewriter_effect": True,
    },
    3: {
        "name": "Orion",
        # Layout (anchor-based)
        "anchor": Anchor.BOTTOM_LEFT,
        "priority": 20,
        "persistent_anchor": Anchor.BOTTOM_LEFT,
        "persistent_priority": 10,
        "layout_mode": LayoutMode.AUTO,
        # Sizes
        "hud_width": 380,
        "persistent_width": 300,
        "hud_max_height": 480,
        # Visual
        "bg_color": "#12161f",
        "text_color": "#d0d0d0",
        "accent_color": HudColor.ACCENT_PURPLE,
        "user_color": HudColor.ACCENT_GREEN,
        "opacity": 0.88,
        "border_radius": 16,
        "font_size": 15,
        "content_padding": 18,
        "typewriter_effect": False,
    },
}


class TestSession:
    """Manages a single HUD test session using HTTP API."""

    def __init__(self, session_id: int, config: dict[str, Any], base_url: str = "http://127.0.0.1:7862"):
        self.session_id = session_id
        self.config = config
        self.name = config["name"]
        self.base_url = base_url
        self._client: Optional[HudHttpClient] = None
        self.running = False

        # Group name for this session (just the identifier, element passed separately)
        self.group_name = f"session_{session_id}_{self.name.lower()}"

    async def start(self) -> bool:
        """Connect to the HUD server."""
        try:
            self._client = HudHttpClient(self.base_url)
            if await self._client.connect(timeout=5.0):
                self.running = True
                print(f"[Session {self.session_id} - {self.name}] Connected to {self.base_url}")
                return True
            else:
                print(f"[Session {self.session_id}] Failed to connect")
                return False
        except Exception as e:
            print(f"[Session {self.session_id}] Error: {e}")
            return False

    async def stop(self):
        """Disconnect from the HUD server."""
        if self._client:
            await self._client.disconnect()
        self.running = False
        print(f"[Session {self.session_id} - {self.name}] Disconnected")

    def _get_props(self) -> MessageProps:
        """Get display properties from config as MessageProps."""
        return MessageProps(
            # Layout (anchor-based)
            anchor=self._get_color_value(self.config.get("anchor", Anchor.TOP_LEFT)),
            priority=self.config.get("priority", 20),
            layout_mode=self._get_color_value(self.config.get("layout_mode", LayoutMode.AUTO)),
            # Size
            width=self.config["hud_width"],
            max_height=self.config["hud_max_height"],
            # Visual
            bg_color=self._get_color_value(self.config["bg_color"]),
            text_color=self._get_color_value(self.config["text_color"]),
            accent_color=self._get_color_value(self.config["accent_color"]),
            opacity=self.config["opacity"],
            border_radius=self.config["border_radius"],
            font_size=self.config["font_size"],
            content_padding=self.config["content_padding"],
            typewriter_effect=self.config["typewriter_effect"],
            fade_delay=8.0,
        )

    def _get_persistent_props(self) -> PersistentProps:
        """Get persistent panel properties from config as PersistentProps."""
        return PersistentProps(
            # Layout (anchor-based)
            anchor=self._get_color_value(self.config.get("persistent_anchor", Anchor.TOP_LEFT)),
            priority=self.config.get("persistent_priority", 10),
            layout_mode=self._get_color_value(self.config.get("layout_mode", LayoutMode.AUTO)),
            # Size
            width=self.config["persistent_width"],
            # Visual
            bg_color=self._get_color_value(self.config["bg_color"]),
            text_color=self._get_color_value(self.config["text_color"]),
            accent_color=self._get_color_value(self.config["accent_color"]),
            opacity=self.config["opacity"],
            border_radius=self.config["border_radius"],
            font_size=self.config["font_size"],
            content_padding=self.config["content_padding"],
        )

    def _get_color_value(self, value: Any) -> str:
        """Get the string value from a color/enum or return as-is."""
        if hasattr(value, 'value'):
            return value.value
        return value

    # =========================================================================
    # Message Commands
    # =========================================================================

    async def draw_message(self, title: str, message: str, color: Optional[str] = None,
                           tools: Optional[list[dict]] = None):
        """Draw a message on the overlay."""
        if not self._client:
            return
        color_value = color or self.config["accent_color"]
        if hasattr(color_value, 'value'):
            color_value = color_value.value
        await self._client.show_message(
            group_name=self.group_name,
            element=WindowType.MESSAGE,
            title=title,
            content=message,
            color=color_value,
            tools=tools,
            props=self._get_props().to_dict(),
        )

    async def draw_message_with_props(self, title: str, message: str, custom_props: dict):
        """Draw a message with custom properties (e.g., smaller max_height to trigger overflow)."""
        if not self._client:
            return
        # Start with default props and merge custom props
        base_props = self._get_props().to_dict()
        base_props.update(custom_props)

        color_value = self.config["accent_color"]
        if hasattr(color_value, 'value'):
            color_value = color_value.value

        await self._client.show_message(
            group_name=self.group_name,
            element=WindowType.MESSAGE,
            title=title,
            content=message,
            color=color_value,
            props=base_props,
        )

    async def draw_user_message(self, message: str):
        """Draw a user message."""
        color_value = self.config["user_color"]
        if hasattr(color_value, 'value'):
            color_value = color_value.value
        await self.draw_message("USER", message, color_value)

    async def draw_assistant_message(self, message: str, tools: Optional[list[dict]] = None):
        """Draw an assistant message."""
        color_value = self.config["accent_color"]
        if hasattr(color_value, 'value'):
            color_value = color_value.value
        await self.draw_message(self.name, message, color_value, tools)

    async def hide(self):
        """Hide the current message."""
        if not self._client:
            return
        await self._client.hide_message(group_name=self.group_name, element=WindowType.MESSAGE)

    async def set_loading(self, state: bool):
        """Set loading indicator state."""
        if not self._client:
            return
        color_value = self.config["accent_color"]
        if hasattr(color_value, 'value'):
            color_value = color_value.value
        await self._client.show_loader(
            group_name=self.group_name,
            element=WindowType.MESSAGE,
            show=state,
            color=color_value,
        )

    # =========================================================================
    # Persistent Info Commands
    # =========================================================================

    async def add_persistent_info(self, title: str, description: str, duration: Optional[float] = None):
        """Add persistent information."""
        if not self._client:
            return
        await self._client.add_item(
            group_name=self.group_name,
            element=WindowType.PERSISTENT,
            title=title,
            description=description,
            duration=duration,
        )

    async def update_persistent_info(self, title: str, description: str):
        """Update persistent information."""
        if not self._client:
            return
        await self._client.update_item(
            group_name=self.group_name,
            element=WindowType.PERSISTENT,
            title=title,
            description=description,
        )

    async def remove_persistent_info(self, title: str):
        """Remove persistent information."""
        if not self._client:
            return
        await self._client.remove_item(group_name=self.group_name, element=WindowType.PERSISTENT, title=title)

    async def clear_all_persistent_info(self):
        """Clear all persistent information."""
        if not self._client:
            return
        await self._client.clear_items(group_name=self.group_name, element=WindowType.PERSISTENT)

    # =========================================================================
    # Element Visibility Commands
    # =========================================================================

    async def hide_element(self, element: WindowType):
        """Hide a HUD element (message, persistent, or chat)."""
        if not self._client:
            return
        await self._client.hide_element(group_name=self.group_name, element=element)

    async def show_element(self, element: WindowType):
        """Show a HUD element (message, persistent, or chat)."""
        if not self._client:
            return
            group = self.group_name
        await self._client.show_element(group_name=group, element=element)

    async def hide_persistent(self):
        """Hide the persistent info panel."""
        await self.hide_element(WindowType.PERSISTENT)

    async def show_persistent(self):
        """Show the persistent info panel."""
        await self.show_element(WindowType.PERSISTENT)

    # =========================================================================
    # Progress Commands
    # =========================================================================

    async def show_progress(self, title: str, current: float, maximum: float,
                            description: str = "", auto_close: bool = False,
                            progress_color: Optional[str] = None):
        """Show a graphical progress bar."""
        if not self._client:
            return
        await self._client.show_progress(
            group_name=self.group_name,
            element=WindowType.PERSISTENT,
            title=title,
            current=current,
            maximum=maximum,
            description=description,
            color=progress_color,
            auto_close=auto_close,
        )

    async def show_timer(self, title: str, duration: float, description: str = "",
                         auto_close: bool = True, progress_color: Optional[str] = None):
        """Show a timer-based progress bar."""
        if not self._client:
            return
        await self._client.show_timer(
            group_name=self.group_name,
            element=WindowType.PERSISTENT,
            title=title,
            duration=duration,
            description=description,
            color=progress_color,
            auto_close=auto_close,
        )

    # =========================================================================
    # Chat Window Commands
    # =========================================================================

    async def create_chat_window(self, name: str, **props):
        """Create a chat window."""
        if not self._client:
            return
        await self._client.create_chat_window(group_name=name, element=WindowType.CHAT, **props)

    async def send_chat_message(self, window_name: str, sender: str, text: str,
                                color: Optional[str] = None) -> Optional[str]:
        """Send a message to a chat window. Returns the message ID."""
        if not self._client:
            return None
        result = await self._client.send_chat_message(
            group_name=window_name,
            element=WindowType.CHAT,
            sender=sender,
            text=text,
            color=color,
        )
        if result:
            return result.get("message_id")
        return None

    async def update_chat_message(self, window_name: str, message_id: str, text: str):
        """Update an existing chat message's text content by its ID."""
        if not self._client:
            return
        await self._client.update_chat_message(
            group_name=window_name,
            element=WindowType.CHAT,
            message_id=message_id,
            text=text,
        )

    async def clear_chat_window(self, name: str):
        """Clear a chat window."""
        if not self._client:
            return
        await self._client.clear_chat_window(group_name=name, element=WindowType.CHAT)

    async def delete_chat_window(self, name: str):
        """Delete a chat window."""
        if not self._client:
            return
        await self._client.delete_chat_window(group_name=name, element=WindowType.CHAT)

    async def show_chat_window(self, name: str):
        """Show a chat window."""
        if not self._client:
            return
        await self._client.show_chat_window(group_name=name, element=WindowType.CHAT)

    async def hide_chat_window(self, name: str):
        """Hide a chat window."""
        if not self._client:
            return
        await self._client.hide_chat_window(group_name=name, element=WindowType.CHAT)

    # =========================================================================
    # State Management
    # =========================================================================

    async def get_state(self) -> Optional[dict]:
        """Get the current state of this session's group."""
        if not self._client:
            return None
        result = await self._client.get_state(self.group_name)
        return result.get("state") if result else None

    async def health_check(self) -> bool:
        """Check if the server is healthy."""
        if not self._client:
            return False
        return await self._client.health_check()

    async def update_settings(self, framerate: Optional[int] = None,
                           layout_margin: Optional[int] = None,
                           layout_spacing: Optional[int] = None,
                           screen: Optional[int] = None):
        """Update HUD server settings dynamically.

        Args:
            framerate: New framerate (1-240)
            layout_margin: New layout margin in pixels
            layout_spacing: New layout spacing in pixels
            screen: New screen index (1=primary, etc.)
        """
        if not self._client:
            print(f"[{self.name}] Cannot update settings: not connected")
            return

        # Build query parameters
        params = {}
        if framerate is not None:
            params["framerate"] = framerate
        if layout_margin is not None:
            params["layout_margin"] = layout_margin
        if layout_spacing is not None:
            params["layout_spacing"] = layout_spacing
        if screen is not None:
            params["screen"] = screen

        print(f"[{self.name}] Updating settings: {params}")

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{self.base_url}/settings/update",
                    params=params
                )
                if response.status_code == 200:
                    print(f"[{self.name}] Settings updated successfully")
                else:
                    print(f"[{self.name}] Settings update failed: {response.status_code}")
        except Exception as e:
            print(f"[{self.name}] Settings update error: {e}")

