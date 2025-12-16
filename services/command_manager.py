"""Command Manager Service

Manages command execution, instant activation matching, and response selection.
Handles all command-related operations for Wingmen.
"""

import random
import difflib
import traceback
import asyncio
from typing import Optional
import keyboard.keyboard as keyboard
import mouse.mouse as mouse
from api.interface import CommandConfig, SettingsConfig
from api.enums import LogType
from services.printr import Printr
from services.audio_library import AudioLibrary

printr = Printr()


class CommandManager:
    """Manages all command-related operations for a Wingman.

    Responsibilities:
    - Command lookup and retrieval
    - Instant activation phrase matching
    - Command execution (keyboard, mouse, audio, joystick)
    - Response selection
    - Action execution
    """

    def __init__(
        self,
        wingman_name: str,
        audio_library: AudioLibrary,
        settings: SettingsConfig,
    ):
        """Initialize the command manager.

        Args:
            wingman_name: Name of the wingman (for logging)
            audio_library: Audio library for playing sound effects
            settings: User settings
        """
        self.wingman_name = wingman_name
        self.audio_library = audio_library
        self.settings = settings

    def get_command(
        self, commands: list[CommandConfig], command_name: str
    ) -> Optional[CommandConfig]:
        """Get a command by name.

        Args:
            commands: List of available commands (from live config)
            command_name: Name of the command to retrieve

        Returns:
            CommandConfig or None if not found
        """
        if not commands:
            return None

        return next(
            (cmd for cmd in commands if cmd.name == command_name),
            None,
        )

    def select_response(self, command: CommandConfig) -> Optional[str]:
        """Select a random response from the command's response list.

        Args:
            command: The command to get a response from

        Returns:
            Random response string or None if no responses configured
        """
        if not command.responses or len(command.responses) == 0:
            return None
        return random.choice(command.responses)

    async def try_instant_activation(
        self,
        commands: list[CommandConfig],
        transcript: str,
    ) -> Optional[list[CommandConfig]]:
        """Match transcript against instant activation phrases and execute commands.

        Uses fuzzy string matching to find the best matching instant activation
        phrase and executes all associated commands.

        Args:
            commands: List of available commands (from live config)
            transcript: User's spoken text to match against

        Returns:
            List of executed commands or None if no match found
        """
        try:
            # Build phrase-to-command mapping
            commands_by_phrase = {}
            for command in commands:
                if command.instant_activation:
                    for phrase in command.instant_activation:
                        phrase_lower = phrase.lower()
                        if phrase_lower in commands_by_phrase:
                            commands_by_phrase[phrase_lower].append(command)
                        else:
                            commands_by_phrase[phrase_lower] = [command]

            # Find best matching phrase using fuzzy matching
            matched_phrases = difflib.get_close_matches(
                transcript.lower(),
                commands_by_phrase.keys(),
                n=1,
                cutoff=1,  # Exact match required
            )

            if not matched_phrases:
                return None

            # Execute all commands for the matched phrase
            matched_commands = commands_by_phrase[matched_phrases[0]]
            for command in matched_commands:
                await self.execute_command(command, is_instant=True)

            return matched_commands

        except Exception as e:
            await printr.print_async(
                f"Error during instant activation: {str(e)}",
                color=LogType.ERROR,
                source_name=self.wingman_name,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return None

    async def execute_command(
        self,
        command: CommandConfig,
        is_instant: bool = False,
        reset_conversation_callback: Optional[callable] = None,
    ) -> str:
        """Execute a command's actions and return a response.

        Args:
            command: Command to execute
            is_instant: Whether this is an instant activation command
            reset_conversation_callback: Callback for ResetConversationHistory command

        Returns:
            Command response string or "Ok" if no response configured
        """
        if not command:
            return "Command not found"

        try:
            if not command.actions or len(command.actions) == 0:
                await printr.print_async(
                    f"No actions found for command: {command.name}",
                    color=LogType.WARNING,
                    source_name=self.wingman_name,
                )
            else:
                await self.execute_actions(command)
                await printr.print_async(
                    f"Executed {'instant' if is_instant else 'AI'} command: {command.name}",
                    color=LogType.COMMAND,
                    source_name=self.wingman_name,
                )

            # Handle special system commands
            if (
                command.name == "ResetConversationHistory"
                and reset_conversation_callback
            ):
                reset_conversation_callback()
                await printr.print_async(
                    f"Executed command: {command.name}",
                    color=LogType.COMMAND,
                    source_name=self.wingman_name,
                )

            return self.select_response(command) or "Ok"

        except Exception as e:
            await printr.print_async(
                f"Error executing command '{command.name}': {str(e)}",
                color=LogType.ERROR,
                source_name=self.wingman_name,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return "ERROR DURING PROCESSING"

    async def execute_actions(self, command: CommandConfig):
        """Execute all actions defined in a command (in order).

        Args:
            command: Command containing actions to execute
        """
        if not command or not command.actions:
            return

        try:
            for action in command.actions:
                # Keyboard actions
                if action.keyboard:
                    if action.keyboard.press == action.keyboard.release:
                        # Single key press
                        self.__press_keys(action.keyboard.press)
                        if action.keyboard.hotkey is not None:
                            keyboard.read_event()  # Wait for key up
                    elif action.keyboard.press:
                        for key in action.keyboard.press:
                            keyboard.press(key)
                    elif action.keyboard.release:
                        for key in action.keyboard.release:
                            keyboard.release(key)

                # Mouse actions
                if action.mouse:
                    if action.mouse.click:
                        mouse.click(button=action.mouse.click)
                    elif action.mouse.press:
                        mouse.press(button=action.mouse.press)
                    elif action.mouse.release:
                        mouse.release(button=action.mouse.release)
                    elif action.mouse.hold:
                        mouse.hold(button=action.mouse.hold)
                    elif action.mouse.move:
                        mouse.move(
                            action.mouse.move.x_offset,
                            action.mouse.move.y_offset,
                            absolute=False,
                            duration=0.2,
                        )
                    elif action.mouse.scroll:
                        mouse.wheel(delta=action.mouse.scroll.clicks)

                # Joystick actions
                if action.joystick:
                    await printr.print_async(
                        "Joystick actions are not yet implemented.",
                        color=LogType.WARNING,
                        source_name=self.wingman_name,
                    )

                # Audio playback actions
                if action.audio:
                    await self.audio_library.play_from_library(action.audio)

                # Write text actions
                if action.write:
                    keyboard.write(action.write.text, delay=action.write.delay or 0)

                # Wait/delay actions
                if action.wait:
                    await asyncio.sleep(action.wait.seconds)

        except Exception as e:
            await printr.print_async(
                f"Error executing actions for command '{command.name}': {str(e)}",
                color=LogType.ERROR,
                source_name=self.wingman_name,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

    def __press_keys(self, keys: list[str]):
        """Press multiple keys as a hotkey combination.

        Args:
            keys: List of keys to press together
        """
        keyboard.press_and_release("+".join(keys))

    def get_executable_commands(self, commands: list[CommandConfig]) -> list[str]:
        """Get list of command names that can be executed by the AI.

        Filters out instant-activation-only commands and commands without actions.

        Args:
            commands: List of available commands (from live config)

        Returns:
            List of command names for the AI tool definition
        """

        def has_effective_actions(command: CommandConfig) -> bool:
            """Check if command has any meaningful actions to execute."""
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

        return [
            cmd.name
            for cmd in commands
            if not cmd.force_instant_activation and has_effective_actions(cmd)
        ]
