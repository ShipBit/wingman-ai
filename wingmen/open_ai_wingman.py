import json
from exceptions import MissingApiKeyException
from services.open_ai import OpenAi
from services.printr import Printr
from wingmen.wingman import Wingman


class OpenAiWingman(Wingman):
    def __init__(self, name: str, config: dict[str, any]):
        super().__init__(name, config)

        if not self.config.get("openai").get("api_key"):
            raise MissingApiKeyException

        api_key = self.config["openai"]["api_key"]
        if api_key == "YOUR_API_KEY":
            raise MissingApiKeyException

        self.openai = OpenAi(api_key)
        self.messages = [
            {
                "role": "system",
                "content": self.config["openai"].get("context"),
            },
        ]

    def _transcribe(self, audio_input_wav: str) -> str:
        super()._transcribe(audio_input_wav)
        transcript = self.openai.transcribe(audio_input_wav)
        return transcript.text if transcript else None

    def _process_transcript(self, transcript: str) -> str:
        self.messages.append({"role": "user", "content": transcript})

        # Check if the transcript is an instant activation command.
        # If so, it will be executed immediately and no further processing is needed.
        instant_activation_command = self._process_instant_activation_command(
            transcript
        )
        if instant_activation_command:
            self._play_audio(self._get_exact_response(instant_activation_command))
            return None

        conversation_model = self.config["openai"].get("conversation_model")

        # This is the main GPT call including tools / functions
        completion = self.openai.ask(
            messages=self.messages,
            tools=self.__get_tools(),
            model=conversation_model,
        )

        if completion is None:
            return None

        response_message = completion.choices[0].message
        tool_calls = response_message.tool_calls
        content = response_message.content

        # add the response message to the messages list so that it can be used in the next GPT call
        self.messages.append(response_message)

        # if there are tool calls, we have to process them
        if tool_calls:
            for tool_call in tool_calls:  # there could be multiple tool calls at once
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                function_response = ""
                if function_name == "execute_command":
                    # get the command based on the argument passed by GPT
                    command = self._get_command(function_args["command_name"])
                    # execute the command
                    function_response = self._execute_command(command)
                    # if the command has responses, we have to play one of them
                    if command.get("responses"):
                        self._play_audio(self._get_exact_response(command))

                # add the response of the function to the messages list so that it can be used in the next GPT call
                self.messages.append(
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": function_response,
                    }
                )

            # Make a second GPT call to process the function responses.
            # This basically summarizes the function responses.
            # We don't need GPT-4-Turbo for this, GPT-3.5 is enough
            summarize_model = self.config["openai"].get("summarize_model")
            second_response = self.openai.ask(
                messages=self.messages,
                model=summarize_model,
            )

            if second_response is None:
                return content

            second_content = second_response.choices[0].message.content
            self.messages.append(second_response.choices[0].message)
            return second_content

        return content

    def _finish_processing(self, text: str):
        if text:
            self._play_audio(text)

    def _play_audio(self, text: str):
        response = self.openai.speak(text, self.config["openai"].get("tts_voice"))
        if response is not None:
            self.audio_player.stream_with_effects(
                response.content,
                self.config.get("features", {}).get("play_beep_on_receiving"),
                self.config.get("features", {}).get("enable_radio_sound_effect"),
                self.config.get("features", {}).get("enable_robot_sound_effect")
            )

    def __get_tools(self) -> list[dict[str, any]]:
        # all commands that are NOT instant_activation
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
