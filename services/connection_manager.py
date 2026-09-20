from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any

from fastapi import WebSocket

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
            self._send_locks: dict[int, asyncio.Lock] = {}

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
            self._send_locks[id(websocket)] = asyncio.Lock()

    async def client_ready(self, websocket: WebSocket) -> None:
        await self._broadcast_queued_messages(websocket)

    def _enum_encoder(self, obj: Any) -> Any:
        if isinstance(obj, Enum):
            return obj.value
        raise TypeError(
            f"Object of type {obj.__class__.__name__} is not JSON serializable"
        )

    async def _send_text(self, websocket: WebSocket, json_str: str) -> bool:
        """Send one message to one client. Returns False if the client is gone.

        Sends to the same socket are serialized: large payloads (e.g. a generated
        image as a data URL) fill the transport buffer, and a second send landing
        in the middle of that raises BufferError deep inside asyncio. Every
        failure is swallowed here - a broken WebSocket must never abort the caller,
        which used to kill the running tool call and swallow the Wingman's answer."""
        lock = self._send_locks.get(id(websocket))
        try:
            if lock is None:
                await websocket.send_text(json_str)
            else:
                async with lock:
                    await websocket.send_text(json_str)
            return True
        except Exception:
            return False

    async def _close(self, websocket: WebSocket) -> None:
        """Close a socket, ignoring anything it throws on the way out."""
        try:
            await websocket.close()
        except Exception:
            pass

    async def _broadcast_queued_messages(self, websocket: WebSocket) -> None:
        while True:
            async with self._lock:
                if not self.message_queue:
                    return
                payload = self.message_queue.pop(0)

            if not await self._send_text(websocket, payload.model_dump_json()):
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
            if not await self._send_text(connection, json_str):
                stale_connections.append(connection)

        if stale_connections:
            async with self._lock:
                for ws in stale_connections:
                    if ws in self.active_connections:
                        self.active_connections.remove(ws)
                    self._send_locks.pop(id(ws), None)

            for ws in stale_connections:
                await self._close(ws)

            async with self._lock:
                has_live_connections = bool(self.active_connections)

            if not has_live_connections and command.command != "core_state_changed":
                async with self._lock:
                    self.message_queue.append(command)

    async def send_to(
        self, command: WebSocketCommandModel, websocket: WebSocket
    ) -> None:
        """Send a command to a specific client."""
        if not await self._send_text(websocket, command.model_dump_json()):
            await self.disconnect(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
            self._send_locks.pop(id(websocket), None)

        await self._close(websocket)

    async def shutdown(self) -> None:
        async with self._lock:
            websockets = list(self.active_connections)
            self.active_connections.clear()
            self._send_locks.clear()

        for websocket in websockets:
            await self._close(websocket)
