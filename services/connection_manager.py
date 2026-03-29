from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from api.commands import WebSocketCommandModel


class ConnectionManager:
    """Singleton"""

    _instance = None

    def __new__(cls) -> "ConnectionManager":
        if cls._instance is None:
            cls._instance = super(ConnectionManager, cls).__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not hasattr(self, "active_connections"):
            self.active_connections: list[WebSocket] = []
            self.message_queue: list[WebSocketCommandModel] = []
            self._lock: asyncio.Lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)

    async def client_ready(self, websocket: WebSocket) -> None:
        await self._broadcast_queued_messages(websocket)

    def _enum_encoder(self, obj: Any) -> Any:
        if isinstance(obj, Enum):
            return obj.value
        raise TypeError(
            f"Object of type {obj.__class__.__name__} is not JSON serializable"
        )

    async def _broadcast_queued_messages(self, websocket: WebSocket) -> None:
        while True:
            async with self._lock:
                if not self.message_queue:
                    return
                payload = self.message_queue.pop(0)

            try:
                await websocket.send_text(payload.model_dump_json())
            except (RuntimeError, WebSocketDisconnect, OSError):
                # Client is gone (sleep/tab discard/server restart). Stop flushing.
                await self.disconnect(websocket)
                return

    async def broadcast(self, command: WebSocketCommandModel) -> None:
        json_str = command.model_dump_json()

        async with self._lock:
            connections_snapshot = list(self.active_connections)

        if not connections_snapshot:
            # Don't queue ephemeral state updates - client can poll /ping for current state
            if command.command != "core_state_changed":
                async with self._lock:
                    self.message_queue.append(command)
            return

        stale_connections: list[WebSocket] = []
        for connection in connections_snapshot:
            try:
                await connection.send_text(json_str)
            except (RuntimeError, WebSocketDisconnect, OSError):
                stale_connections.append(connection)

        if stale_connections:
            async with self._lock:
                for ws in stale_connections:
                    if ws in self.active_connections:
                        self.active_connections.remove(ws)

            for ws in stale_connections:
                try:
                    await ws.close()
                except (RuntimeError, WebSocketDisconnect, OSError):
                    pass

            async with self._lock:
                has_live_connections = bool(self.active_connections)

            if not has_live_connections and command.command != "core_state_changed":
                async with self._lock:
                    self.message_queue.append(command)

    async def send_to(self, command: WebSocketCommandModel, websocket: WebSocket) -> None:
        """Send a command to a specific client."""
        try:
            await websocket.send_text(command.model_dump_json())
        except (RuntimeError, WebSocketDisconnect, OSError):
            await self.disconnect(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

        try:
            await websocket.close()
        except RuntimeError:
            pass  # already closed, e.g. if the client closed the browser tab
        except (WebSocketDisconnect, OSError):
            pass

    async def shutdown(self) -> None:
        async with self._lock:
            websockets = list(self.active_connections)
            self.active_connections.clear()

        for websocket in websockets:
            await self.disconnect(websocket)
