# -*- coding: utf-8 -*-
"""
HUD HTTP Client - Client for interacting with the integrated HUD Server.

Provides both async and sync APIs for controlling HUD groups via HTTP.
This replaces the WebSocket-based client for the integrated HUD server.

Usage:
    # Async usage
    async with HudHttpClient() as client:
        await client.show_message("group1", "Title", "Content")

    # Sync usage
    client = HudHttpClientSync()
    client.show_message("group1", "Title", "Content")
"""

import asyncio
import threading
import time
import httpx
from typing import Optional, Any
from urllib.parse import quote
from api.enums import LogType
from services.printr import Printr
from hud_server import constants as hud_const

printr = Printr()


class HudHttpClient:
    """Async HTTP client for the HUD Server."""

    # Timeout constants
    DEFAULT_CONNECT_TIMEOUT = hud_const.HTTP_CONNECT_TIMEOUT
    DEFAULT_REQUEST_TIMEOUT = hud_const.HTTP_REQUEST_TIMEOUT
    RECONNECT_ATTEMPTS = 1

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
            response = await self._client.get("/health")
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
        except Exception as e:
            printr.print(
                f"[HUD HTTP Client] Request {method} {path} error: {type(e).__name__}: {e}",
                color=LogType.WARNING,
                server_only=True
            )
            self._connected = False
            return None

    # ─────────────────────────────── Health ─────────────────────────────── #

    async def health_check(self) -> bool:
        """Check if server is responsive."""
        result = await self._request("GET", "/health")
        return result is not None and result.get("status") == "healthy"

    async def get_status(self) -> Optional[dict]:
        """Get server status including all groups."""
        return await self._request("GET", "/health")

    # ─────────────────────────────── Groups ─────────────────────────────── #

    async def create_group(
        self,
        group_name: str,
        props: Optional[dict] = None
    ) -> Optional[dict]:
        """Create or update a HUD group."""
        return await self._request("POST", "/groups", {
            "group_name": group_name,
            "props": props
        })

    async def update_group(
        self,
        group_name: str,
        props: dict
    ) -> bool:
        """
        Update properties of an existing group.
        The server will broadcast the updated props to the overlay for real-time updates.
        Returns True if successful, False otherwise.
        """
        encoded_group = quote(group_name, safe='')
        result = await self._request("PATCH", f"/groups/{encoded_group}", {
            "props": props
        })
        return result is not None

    async def delete_group(self, group_name: str) -> Optional[dict]:
        """Delete a HUD group."""
        encoded_group = quote(group_name, safe='')
        return await self._request("DELETE", f"/groups/{encoded_group}")

    async def get_groups(self) -> Optional[dict]:
        """Get list of all group names."""
        return await self._request("GET", "/groups")

    # ─────────────────────────────── State ─────────────────────────────── #

    async def get_state(self, group_name: str) -> Optional[dict]:
        """Get the current state of a group for persistence."""
        encoded_group = quote(group_name, safe='')
        return await self._request("GET", f"/state/{encoded_group}")

    async def restore_state(self, group_name: str, state: dict) -> Optional[dict]:
        """Restore a group's state from a previous snapshot."""
        return await self._request("POST", "/state/restore", {
            "group_name": group_name,
            "state": state
        })

    # ─────────────────────────────── Messages ─────────────────────────────── #

    async def show_message(
        self,
        group_name: str,
        title: str,
        content: str,
        color: Optional[str] = None,
        tools: Optional[list] = None,
        props: Optional[dict] = None,
        duration: Optional[float] = None
    ) -> Optional[dict]:
        """Show a message in a HUD group."""
        data: dict[str, Any] = {
            "group_name": group_name,
            "title": title,
            "content": content
        }
        if color:
            data["color"] = color
        if tools:
            data["tools"] = tools
        if props:
            data["props"] = props
        if duration is not None:
            data["duration"] = duration

        return await self._request("POST", "/message", data)

    async def append_message(
        self,
        group_name: str,
        content: str
    ) -> Optional[dict]:
        """Append content to the current message (for streaming)."""
        return await self._request("POST", "/message/append", {
            "group_name": group_name,
            "content": content
        })

    async def hide_message(self, group_name: str) -> Optional[dict]:
        """Hide the current message in a group."""
        encoded_group = quote(group_name, safe='')
        return await self._request("POST", f"/message/hide/{encoded_group}")

    # ─────────────────────────────── Loader ─────────────────────────────── #

    async def show_loader(
        self,
        group_name: str,
        show: bool = True,
        color: Optional[str] = None
    ) -> Optional[dict]:
        """Show or hide the loader animation."""
        data = {"group_name": group_name, "show": show}
        if color:
            data["color"] = color
        return await self._request("POST", "/loader", data)

    # ─────────────────────────────── Items ─────────────────────────────── #

    async def add_item(
        self,
        group_name: str,
        title: str,
        description: str = "",
        color: Optional[str] = None,
        duration: Optional[float] = None
    ) -> Optional[dict]:
        """Add a persistent item to a group."""
        data: dict[str, Any] = {
            "group_name": group_name,
            "title": title,
            "description": description
        }
        if color:
            data["color"] = color
        if duration is not None:
            data["duration"] = duration

        return await self._request("POST", "/items", data)

    async def update_item(
        self,
        group_name: str,
        title: str,
        description: Optional[str] = None,
        color: Optional[str] = None,
        duration: Optional[float] = None
    ) -> Optional[dict]:
        """Update an existing item."""
        data: dict[str, Any] = {"group_name": group_name, "title": title}
        if description is not None:
            data["description"] = description
        if color is not None:
            data["color"] = color
        if duration is not None:
            data["duration"] = duration

        return await self._request("PUT", "/items", data)

    async def remove_item(self, group_name: str, title: str) -> Optional[dict]:
        """Remove an item from a group."""
        encoded_title = quote(title, safe='')
        return await self._request("DELETE", f"/items/{group_name}/{encoded_title}")

    async def clear_items(self, group_name: str) -> Optional[dict]:
        """Clear all items from a group."""
        encoded_group = quote(group_name, safe='')
        return await self._request("DELETE", f"/items/{encoded_group}")

    # ─────────────────────────────── Progress ─────────────────────────────── #

    async def show_progress(
        self,
        group_name: str,
        title: str,
        current: float,
        maximum: float = 100,
        description: str = "",
        color: Optional[str] = None,
        auto_close: bool = False,
        props: Optional[dict] = None
    ) -> Optional[dict]:
        """Show or update a progress bar."""
        data: dict[str, Any] = {
            "group_name": group_name,
            "title": title,
            "current": current,
            "maximum": maximum,
            "description": description,
            "auto_close": auto_close
        }
        if color:
            data["color"] = color
        if props:
            data["props"] = props

        return await self._request("POST", "/progress", data)

    async def show_timer(
        self,
        group_name: str,
        title: str,
        duration: float,
        description: str = "",
        color: Optional[str] = None,
        auto_close: bool = True,
        initial_progress: float = 0,
        props: Optional[dict] = None
    ) -> Optional[dict]:
        """Show a timer-based progress bar."""
        data: dict[str, Any] = {
            "group_name": group_name,
            "title": title,
            "duration": duration,
            "description": description,
            "auto_close": auto_close,
            "initial_progress": initial_progress
        }
        if color:
            data["color"] = color
        if props:
            data["props"] = props

        return await self._request("POST", "/timer", data)

    # ─────────────────────────────── Chat Window ─────────────────────────────── #

    async def create_chat_window(
        self,
        name: str,
        # Layout (anchor-based) - preferred
        anchor: str = "top_left",
        priority: int = 5,
        layout_mode: str = "auto",
        # Legacy position - only used if layout_mode='manual'
        x: int = 20,
        y: int = 20,
        # Size
        width: int = 400,
        max_height: int = 400,
        # Behavior
        auto_hide: bool = False,
        auto_hide_delay: float = 10.0,
        max_messages: int = 50,
        sender_colors: Optional[dict[str, str]] = None,
        fade_old_messages: bool = True,
        **props
    ) -> Optional[dict]:
        """Create a new chat window."""
        data = {
            "name": name,
            # Layout
            "anchor": anchor,
            "priority": priority,
            "layout_mode": layout_mode,
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
        return await self._request("POST", "/chat/window", data)

    async def delete_chat_window(self, name: str) -> Optional[dict]:
        """Delete a chat window."""
        encoded_name = quote(name, safe='')
        return await self._request("DELETE", f"/chat/window/{encoded_name}")

    async def send_chat_message(
        self,
        window_name: str,
        sender: str,
        text: str,
        color: Optional[str] = None
    ) -> Optional[dict]:
        """Send a message to a chat window."""
        data = {
            "window_name": window_name,
            "sender": sender,
            "text": text
        }
        if color:
            data["color"] = color

        return await self._request("POST", "/chat/message", data)

    async def clear_chat_window(self, name: str) -> Optional[dict]:
        """Clear all messages from a chat window."""
        encoded_name = quote(name, safe='')
        return await self._request("DELETE", f"/chat/messages/{encoded_name}")

    async def show_chat_window(self, name: str) -> Optional[dict]:
        """Show a hidden chat window."""
        encoded_name = quote(name, safe='')
        return await self._request("POST", f"/chat/show/{encoded_name}")

    async def hide_chat_window(self, name: str) -> Optional[dict]:
        """Hide a chat window."""
        encoded_name = quote(name, safe='')
        return await self._request("POST", f"/chat/hide/{encoded_name}")



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

    def create_group(self, group_name: str, props: Optional[dict] = None):
        return self._run_coro(self._client.create_group(group_name, props)) if self._client else None

    def update_group(self, group_name: str, props: dict) -> bool:
        """Update properties for an existing group for real-time updates."""
        return self._run_coro(self._client.update_group(group_name, props)) if self._client else False

    def delete_group(self, group_name: str):
        return self._run_coro(self._client.delete_group(group_name)) if self._client else None

    def get_groups(self):
        return self._run_coro(self._client.get_groups()) if self._client else None

    def get_state(self, group_name: str):
        return self._run_coro(self._client.get_state(group_name)) if self._client else None

    def restore_state(self, group_name: str, state: dict):
        return self._run_coro(self._client.restore_state(group_name, state)) if self._client else None

    def show_message(
        self,
        group_name: str,
        title: str,
        content: str,
        color: Optional[str] = None,
        tools: Optional[list] = None,
        props: Optional[dict] = None,
        duration: Optional[float] = None
    ):
        return self._run_coro(self._client.show_message(
            group_name, title, content, color, tools, props, duration
        )) if self._client else None

    def append_message(self, group_name: str, content: str):
        return self._run_coro(self._client.append_message(group_name, content)) if self._client else None

    def hide_message(self, group_name: str):
        return self._run_coro(self._client.hide_message(group_name)) if self._client else None

    def show_loader(self, group_name: str, show: bool = True, color: Optional[str] = None):
        return self._run_coro(self._client.show_loader(group_name, show, color)) if self._client else None

    def add_item(
        self,
        group_name: str,
        title: str,
        description: str = "",
        color: Optional[str] = None,
        duration: Optional[float] = None
    ):
        return self._run_coro(self._client.add_item(
            group_name, title, description, color, duration
        )) if self._client else None

    def update_item(
        self,
        group_name: str,
        title: str,
        description: Optional[str] = None,
        color: Optional[str] = None,
        duration: Optional[float] = None
    ):
        return self._run_coro(self._client.update_item(
            group_name, title, description, color, duration
        )) if self._client else None

    def remove_item(self, group_name: str, title: str):
        return self._run_coro(self._client.remove_item(group_name, title)) if self._client else None

    def clear_items(self, group_name: str):
        return self._run_coro(self._client.clear_items(group_name)) if self._client else None

    def show_progress(
        self,
        group_name: str,
        title: str,
        current: float,
        maximum: float = 100,
        description: str = "",
        color: Optional[str] = None,
        auto_close: bool = False,
        props: Optional[dict] = None
    ):
        return self._run_coro(self._client.show_progress(
            group_name, title, current, maximum, description, color, auto_close, props
        )) if self._client else None

    def show_timer(
        self,
        group_name: str,
        title: str,
        duration: float,
        description: str = "",
        color: Optional[str] = None,
        auto_close: bool = True,
        initial_progress: float = 0,
        props: Optional[dict] = None
    ):
        return self._run_coro(self._client.show_timer(
            group_name, title, duration, description, color, auto_close, initial_progress, props
        )) if self._client else None

    def create_chat_window(
        self,
        name: str,
        # Layout (anchor-based) - preferred
        anchor: str = "top_left",
        priority: int = 5,
        layout_mode: str = "auto",
        # Legacy position - only used if layout_mode='manual'
        x: int = 20,
        y: int = 20,
        # Size
        width: int = 400,
        max_height: int = 400,
        # Behavior
        auto_hide: bool = False,
        auto_hide_delay: float = 10.0,
        max_messages: int = 50,
        sender_colors: Optional[dict[str, str]] = None,
        fade_old_messages: bool = True,
        **props
    ):
        return self._run_coro(self._client.create_chat_window(
            name=name,
            anchor=anchor,
            priority=priority,
            layout_mode=layout_mode,
            x=x, y=y,
            width=width, max_height=max_height,
            auto_hide=auto_hide, auto_hide_delay=auto_hide_delay,
            max_messages=max_messages,
            sender_colors=sender_colors,
            fade_old_messages=fade_old_messages,
            **props
        )) if self._client else None

    def delete_chat_window(self, name: str):
        return self._run_coro(self._client.delete_chat_window(name)) if self._client else None

    def send_chat_message(self, window_name: str, sender: str, text: str, color: Optional[str] = None):
        return self._run_coro(self._client.send_chat_message(
            window_name, sender, text, color
        )) if self._client else None

    def clear_chat_window(self, name: str):
        return self._run_coro(self._client.clear_chat_window(name)) if self._client else None

    def show_chat_window(self, name: str):
        return self._run_coro(self._client.show_chat_window(name)) if self._client else None

    def hide_chat_window(self, name: str):
        return self._run_coro(self._client.hide_chat_window(name)) if self._client else None
