import json
import asyncio
from fastapi import WebSocket
import keyboard.keyboard as keyboard
from api.commands import (
    ActionsRecordedCommand,
    RecordKeyboardActionsCommand,
    RecordMouseActionsCommand,
    SaveSecretCommand,
    StopRecordingCommand,
    WebSocketCommandModel,
)
from api.enums import LogSource, ToastType
from api.interface import CommandActionConfig, CommandKeyboardConfig
from services.connection_manager import ConnectionManager
from services.printr import Printr
from services.secret_keeper import SecretKeeper
from wingman_core import WingmanCore


class CommandHandler:
    def __init__(self, connection_manager: ConnectionManager, core: WingmanCore):
        self.source_name = "WebSocket Command Handler"
        self.connection_manager = connection_manager
        self.core = core
        self.secret_keeper: SecretKeeper = SecretKeeper()
        self.printr: Printr = Printr()
        self.timeout_task = None

    async def dispatch(self, message, websocket: WebSocket):
        try:
            command: WebSocketCommandModel = json.loads(message)
            command_name = command["command"]

            if command_name == "client_ready":
                await self.handle_client_ready(websocket)
            elif command_name == "save_secret":
                await self.handle_secret(SaveSecretCommand(**command), websocket)
            elif command_name == "record_keyboard_actions":
                await self.handle_record_keyboard_actions(
                    RecordKeyboardActionsCommand(**command), websocket
                )
            elif command_name == "record_mouse_actions":
                await self.handle_record_mouse_actions(
                    RecordMouseActionsCommand(**command), websocket
                )
            elif command_name == "stop_recording":
                await self.handle_stop_recording(
                    StopRecordingCommand(**command), websocket
                )
            else:
                raise ValueError("Unknown command")
        except Exception as e:
            await self.printr.print_async(
                f"Error executing command {command_name}: {str(e)}",
                toast=ToastType.ERROR,
                source=LogSource.SYSTEM,
                source_name=self.source_name,
            )

    async def handle_client_ready(self, websocket: WebSocket):
        await self.connection_manager.client_ready(websocket)

    # todo: make this a POST request - was just a demo for commands with params
    async def handle_secret(self, command: SaveSecretCommand, websocket: WebSocket):
        secret_name = command.secret_name
        secret_value = command.secret_value
        self.secret_keeper.secrets[secret_name] = secret_value
        self.secret_keeper.save()

        await self.printr.print_async(
            f"Secret '{secret_name}' saved",
            toast=ToastType.NORMAL,
            source=LogSource.SYSTEM,
            source_name=self.source_name,
        )

    async def handle_record_keyboard_actions(
        self, command: RecordKeyboardActionsCommand, websocket: WebSocket
    ):
        await self.printr.print_async(
            "Recording keyboard actions...",
            toast=ToastType.NORMAL,
            source=LogSource.SYSTEM,
            source_name=self.source_name,
            server_only=True,
        )

        # Start timeout
        # self.timeout_task = WebSocketUser.ensure_async(self._start_timeout(10))

        keyboard.start_recording()

    async def handle_record_mouse_actions(
        self, command: RecordMouseActionsCommand, websocket: WebSocket
    ):
        # TODO: Start recording mouse actions and build a list of CommandActionConfig
        await self.printr.print_async(
            "Recording mouse actions...",
            toast=ToastType.NORMAL,
            source=LogSource.SYSTEM,
            source_name=self.source_name,
            server_only=True,
        )

    async def handle_stop_recording(
        self, command: StopRecordingCommand, websocket: WebSocket
    ):
        recorded_keys = keyboard.stop_recording()
        if self.timeout_task:
            self.timeout_task.cancel()

        actions = self._get_actions_from_recorded_keys(recorded_keys)
        command = ActionsRecordedCommand(command="actions_recorded", actions=actions)
        await self.connection_manager.broadcast(command)

        await self.printr.print_async(
            "Stopped recording actions.",
            toast=ToastType.NORMAL,
            source=LogSource.SYSTEM,
            source_name=self.source_name,
            server_only=True,
        )

    async def _start_timeout(self, timeout):
        await asyncio.sleep(timeout)
        await self.handle_stop_recording(None, None)

    def _get_actions_from_recorded_keys(self, recorded):
        actions: list[CommandActionConfig] = []

        key_down_time = {}  # Track initial down times for keys
        last_up_time = None  # Track the last up time to measure durations of inactivity
        keys_pressed = []  # Track the keys currently pressed in the order they were pressed

        # Initialize such that we consider the keyboard initially inactive
        all_keys_released = True

        # Process recorded key events to calculate press durations and inactivity
        for key in recorded:
            key_name = key.name.lower()
            if key.event_type == "down":
                # Ignore further processing if 'esc' was pressed
                if key_name == "esc":
                    break

                if all_keys_released:
                    # There was a period of inactivity, calculate its duration
                    if last_up_time is not None:
                        inactivity_duration = key.time - last_up_time
                        if inactivity_duration > 1.0:
                            wait_config = CommandActionConfig()
                            wait_config.wait = round(inactivity_duration, 2)
                            actions.append(wait_config)

                    all_keys_released = False

                # Record only the first down event time for each key and add to keys_pressed
                if key_name not in key_down_time:
                    key_down_time[key_name] = key.time
                    keys_pressed.append(key_name)  # Add key to keys_pressed when pressed down

            elif key.event_type == "up":
                if key_name == "esc":
                    break  # Stop processing if 'esc' was released as we don't need the last inactivity period

                if key_name in key_down_time:
                    # Calculate the press duration for the current key
                    press_duration = key.time - key_down_time[key_name]

                    # Remove the key from the dictionary after calculating press duration
                    del key_down_time[key_name]

                    # If no more keys are pressed, update last_up_time and set the keyboard to inactive
                    if not key_down_time:
                        last_up_time = key.time
                        all_keys_released = True

                        hotkey_name = keyboard.get_hotkey_name(keys_pressed)
                        keys_pressed = []  # Clear keys_pressed after getting the hotkey_name

                        key_config = CommandActionConfig()
                        key_config.keyboard = CommandKeyboardConfig(hotkey=hotkey_name)

                        if press_duration > 0.2 and not keyboard.is_modifier(key_name):
                            key_config.keyboard.hold = round(press_duration, 2)

                        actions.append(key_config)

        return actions
