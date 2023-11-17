import json
from typing import Literal
from exceptions import MissingApiKeyException
from wingmen.wingman import Wingman
from services.open_ai import OpenAi

import pydirectinput
import time


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
        transcript = self.openai.transcribe(audio_input_wav)
        return transcript.text

    def _process_transcript(self, transcript: str) -> str:
        self.messages.append({"role": "user", "content": transcript})

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
                    function_response = self.__execute_command(**function_args)

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
            print(second_content)
            self.messages.append(second_response.choices[0].message)
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
                                "enum": [
                                    command["name"]
                                    for command in self.config["commands"]
                                ],
                            },
                        },
                        "required": ["command_name"],
                    },
                },
            },
        ]
        return tools

    def __execute_command(self, command_name) -> Literal["Ok"]:
        print(f">>>{command_name}<<<")

        if self.config.get("debug_mode"):
            return "OK"

        # Get the command from the list of commands
        command = next(
            (
                item
                for item in self.config.get("commands")
                if item["name"] == command_name
            ),
            None,
        )

        if not command:
            return "Command not found"

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

        return "Ok"
