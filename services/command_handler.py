import json
import asyncio
import threading
from fastapi import WebSocket
import pygame
import keyboard.keyboard as keyboard
from api.commands import (
    ActionsRecordedCommand,
    RecordJoystickActionsCommand,
    RecordKeyboardActionsCommand,
    RecordMouseActionsCommand,
    SaveSecretCommand,
    StopRecordingCommand,
    WebSocketCommandModel,
)
from api.enums import KeyboardRecordingType, LogSource, RecordingDevice, ToastType
from api.interface import CommandActionConfig, CommandJoystickConfig, CommandKeyboardConfig, CommandMouseConfig
from mouse import mouse
from services.connection_manager import ConnectionManager
from services.printr import Printr
from services.secret_keeper import SecretKeeper
from services.websocket_user import WebSocketUser
from wingman_core import WingmanCore


class CommandHandler:
    def __init__(self, connection_manager: ConnectionManager, core: WingmanCore):
        self.source_name = "WebSocket Command Handler"
        self.connection_manager = connection_manager
        self.core = core
        self.secret_keeper: SecretKeeper = SecretKeeper()
        self.printr: Printr = Printr()
        self.timeout_task = None
        self.recorded_keys = []
        self.keyboard_hook_callback = None
        self.is_joystick_recording = False

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
            elif command_name == "record_joystick_actions":
                def run_async_joystick_recording():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(self.handle_record_joystick_actions(
                            RecordJoystickActionsCommand(**command), websocket
                        ))
                    finally:
                        loop.close()
                
                play_thread = threading.Thread(target=run_async_joystick_recording)
                play_thread.start()
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
        await self.secret_keeper.save()

        if command.show_message:
            await self.printr.print_async(
                f"Secret '{secret_name}' saved",
                toast=ToastType.NORMAL,
                source=LogSource.SYSTEM,
                source_name=self.source_name,
            )

    def _is_hotkey_recording_finished(self, recorded_keys):
        # Check if for all down events there is a corresponding up event
        for key in recorded_keys:
            if key.event_type == "down":
                key_up_event = next(
                    (
                        k
                        for k in recorded_keys
                        if k.event_type == "up" and k.scan_code == key.scan_code
                    ),
                    None,
                )
                if not key_up_event:
                    return False
        return True
    
    def on_mouse(self, event):
        # Check if event is of type ButtonEvent
        if not isinstance(event, mouse.ButtonEvent):
            return
        
        if event.event_type == "up":
            self.recorded_keys.append(event)

            stop_command = StopRecordingCommand(
                command="stop_recording",
                recording_device=RecordingDevice.MOUSE
            )
            
            WebSocketUser.ensure_async(
                self.handle_stop_recording(stop_command, None)
            )
    
    async def handle_record_mouse_actions(
        self, command: RecordMouseActionsCommand, websocket: WebSocket
    ):
        await self.printr.print_async(
            "Recording mouse actions...",
            toast=ToastType.NORMAL,
            source=LogSource.SYSTEM,
            source_name=self.source_name,
            server_only=True,
        )

        mouse.hook(self.on_mouse)

    async def handle_record_joystick_actions(
        self, command: RecordJoystickActionsCommand, websocket: WebSocket
    ):
        await self.printr.print_async(
            "Recording joystick actions...",
            toast=ToastType.NORMAL,
            source=LogSource.SYSTEM,
            source_name=self.source_name,
            server_only=True,
        )

        was_init = pygame.get_init()
        pygame.init()
        joysticks = [pygame.joystick.Joystick(x) for x in range(pygame.joystick.get_count())]

        for joystick in joysticks:
            joystick.init()

        self.is_joystick_recording = True
        while self.is_joystick_recording and pygame.get_init():
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.is_joystick_recording = False
                elif event.type == pygame.JOYBUTTONUP:
                    # Get guid of joystick with instance id
                    joystick_origin = pygame.joystick.Joystick(event.joy)
                    self.recorded_keys.append({
                        "button": event.button,
                        "guid": joystick_origin.get_guid(),
                        "name": joystick_origin.get_name()
                        })
                    self.is_joystick_recording = False

        stop_command = StopRecordingCommand(
            command="stop_recording",
            recording_device=RecordingDevice.JOYSTICK
        )
        
        await self.handle_stop_recording(stop_command, None)

        if not was_init:
            pygame.quit()

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
        self.recorded_keys = []

        stop_command = StopRecordingCommand(
            command="stop_recording",
            recording_device=RecordingDevice.KEYBOARD,
            recording_type=command.recording_type
        )

        def _on_key_event(event):
            if event.event_type == "down" and event.name == "esc":
                WebSocketUser.ensure_async(
                    self.handle_stop_recording(stop_command, websocket)
                )
            if (
                event.scan_code == 58
                or event.scan_code == 70
                or (event.scan_code == 69 and event.is_extended)
            ):
                # let capslock, numlock or scrolllock through, as it changes following keypresses
                keyboard.direct_event(
                    event.scan_code,
                    (0 if event.event_type == "down" else 2) + int(event.is_extended),
                )

            self.recorded_keys.append(event)
            if (
                command.recording_type == KeyboardRecordingType.SINGLE
                and self._is_hotkey_recording_finished(self.recorded_keys)
            ):
                WebSocketUser.ensure_async(
                    self.handle_stop_recording(stop_command, websocket)
                )

        self.keyboard_hook_callback = keyboard.hook(_on_key_event, suppress=True)

    async def handle_stop_recording(
        self,
        command: StopRecordingCommand,
        websocket: WebSocket,
    ):
        if self.keyboard_hook_callback:
            keyboard.unhook(self.keyboard_hook_callback)
            self.keyboard_hook_callback = None
        if command.recording_device == RecordingDevice.JOYSTICK:
            self.is_joystick_recording = False
        if command.recording_device == RecordingDevice.MOUSE:
            mouse.unhook(self.on_mouse)

        recorded_keys = self.recorded_keys
        if self.timeout_task:
            self.timeout_task.cancel()

        actions: list[CommandActionConfig] = []

        if command.recording_device == RecordingDevice.KEYBOARD:
            actions = (
                self._get_actions_from_recorded_keys(recorded_keys)
                if command.recording_type == KeyboardRecordingType.MACRO_ADVANCED
                else self._get_actions_from_recorded_hotkey(recorded_keys)
            )
        elif command.recording_device == RecordingDevice.JOYSTICK:
            if len(recorded_keys) > 0:
                joystick_config = CommandActionConfig()
                joystick_config.joystick = CommandJoystickConfig()
                joystick_config.joystick.button = recorded_keys[0]["button"]
                joystick_config.joystick.name = recorded_keys[0]["name"]
                joystick_config.joystick.guid = recorded_keys[0]["guid"]
                actions.append(joystick_config)
        elif command.recording_device == RecordingDevice.MOUSE:
            if len(recorded_keys) > 0:
                mouse_config = CommandActionConfig()
                mouse_config.mouse = CommandMouseConfig()
                mouse_config.mouse.button = recorded_keys[0].button
                actions.append(mouse_config)

        command = ActionsRecordedCommand(command="actions_recorded", actions=actions)
        await self.connection_manager.broadcast(command)

        self.recorded_keys = []

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

        def add_action(name, code, extended, press, release, hold):
            if press or release:
                hold = None  # reduces yaml size
            else:
                hold = round(hold, 2)
                if hold < 0.1:
                    hold = 0.1  # 100ms min hold time
                else:
                    hold = round(round(hold / 0.05) * 0.05, 3)

            if not extended:
                extended = None  # reduces yaml size

            # add keyboard action
            actions.append(
                CommandActionConfig(
                    keyboard=CommandKeyboardConfig(
                        hotkey=name,
                        hotkey_codes=[code],
                        hotkey_extended=extended,
                        press=press,
                        release=release,
                        hold=hold,
                    )
                )
            )

        def add_wait(duration):
            if not duration:
                return
            duration = round(duration, 2)
            if duration < 0.05:
                duration = 0.05  # 50ms min wait time
            else:
                duration = round(round(duration / 0.05) * 0.05, 3)
            actions.append(CommandActionConfig(wait=duration))

        last_last_key_data = []
        last_key_data = []
        key_data = []

        # Process recorded key events to calculate press durations and wait times
        # We are trying to compress press and release events into one action.
        # This reduces the amount of actions and increases readability of yaml files.
        # Tradeoff is a bit confusing logic below.
        for key in recorded:
            key_data = [
                key.name.lower(),
                key.scan_code,
                bool(key.is_extended),
                key.event_type,
                key.time,
                0,
            ]

            if last_key_data:
                if (
                    key_data[1] == last_key_data[1]
                    and key_data[2] == last_key_data[2]
                    and key_data[3] == last_key_data[3]
                ):
                    # skip double actions
                    continue
                key_data[5] = key_data[4] - last_key_data[4]  # set time diff

            # check if last key was down event
            if last_key_data and last_key_data[3] == "down":
                # same key?
                if key_data[1] == last_key_data[1] and key_data[2] == last_key_data[2]:
                    # write as compressed action
                    add_wait(last_key_data[5])
                    add_action(
                        key_data[0], key_data[1], key_data[2], None, None, key_data[5]
                    )
                else:
                    # write as separate action
                    add_wait(last_key_data[5])
                    add_action(
                        last_key_data[0],
                        last_key_data[1],
                        last_key_data[2],
                        True,
                        None,
                        0,
                    )

            if last_key_data and last_key_data[3] == "up":
                if (
                    last_last_key_data
                    and last_last_key_data[1] != last_key_data[1]
                    or last_last_key_data[2] != last_key_data[2]
                ):
                    add_wait(last_key_data[5])
                    add_action(
                        last_key_data[0],
                        last_key_data[1],
                        last_key_data[2],
                        None,
                        True,
                        0,
                    )

            last_last_key_data = last_key_data
            last_key_data = key_data

        # add last action
        if key_data and key_data[3] == "down":
            add_wait(key_data[5])
            add_action(key_data[0], key_data[1], key_data[2], True, None, 0)
        elif (
            key_data
            and last_key_data
            and last_last_key_data
            and key_data[3] == "up"
            and (
                last_last_key_data[1] != last_key_data[1]
                or last_last_key_data[2] != last_key_data[2]
            )
        ):
            add_wait(key_data[5])
            add_action(key_data[0], key_data[1], key_data[2], None, True, 0)

        return actions

    def _get_actions_from_recorded_hotkey(self, recorded):
        # legacy function used for single key recording
        actions: list[CommandActionConfig] = []
        extended: None|bool = None

        key_down_time = {}  # Track initial down times for keys
        last_up_time = None  # Track the last up time to measure durations of inactivity

        # Track the keys currently pressed in the order they were pressed
        keys_pressed = []
        # Initialize such that we consider the keyboard initially inactive
        all_keys_released = True

        # Process recorded key events to calculate press durations and inactivity
        for key in recorded:
            key_name = key.name.lower()
            key_code = key.scan_code
            key_extended = key.is_extended
            if extended is None:
                extended = key_extended
            elif extended != key_extended:
                # fallback to advanced mode, if mixed extended flags are detected
                return self._get_actions_from_recorded_keys(recorded)
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
                if key_code not in key_down_time:
                    key_down_time[key_code] = key.time
                    # Add key to keys_pressed when pressed down
                    keys_pressed.append(key)

            elif key.event_type == "up":
                if key_name == "esc":
                    break  # Stop processing if 'esc' was released as we don't need the last inactivity period

                if key_code in key_down_time:
                    # Calculate the press duration for the current key
                    press_duration = key.time - key_down_time[key_code]

                    # Remove the key from the dictionary after calculating press duration
                    del key_down_time[key_code]

                    # If no more keys are pressed, update last_up_time and set the keyboard to inactive
                    if not key_down_time:
                        last_up_time = key.time
                        all_keys_released = True

                        hotkey_name = "+".join(key.name.lower() for key in keys_pressed)

                        key_config = CommandActionConfig()
                        key_config.keyboard = CommandKeyboardConfig(hotkey=hotkey_name)
                        key_config.keyboard.hotkey_codes = [
                            key.scan_code for key in keys_pressed
                        ]
                        key_config.keyboard.hotkey_extended = bool(key_extended)

                        if press_duration > 0.2 and len(keys_pressed) == 1:
                            key_config.keyboard.hold = round(press_duration, 2)

                        keys_pressed = (
                            []
                        )  # Clear keys_pressed after getting the hotkey_name
                        actions.append(key_config)

        return actions
