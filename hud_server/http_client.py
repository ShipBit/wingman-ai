# -*- coding: utf-8 -*-
"""
HUD HTTP Client - Client for interacting with the integrated HUD Server.

Provides both async and sync APIs for controlling HUD groups via HTTP.
This replaces the WebSocket-based client for the integrated HUD server.

Usage:
    from hud_server.http_client import HudHttpClient
    from hud_server.types import Anchor, HudColor, FontFamily, message_props

    # Async usage with type-safe props
    async with HudHttpClient() as client:
        # Using convenience constructors
        props = message_props(
            anchor=Anchor.TOP_RIGHT,
            accent_color=HudColor.ACCENT_ORANGE,
            font_family=FontFamily.CONSOLAS
        )
        await client.create_group("notifications", props=props)
        await client.show_message("notifications", "Alert", "Something happened!")

        # Using enums directly (auto-converted to values)
        await client.create_chat_window(
            "chat",
            anchor=Anchor.BOTTOM_LEFT,
            width=500
        )

    # Sync usage
    client = HudHttpClientSync()
    client.connect()
    client.show_message("group1", "Title", "Content", color=HudColor.SUCCESS)
    client.disconnect()

For available property types and values, see:
    - hud_server.types - Enums and typed property classes
    - Anchor, LayoutMode - Position/layout options
    - HudColor - Predefined color palette
    - FontFamily - Available fonts
    - MessageProps, ChatWindowProps, PersistentProps - Typed property containers
"""

import asyncio
import threading
import httpx
from typing import Optional, Any, Union
from urllib.parse import quote
from api.enums import LogType
from hud_server.constants import PATH_GROUPS, PATH_STATE, PATH_STATE_RESTORE, PATH_HEALTH, PATH_MESSAGE, \
    PATH_MESSAGE_APPEND, PATH_MESSAGE_HIDE, PATH_LOADER, PATH_ITEMS, PATH_PROGRESS, PATH_TIMER, PATH_CHAT_WINDOW, \
    PATH_CHAT_MESSAGE, PATH_CHAT_SHOW, PATH_CHAT_HIDE, PATH_ELEMENT_SHOW, PATH_ELEMENT_HIDE
from services.printr import Printr
from hud_server import constants as hud_const
from hud_server.types import (
    Anchor,
    LayoutMode,
    HudColor,
    FontFamily,
    BaseProps,
    WindowType
)

printr = Printr()


def _resolve_enum(value: Any) -> Any:
    """Convert enum values to their string representation."""
    if isinstance(value, (Anchor, LayoutMode, HudColor, FontFamily, WindowType)):
        return value.value
    return value


def _resolve_props(props: Optional[BaseProps]) -> Optional[dict]:
    """Resolve all enum values in a props dictionary or BaseProps instance."""
    if props is None:
        return None
    # Convert BaseProps to dict if needed
    props_dict = props.to_dict() if isinstance(props, BaseProps) else props
    return {k: _resolve_enum(v) for k, v in props_dict.items()}


class HudHttpClient:
    """Async HTTP client for the HUD Server."""

    # Timeout constants
    DEFAULT_CONNECT_TIMEOUT = hud_const.HTTP_CONNECT_TIMEOUT
    DEFAULT_REQUEST_TIMEOUT = hud_const.HTTP_REQUEST_TIMEOUT
    RECONNECT_ATTEMPTS = 1
    MAX_TIMEOUT_RETRIES = 3

    def __init__(self, base_url: str = f"http://{hud_const.DEFAULT_HOST}:{hud_const.DEFAULT_PORT}"):
        self.base_url = base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self, timeout: float = DEFAULT_CONNECT_TIMEOUT) -> bool:
        """
        Connect to the HUD server.

        Args:
            timeout: Connection timeout in seconds

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Close existing client if any - ignore all errors since the loop might be closed
            if self._client:
                try:
                    await self._client.aclose()
                except Exception:
                    pass  # Expected during cleanup
                self._client = None

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=timeout,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Accept": "application/json; charset=utf-8"
                }
            )
            # Test connection
            response = await self._client.get(PATH_HEALTH)
            if response.status_code == 200:
                self._connected = True
                return True
            return False
        except httpx.ConnectError:
            # Server not reachable - expected during startup/shutdown
            self._connected = False
            return False
        except Exception as e:
            # Unexpected error - log it
            printr.print(
                f"[HUD HTTP Client] Unexpected connection error: {type(e).__name__}: {e}",
                color=LogType.WARNING,
                server_only=True
            )
            self._connected = False
            return False

    async def disconnect(self):
        """Disconnect from the HUD server."""
        if self._client:
            await self._client.aclose()
        self._connected = False
        self._client = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[dict] = None
    ) -> Optional[dict]:
        """
        Make an HTTP request to the server.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            path: URL path
            json: Optional JSON payload

        Returns:
            Response JSON dict if successful, None otherwise
        """

        # Reconnect if not connected (either no client or marked as disconnected)
        if not self._client or not self._connected:
            if not await self.connect():
                return None

        async def _execute_request():
            """Execute the HTTP request with the given method."""
            if method == "GET":
                return await self._client.get(path)
            elif method == "POST":
                return await self._client.post(path, json=json)
            elif method == "PUT":
                return await self._client.put(path, json=json)
            elif method == "DELETE":
                return await self._client.delete(path)
            else:
                printr.print(
                    f"[HUD HTTP Client] Unsupported HTTP method: {method}",
                    color=LogType.ERROR,
                    server_only=True
                )
                return None

        for attempt in range(1, self.MAX_TIMEOUT_RETRIES + 1):
            try:
                response = await _execute_request()
                if response and 200 <= response.status_code < 300:
                    return response.json()
                elif response:
                    # Log non-2xx responses for debugging
                    printr.print(
                        f"[HUD HTTP Client] Request {method} {path} failed with status {response.status_code}",
                        color=LogType.WARNING,
                        server_only=True
                    )
                return None
            except RuntimeError as e:
                # Handle "Event loop is closed" error by reconnecting
                if "loop" in str(e).lower() or "closed" in str(e).lower():
                    self._connected = False
                    self._client = None
                    # Try to reconnect and retry once
                    if await self.connect():
                        try:
                            response = await _execute_request()
                            if response and 200 <= response.status_code < 300:
                                return response.json()
                        except Exception:
                            pass  # Give up after retry
                self._connected = False
                return None
            except httpx.ConnectError:
                # Server not reachable - don't spam logs
                self._connected = False
                return None
            except httpx.TimeoutException:
                if attempt < self.MAX_TIMEOUT_RETRIES:
                    continue
                printr.print(
                    f"[HUD HTTP Client] Request {method} {path} timed out after {self.MAX_TIMEOUT_RETRIES} attempts",
                    color=LogType.WARNING,
                    server_only=True
                )
                self._connected = False
                return None
            except Exception as e:
                printr.print(
                    f"[HUD HTTP Client] Request {method} {path} error: {type(e).__name__}: {e}",
                    color=LogType.WARNING,
                    server_only=True
                )
                self._connected = False
                return None
        return None

    # ─────────────────────────────── Health ─────────────────────────────── #

    async def health_check(self) -> bool:
        """Check if server is responsive."""
        result = await self._request("GET", PATH_HEALTH)
        return result is not None and result.get("status") == "healthy"

    async def get_status(self) -> Optional[dict]:
        """Get server status including all groups."""
        return await self._request("GET", PATH_HEALTH)

    # ─────────────────────────────── Groups ─────────────────────────────── #

    async def create_group(
        self,
        group_name: str,
        element: WindowType,
        props: Optional[BaseProps] = None
    ) -> Optional[dict]:
        """Create or update a HUD group.

        Args:
            group_name: Unique identifier for the group (e.g., wingman name)
            element: The element type for this group (message, persistent, or chat)
            props: Optional group properties (use types module for type-safe construction)

        Properties can include (see types.py for full list):
            - anchor: Screen anchor point (use Anchor enum)
            - layout_mode: 'auto', 'manual', 'hybrid' (use LayoutMode enum)
            - priority: Stacking priority (0-100)
            - width, max_height: Size in pixels
            - bg_color, text_color, accent_color: Colors (use HudColor enum)
            - opacity: Window opacity (0.0-1.0)
            - font_size, font_family: Typography (use FontFamily enum)
            - border_radius, content_padding: Visual styling

        Returns:
            Server response dict or None if failed

        Example:
            from hud_server.types import Anchor, HudColor, WindowType, message_props

            props = message_props(
                anchor=Anchor.TOP_RIGHT,
                accent_color=HudColor.ACCENT_ORANGE
            )
            await client.create_group("Computer", WindowType.PERSISTENT, props=props)
        """
        return await self._request("POST", PATH_GROUPS, {
            "group_name": group_name,
            "element": _resolve_enum(element),
            "props": _resolve_props(props)
        })

    async def update_group(
        self,
        group_name: str,
        element: WindowType,
        props: BaseProps
    ) -> bool:
        """Update properties of an existing group.

        The server will broadcast the updated props to the overlay for real-time updates.
        Props can contain enum values (Anchor, HudColor, etc.) which will be auto-resolved.

        Args:
            group_name: Name of the group to update
            element: The element type (message, persistent, or chat)
            props: Properties to update (use types module for type-safe construction)

        Returns:
            True if successful, False otherwise
        """
        encoded_group = quote(group_name, safe='')
        result = await self._request("PATCH", f"{PATH_GROUPS}/{encoded_group}", {
            "element": _resolve_enum(element),
            "props": _resolve_props(props)
        })
        return result is not None

    async def delete_group(self, group_name: str, element: WindowType) -> Optional[dict]:
        """Delete a HUD group."""
        encoded_group = quote(group_name, safe='')
        return await self._request("DELETE", f"{PATH_GROUPS}/{encoded_group}/{_resolve_enum(element)}")

    async def get_groups(self) -> Optional[dict]:
        """Get list of all group names."""
        return await self._request("GET", PATH_GROUPS)

    # ─────────────────────────────── State ─────────────────────────────── #

    async def get_state(self, group_name: str) -> Optional[dict]:
        """Get the current state of a group for persistence."""
        encoded_group = quote(group_name, safe='')
        return await self._request("GET", f"{PATH_STATE}/{encoded_group}")

    async def restore_state(self, group_name: str, state: dict) -> Optional[dict]:
        """Restore a group's state from a previous snapshot."""
        return await self._request("POST", PATH_STATE_RESTORE, {
            "group_name": group_name,
            "state": state
        })

    # ─────────────────────────────── Messages ─────────────────────────────── #

    async def show_message(
        self,
        group_name: str,
        element: WindowType,
        title: str,
        content: str,
        color: Optional[Union[str, HudColor]] = None,
        tools: Optional[list] = None,
        props: Optional[BaseProps] = None,
        duration: Optional[float] = None
    ) -> Optional[dict]:
        """Show a message in a HUD group.

        Args:
            group_name: Name of the HUD group (e.g., wingman name)
            element: The element type (message, persistent, or chat)
            title: Message title (displayed prominently)
            content: Message content (supports Markdown)
            color: Optional accent color override (use HudColor enum or hex string)
            tools: Optional list of tool information for display
            props: Optional MessageProps to override group defaults
            duration: Optional display duration in seconds (0.1-3600)

        Returns:
            Server response dict or None if failed

        Example:
            from hud_server.types import WindowType
            await client.show_message(
                "Computer",
                WindowType.MESSAGE,
                "Alert",
                "Something **important** happened!",
                color=HudColor.WARNING,
                duration=10.0
            )
        """
        data: dict[str, Any] = {
            "group_name": group_name,
            "element": _resolve_enum(element),
            "title": title,
            "content": content
        }
        if color:
            data["color"] = _resolve_enum(color)
        if tools:
            data["tools"] = tools
        if props:
            data["props"] = _resolve_props(props)
        if duration is not None:
            data["duration"] = duration

        return await self._request("POST", PATH_MESSAGE, data)

    async def append_message(
        self,
        group_name: str,
        element: WindowType,
        content: str
    ) -> Optional[dict]:
        """Append content to the current message (for streaming)."""
        return await self._request("POST", PATH_MESSAGE_APPEND, {
            "group_name": group_name,
            "element": _resolve_enum(element),
            "content": content
        })

    async def hide_message(self, group_name: str, element: WindowType) -> Optional[dict]:
        """Hide the current message in a group."""
        encoded_group = quote(group_name, safe='')
        return await self._request("POST", f"{PATH_MESSAGE_HIDE}/{encoded_group}/{_resolve_enum(element)}")

    # ─────────────────────────────── Loader ─────────────────────────────── #

    async def show_loader(
        self,
        group_name: str,
        element: WindowType,
        show: bool = True,
        color: Optional[Union[str, HudColor]] = None
    ) -> Optional[dict]:
        """Show or hide the loader animation.

        Args:
            group_name: Name of the HUD group
            element: The element type (message, persistent, or chat)
            show: True to show, False to hide
            color: Optional loader color (use HudColor enum or hex string)

        Returns:
            Server response dict or None if failed
        """
        data = {
            "group_name": group_name,
            "element": _resolve_enum(element),
            "show": show
        }
        if color:
            data["color"] = _resolve_enum(color)
        return await self._request("POST", PATH_LOADER, data)

    # ─────────────────────────────── Items ─────────────────────────────── #

    async def add_item(
        self,
        group_name: str,
        element: WindowType,
        title: str,
        description: str = "",
        color: Optional[Union[str, HudColor]] = None,
        duration: Optional[float] = None
    ) -> Optional[dict]:
        """Add a persistent item to a group.

        Args:
            group_name: Name of the HUD group (e.g., wingman name)
            element: The element type (must be WindowType.PERSISTENT)
            title: Item title (unique identifier within group)
            description: Item description text
            color: Optional item color (use HudColor enum or hex string)
            duration: Optional auto-remove duration in seconds

        Returns:
            Server response dict or None if failed

        Example:
            from hud_server.types import WindowType
            await client.add_item(
                "Computer",
                WindowType.PERSISTENT,
                "Shield Status",
                "Shields at 100%",
                color=HudColor.SHIELD
            )
        """
        data: dict[str, Any] = {
            "group_name": group_name,
            "element": _resolve_enum(element),
            "title": title,
            "description": description
        }
        if color:
            data["color"] = _resolve_enum(color)
        if duration is not None:
            data["duration"] = duration

        return await self._request("POST", PATH_ITEMS, data)

    async def update_item(
        self,
        group_name: str,
        element: WindowType,
        title: str,
        description: Optional[str] = None,
        color: Optional[Union[str, HudColor]] = None,
        duration: Optional[float] = None
    ) -> Optional[dict]:
        """Update an existing item.

        Args:
            group_name: Name of the HUD group
            element: The element type (must be WindowType.PERSISTENT)
            title: Item title to update
            description: New description (None to keep current)
            color: New color (use HudColor enum or hex string, None to keep current)
            duration: New auto-remove duration (None to keep current)

        Returns:
            Server response dict or None if failed
        """
        data: dict[str, Any] = {
            "group_name": group_name,
            "element": _resolve_enum(element),
            "title": title
        }
        if description is not None:
            data["description"] = description
        if color is not None:
            data["color"] = _resolve_enum(color)
        if duration is not None:
            data["duration"] = duration

        return await self._request("PUT", PATH_ITEMS, data)

    async def remove_item(self, group_name: str, element: WindowType, title: str) -> Optional[dict]:
        """Remove an item from a group."""
        encoded_title = quote(title, safe='')
        return await self._request("DELETE", f"{PATH_ITEMS}/{group_name}/{_resolve_enum(element)}/{encoded_title}")

    async def clear_items(self, group_name: str, element: WindowType) -> Optional[dict]:
        """Clear all items from a group."""
        encoded_group = quote(group_name, safe='')
        return await self._request("DELETE", f"{PATH_ITEMS}/{encoded_group}/{_resolve_enum(element)}")

    # ─────────────────────────────── Progress ─────────────────────────────── #

    async def show_progress(
        self,
        group_name: str,
        element: WindowType,
        title: str,
        current: float,
        maximum: float = 100,
        description: str = "",
        color: Optional[Union[str, HudColor]] = None,
        auto_close: bool = False,
        props: Optional[BaseProps] = None
    ) -> Optional[dict]:
        """Show or update a progress bar.

        Args:
            group_name: Name of the HUD group
            element: The element type (must be WindowType.PERSISTENT)
            title: Progress bar title
            current: Current progress value
            maximum: Maximum progress value (default: 100)
            description: Optional description text
            color: Progress bar color (use HudColor enum or hex string)
            auto_close: Automatically close when progress reaches maximum
            props: Optional ProgressProps for styling

        Returns:
            Server response dict or None if failed

        Example:
            from hud_server.types import WindowType
            await client.show_progress(
                "Computer",
                WindowType.PERSISTENT,
                "Downloading...",
                current=45,
                maximum=100,
                color=HudColor.INFO,
                auto_close=True
            )
        """
        data: dict[str, Any] = {
            "group_name": group_name,
            "element": _resolve_enum(element),
            "title": title,
            "current": current,
            "maximum": maximum,
            "description": description,
            "auto_close": auto_close
        }
        if color:
            data["color"] = _resolve_enum(color)
        if props:
            data["props"] = _resolve_props(props)

        return await self._request("POST", PATH_PROGRESS, data)

    async def show_timer(
        self,
        group_name: str,
        element: WindowType,
        title: str,
        duration: float,
        description: str = "",
        color: Optional[Union[str, HudColor]] = None,
        auto_close: bool = True,
        initial_progress: float = 0,
        props: Optional[BaseProps] = None
    ) -> Optional[dict]:
        """Show a timer-based progress bar.

        Args:
            group_name: Name of the HUD group
            element: The element type (must be WindowType.PERSISTENT)
            title: Timer title
            duration: Timer duration in seconds
            description: Optional description text
            color: Timer color (use HudColor enum or hex string)
            auto_close: Automatically close when timer completes (default: True)
            initial_progress: Starting progress value (0-100)
            props: Optional TimerProps for styling

        Returns:
            Server response dict or None if failed

        Example:
            from hud_server.types import WindowType
            await client.show_timer(
                "Computer",
                WindowType.PERSISTENT,
                "Quantum Cooldown",
                duration=30.0,
                color=HudColor.QUANTUM,
                auto_close=True
            )
        """
        data: dict[str, Any] = {
            "group_name": group_name,
            "element": _resolve_enum(element),
            "title": title,
            "duration": duration,
            "description": description,
            "auto_close": auto_close,
            "initial_progress": initial_progress
        }
        if color:
            data["color"] = _resolve_enum(color)
        if props:
            data["props"] = _resolve_props(props)

        return await self._request("POST", PATH_TIMER, data)

    # ─────────────────────────────── Chat Window ─────────────────────────────── #

    async def create_chat_window(
        self,
        group_name: str,
        element: WindowType,
        # Layout (anchor-based) - preferred
        anchor: Union[str, Anchor] = Anchor.TOP_LEFT,
        priority: int = 5,
        layout_mode: Union[str, LayoutMode] = LayoutMode.AUTO,
        # Legacy position - only used if layout_mode='manual'
        x: int = 20,
        y: int = 20,
        # Size
        width: int = 400,
        max_height: int = 400,
        # Colors
        bg_color: Optional[Union[str, HudColor]] = None,
        text_color: Optional[Union[str, HudColor]] = None,
        accent_color: Optional[Union[str, HudColor]] = None,
        # Behavior
        auto_hide: bool = False,
        auto_hide_delay: float = 10.0,
        max_messages: int = 50,
        sender_colors: Optional[dict[str, str]] = None,
        fade_old_messages: bool = True,
        # Additional props
        opacity: Optional[float] = None,
        font_size: Optional[int] = None,
        font_family: Optional[Union[str, FontFamily]] = None,
        border_radius: Optional[int] = None,
        **extra_props
    ) -> Optional[dict]:
        """Create a new chat window.

        Args:
            name: Unique name for the chat window
            anchor: Screen anchor point (use Anchor enum)
            priority: Stacking priority within anchor zone (0-100)
            layout_mode: Layout mode (use LayoutMode enum)
            x, y: Manual position (only used if layout_mode='manual')
            width: Window width in pixels
            max_height: Maximum height before scrolling
            bg_color: Background color (use HudColor enum or hex string)
            text_color: Text color (use HudColor enum or hex string)
            accent_color: Accent color (use HudColor enum or hex string)
            auto_hide: Automatically hide after inactivity
            auto_hide_delay: Seconds before auto-hide
            max_messages: Maximum messages to keep in history
            sender_colors: Dict mapping sender names to colors
            fade_old_messages: Fade older messages for visual distinction
            opacity: Window opacity (0.0-1.0)
            font_size: Font size in pixels (8-72)
            font_family: Font family (use FontFamily enum)
            border_radius: Corner radius in pixels (0-50)
            **extra_props: Additional props passed to the window

        Returns:
            Server response dict or None if failed

        Example:
            await client.create_chat_window(
                "game_chat",
                anchor=Anchor.BOTTOM_LEFT,
                width=500,
                max_messages=100,
                sender_colors={
                    "Player": HudColor.ACCENT_GREEN.value,
                    "AI": HudColor.ACCENT_BLUE.value
                }
            )
        """
        # Build props dict with type resolution
        props = {}
        if bg_color is not None:
            props["bg_color"] = _resolve_enum(bg_color)
        if text_color is not None:
            props["text_color"] = _resolve_enum(text_color)
        if accent_color is not None:
            props["accent_color"] = _resolve_enum(accent_color)
        if opacity is not None:
            props["opacity"] = opacity
        if font_size is not None:
            props["font_size"] = font_size
        if font_family is not None:
            props["font_family"] = _resolve_enum(font_family)
        if border_radius is not None:
            props["border_radius"] = border_radius
        props.update(extra_props)

        data = {
            "group_name": group_name,
            "element": _resolve_enum(element),
            # Layout
            "anchor": _resolve_enum(anchor),
            "priority": priority,
            "layout_mode": _resolve_enum(layout_mode),
            # Legacy (for manual mode)
            "x": x,
            "y": y,
            # Size
            "width": width,
            "max_height": max_height,
            # Behavior
            "auto_hide": auto_hide,
            "auto_hide_delay": auto_hide_delay,
            "max_messages": max_messages,
            "sender_colors": sender_colors,
            "fade_old_messages": fade_old_messages,
            "props": props if props else None
        }
        return await self._request("POST", PATH_CHAT_WINDOW, data)

    async def delete_chat_window(self, group_name: str, element: WindowType) -> Optional[dict]:
        """Delete a chat window."""
        encoded_group = quote(group_name, safe='')
        return await self._request("DELETE", f"{PATH_CHAT_WINDOW}/{encoded_group}/{_resolve_enum(element)}")

    async def send_chat_message(
        self,
        group_name: str,
        element: WindowType,
        sender: str,
        text: str,
        color: Optional[Union[str, HudColor]] = None
    ) -> Optional[dict]:
        """Send a message to a chat window.

        Args:
            group_name: Name of the HUD group
            element: The element type (must be WindowType.CHAT)
            sender: Sender name displayed with the message
            text: Message text content
            color: Optional sender color override (use HudColor enum or hex string)

        Returns:
            Server response dict with message_id or None if failed

        Example:
            result = await client.send_chat_message(
                "game_chat",
                "Player",
                "Hello world!",
                color=HudColor.ACCENT_GREEN
            )
            message_id = result["message_id"]  # For later updates
        """
        data = {
            "group_name": group_name,
            "element": _resolve_enum(element),
            "sender": sender,
            "text": text
        }
        if color:
            data["color"] = _resolve_enum(color)

        return await self._request("POST", PATH_CHAT_MESSAGE, data)

    async def update_chat_message(
        self,
        group_name: str,
        element: WindowType,
        message_id: str,
        text: str
    ) -> Optional[dict]:
        """Update an existing chat message's text content by its ID."""
        data = {
            "group_name": group_name,
            "element": _resolve_enum(element),
            "message_id": message_id,
            "text": text
        }
        return await self._request("PUT", PATH_CHAT_MESSAGE, data)

    async def clear_chat_window(self, group_name: str, element: WindowType) -> Optional[dict]:
        """Clear all messages from a chat window."""
        encoded_group = quote(group_name, safe='')
        return await self._request("DELETE", f"{PATH_CHAT_MESSAGE}/{encoded_group}/{_resolve_enum(element)}")

    async def show_chat_window(self, group_name: str, element: WindowType) -> Optional[dict]:
        """Show a hidden chat window."""
        encoded_group = quote(group_name, safe='')
        return await self._request("POST", f"{PATH_CHAT_SHOW}/{encoded_group}/{_resolve_enum(element)}")

    async def hide_chat_window(self, group_name: str, element: WindowType) -> Optional[dict]:
        """Hide a chat window."""
        encoded_group = quote(group_name, safe='')
        return await self._request("POST", f"{PATH_CHAT_HIDE}/{encoded_group}/{_resolve_enum(element)}")

    # ─────────────────────────────── Element Visibility ─────────────────────────────── #

    async def show_element(
        self,
        group_name: str,
        element: WindowType
    ) -> Optional[dict]:
        """Show a hidden HUD element (message, persistent, or chat).

        Args:
            group_name: Name of the HUD group
            element: Element type to show - must be WindowType enum

        Returns:
            Server response dict or None if failed

        Example:
            # Show the persistent info panel for a wingman group
            from hud_server.types import WindowType
            await client.show_element("Computer", WindowType.PERSISTENT)
        """
        return await self._request("POST", PATH_ELEMENT_SHOW, {
            "group_name": group_name,
            "element": _resolve_enum(element)
        })

    async def hide_element(
        self,
        group_name: str,
        element: WindowType
    ) -> Optional[dict]:
        """Hide a HUD element (message, persistent, or chat).

        The element will no longer be displayed but will still receive updates
        and perform all logic (timers, auto-hide, updates) in the background.

        Args:
            group_name: Name of the HUD group
            element: Element type to hide - must be WindowType enum

        Returns:
            Server response dict or None if failed

        Example:
            # Hide the persistent info panel but keep receiving updates
            from hud_server.types import WindowType
            await client.hide_element("Computer", WindowType.PERSISTENT)
        """
        return await self._request("POST", PATH_ELEMENT_HIDE, {
            "group_name": group_name,
            "element": _resolve_enum(element)
        })



class HudHttpClientSync:
    """
    Synchronous wrapper for HudHttpClient.

    Useful for non-async code that needs to interact with the HUD server.
    Uses a background event loop in a dedicated thread for async operations.
    """

    # Timeout for synchronous operations
    SYNC_OPERATION_TIMEOUT = hud_const.SYNC_OPERATION_TIMEOUT

    def __init__(self, base_url: str = f"http://{hud_const.DEFAULT_HOST}:{hud_const.DEFAULT_PORT}"):
        self._base_url = base_url
        self._client: Optional[HudHttpClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._loop_started = threading.Event()

    def _ensure_loop(self) -> None:
        """Ensure event loop is running in background thread."""
        with self._lock:
            if self._loop is None or not self._loop.is_running():
                self._loop_started.clear()
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(
                    target=self._run_loop,
                    daemon=True,
                    name=hud_const.THREAD_NAME_CLIENT_LOOP
                )
                self._thread.start()
                # Wait for loop to start
                if not self._loop_started.wait(timeout=5.0):
                    printr.print(
                        "[HUD HTTP Client Sync] Event loop failed to start",
                        color=LogType.ERROR,
                        server_only=True
                    )

    def _run_loop(self) -> None:
        """Run event loop in background thread."""
        asyncio.set_event_loop(self._loop)
        self._loop_started.set()
        try:
            self._loop.run_forever()
        except Exception as e:
            printr.print(
                f"[HUD HTTP Client Sync] Event loop error: {type(e).__name__}: {e}",
                color=LogType.ERROR,
                server_only=True
            )

    def _run_coro(self, coro):
        """Run a coroutine in the background event loop."""
        self._ensure_loop()
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return future.result(timeout=self.SYNC_OPERATION_TIMEOUT)
        except TimeoutError:
            printr.print(
                f"[HUD HTTP Client Sync] Operation timed out after {self.SYNC_OPERATION_TIMEOUT}s",
                color=LogType.WARNING,
                server_only=True
            )
            return None
        except Exception as e:
            printr.print(
                f"[HUD HTTP Client Sync] Operation error: {type(e).__name__}: {e}",
                color=LogType.WARNING,
                server_only=True
            )
            return None

    @property
    def connected(self) -> bool:
        """Check if client is connected to server."""
        return self._client is not None and self._client.connected

    def connect(self, timeout: float = HudHttpClient.DEFAULT_CONNECT_TIMEOUT) -> bool:
        """
        Connect to the HUD server.

        Args:
            timeout: Connection timeout in seconds

        Returns:
            True if connection successful
        """
        with self._lock:
            self._ensure_loop()
            self._client = HudHttpClient(self._base_url)
            result = self._run_coro(self._client.connect(timeout))
            return result if result is not None else False

    def disconnect(self) -> None:
        """Disconnect from the HUD server and cleanup resources."""
        with self._lock:
            if self._client:
                self._run_coro(self._client.disconnect())
                self._client = None

            # Stop the event loop
            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)

            # Wait for thread to finish
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2.0)
                self._thread = None

            self._loop = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    # Forward all methods to the async client
    def health_check(self) -> bool:
        return self._run_coro(self._client.health_check()) if self._client else False

    def get_status(self) -> Optional[dict]:
        return self._run_coro(self._client.get_status()) if self._client else None

    def create_group(self, group_name: str, element: WindowType, props: Optional[BaseProps] = None):
        """Create or update a HUD group. Props can contain enum values."""
        return self._run_coro(self._client.create_group(group_name, element, props)) if self._client else None

    def update_group(self, group_name: str, element: WindowType, props: BaseProps) -> bool:
        """Update properties for an existing group. Props can contain enum values."""
        return self._run_coro(self._client.update_group(group_name, element, props)) if self._client else False

    def delete_group(self, group_name: str, element: WindowType):
        return self._run_coro(self._client.delete_group(group_name, element)) if self._client else None

    def get_groups(self):
        return self._run_coro(self._client.get_groups()) if self._client else None

    def get_state(self, group_name: str):
        return self._run_coro(self._client.get_state(group_name)) if self._client else None

    def restore_state(self, group_name: str, state: dict):
        return self._run_coro(self._client.restore_state(group_name, state)) if self._client else None

    def show_message(
        self,
        group_name: str,
        element: WindowType,
        title: str,
        content: str,
        color: Optional[Union[str, HudColor]] = None,
        tools: Optional[list] = None,
        props: Optional[BaseProps] = None,
        duration: Optional[float] = None
    ):
        """Show a message. Color accepts HudColor enum or hex string."""
        return self._run_coro(self._client.show_message(
            group_name, element, title, content, color, tools, props, duration
        )) if self._client else None

    def append_message(self, group_name: str, element: WindowType, content: str):
        return self._run_coro(self._client.append_message(group_name, element, content)) if self._client else None

    def hide_message(self, group_name: str, element: WindowType):
        return self._run_coro(self._client.hide_message(group_name, element)) if self._client else None

    def show_loader(
        self,
        group_name: str,
        element: WindowType,
        show: bool = True,
        color: Optional[Union[str, HudColor]] = None
    ):
        """Show/hide loader. Color accepts HudColor enum or hex string."""
        return self._run_coro(self._client.show_loader(group_name, element, show, color)) if self._client else None

    def add_item(
        self,
        group_name: str,
        element: WindowType,
        title: str,
        description: str = "",
        color: Optional[Union[str, HudColor]] = None,
        duration: Optional[float] = None
    ):
        """Add persistent item. Color accepts HudColor enum or hex string."""
        return self._run_coro(self._client.add_item(
            group_name, element, title, description, color, duration
        )) if self._client else None

    def update_item(
        self,
        group_name: str,
        element: WindowType,
        title: str,
        description: Optional[str] = None,
        color: Optional[Union[str, HudColor]] = None,
        duration: Optional[float] = None
    ):
        """Update item. Color accepts HudColor enum or hex string."""
        return self._run_coro(self._client.update_item(
            group_name, element, title, description, color, duration
        )) if self._client else None

    def remove_item(self, group_name: str, element: WindowType, title: str):
        return self._run_coro(self._client.remove_item(group_name, element, title)) if self._client else None

    def clear_items(self, group_name: str, element: WindowType):
        return self._run_coro(self._client.clear_items(group_name, element)) if self._client else None

    def show_progress(
        self,
        group_name: str,
        element: WindowType,
        title: str,
        current: float,
        maximum: float = 100,
        description: str = "",
        color: Optional[Union[str, HudColor]] = None,
        auto_close: bool = False,
        props: Optional[BaseProps] = None
    ):
        """Show progress bar. Color accepts HudColor enum or hex string."""
        return self._run_coro(self._client.show_progress(
            group_name, element, title, current, maximum, description, color, auto_close, props
        )) if self._client else None

    def show_timer(
        self,
        group_name: str,
        element: WindowType,
        title: str,
        duration: float,
        description: str = "",
        color: Optional[Union[str, HudColor]] = None,
        auto_close: bool = True,
        initial_progress: float = 0,
        props: Optional[BaseProps] = None
    ):
        """Show timer. Color accepts HudColor enum or hex string."""
        return self._run_coro(self._client.show_timer(
            group_name, element, title, duration, description, color, auto_close, initial_progress, props
        )) if self._client else None

    def create_chat_window(
        self,
        group_name: str,
        element: WindowType,
        # Layout (anchor-based) - preferred
        anchor: Union[str, Anchor] = Anchor.TOP_LEFT,
        priority: int = 5,
        layout_mode: Union[str, LayoutMode] = LayoutMode.AUTO,
        # Legacy position - only used if layout_mode='manual'
        x: int = 20,
        y: int = 20,
        # Size
        width: int = 400,
        max_height: int = 400,
        # Colors
        bg_color: Optional[Union[str, HudColor]] = None,
        text_color: Optional[Union[str, HudColor]] = None,
        accent_color: Optional[Union[str, HudColor]] = None,
        # Behavior
        auto_hide: bool = False,
        auto_hide_delay: float = 10.0,
        max_messages: int = 50,
        sender_colors: Optional[dict[str, str]] = None,
        fade_old_messages: bool = True,
        # Additional props
        opacity: Optional[float] = None,
        font_size: Optional[int] = None,
        font_family: Optional[Union[str, FontFamily]] = None,
        border_radius: Optional[int] = None,
        **extra_props
    ):
        """Create chat window. Accepts Anchor, LayoutMode, HudColor, FontFamily enums."""
        return self._run_coro(self._client.create_chat_window(
            group_name=group_name,
            element=element,
            anchor=anchor,
            priority=priority,
            layout_mode=layout_mode,
            x=x, y=y,
            width=width, max_height=max_height,
            bg_color=bg_color,
            text_color=text_color,
            accent_color=accent_color,
            auto_hide=auto_hide, auto_hide_delay=auto_hide_delay,
            max_messages=max_messages,
            sender_colors=sender_colors,
            fade_old_messages=fade_old_messages,
            opacity=opacity,
            font_size=font_size,
            font_family=font_family,
            border_radius=border_radius,
            **extra_props
        )) if self._client else None

    def delete_chat_window(self, group_name: str, element: WindowType):
        return self._run_coro(self._client.delete_chat_window(group_name, element)) if self._client else None

    def send_chat_message(
        self,
        group_name: str,
        element: WindowType,
        sender: str,
        text: str,
        color: Optional[Union[str, HudColor]] = None
    ):
        """Send chat message. Color accepts HudColor enum or hex string."""
        return self._run_coro(self._client.send_chat_message(
            group_name, element, sender, text, color
        )) if self._client else None

    def update_chat_message(self, group_name: str, element: WindowType, message_id: str, text: str):
        return self._run_coro(self._client.update_chat_message(
            group_name, element, message_id, text
        )) if self._client else None

    def clear_chat_window(self, group_name: str, element: WindowType):
        return self._run_coro(self._client.clear_chat_window(group_name, element)) if self._client else None

    def show_chat_window(self, group_name: str, element: WindowType):
        return self._run_coro(self._client.show_chat_window(group_name, element)) if self._client else None

    def hide_chat_window(self, group_name: str, element: WindowType):
        return self._run_coro(self._client.hide_chat_window(group_name, element)) if self._client else None

    def show_element(self, group_name: str, element: WindowType):
        """Show a hidden HUD element (message, persistent, or chat)."""
        return self._run_coro(self._client.show_element(group_name, element)) if self._client else None

    def hide_element(self, group_name: str, element: WindowType):
        """Hide a HUD element (message, persistent, or chat)."""
        return self._run_coro(self._client.hide_element(group_name, element)) if self._client else None
