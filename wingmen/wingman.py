from importlib import import_module
from services.audio_player import AudioPlayer
from difflib import SequenceMatcher
from typing import Literal
import random
import time


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
        print(f" >> {transcript}")

        response = self._process_transcript(transcript)
        print(f" << {response}")

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
                if ratio > 0.8:
                    self._execute_command(command)
                    if command.get("responses"):
                        return command
                    return None
        return None
    
    def _get_exact_response(self, command):
        response = random.choice(command.get("responses"))
        return response
    
    def _execute_command(self, command) -> Literal["Ok"]:
        if not command:
            return "Command not found"

        if self.config.get("debug_mode") and self.start_time:
            end_time = time.perf_counter()
            print(f"Execution Time: {end_time - self.start_time}")
        print(f">>>{command.get('name')}<<<")

        command_response = "Ok"

        if self.config.get("debug_mode"):
            return command_response

        try:
            # TODO: pydirectinput only works on Windows. We need to find a better way to do this.
            # pylint:disable=import-outside-toplevel
            import pydirectinput

            if not command.get("modifier") and command.get("key"):
                if not command.get("hold"):
                    pydirectinput.press(command["key"])
                else:
                    pydirectinput.keyDown(command["key"])
                    time.sleep(command["hold"])
                    pydirectinput.keyUp(command["key"])
            elif command.get("modifier") and command.get("key"):
                pydirectinput.keyDown(command["modifier"])
                pydirectinput.press(command["key"])
                pydirectinput.keyUp(command["modifier"])
        except Exception:
            print("Keypresses are currently only supported on Windows.")
            return "Fail"  # this will currently always happen on non-Windows systems.

        return command_response

    # virtual methods:

    def _transcribe(self, audio_input_wav: str) -> str:
        if self.config.get("debug_mode"):
            self.start_time = time.perf_counter()

        return ""

    def _process_transcript(self, transcript: str) -> str:
        return ""

    def _finish_processing(self, text: str):
        pass
