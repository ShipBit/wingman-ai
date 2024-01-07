from enum import Enum
from fastapi import WebSocket
from api.commands import WebSocketCommandModel


class ConnectionManager:
    """Singleton"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConnectionManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "active_connections"):
            self.active_connections = []
            self.message_queue = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    async def client_ready(self, websocket: WebSocket):
        await self._broadcast_queued_messages(websocket)

    def _enum_encoder(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        raise TypeError(
            f"Object of type {obj.__class__.__name__} is not JSON serializable"
        )

    async def _broadcast_queued_messages(self, websocket: WebSocket):
        while self.message_queue:
            payload = self.message_queue.pop(0)
            await websocket.send_text(payload.model_dump_json())

    async def broadcast(self, command: WebSocketCommandModel):
        json_str = command.model_dump_json()
        if self.active_connections:
            for connection in self.active_connections:
                await connection.send_text(json_str)
        else:
            self.message_queue.append(command)

    async def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            try:
                await websocket.close()
            except RuntimeError:
                pass  # already closed, e.g. if the client closed the browser tab

    async def shutdown(self):
        for websocket in self.active_connections[:]:
            await self.disconnect(websocket)
