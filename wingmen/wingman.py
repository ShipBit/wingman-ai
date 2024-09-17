from copy import deepcopy
import random
import time
import difflib
import asyncio
import threading
from typing import Optional
import keyboard.keyboard as keyboard
import mouse.mouse as mouse
from api.interface import (
    CommandConfig,
    SettingsConfig,
    SoundConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from api.enums import LogSource, LogType, WingmanInitializationErrorType
from providers.whispercpp import Whispercpp
from providers.xvasynth import XVASynth
from services.audio_player import AudioPlayer
from services.module_manager import ModuleManager
from services.secret_keeper import SecretKeeper
from services.printr import Printr
from services.audio_library import AudioLibrary

from skills.skill_base import Skill

printr = Printr()


class Wingman:
    """The "highest" Wingman base class in the chain. It does some very basic things but is meant to be 'virtual', and so are most its methods, so you'll probably never instantiate it directly.

    Instead, you'll create a custom wingman that inherits from this (or a another subclass of it) and override its methods if needed.
    """

    def __init__(
        self,
        name: str,
        config: WingmanConfig,
        settings: SettingsConfig,
        audio_player: AudioPlayer,
        audio_library: AudioLibrary,
        whispercpp: Whispercpp,
        xvasynth: XVASynth,
    ):
        """The constructor of the Wingman class. You can override it in your custom wingman.

        Args:
            name (str): The name of the wingman. This is the key you gave it in the config, e.g. "atc"
            config (WingmanConfig): All "general" config entries merged with the specific Wingman config settings. The Wingman takes precedence and overrides the general config. You can just add new keys to the config and they will be available here.
        """

        self.config = config
        """All "general" config entries merged with the specific Wingman config settings. The Wingman takes precedence and overrides the general config. You can just add new keys to the config and they will be available here."""

        self.settings = settings
        """The general user settings."""

        self.secret_keeper = SecretKeeper()
        """A service that allows you to store and retrieve secrets like API keys. It can prompt the user for secrets if necessary."""
        self.secret_keeper.secret_events.subscribe("secrets_saved", self.validate)

        self.name = name
        """The name of the wingman. This is the key you gave it in the config, e.g. "atc"."""

        self.audio_player = audio_player
        """A service that allows you to play audio files and add sound effects to them."""

        self.audio_library = audio_library
        """A service that allows you to play and manage audio files from the audio library."""

        self.execution_start: None | float = None
        """Used for benchmarking executon times. The timer is (re-)started whenever the process function starts."""

        self.whispercpp = whispercpp
        """A class that handles the communication with the Whispercpp server for transcription."""

        self.xvasynth = xvasynth
        """A class that handles the communication with the XVASynth server for TTS."""

        self.skills: list[Skill] = []

    def get_record_key(self) -> str | int:
        """Returns the activation or "push-to-talk" key for this Wingman."""
        return self.config.record_key_codes or self.config.record_key

    def get_record_button(self) -> str:
        """Returns the activation or "push-to-talk" mouse button for this Wingman."""
        return self.config.record_mouse_button

    def start_execution_benchmark(self):
        """Starts the execution benchmark timer."""
        self.execution_start = time.perf_counter()

    async def print_execution_time(self, reset_timer=False):
        """Prints the current time since the execution started (in seconds)."""
        if self.execution_start:
            execution_stop = time.perf_counter()
            elapsed_seconds = execution_stop - self.execution_start
            await printr.print_async(
                f"...took {elapsed_seconds:.2f}s", color=LogType.INFO
            )
        if reset_timer:
            self.start_execution_benchmark()

    # ──────────────────────────────────── Hooks ─────────────────────────────────── #

    async def validate(self) -> list[WingmanInitializationError]:
        """Use this function to validate params and config before the Wingman is started.
        If you add new config sections or entries to your custom wingman, you should validate them here.

        It's a good idea to collect all errors from the base class and not to swallow them first.

        If you return MISSING_SECRET errors, the user will be asked for them.
        If you return other errors, your Wingman will not be loaded by Tower.

        Returns:
            list[WingmanInitializationError]: A list of errors or an empty list if everything is okay.
        """
        return []

    async def retrieve_secret(self, secret_name, errors):
        """Use this method to retrieve secrets like API keys from the SecretKeeper.
        If the key is missing, the user will be prompted to enter it.
        """
        api_key = await self.secret_keeper.retrieve(
            requester=self.name,
            key=secret_name,
            prompt_if_missing=True,
        )
        if not api_key:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.name,
                    message=f"Missing secret '{secret_name}'.",
                    error_type=WingmanInitializationErrorType.MISSING_SECRET,
                    secret_name=secret_name,
                )
            )
        return api_key

    async def prepare(self):
        """This method is called only once when the Wingman is instantiated by Tower.
        It is run AFTER validate() and AFTER init_skills() so you can access validated params safely here.

        You can override it if you need to load async data from an API or file."""

    async def unload(self):
        """This method is called when the Wingman is unloaded by Tower. You can override it if you need to clean up resources."""

    async def unload_skills(self):
        """Call this to trigger unload for all skills."""
        for skill in self.skills:
            await skill.unload()

    async def init_skills(self) -> list[WingmanInitializationError]:
        """This method is called when the Wingman is instantiated by Tower or when a skill's config changes.
        It is run AFTER validate() so you can access validated params safely here.
        It is used to load and init the skills of the Wingman."""
        if self.skills:
            await self.unload_skills()

        errors = []
        self.skills = []
        if not self.config.skills:
            return errors

        for skill_config in self.config.skills:
            try:
                skill = ModuleManager.load_skill(
                    config=skill_config,
                    settings=self.settings,
                    wingman=self,
                )
                if skill:
                    # init skill methods
                    skill.threaded_execution = self.threaded_execution

                    validation_errors = await skill.validate()

                    # Give the user 2*5 seconds to enter the secret if one is required and missing
                    if any(
                        error.error_type == "missing_secret"
                        for error in validation_errors
                    ):
                        for _attempt in range(2):
                            await asyncio.sleep(5)
                            validation_errors = await skill.validate()
                            if not validation_errors:
                                break

                    errors.extend(validation_errors)

                    if len(errors) == 0:
                        self.skills.append(skill)
                        await self.prepare_skill(skill)
                        await skill.prepare()
                        printr.print(
                            f"Skill '{skill_config.name}' loaded successfully.",
                            color=LogType.INFO,
                            server_only=True,
                        )
                    else:
                        await printr.print_async(
                            f"Skill '{skill_config.name}' could not be loaded: {' '.join(error.message for error in validation_errors)}",
                            color=LogType.ERROR,
                        )
            except Exception as e:
                await printr.print_async(
                    f"Could not load skill '{skill_config.name}': {str(e)}",
                    color=LogType.ERROR,
                )

        return errors

    async def prepare_skill(self, skill: Skill):
        """This method is called only once when the Skill is instantiated.
        It is run AFTER validate() so you can access validated params safely here.

        You can override it if you need to react on data of this skill."""

    def reset_conversation_history(self):
        """This function is called when the user triggers the ResetConversationHistory command.
        It's a global command that should be implemented by every Wingman that keeps a message history.
        """

    # ──────────────────────────── The main processing loop ──────────────────────────── #

    async def process(self, audio_input_wav: str = None, transcript: str = None):
        """The main method that gets called when the wingman is activated. This method controls what your wingman actually does and you can override it if you want to.

        The base implementation here triggers the transcription and processing of the given audio input.
        If you don't need even transcription, you can just override this entire process method. If you want transcription but then do something in addition, you can override the listed hooks.

        Async so you can do async processing, e.g. send a request to an API.

        Args:
            audio_input_wav (str): The path to the audio file that contains the user's speech. This is a recording of what you you said.

        Hooks:
            - async _transcribe: transcribe the audio to text
            - async _get_response_for_transcript: process the transcript and return a text response
            - async play_to_user: do something with the response, e.g. play it as audio
        """

        self.start_execution_benchmark()

        process_result = None

        if self.settings.debug_mode and not transcript:
            await printr.print_async("Starting transcription...", color=LogType.INFO)

        if not transcript:
            # transcribe the audio.
            transcript = await self._transcribe(audio_input_wav)

        if self.settings.debug_mode and not transcript:
            await self.print_execution_time(reset_timer=True)

        if transcript:
            await printr.print_async(
                f"{transcript}",
                color=LogType.PURPLE,
                source_name="User",
                source=LogSource.USER,
            )

            if self.settings.debug_mode:
                await printr.print_async(
                    "Getting response for transcript...", color=LogType.INFO
                )

            # process the transcript further. This is where you can do your magic. Return a string that is the "answer" to your passed transcript.
            process_result, instant_response, skill, interrupt = (
                await self._get_response_for_transcript(transcript)
            )

            if self.settings.debug_mode:
                await self.print_execution_time(reset_timer=True)

            actual_response = instant_response or process_result
            if actual_response:
                await printr.print_async(
                    f"{actual_response}",
                    color=LogType.POSITIVE,
                    source=LogSource.WINGMAN,
                    source_name=self.name,
                    skill_name=skill.name if skill else "",
                )

        # the last step in the chain. You'll probably want to play the response to the user as audio using a TTS provider or mechanism of your choice.
        if process_result:
            await self.play_to_user(str(process_result), not interrupt)

    # ───────────────── virtual methods / hooks ───────────────── #

    async def _transcribe(self, audio_input_wav: str) -> str | None:
        """Transcribes the audio to text. You can override this method if you want to use a different transcription service.

        Args:
            audio_input_wav (str): The path to the audio file that contains the user's speech. This is a recording of what you you said.

        Returns:
            str | None: The transcript of the audio file and the detected language as locale (if determined).
        """
        return None

    async def _get_response_for_transcript(
        self, transcript: str
    ) -> tuple[str, str, Skill | None]:
        """Processes the transcript and return a response as text. This where you'll do most of your work.
        Pass the transcript to AI providers and build a conversation. Call commands or APIs. Play temporary results to the user etc.


        Args:
            transcript (str): The user's spoken text transcribed as text.

        Returns:
            A tuple of strings representing the response to a function call and/or an instant response.
        """
        return ("", "", None)

    async def play_to_user(
        self,
        text: str,
        no_interrupt: bool = False,
        sound_config: Optional[SoundConfig] = None,
    ):
        """You'll probably want to play the response to the user as audio using a TTS provider or mechanism of your choice.

        Args:
            text (str): The response of your _get_response_for_transcript. This is usually the "response" from conversation with the AI.
            no_interrupt (bool): prevent interrupting the audio playback
            sound_config (SoundConfig): An optional sound configuration to use for the playback. If unset, the Wingman's sound config is used.
        """
        pass

    # ───────────────────────────────── Commands ─────────────────────────────── #

    def get_command(self, command_name: str):
        """Extracts the command with the given name

        Args:
            command_name (str): the name of the command you used in the config

        Returns:
            {}: The command object from the config
        """
        if self.config.commands is None:
            return None

        command = next(
            (item for item in self.config.commands if item.name == command_name),
            None,
        )
        return command

    def _select_command_response(self, command: CommandConfig) -> str | None:
        """Returns one of the configured responses of the command. This base implementation returns a random one.

        Args:
            command (dict): The command object from the config

        Returns:
            str: A random response from the command's responses list in the config.
        """
        command_responses = command.responses
        if (command_responses is None) or (len(command_responses) == 0):
            return None

        return random.choice(command_responses)

    async def _execute_instant_activation_command(
        self, transcript: str
    ) -> list[CommandConfig] | None:
        """Uses a fuzzy string matching algorithm to match the transcript to a configured instant_activation command and executes it immediately.

        Args:
            transcript (text): What the user said, transcripted to text. Needs to be similar to one of the defined instant_activation phrases to work.

        Returns:
            {} | None: The executed instant_activation command.
        """

        # create list with phrases pointing to commands
        commands_by_instant_activation = {}
        for command in self.config.commands:
            if command.instant_activation:
                for phrase in command.instant_activation:
                    if phrase.lower() in commands_by_instant_activation:
                        commands_by_instant_activation[phrase.lower()].append(command)
                    else:
                        commands_by_instant_activation[phrase.lower()] = [command]

        # find best matching phrase
        phrase = difflib.get_close_matches(
            transcript.lower(), commands_by_instant_activation.keys(), n=1, cutoff=0.8
        )

        # if no phrase found, return None
        if not phrase:
            return None

        # execute all commands for the phrase
        commands = commands_by_instant_activation[phrase[0]]
        for command in commands:
            await self._execute_command(command)

        # return the executed command
        return commands

    async def _execute_command(self, command: CommandConfig) -> str:
        """Triggers the execution of a command. This base implementation executes the keypresses defined in the command.

        Args:
            command (dict): The command object from the config to execute

        Returns:
            str: the selected response from the command's responses list in the config. "Ok" if there are none.
        """

        if not command:
            return "Command not found"

        if len(command.actions or []) > 0:
            await printr.print_async(
                f"Executing command: {command.name}", color=LogType.INFO
            )
            if not self.settings.debug_mode:
                # in debug mode we already printed the separate execution times
                await self.print_execution_time()
            await self.execute_action(command)

        if len(command.actions or []) == 0:
            await printr.print_async(
                f"No actions found for command: {command.name}", color=LogType.WARNING
            )

        # handle the global special commands:
        if command.name == "ResetConversationHistory":
            self.reset_conversation_history()

        return self._select_command_response(command) or "Ok"

    async def execute_action(self, command: CommandConfig):
        """Executes the actions defined in the command (in order).

        Args:
            command (dict): The command object from the config to execute
        """
        if not command or not command.actions:
            return

        for action in command.actions:
            if action.keyboard:
                if action.keyboard.press == action.keyboard.release:
                    # compressed key events
                    hold = action.keyboard.hold or 0.1
                    if (
                        action.keyboard.hotkey_codes
                        and len(action.keyboard.hotkey_codes) == 1
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
                        keyboard.press(
                            action.keyboard.hotkey_codes or action.keyboard.hotkey
                        )
                        time.sleep(hold)
                        keyboard.release(
                            action.keyboard.hotkey_codes or action.keyboard.hotkey
                        )
                else:
                    # single key events
                    if (
                        action.keyboard.hotkey_codes
                        and len(action.keyboard.hotkey_codes) == 1
                    ):
                        keyboard.direct_event(
                            action.keyboard.hotkey_codes[0],
                            (0 if action.keyboard.press else 2)
                            + (1 if action.keyboard.hotkey_extended else 0),
                        )
                    else:
                        keyboard.send(
                            action.keyboard.hotkey_codes or action.keyboard.hotkey,
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
                await self.audio_library.start_playback(
                    action.audio, self.config.sound.volume
                )

    def threaded_execution(self, function, *args) -> threading.Thread:
        """Execute a function in a separate thread."""

        def start_thread(function, *args):
            if asyncio.iscoroutinefunction(function):
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                new_loop.run_until_complete(function(*args))
                new_loop.close()
            else:
                function(*args)

        thread = threading.Thread(target=start_thread, args=(function, *args))
        thread.start()
        return thread

    async def update_config(
        self, config: WingmanConfig, validate=False, update_skills=False
    ):
        """Update the config of the Wingman. This method should always be called if the config of the Wingman has changed."""
        if validate:
            old_config = deepcopy(self.config)

        self.config = config

        if update_skills:
            await self.init_skills()

        if validate:
            errors = await self.validate()

            for error in errors:
                if error.error_type != WingmanInitializationErrorType.MISSING_SECRET:
                    self.config = old_config
                    return False

        return True

    async def update_settings(self, settings: SettingsConfig):
        """Update the settings of the Wingman. This method should always be called when the user Settings have changed."""
        self.settings = settings
        await self.init_skills()

        printr.print(f"Wingman {self.name}'s settings changed", server_only=True)
