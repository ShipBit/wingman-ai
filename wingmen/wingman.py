import random
import time
from difflib import SequenceMatcher
from importlib import import_module
from services.audio_player import AudioPlayer
from services.printr import Printr

# PyDirectInput uses SIGEVENTS to send keypresses to the OS.
# This is the only way to send keypresses to games reliably.
# It only works on Windows, though. For MacOS, we fall back to PyAutoGUI.
try:
    import pydirectinput as key_module
except AttributeError:
    Printr.warn_print(
        "pydirectinput is only supported on Windows. Falling back to pyautogui which might not work in games."
    )
    import pyautogui as key_module


class Wingman:
    """The "highest" Wingman base class in the chain. It does some very basic things but is meant to be 'virtual', and so are most its methods, so you'll probably never instantiate it directly.

    Instead, you'll create a custom wingman that inherits from this (or a another subclass of it) and override its methods if needed.
    """

    start_time = None

    def __init__(self, name: str, config: dict[str, any]):
        """The constructor of the Wingman class. You can override it in your custom wingman.

        Args:
            name (str): The name of the wingman. This is the key you gave it in the config, e.g. "atc"
            config (dict[str, any]): All "general" config entries merged with the specific Wingman config settings. The Wingman takes precedence and overrides the general config. You can just add new keys to the config and they will be available here.
        """

        self.config = config
        """All "general" config entries merged with the specific Wingman config settings. The Wingman takes precedence and overrides the general config. You can just add new keys to the config and they will be available here."""

        self.name = name
        """The name of the wingman. This is the key you gave it in the config, e.g. "atc"""

        self.audio_player = AudioPlayer()
        """A service that allows you to play audio files and add sound effects to them."""

    @staticmethod
    def create_dynamically(
        module_path: str, class_name: str, name: str, config: dict[str, any], **kwargs
    ):
        """Dynamically create a Wingman instance from a module path and class name

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
        return self.config.get("record_key", None)

    async def process(self, audio_input_wav: str):
        """The main method that gets called when the wingman is activated. This method controls what your wingman actually does and you can override it if you want to.

        The base implementation here triggers the transcription and processing of the given audio input.
        If you don't need even transcription, you can just override this entire process method.

        Async so you can do async processing, e.g. send a request to an API.

        Args:
            audio_input_wav (str): The path to the audio file that contains the user's speech. This is a recording of what you you said.

        Hooks:
            - async _transcribe
            - async _process_transcript
            - async _on_process_finished
        """
        process_result = None

        # transcribe the audio.
        transcript = await self._transcribe(audio_input_wav)
        if transcript:
            print(
                f"{Printr.clr('>> (You):', Printr.LILA)} {Printr.clr(transcript, Printr.LILA)}"
            )

            process_result, instant_response = self._process_transcript(transcript)
            print(
                f"{Printr.clr('<<', Printr.GREEN)} ({Printr.clr(self.name, Printr.GREEN)}): {Printr.clr(instant_response or response, Printr.GREEN)}"
            )

        # the last step in the chain. Usually, you'll want to play the response to the user as audio using a TTS provider or mechanism of your choice.
        await self._on_process_finished(process_result)

    def _get_command(self, command_name):
        # Get the command from the list of commands
        command = next(
            (
                item
                for item in self.config.get("commands")
                if item["name"] == command_name
            ),
            None,
        )
        return command

    def _process_instant_activation_command(self, transcript) -> bool | None:
        # all instant activation commands
        instant_activation_commands = [
            command
            for command in self.config["commands"]
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
                    self._execute_command(command)  # execute the command immediately
                    if command.get("responses"):
                        return command
                    return None
        return None

    def _get_exact_response(self, command):
        response = random.choice(command.get("responses"))
        return response

    def _execute_command(self, command) -> str:
        if not command:
            return "Command not found"

        if self.config.get("debug_mode") and self.start_time:
            end_time = time.perf_counter()
            print(f"Execution Time: {end_time - self.start_time}")

        print(
            f"{Printr.clr('❖ Executing command:', Printr.BLUE)} {command.get('name')}"
        )

        command_response = "Ok"

        if self.config.get("debug_mode"):
            return command_response

        for entry in command.get("keys"):
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

        return command_response

    # virtual methods:

    async def _transcribe(self, audio_input_wav: str) -> str | None:
        if self.config.get("debug_mode"):
            self.start_time = time.perf_counter()

        return None

    def _process_transcript(self, transcript: str) -> tuple[str, str]:
        return ""

    async def _on_process_finished(self, text: str):
        pass
