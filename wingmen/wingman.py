import random
import time
from difflib import SequenceMatcher
from importlib import import_module
from typing import Any
from services.audio_player import AudioPlayer
from services.printr import Printr
# see execute_keypress() method
printr = Printr()
try:
    import pydirectinput as key_module
except AttributeError:
    printr.print_warn(
        "pydirectinput is only supported on Windows. Falling back to pyautogui which might not work in games.",
        wait_for_gui=True
    )
    import pyautogui as key_module


class Wingman:
    """The "highest" Wingman base class in the chain. It does some very basic things but is meant to be 'virtual', and so are most its methods, so you'll probably never instantiate it directly.

    Instead, you'll create a custom wingman that inherits from this (or a another subclass of it) and override its methods if needed.
    """

    def __init__(self, name: str, config: dict[str, Any]):
        """The constructor of the Wingman class. You can override it in your custom wingman.

        Args:
            name (str): The name of the wingman. This is the key you gave it in the config, e.g. "atc"
            config (dict[str, any]): All "general" config entries merged with the specific Wingman config settings. The Wingman takes precedence and overrides the general config. You can just add new keys to the config and they will be available here.
        """

        self.config = config
        """All "general" config entries merged with the specific Wingman config settings. The Wingman takes precedence and overrides the general config. You can just add new keys to the config and they will be available here."""

        self.name = name
        """The name of the wingman. This is the key you gave it in the config, e.g. "atc"."""

        self.audio_player = AudioPlayer()
        """A service that allows you to play audio files and add sound effects to them."""

        self.execution_start: None | float = None
        """Used for benchmarking executon times. The timer is (re-)started whenever the process function starts."""

        self.debug: bool = self.config["features"].get("debug_mode", False)
        """If enabled, the Wingman will skip executing any keypresses. It will also print more debug messages and benchmark results."""

        self.tts_provider = self.config["features"].get("tts_provider")
        """The name of the TTS provider you configured in the config.yaml"""
        # todo: remove warning for release
        if not self.tts_provider or not self.config.get("edge_tts"):
            printr.print_warn(
                "No TTS provider configured. You're probably using an outdated config.yaml",
                True
            )

    @staticmethod
    def create_dynamically(
        module_path: str, class_name: str, name: str, config: dict[str, Any], **kwargs
    ):
        """Dynamically creates a Wingman instance from a module path and class name

        Args:
            module_path (str): The module path, e.g. wingmen.open_ai_wingman. It's like the filepath from root to your custom-wingman.py but with dots instead of slashes and without the .py extension. Case-sensitive!
            class_name (str): The name of the class inside your custom-wingman.py, e.g. OpenAiWingman. Case-sensitive!
            name (str): The name of the wingman. This is the key you gave it in the config, e.g. "atc"
            config (dict[str, any]): All "general" config entries merged with the specific Wingman config settings. The Wingman takes precedence and overrides the general config. You can just add new keys to the config and they will be available here.
        """

        module = import_module(module_path)
        DerivedWingmanClass = getattr(module, class_name)
        instance = DerivedWingmanClass(name, config, **kwargs)
        return instance

    def get_record_key(self) -> str:
        """Returns the activation or "push-to-talk" key for this Wingman."""
        return self.config.get("record_key", None)

    def print_execution_time(self, reset_timer=False):
        """Prints the current time since the execution started (in seconds)."""
        if self.execution_start:
            execution_stop = time.perf_counter()
            elapsed_seconds = execution_stop - self.execution_start
            Printr.info_print(f"...took {elapsed_seconds:.2f}s", first_message=False)
        if reset_timer:
            self.start_execution_benchmark()

    def start_execution_benchmark(self):
        """Starts the execution benchmark timer."""
        self.execution_start = time.perf_counter()

    # ──────────────────────────────────── Hooks ─────────────────────────────────── #

    # TODO: this should be async
    def prepare(self):
        """This method is called only once when the Wingman is instantiated by Tower.

        You can override it if you need to load async data from an API or file."""
        pass

    def validate(self) -> list[str]:
        """Use this function to validate params and config before the Wingman is started.
        If you add new config sections or entries to your custom wingman, you should validate them here.

        It's a good idea to collect all errors from the base class and not to swallow them first.

        If you return errors, your Wingman will be disabled by Tower and not be loaded.

        Returns:
            list[str]: A list of error messages or an empty list if everything is okay.
        """
        return []

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
            Printr.info_print("Starting transcription...")

        # transcribe the audio.
        transcript, locale = await self._transcribe(audio_input_wav)

        if self.debug:
            self.print_execution_time(reset_timer=True)

        if transcript:
            # TODO:
            # Printr.clr_print(f">> (You): {transcript}", Printr.LILA)
            printr.print(f">> (You): {transcript}")

            if self.debug:
                Printr.info_print("Getting response for transcript...")

            # process the transcript further. This is where you can do your magic. Return a string that is the "answer" to your passed transcript.
            process_result, instant_response = await self._get_response_for_transcript(
                transcript, locale
            )

            if self.debug:
                self.print_execution_time(reset_timer=True)

            actual_response = instant_response or process_result
            # TODO:
            # Printr.clr_print(f"<< ({self.name}): {actual_response}", Printr.GREEN)
            printr.print(f"<< ({self.name}): {actual_response}")

        if self.debug:
            Printr.info_print("Playing response back to user...")

        # the last step in the chain. You'll probably want to play the response to the user as audio using a TTS provider or mechanism of your choice.
        await self._play_to_user(str(process_result))

        if self.debug:
            self.print_execution_time()

    # ───────────────── virtual methods / hooks ───────────────── #

    async def _transcribe(self, audio_input_wav: str) -> tuple[str | None, str | None]:
        """Transcribes the audio to text. You can override this method if you want to use a different transcription service.

        Args:
            audio_input_wav (str): The path to the audio file that contains the user's speech. This is a recording of what you you said.

        Returns:
            tuple[str | None, str | None]: The transcript of the audio file and the detected language as locale (if determined).
        """
        return None, None

    async def _get_response_for_transcript(
        self, transcript: str, locale: str | None
    ) -> tuple[str, str]:
        """Processes the transcript and return a response as text. This where you'll do most of your work.
        Pass the transcript to AI providers and build a conversation. Call commands or APIs. Play temporary results to the user etc.


        Args:
            transcript (str): The user's spoken text transcribed as text.
            locale (str | None): The language that was detected to be used in the transcript, e.g. "de-DE".

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

    def _get_command(self, command_name: str) -> dict | None:
        """Extracts the command with the given name

        Args:
            command_name (str): the name of the command you used in the config

        Returns:
            {}: The command object from the config
        """

        command = next(
            (
                item
                for item in self.config.get("commands", [])
                if item["name"] == command_name
            ),
            None,
        )
        return command

    def _select_command_response(self, command: dict) -> str | None:
        """Returns one of the configured responses of the command. This base implementation returns a random one.

        Args:
            command (dict): The command object from the config

        Returns:
            str: A random response from the command's responses list in the config.
        """
        command_responses = command.get("responses", None)
        if (command_responses is None) or (len(command_responses) == 0):
            return None

        return random.choice(command_responses)

    def _execute_instant_activation_command(self, transcript: str) -> dict | None:
        """Uses a fuzzy string matching algorithm to match the transcript to a configured instant_activation command and executes it immediately.

        Args:
            transcript (text): What the user said, transcripted to text. Needs to be similar to one of the defined instant_activation phrases to work.

        Returns:
            {} | None: The executed instant_activation command.
        """

        instant_activation_commands = [
            command
            for command in self.config.get("commands", [])
            if command.get("instant_activation")
        ]

        # check if transcript matches any instant activation command. Each command has a list of possible phrases
        for command in instant_activation_commands:
            for phrase in command.get("instant_activation"):
                ratio = SequenceMatcher(
                    None,
                    transcript.lower(),
                    phrase.lower(),
                ).ratio()
                if (
                    ratio > 0.8
                ):  # if the ratio is higher than 0.8, we assume that the command was spoken
                    self._execute_command(command)

                    if command.get("responses"):
                        return command
                    return None
        return None

    def _execute_command(self, command: dict) -> str:
        """Triggers the execution of a command. This base implementation executes the keypresses defined in the command.

        Args:
            command (dict): The command object from the config to execute

        Returns:
            str: the selected response from the command's responses list in the config. "Ok" if there are none.
        """

        if not command:
            return "Command not found"

        # Printr.info_print(f"❖ Executing command: {command.get('name')}")
        printr.print(f"❖ Executing command: {command.get('name')}")

        if self.debug:
            Printr.warn_print(
                "Skipping actual keypress execution in debug_mode...", False
            )

        if len(command.get("keys", [])) > 0 and not self.debug:
            self.execute_keypress(command)
        # TODO: we could do mouse_events here, too...

        # handle the global special commands:
        if command.get("name", None) == "ResetConversationHistory":
            self.reset_conversation_history()

        if not self.debug:
            # in debug mode we already printed the separate execution times
            self.print_execution_time()

        return self._select_command_response(command) or "Ok"

    def execute_keypress(self, command: dict):
        """Executes the keypresses defined in the command in order.

        pydirectinput uses SIGEVENTS to send keypresses to the OS. This lib seems to be the only way to send keypresses to games reliably.

        It only works on Windows. For MacOS, we fall back to PyAutoGUI (which has the exact same API as pydirectinput is built on top of it).

        Args:
            command (dict): The command object from the config to execute
        """

        for entry in command.get("keys", []):
            if entry.get("modifier"):
                key_module.keyDown(entry["modifier"])

            if entry.get("hold"):
                key_module.keyDown(entry["key"])
                time.sleep(entry["hold"])
                key_module.keyUp(entry["key"])
            else:
                key_module.press(entry["key"])

            if entry.get("modifier"):
                key_module.keyUp(entry["modifier"])

            if entry.get("wait"):
                time.sleep(entry["wait"])
