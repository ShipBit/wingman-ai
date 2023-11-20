import time
import json
from difflib import SequenceMatcher
from exceptions import MissingApiKeyException
from services.printr import Printr
from services.open_ai import OpenAi
from wingmen.wingman import Wingman
from services.open_ai import OpenAi


class OpenAiWingman(Wingman):
    def __init__(self, name: str, config: dict[str, any]):
        super().__init__(name, config)

        if not self.config.get("openai").get("api_key"):
            raise MissingApiKeyException

        self.openai = OpenAi(self.config["openai"]["api_key"])
        self.messages = [
            {
                "role": "system",
                "content": self.config["openai"].get("context"),
            },
        ]

    def _transcribe(self, audio_input_wav: str) -> str:
        super()._transcribe(audio_input_wav)
        transcript = self.openai.transcribe(audio_input_wav)
        return transcript.text

    def _process_transcript(self, transcript: str) -> str:
        self.messages.append({"role": "user", "content": transcript})

        instant_activation_command = self._process_instant_activation_command(
            transcript
        )
        if instant_activation_command:
            self._play_audio(self._get_exact_response(instant_activation_command))
            return None

        completion = self.openai.ask(
            messages=self.messages,
            tools=self.__get_tools(),
        )

        response_message = completion.choices[0].message
        tool_calls = response_message.tool_calls
        content = response_message.content

        self.messages.append(response_message)

        if tool_calls:
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                if function_name == "execute_command":
                    command = self._get_command(function_args["command_name"])
                    function_response = self._execute_command(command)
                    if command.get("responses"):
                        self._play_audio(self._get_exact_response(command))

                if function_response:
                    self.messages.append(
                        {
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": function_response,
                        }
                    )

            second_response = self.openai.ask(
                messages=self.messages,
                model="gpt-3.5-turbo-1106",
            )
            second_content = second_response.choices[0].message.content
            self.messages.append(second_response.choices[0].message)
            if not command.get("responses"):
                self._play_audio(second_content)

        return content

    def _finish_processing(self, text: str):
        if text:
            self._play_audio(text)

    def _play_audio(self, text: str):
        response = self.openai.speak(text, self.config["openai"].get("tts_voice"))
        self.audio_player.stream_with_effects(
            response.content,
            self.config["openai"].get("features", {}).get("play_beep_on_receiving"),
            self.config["openai"].get("features", {}).get("enable_radio_sound_effect"),
        )

    def __get_tools(self) -> list[dict[str, any]]:
        # all commands which do not have to property instant_activation
        commands = [
            command["name"]
            for command in self.config["commands"]
            if not command.get("instant_activation")
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "description": "Executes a command",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command_name": {
                                "type": "string",
                                "description": "The command to execute",
                                "enum": commands,
                            },
                        },
                        "required": ["command_name"],
                    },
                },
            },
        ]
        return tools

    def __execute_command(self, command_name) -> str:
        print(f"{Printr.clr('❖ Executing command:', Printr.BLUE)} {command_name}")

        if self.config.get("debug_mode"):
            return "OK"

        # Retrieve the command from the config
        command = next(
            (
                item
                for item in self.config.get("commands", [])
                if item["name"] == command_name
            ),
            None,
        )

        if not command:
            return "Command not found"

        # Try to import pydirectinput and fall back to pyautogui if necessary
        try:
            import pydirectinput as module
        except ModuleNotFoundError:
            print(
                f"{Printr.clr('pydirectinput is only supported on Windows. Falling back to pyautogui which might not work in games.', Printr.YELLOW)}"
            )
            import pyautogui as module

        for entry in command.get("keys"):
            if entry.get("modifier"):
                module.keyDown(entry["modifier"])
            if entry.get("hold"):
                module.keyDown(entry["key"])
                time.sleep(entry["hold"])
                module.keyUp(entry["key"])
            else:
                module.press(entry["key"])
            if entry.get("modifier"):
                module.keyUp(entry["modifier"])
            if entry.get("wait"):
                time.sleep(entry["wait"])

        return "Ok"
