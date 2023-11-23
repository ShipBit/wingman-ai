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
    start_time = None

    def __init__(self, name: str, config: dict[str, any]):
        self.config = config
        self.name = name
        self.audio_player = AudioPlayer()

    @staticmethod
    def create_dynamically(
        module_path, class_name, name: str, config: dict[str, any], **kwargs
    ):
        module = import_module(module_path)
        DerivedWingmanClass = getattr(module, class_name)
        instance = DerivedWingmanClass(name, config, **kwargs)
        return instance

    def get_record_key(self) -> str:
        return self.config.get("record_key", None)

    async def process(self, audio_input_wav: str):
        transcript = self._transcribe(audio_input_wav)
        if transcript:
            print(
                f"{Printr.clr('>> (You):', Printr.LILA)} {Printr.clr(transcript, Printr.LILA)}"
            )

            response, instant_response = self._process_transcript(transcript)
            print(
                f"{Printr.clr('<<', Printr.GREEN)} ({Printr.clr(self.name, Printr.GREEN)}): {Printr.clr(instant_response or response, Printr.GREEN)}"
            )

            self._finish_processing(response)

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

    def _transcribe(self, audio_input_wav: str) -> str:
        if self.config.get("debug_mode"):
            self.start_time = time.perf_counter()

        return ""

    def _process_transcript(self, transcript: str) -> tuple[str, str]:
        return ""

    def _finish_processing(self, text: str):
        pass
