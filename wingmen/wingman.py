import json
from importlib import import_module
from typing import Literal
from services.audio_player import AudioPlayer
from services.open_ai import OpenAi


class Wingman:
    def __init__(self, name: str, config: dict[str, any]):
        if config:
            self.config = config
            self.name = name
            self.openai = OpenAi(self.config["openai"]["api_key"])
            self.audio_player = AudioPlayer()
            self.messages = [
                {
                    "role": "system",
                    "content": self.config["system_prompt"],
                },
            ]

    @staticmethod
    def create_dynamically(module_path, class_name, **kwargs):
        module = import_module(module_path)
        DerivedWingmanClass = getattr(module, class_name)
        instance = DerivedWingmanClass(**kwargs)
        return instance

    def get_record_key(self) -> str:
        return self.config.get("record_key", None)

    def get_tools(self) -> list[dict[str, any]]:
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

    def process(self, audio_input_wav: str):
        transcript = self.openai.transcribe(audio_input_wav)
        print(f" >> {transcript.text}")

        self.messages.append(
            {
                "role": "user",
                "content": transcript.text,
            }
        )

        completion = self.openai.ask(
            messages=self.messages,
            tools=self.get_tools(),
        )

        response_message = completion.choices[0].message
        tool_calls = response_message.tool_calls
        content = response_message.content
        print(f" << {content}")

        self.messages.append(response_message)

        if tool_calls:
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                if function_name == "execute_command":
                    function_response = self.execute_command(**function_args)

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
            self.play_audio(second_content)

        if content:
            self.play_audio(content)

    def play_audio(self, text: str):
        response = self.openai.speak(text)
        self.audio_player.stream(response.content)

    def execute_command(self, command_name) -> Literal["Ok"]:
        print(f">>>{command_name}<<<")
        return "Ok"
