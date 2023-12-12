import json
from fastapi import WebSocket
from api.enums import LogType, ToastType, LogSource


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

    async def _broadcast_queued_messages(self, websocket: WebSocket):
        while self.message_queue:
            payload = self.message_queue.pop(0)
            await websocket.send_text(json.dumps(payload))

    async def _broadcast(self, command: str, data: dict):
        payload = {"command": command, "data": data}
        if self.active_connections:
            for connection in self.active_connections:
                # Use manual serialization for the Enum in the dict
                await connection.send_text(
                    json.dumps(payload, default=str)
                )  # provides a fallback for other non-serializable types
        else:
            self.message_queue.append(payload)

    async def toast(self, message: str, toast_type: ToastType):
        data = {
            "text": message,
            "toastType": toast_type,
        }
        await self._broadcast("toast", data)

    async def prompt_secret(self, secret_name: str, requester: str):
        data = {
            "requester": requester,
            "secret_name": secret_name,
        }
        await self._broadcast("prompt_secret", data)

    async def log(
        self,
        message: str,
        log_type: LogType,
        source: LogSource = LogSource.SYSTEM,
        source_name: str = None,
    ):
        data = {
            "text": message,
            "logType": log_type,
            "source": source,
            "sourceName": source_name,
        }
        await self._broadcast("log", data)

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
