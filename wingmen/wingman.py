import traceback
from copy import deepcopy
import random
import time
import difflib
import asyncio
import threading
from typing import (
    Optional,
    TYPE_CHECKING,
)
import keyboard.keyboard as keyboard
import mouse.mouse as mouse
from api.interface import (
    CommandConfig,
    SettingsConfig,
    SoundConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from api.enums import (
    LogSource,
    LogType,
    WingmanInitializationErrorType,
)
from providers.faster_whisper import FasterWhisper
from providers.whispercpp import Whispercpp
from providers.xvasynth import XVASynth
from services.audio_player import AudioPlayer
from services.benchmark import Benchmark
from services.module_manager import ModuleManager
from services.secret_keeper import SecretKeeper
from services.printr import Printr
from services.audio_library import AudioLibrary
from skills.skill_base import Skill

if TYPE_CHECKING:
    from services.tower import Tower

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
        fasterwhisper: FasterWhisper,
        xvasynth: XVASynth,
        tower: "Tower",
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

        self.fasterwhisper = fasterwhisper
        """A class that handles local transcriptions using FasterWhisper."""

        self.xvasynth = xvasynth
        """A class that handles the communication with the XVASynth server for TTS."""

        self.tower = tower
        """The Tower instance that manages all Wingmen in the same config dir."""

        self.skills: list[Skill] = []

    def get_record_key(self) -> str | int:
        """Returns the activation or "push-to-talk" key for this Wingman."""
        return self.config.record_key_codes or self.config.record_key

    def get_record_mouse_button(self) -> str:
        """Returns the activation or "push-to-talk" mouse button for this Wingman."""
        return self.config.record_mouse_button

    def get_record_joystick_button(self) -> str:
        """Returns the activation or "push-to-talk" joystick button for this Wingman."""
        if not self.config.record_joystick_button:
            return None
        return f"{self.config.record_joystick_button.guid}{self.config.record_joystick_button.button}"

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
        try:
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
        except Exception as e:
            printr.print(
                f"Error retrieving secret ''{secret_name}: {e}",
                color=LogType.ERROR,
                server_only=True,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.name,
                    message=f"Could not retrieve secret '{secret_name}': {str(e)}",
                    error_type=WingmanInitializationErrorType.MISSING_SECRET,
                    secret_name=secret_name,
                )
            )
            api_key = None

        return api_key

    async def prepare(self):
        """This method is called only once when the Wingman is instantiated by Tower.
        It is run AFTER validate() and AFTER init_skills() so you can access validated params safely here.

        You can override it if you need to load async data from an API or file."""

    async def unload(self):
        """This method is called when the Wingman is unloaded by Tower. You can override it if you need to clean up resources."""
        await self.unload_skills()

    async def unload_skills(self):
        """Call this to trigger unload for all skills."""
        for skill in self.skills:
            try:
                await skill.unload()
            except Exception as e:
                await printr.print_async(
                    f"Error unloading skill '{skill.name}': {str(e)}",
                    color=LogType.ERROR,
                )
                printr.print(
                    traceback.format_exc(), color=LogType.ERROR, server_only=True
                )

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
                            color=LogType.POSITIVE,
                            server_only=True,
                        )
                    else:
                        await printr.print_async(
                            f"Skill '{skill_config.name}' could not be loaded: {' '.join(error.message for error in validation_errors)}",
                            color=LogType.ERROR,
                        )
            except Exception as e:
                await printr.print_async(
                    f"Error loading skill '{skill_config.name}': {str(e)}",
                    color=LogType.ERROR,
                )
                printr.print(
                    traceback.format_exc(), color=LogType.ERROR, server_only=True
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

        try:
            process_result = None

            benchmark_transcribe = None
            if not transcript:
                # transcribe the audio.
                benchmark_transcribe = Benchmark(label="Voice transcription")
                transcript = await self._transcribe(audio_input_wav)

            interrupt = None
            if transcript:
                await printr.print_async(
                    f"{transcript}",
                    color=LogType.PURPLE,
                    source_name="User",
                    source=LogSource.USER,
                    benchmark_result=(
                        benchmark_transcribe.finish() if benchmark_transcribe else None
                    ),
                )

                # Further process the transcript.
                # Return a string that is the "answer" to your passed transcript.

                benchmark_llm = Benchmark(label="Command/AI Processing")
                process_result, instant_response, skill, interrupt = (
                    await self._get_response_for_transcript(
                        transcript=transcript, benchmark=benchmark_llm
                    )
                )

                actual_response = instant_response or process_result

                if actual_response:
                    await printr.print_async(
                        f"{actual_response}",
                        color=LogType.POSITIVE,
                        source=LogSource.WINGMAN,
                        source_name=self.name,
                        skill_name=skill.name if skill else "",
                        benchmark_result=benchmark_llm.finish(),
                    )

            if process_result:
                if self.settings.streamer_mode:
                    self.tower.save_last_message(self.name, process_result)

                # the last step in the chain. You'll probably want to play the response to the user as audio using a TTS provider or mechanism of your choice.
                await self.play_to_user(str(process_result), not interrupt)
        except Exception as e:
            await printr.print_async(
                f"Error during processing of Wingman '{self.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

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
        self, transcript: str, benchmark: Benchmark
    ) -> tuple[str | None, str | None, Skill | None, bool | None]:
        """Processes the transcript and return a response as text. This where you'll do most of your work.
        Pass the transcript to AI providers and build a conversation. Call commands or APIs. Play temporary results to the user etc.


        Args:
            transcript (str): The user's spoken text transcribed as text.

        Returns:
            A tuple of strings representing the response to a function call and/or an instant response.
        """
        return "", "", None, None

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

    def get_command(self, command_name: str) -> CommandConfig | None:
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

        try:
            # create list with phrases pointing to commands
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

            # find best matching phrase
            phrase = difflib.get_close_matches(
                transcript.lower(),
                commands_by_instant_activation.keys(),
                n=1,
                cutoff=0.8,
            )

            # if no phrase found, return None
            if not phrase:
                return None

            # execute all commands for the phrase
            commands = commands_by_instant_activation[phrase[0]]
            for command in commands:
                await self._execute_command(command, True)

            # return the executed command
            return commands
        except Exception as e:
            await printr.print_async(
                f"Error during instant activation in Wingman '{self.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return None

    async def _execute_command(self, command: CommandConfig, is_instant=False) -> str:
        """Triggers the execution of a command. This base implementation executes the keypresses defined in the command.

        Args:
            command (dict): The command object from the config to execute

        Returns:
            str: the selected response from the command's responses list in the config. "Ok" if there are none.
        """

        if not command:
            return "Command not found"

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
                    color=LogType.INFO,
                )

            # handle the global special commands:
            if command.name == "ResetConversationHistory":
                self.reset_conversation_history()
                await printr.print_async(
                    f"Executed command: {command.name}", color=LogType.INFO
                )

            return self._select_command_response(command) or "Ok"
        except Exception as e:
            await printr.print_async(
                f"Error executing command '{command.name}' for Wingman '{self.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return "ERROR DURING PROCESSING"  # hints to AI that there was an Error

    async def execute_action(self, command: CommandConfig):
        """Executes the actions defined in the command (in order).

        Args:
            command (dict): The command object from the config to execute
        """
        if not command or not command.actions:
            return

        try:
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
                    await self.audio_library.handle_action(
                        action.audio, self.config.sound.volume
                    )
        except Exception as e:
            await printr.print_async(
                f"Error executing actions of command '{command.name}' for wingman '{self.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

    def threaded_execution(self, function, *args) -> threading.Thread | None:
        """Execute a function in a separate thread."""
        try:

            def start_thread(function, *args):
                if asyncio.iscoroutinefunction(function):
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    new_loop.run_until_complete(function(*args))
                    new_loop.close()
                else:
                    function(*args)

            thread = threading.Thread(target=start_thread, args=(function, *args))
            thread.name = function.__name__
            thread.start()
            return thread
        except Exception as e:
            printr.print(
                f"Error starting threaded execution: {str(e)}", color=LogType.ERROR
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return None

    async def update_config(
        self, config: WingmanConfig, validate=False, update_skills=False
    ) -> bool:
        """Update the config of the Wingman. This method should always be called if the config of the Wingman has changed."""
        try:
            if validate:
                old_config = deepcopy(self.config)

            self.config = config

            if update_skills:
                await self.init_skills()

            if validate:
                errors = await self.validate()

                for error in errors:
                    if (
                        error.error_type
                        != WingmanInitializationErrorType.MISSING_SECRET
                    ):
                        self.config = old_config
                        return False

            return True
        except Exception as e:
            await printr.print_async(
                f"Error updating config for wingman '{self.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return False

    async def save_config(self):
        """Save the config of the Wingman."""
        self.tower.save_wingman(self.name)

    async def update_settings(self, settings: SettingsConfig):
        """Update the settings of the Wingman. This method should always be called when the user Settings have changed."""
        self.settings = settings
        await self.init_skills()

        printr.print(f"Wingman {self.name}'s settings changed", server_only=True)
