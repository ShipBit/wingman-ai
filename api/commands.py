from typing import Literal, Optional
from pydantic import BaseModel
from api.enums import CommandTag, LogSource, LogType, ToastType


# We use this Marker base class for reflection to "iterate all commands"
class WebSocketCommandModel(BaseModel):
    command: str


# RECEIVED FROM CLIENT


class ClientReadyCommand(WebSocketCommandModel):
    command: Literal["client_ready"] = "client_ready"


# TODO: make this a regular POST request
class SaveSecretCommand(WebSocketCommandModel):
    command: Literal["save_secret"] = "save_secret"
    secret_name: str
    secret_value: str


# SENT TO CLIENT


class LogCommand(WebSocketCommandModel):
    command: Literal["log"] = "log"
    text: str
    log_type: LogType
    source_name: str = None
    source: LogSource = "system"
    tag: Optional[CommandTag] = None


class PromptSecretCommand(WebSocketCommandModel):
    command: Literal["prompt_secret"] = "prompt_secret"
    requester: str
    secret_name: str


class ToastCommand(WebSocketCommandModel):
    command: Literal["toast"] = "toast"
    text: str
    toast_type: ToastType
