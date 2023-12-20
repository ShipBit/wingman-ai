import json
from fastapi import WebSocket
from pydantic import ValidationError
from api.commands import ChangeContextCommand, ClientReadyCommand, SaveSecretCommand
from api.enums import ToastType


class CommandHandler:
    def __init__(self, connection_manager, core, secret_keeper, printr):
        self.connection_manager = connection_manager
        self.core = core
        self.secret_keeper = secret_keeper
        self.printr = printr

    async def dispatch(self, message, websocket: WebSocket):
        try:
            command = json.loads(message)

            if command["command"] == "client_ready":
                await self.handle_client_ready(ClientReadyCommand(**command), websocket)
            elif command["command"] == "change_context":
                await self.handle_change_context(
                    ChangeContextCommand(**command), websocket
                )
            elif command["command"] == "secret":
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

    async def handle_change_context(
        self, command: ChangeContextCommand, websocket: WebSocket
    ):
        context = command.context
        await self.core.load_context(context)
        self.core.activate()
        self.printr.print(
            f"Loaded context: {context or 'default'}", toast=ToastType.NORMAL
        )

    async def handle_secret(self, command: SaveSecretCommand, websocket: WebSocket):
        secret_name = command.secret_name
        secret_value = command.secret_value
        self.secret_keeper.secrets[secret_name] = secret_value
        self.secret_keeper.save()
        self.printr.print(f"Secret '{secret_name}' saved", toast=ToastType.NORMAL)
