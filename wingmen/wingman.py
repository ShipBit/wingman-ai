import random
import time
from difflib import SequenceMatcher
from importlib import import_module, util
from os import path
import keyboard.keyboard as keyboard
import mouse.mouse as mouse
from api.interface import CommandConfig, WingmanConfig, WingmanInitializationError
from api.enums import LogSource, LogType, WingmanInitializationErrorType
from services.audio_player import AudioPlayer
from services.secret_keeper import SecretKeeper
from services.printr import Printr
from services.file import get_writable_dir

printr = Printr()


class Wingman:
    """The "highest" Wingman base class in the chain. It does some very basic things but is meant to be 'virtual', and so are most its methods, so you'll probably never instantiate it directly.

    Instead, you'll create a custom wingman that inherits from this (or a another subclass of it) and override its methods if needed.
    """

    def __init__(
        self,
        name: str,
        config: WingmanConfig,
    ):
        """The constructor of the Wingman class. You can override it in your custom wingman.

        Args:
            name (str): The name of the wingman. This is the key you gave it in the config, e.g. "atc"
            config (WingmanConfig): All "general" config entries merged with the specific Wingman config settings. The Wingman takes precedence and overrides the general config. You can just add new keys to the config and they will be available here.
        """

        self.config = config
        """All "general" config entries merged with the specific Wingman config settings. The Wingman takes precedence and overrides the general config. You can just add new keys to the config and they will be available here."""

        self.secret_keeper = SecretKeeper()
        """A service that allows you to store and retrieve secrets like API keys. It can prompt the user for secrets if necessary."""

        self.name = name
        """The name of the wingman. This is the key you gave it in the config, e.g. "atc"."""

        self.audio_player = AudioPlayer()
        """A service that allows you to play audio files and add sound effects to them."""

        self.execution_start: None | float = None
        """Used for benchmarking executon times. The timer is (re-)started whenever the process function starts."""

        self.debug: bool = self.config.features.debug_mode
        """If enabled, the Wingman will skip executing any keypresses. It will also print more debug messages and benchmark results."""

        self.tts_provider = self.config.features.tts_provider
        self.stt_provider = self.config.features.stt_provider
        self.conversation_provider = self.config.features.conversation_provider
        self.summarize_provider = self.config.features.summarize_provider

    @staticmethod
    def create_dynamically(
        name: str,
        config: WingmanConfig,
    ):
        """Dynamically creates a Wingman instance from a module path and class name

        Args:
            module_path (str): The module path, e.g. wingmen.open_ai_wingman. It's like the filepath from root to your custom-wingman.py but with dots instead of slashes and without the .py extension. Case-sensitive!
            class_name (str): The name of the class inside your custom-wingman.py, e.g. OpenAiWingman. Case-sensitive!
            name (str): The name of the wingman. This is the key you gave it in the config, e.g. "atc"
            config (Config): All "general" config entries merged with the specific Wingman config settings. The Wingman takes precedence and overrides the general config. You can just add new keys to the config and they will be available here.
        """

        try:
            # try to load from app dir first
            module = import_module(config.custom_class.module)
        except ModuleNotFoundError:
            # split module into name and path
            module_name = config.custom_class.module.split(".")[-1]
            module_path = ""
            for sub_dir in config.custom_class.module.split(".")[:-1]:
                module_path = path.join(module_path, sub_dir)
            module_path = path.join(get_writable_dir(module_path), module_name + ".py")
            # load from alternative absolute file path
            spec = util.spec_from_file_location(module_name, module_path)
            module = util.module_from_spec(spec)
            spec.loader.exec_module(module)
        DerivedWingmanClass = getattr(module, config.custom_class.name)
        instance = DerivedWingmanClass(
            name=name,
            config=config,
        )
        return instance

    def get_record_key(self) -> str:
        """Returns the activation or "push-to-talk" key for this Wingman."""
        return self.config.record_key

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

    def start_execution_benchmark(self):
        """Starts the execution benchmark timer."""
        self.execution_start = time.perf_counter()

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

    # TODO: this should be async
    def prepare(self):
        """This method is called only once when the Wingman is instantiated by Tower.
        It is run AFTER validate() so you can access validated params safely here.

        You can override it if you need to load async data from an API or file."""
        pass

    def reset_conversation_history(self):
        """This function is called when the user triggers the ResetConversationHistory command.
        It's a global command that should be implemented by every Wingman that keeps a message history.
        """

    # ──────────────────────────── The main processing loop ──────────────────────────── #

    async def process(self, audio_input_wav: str):
        """The main method that gets called when the wingman is activated. This method controls what your wingman actually does and you can override it if you want to.

        The base implementation here triggers the transcription and processing of the given audio input.
        If you don't need even transcription, you can just override this entire process method. If you want transcription but then do something in addition, you can override the listed hooks.

        Async so you can do async processing, e.g. send a request to an API.

        Args:
            audio_input_wav (str): The path to the audio file that contains the user's speech. This is a recording of what you you said.

        Hooks:
            - async _transcribe: transcribe the audio to text
            - async _get_response_for_transcript: process the transcript and return a text response
            - async _play_to_user: do something with the response, e.g. play it as audio
        """

        self.start_execution_benchmark()

        process_result = None

        if self.debug:
            await printr.print_async("Starting transcription...", color=LogType.INFO)

        # transcribe the audio.
        transcript = await self._transcribe(audio_input_wav)

        if self.debug:
            await self.print_execution_time(reset_timer=True)

        if transcript:
            await printr.print_async(
                f"{transcript}",
                color=LogType.PURPLE,
                source_name="User",
                source=LogSource.USER,
            )

            if self.debug:
                await printr.print_async(
                    "Getting response for transcript...", color=LogType.INFO
                )

            # process the transcript further. This is where you can do your magic. Return a string that is the "answer" to your passed transcript.
            process_result, instant_response = await self._get_response_for_transcript(
                transcript
            )

            if self.debug:
                await self.print_execution_time(reset_timer=True)

            actual_response = instant_response or process_result
            if actual_response:
                await printr.print_async(
                    f"{actual_response}",
                    color=LogType.POSITIVE,
                    source=LogSource.WINGMAN,
                    source_name=self.name,
                )

        if self.debug:
            await printr.print_async(
                "Playing response back to user...", color=LogType.INFO
            )

        # the last step in the chain. You'll probably want to play the response to the user as audio using a TTS provider or mechanism of your choice.
        if process_result:
            await self._play_to_user(str(process_result))

        if self.debug:
            await self.print_execution_time()

    # ───────────────── virtual methods / hooks ───────────────── #

    async def _transcribe(self, audio_input_wav: str) -> str | None:
        """Transcribes the audio to text. You can override this method if you want to use a different transcription service.

        Args:
            audio_input_wav (str): The path to the audio file that contains the user's speech. This is a recording of what you you said.

        Returns:
            str | None: The transcript of the audio file and the detected language as locale (if determined).
        """
        return None

    async def _get_response_for_transcript(self, transcript: str) -> tuple[str, str]:
        """Processes the transcript and return a response as text. This where you'll do most of your work.
        Pass the transcript to AI providers and build a conversation. Call commands or APIs. Play temporary results to the user etc.


        Args:
            transcript (str): The user's spoken text transcribed as text.

        Returns:
            A tuple of strings representing the response to a function call and/or an instant response.
        """
        return ("", "")

    async def _play_to_user(self, text: str):
        """You'll probably want to play the response to the user as audio using a TTS provider or mechanism of your choice.

        Args:
            text (str): The response of your _get_response_for_transcript. This is usually the "response" from conversation with the AI.
        """
        pass

    # ───────────────────────────────── Commands ─────────────────────────────── #

    def _get_command(self, command_name: str):
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

    async def _execute_instant_activation_command(self, transcript: str):
        """Uses a fuzzy string matching algorithm to match the transcript to a configured instant_activation command and executes it immediately.

        Args:
            transcript (text): What the user said, transcripted to text. Needs to be similar to one of the defined instant_activation phrases to work.

        Returns:
            {} | None: The executed instant_activation command.
        """

        instant_activation_commands = [
            command for command in self.config.commands if command.instant_activation
        ]

        # check if transcript matches any instant activation command. Each command has a list of possible phrases
        for command in instant_activation_commands:
            for phrase in command.instant_activation:
                ratio = SequenceMatcher(
                    None,
                    transcript.lower(),
                    phrase.lower(),
                ).ratio()
                if (
                    ratio > 0.8
                ):  # if the ratio is higher than 0.8, we assume that the command was spoken
                    await self._execute_command(command)
                    return command
        return None

    async def _execute_command(self, command: CommandConfig) -> str:
        """Triggers the execution of a command. This base implementation executes the keypresses defined in the command.

        Args:
            command (dict): The command object from the config to execute

        Returns:
            str: the selected response from the command's responses list in the config. "Ok" if there are none.
        """

        if not command:
            return "Command not found"

        if len(command.actions or []) > 0 and not self.debug:
            await printr.print_async(
                f"❖ Executing command: {command.name}", color=LogType.INFO
            )
            if not self.debug:
                # in debug mode we already printed the separate execution times
                await self.print_execution_time()
            self.execute_action(command)

        if len(command.actions or []) == 0:
            await printr.print_async(
                f"❖ No actions found for command: {command.name}", color=LogType.WARNING
            )

        if self.debug:
            await printr.print_async(
                "Skipping actual keypress execution in debug_mode...",
                color=LogType.WARNING,
            )

        # handle the global special commands:
        if command.name == "ResetConversationHistory":
            self.reset_conversation_history()

        return self._select_command_response(command) or "Ok"

    def execute_action(self, command: CommandConfig):
        """Executes the keypresses defined in the command in order.

        pydirectinput uses SIGEVENTS to send keypresses to the OS. This lib seems to be the only way to send keypresses to games reliably.

        It only works on Windows. For MacOS, we fall back to PyAutoGUI (which has the exact same API as pydirectinput is built on top of it).

        Args:
            command (dict): The command object from the config to execute
        """
        if not command or not command.actions:
            return

        for action in command.actions:
            if action.keyboard:
                if action.keyboard.hold:
                    keyboard.press(action.keyboard.hotkey)
                    time.sleep(action.keyboard.hold)
                    keyboard.release(action.keyboard.hotkey)
                else:
                    keyboard.send(action.keyboard.hotkey)

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
