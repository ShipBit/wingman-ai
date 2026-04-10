"""Command and action execution service.

Handles instant-activation matching, command dispatch, and the
keyboard/mouse/joystick/audio action dispatcher extracted from Wingman.
"""

import difflib
import random
import time
import traceback

import keyboard.keyboard as keyboard
import mouse.mouse as mouse

from api.enums import LogType
from api.interface import CommandConfig, WingmanConfig
from services.audio_library import AudioLibrary
from services.printr import Printr

printr = Printr()


def _command_has_effective_actions(command: CommandConfig) -> bool:
    """True if the command has at least one action the LLM can meaningfully trigger."""
    if command.is_system_command:
        return True
    if not command.actions:
        return False
    for action in command.actions:
        if not action:
            continue
        if (
            action.keyboard is not None
            or action.mouse is not None
            or action.joystick is not None
            or action.audio is not None
            or action.write is not None
            or action.wait is not None
        ):
            return True
    return False


class CommandExecutor:
    """Focused service for command lookup, instant activation, and action dispatch."""

    def __init__(
        self,
        config: WingmanConfig,
        audio_library: AudioLibrary,
        wingman_name: str,
        on_reset_history,  # async callable: reset_conversation_history
        on_add_forced_commands=None,  # async callable: add_forced_assistant_command_calls
    ):
        self.config = config
        self.audio_library = audio_library
        self.wingman_name = wingman_name
        self.on_reset_history = on_reset_history
        self.on_add_forced_commands = on_add_forced_commands

    # ───────────────── Command lookup ─────────────────────────── #

    def get_command(self, command_name: str) -> CommandConfig | None:
        if self.config.commands is None:
            return None
        command = next(
            (item for item in self.config.commands if item.name == command_name),
            None,
        )
        return command

    def select_instant_command_response(self, command: CommandConfig) -> str | None:
        command_responses = command.responses
        if (command_responses is None) or (len(command_responses) == 0):
            return None
        return random.choice(command_responses)

    # ───────────────── Instant activation ─────────────────────── #

    async def try_instant_activation(self, transcript: str) -> tuple[str, bool]:
        commands = await self._execute_instant_activation_command(transcript)
        if commands:
            if self.on_add_forced_commands is not None:
                await self.on_add_forced_commands(commands)
            responses = []
            for command in commands:
                if command.responses:
                    responses.append(self.select_instant_command_response(command))

            if len(responses) == len(commands):
                responses = list(dict.fromkeys(responses))
                responses = [
                    response + "." if not response.endswith(".") else response
                    for response in responses
                ]
                return " ".join(responses), True

            return None, True

        return None, False

    async def _execute_instant_activation_command(
        self, transcript: str
    ) -> list[CommandConfig] | None:
        if not self.config.commands:
            return None
        try:
            commands_by_instant_activation = {}
            for command in self.config.commands:
                if command.instant_activation:
                    for phrase in command.instant_activation:
                        if phrase.lower() in commands_by_instant_activation:
                            commands_by_instant_activation[phrase.lower()].append(
                                command
                            )
                        else:
                            commands_by_instant_activation[phrase.lower()] = [command]

            phrase = difflib.get_close_matches(
                transcript.lower(),
                commands_by_instant_activation.keys(),
                n=1,
                cutoff=1,
            )

            if not phrase:
                return None

            commands = commands_by_instant_activation[phrase[0]]
            for command in commands:
                await self.execute_command(command, True)

            return commands
        except Exception as e:
            await printr.print_async(
                f"Error during instant activation in Wingman '{self.wingman_name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return None

    # ───────────────── Command execution ──────────────────────── #

    async def execute_command(
        self, command: CommandConfig, is_instant=False
    ) -> tuple[str | None, str]:
        if not command:
            return None, "Command not found"

        try:
            if len(command.actions or []) == 0:
                await printr.print_async(
                    f"No actions found for command: {command.name}",
                    color=LogType.WARNING,
                )
            else:
                await self.execute_action(command)
                await printr.print_async(
                    f"Executed {'instant' if is_instant else 'AI'} command: {command.name}",
                    color=LogType.COMMAND,
                )

            if command.name == "ResetConversationHistory":
                await self.on_reset_history()
                await printr.print_async(
                    f"Executed command: {command.name}", color=LogType.COMMAND
                )

            return (
                self.select_instant_command_response(command),
                command.additional_context or "OK",
            )
        except Exception as e:
            await printr.print_async(
                f"Error executing command '{command.name}' for Wingman '{self.wingman_name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return None, "ERROR DURING PROCESSING"

    # ───────────────── Tool definition ───────────────────────── #

    def get_tool_definition(self) -> dict | None:
        """Return the OpenAI-style execute_command tool definition, or None if no
        eligible commands are configured."""
        if not self.config.commands:
            return None
        commands = [
            command.name
            for command in self.config.commands
            if (not command.force_instant_activation)
            and _command_has_effective_actions(command)
        ]
        if not commands:
            return None
        return {
            "type": "function",
            "function": {
                "name": "execute_command",
                "description": "Executes a command",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command_name": {
                            "type": "string",
                            "description": "The name of the command to execute",
                            "enum": commands,
                        },
                    },
                    "required": ["command_name"],
                },
            },
        }

    # ───────────────── Action dispatch ────────────────────────── #

    async def execute_action(self, command: CommandConfig):
        if not command or not command.actions:
            return

        def contains_numpad_key(hotkey: str) -> bool:
            if not hotkey:
                return False
            tokens = hotkey.lower().split("+")
            return any(token.startswith("num ") for token in tokens)

        try:
            for action in command.actions:
                if action.keyboard:
                    if action.keyboard.hotkey_codes and not contains_numpad_key(
                        action.keyboard.hotkey
                    ):
                        code = action.keyboard.hotkey_codes
                    else:
                        code = action.keyboard.hotkey

                    if action.keyboard.press == action.keyboard.release:
                        hold = action.keyboard.hold or 0.1
                        if (
                            action.keyboard.hotkey_codes
                            and len(action.keyboard.hotkey_codes) == 1
                            and not contains_numpad_key(action.keyboard.hotkey)
                        ):
                            keyboard.direct_event(
                                action.keyboard.hotkey_codes[0],
                                0 + (1 if action.keyboard.hotkey_extended else 0),
                            )
                            time.sleep(hold)
                            keyboard.direct_event(
                                action.keyboard.hotkey_codes[0],
                                2 + (1 if action.keyboard.hotkey_extended else 0),
                            )
                        else:
                            keyboard.press(code)
                            time.sleep(hold)
                            keyboard.release(code)
                    else:
                        if (
                            action.keyboard.hotkey_codes
                            and len(action.keyboard.hotkey_codes) == 1
                            and not contains_numpad_key(action.keyboard.hotkey)
                        ):
                            keyboard.direct_event(
                                action.keyboard.hotkey_codes[0],
                                (0 if action.keyboard.press else 2)
                                + (1 if action.keyboard.hotkey_extended else 0),
                            )
                        else:
                            keyboard.send(
                                code,
                                action.keyboard.press,
                                action.keyboard.release,
                            )

                if action.mouse:
                    if action.mouse.move_to:
                        x, y = action.mouse.move_to
                        mouse.move(x, y)

                    if action.mouse.move:
                        x, y = action.mouse.move
                        mouse.move(x, y, absolute=False, duration=0.5)

                    if action.mouse.scroll:
                        mouse.wheel(action.mouse.scroll)

                    if action.mouse.button:
                        if action.mouse.hold:
                            mouse.press(button=action.mouse.button)
                            time.sleep(action.mouse.hold)
                            mouse.release(button=action.mouse.button)
                        else:
                            mouse.click(button=action.mouse.button)

                if action.write:
                    keyboard.write(action.write)

                if action.wait:
                    time.sleep(action.wait)

                if action.audio:
                    await self.audio_library.handle_action(
                        action.audio, self.config.sound.volume
                    )
        except Exception as e:
            await printr.print_async(
                f"Error executing actions of command '{command.name}' for wingman '{self.wingman_name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
