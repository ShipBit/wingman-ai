import json
from fastapi import WebSocket
from pydantic import ValidationError
from api.commands import (
    ChangeConfigCommand,
    ClientReadyCommand,
    SaveSecretCommand,
    WebSocketCommandModel,
)
from api.enums import ToastType
from services.printr import Printr
from services.secret_keeper import SecretKeeper
from wingman_core import WingmanCore


class CommandHandler:
    def __init__(self, connection_manager, core, secret_keeper, printr):
        self.connection_manager = connection_manager
        self.core: WingmanCore = core
        self.secret_keeper: SecretKeeper = secret_keeper
        self.printr: Printr = printr

    async def dispatch(self, message, websocket: WebSocket):
        try:
            command: WebSocketCommandModel = json.loads(message)

            if command["command"] == "client_ready":
                await self.handle_client_ready(ClientReadyCommand(**command), websocket)
            elif command["command"] == "change_config":
                await self.handle_change_config(
                    ChangeConfigCommand(**command), websocket
                )
            elif command["command"] == "save_secret":
                await self.handle_secret(SaveSecretCommand(**command), websocket)
            else:
                raise ValueError("Unknown command")
        except (ValidationError, KeyError, ValueError) as e:
            # Handle invalid commands or parsing errors
            self.printr.print(str(e), toast=ToastType.ERROR)

    async def handle_client_ready(
        self, command: ClientReadyCommand, websocket: WebSocket
    ):
        await self.connection_manager.client_ready(websocket)

    async def handle_change_config(
        self, command: ChangeConfigCommand, websocket: WebSocket
    ):
        config = command.config
        errors = await self.core.load_config(config)
        self.printr.print(
            f"Loaded config: {config or 'default'}",
            toast=ToastType.NORMAL,
            server_only=True,
        )

    async def handle_secret(self, command: SaveSecretCommand, websocket: WebSocket):
        secret_name = command.secret_name
        secret_value = command.secret_value
        self.secret_keeper.secrets[secret_name] = secret_value
        self.secret_keeper.save()
        self.printr.print(f"Secret '{secret_name}' saved", toast=ToastType.NORMAL)
