from typing import Literal
from pydantic import BaseModel


# Marker base class for WebSocket command models
# We use this for reflection to "iterate all commands"
class WebSocketCommandModel(BaseModel):
    command: str


class ClientReadyCommand(WebSocketCommandModel):
    command: Literal["client_ready"] = "client_ready"


class ChangeContextCommand(WebSocketCommandModel):
    command: Literal["change_context"] = "change_context"
    context: str


class SaveSecretCommand(WebSocketCommandModel):
    command: Literal["save_secret"] = "save_secret"
    secret_name: str
    secret_value: str
