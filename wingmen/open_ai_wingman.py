import json
from typing import Mapping
from api.interface import WingmanConfig, WingmanInitializationError
from api.enums import (
    LogType,
    OpenAiModel,
    TtsProvider,
    SttProvider,
    ConversationProvider,
    SummarizeProvider,
)
from providers.edge import Edge
from providers.elevenlabs import ElevenLabs
from providers.open_ai import OpenAi, OpenAiAzure
from services.printr import Printr
from wingmen.wingman import Wingman

printr = Printr()


class OpenAiWingman(Wingman):
    """Our OpenAI Wingman base gives you everything you need to interact with OpenAI's various APIs.

    It transcribes speech to text using Whisper, uses the Completion API for conversation and implements the Tools API to execute functions.
    """

    AZURE_SERVICES = {
        "tts": TtsProvider.AZURE,
        "whisper": [SttProvider.AZURE, SttProvider.AZURE_SPEECH],
        "conversation": ConversationProvider.AZURE,
        "summarize": SummarizeProvider.AZURE,
    }

    def __init__(
        self,
        name: str,
        config: WingmanConfig,
        app_root_dir: str,
    ):
        super().__init__(
            name=name,
            config=config,
            app_root_dir=app_root_dir,
        )

        self.edge_tts = Edge(app_root_dir)
        self.openai: OpenAi = None  # validate will set this
        self.openai_azure: OpenAiAzure = None  # validate will set this
        self.elevenlabs: ElevenLabs = None  # validate will set this

        # every conversation starts with the "context" that the user has configured
        self.messages = (
            [{"role": "system", "content": self.config.openai.context}]
            if self.config.openai.context
            else []
        )
        """The conversation history that is used for the GPT calls"""

        self.azure_api_keys = {key: None for key in self.AZURE_SERVICES}

    async def validate(self):
        errors = await super().validate()

        if self.uses_provider("openai"):
            await self.validate_and_set_openai(errors)

        if self.uses_provider("elevenlabs"):
            await self.validate_and_set_elevenlabs(errors)

        await self.validate_and_set_azure(errors)

        return errors

    def uses_provider(self, provider_type):
        if provider_type == "openai":
            return any(
                [
                    self.tts_provider == TtsProvider.OPENAI,
                    self.stt_provider == SttProvider.OPENAI,
                    self.conversation_provider == ConversationProvider.OPENAI,
                    self.summarize_provider == SummarizeProvider.OPENAI,
                ]
            )
        elif provider_type == "azure":
            return any(
                [
                    self.tts_provider == TtsProvider.AZURE,
                    self.stt_provider == SttProvider.AZURE,
                    self.stt_provider == SttProvider.AZURE_SPEECH,
                    self.conversation_provider == ConversationProvider.AZURE,
                    self.summarize_provider == SummarizeProvider.AZURE,
                ]
            )
        elif provider_type == "edge_tts":
            return self.tts_provider == TtsProvider.EDGE_TTS
        elif provider_type == "elevenlabs":
            return self.tts_provider == TtsProvider.ELEVENLABS
        return False

    async def validate_and_set_openai(self, errors: list[WingmanInitializationError]):
        api_key = await self.retrieve_secret("openai", errors)
        if api_key:
            self.openai = OpenAi(
                api_key=api_key,
                organization=self.config.openai.organization,
                base_url=self.config.openai.base_url,
            )

    async def validate_and_set_elevenlabs(
        self, errors: list[WingmanInitializationError]
    ):
        api_key = await self.retrieve_secret("elevenlabs", errors)
        if api_key:
            self.elevenlabs = ElevenLabs(
                api_key=api_key,
                wingman_name=self.name,
            )
            self.elevenlabs.validate_config(
                config=self.config.elevenlabs, errors=errors
            )

    async def validate_and_set_azure(self, errors: list[WingmanInitializationError]):
        for key_type in self.AZURE_SERVICES:
            if self.uses_provider("azure"):
                api_key = await self.retrieve_secret(f"azure_{key_type}", errors)
                if api_key:
                    self.azure_api_keys[key_type] = api_key
        if len(errors) == 0:
            self.openai_azure = OpenAiAzure()

    async def _transcribe(self, audio_input_wav: str) -> tuple[str | None, str | None]:
        """Transcribes the recorded audio to text using the OpenAI Whisper API.

        Args:
            audio_input_wav (str): The path to the audio file that contains the user's speech. This is a recording of what you you said.

        Returns:
            str | None: The transcript of the audio file or None if the transcription failed.
        """
        response_format = (
            "verbose_json"  # verbose_json will return the language detected in the transcript.
            if self.tts_provider == TtsProvider.EDGE_TTS
            and self.config.edge_tts.detect_language
            else "json"
        )

        if self.stt_provider == SttProvider.AZURE:
            transcript = self.openai_azure.transcribe(
                filename=audio_input_wav,
                api_key=self.azure_api_keys["whisper"],
                config=self.config.azure.whisper,
                response_format=response_format,
            )
        elif self.stt_provider == SttProvider.AZURE_SPEECH:
            transcript = self.openai_azure.transcribe_with_azure(
                filename=audio_input_wav,
                api_key=self.azure_api_keys["tts"],
                config=self.config.azure.tts,
            )
        else:
            transcript = self.openai.transcribe(
                filename=audio_input_wav, response_format=response_format
            )

        locale = None
        # skip the GPT call if we didn't change the language
        if (
            response_format == "verbose_json"
            and transcript
            and transcript.language != self.edge_tts.last_transcript_locale
        ):
            printr.print(
                f"   EdgeTTS detected language '{transcript.language}'.", color=LogType.INFO  # type: ignore
            )
            locale = self.__ask_gpt_for_locale(transcript.language)

        return transcript.text if transcript else None, locale

    async def _get_response_for_transcript(
        self, transcript: str, locale: str | None
    ) -> tuple[str, str]:
        """Gets the response for a given transcript.

        This function interprets the transcript, runs instant commands if triggered,
        calls the OpenAI API when needed, processes any tool calls, and generates the final response.

        Args:
            transcript (str): The user's spoken text transcribed.

        Returns:
            A tuple of strings representing the response to a function call and an instant response.
        """
        self.edge_tts.last_transcript_locale = locale
        self._add_user_message(transcript)

        instant_response = self._try_instant_activation(transcript)
        if instant_response:
            return instant_response, instant_response

        completion = self._gpt_call()

        if completion is None:
            return None, None

        response_message, tool_calls = self._process_completion(completion)

        # do not tamper with this message as it will lead to 400 errors!
        self.messages.append(response_message)

        if tool_calls:
            instant_response = await self._handle_tool_calls(tool_calls)
            if instant_response:
                return None, instant_response

            summarize_response = self._summarize_function_calls()
            return self._finalize_response(str(summarize_response))

        return response_message.content, response_message.content

    def _add_user_message(self, content: str):
        """Shortens the conversation history if needed and adds a user message to it.

        Args:
            content (str): The message content to add.
            role (str): The role of the message sender ("user", "assistant", "function" or "tool").
            tool_call_id (Optional[str]): The identifier for the tool call, if applicable.
            name (Optional[str]): The name of the function associated with the tool call, if applicable.
        """
        msg = {"role": "user", "content": content}
        self._cleanup_conversation_history()
        self.messages.append(msg)

    def _cleanup_conversation_history(self):
        """Cleans up the conversation history by removing messages that are too old."""
        remember_messages = self.config.features.remember_messages

        if remember_messages is None or len(self.messages) == 0:
            return 0  # Configuration not set, nothing to delete.

        # The system message aka `context` does not count
        context_offset = (
            1 if self.messages and self.messages[0]["role"] == "system" else 0
        )

        # Find the cutoff index where to end deletion, making sure to only count 'user' messages towards the limit starting with newest messages.
        cutoff_index = len(self.messages) - 1
        user_message_count = 0
        for message in reversed(self.messages):
            if self.__get_message_role(message) == "user":
                user_message_count += 1
                if user_message_count == remember_messages:
                    break  # Found the cutoff point.
            cutoff_index -= 1

        # If messages below the keep limit, don't delete anything.
        if user_message_count < remember_messages:
            return 0

        total_deleted_messages = cutoff_index - context_offset  # Messages to delete.

        # Remove the messages before the cutoff index, exclusive of the system message.
        del self.messages[context_offset:cutoff_index]

        # Optional debugging printout.
        if self.debug and total_deleted_messages > 0:
            printr.print(
                f"Deleted {total_deleted_messages} messages from the conversation history.",
                color=LogType.WARNING,
            )

        return total_deleted_messages

    def reset_conversation_history(self):
        """Resets the conversation history by removing all messages except for the initial system message."""
        del self.messages[1:]

    def _try_instant_activation(self, transcript: str) -> str:
        """Tries to execute an instant activation command if present in the transcript.

        Args:
            transcript (str): The transcript to check for an instant activation command.

        Returns:
            str: The response to the instant command or None if no such command was found.
        """
        command = self._execute_instant_activation_command(transcript)
        if command:
            response = self._select_command_response(command)
            return response
        return None

    def _gpt_call(self):
        """Makes the primary GPT call with the conversation history and tools enabled.

        Returns:
            The GPT completion object or None if the call fails.
        """
        if self.debug:
            printr.print(
                f"Calling GPT with {(len(self.messages) - 1)} messages (excluding context)",
                color=LogType.INFO,
            )

        if self.conversation_provider == ConversationProvider.AZURE:
            return self.openai_azure.ask(
                messages=self.messages,
                api_key=self.azure_api_keys["conversation"],
                config=self.config.azure.conversation,
                tools=self._build_tools(),
                model=self.config.openai.conversation_model,
            )

        return self.openai.ask(
            messages=self.messages,
            tools=self._build_tools(),
            model=self.config.openai.conversation_model,
        )

    def _process_completion(self, completion):
        """Processes the completion returned by the GPT call.

        Args:
            completion: The completion object from an OpenAI call.

        Returns:
            A tuple containing the message response and tool calls from the completion.
        """
        response_message = completion.choices[0].message

        content = response_message.content
        if content is None:
            response_message.content = ""

        return response_message, response_message.tool_calls

    async def _handle_tool_calls(self, tool_calls):
        """Processes all the tool calls identified in the response message.

        Args:
            tool_calls: The list of tool calls to process.

        Returns:
            str: The immediate response from processed tool calls or None if there are no immediate responses.
        """
        instant_response = None
        function_response = ""

        for tool_call in tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            (
                function_response,
                instant_response,
            ) = await self._execute_command_by_function_call(
                function_name, function_args
            )

            msg = {"role": "tool", "content": function_response}
            if tool_call.id is not None:
                msg["tool_call_id"] = tool_call.id
            if function_name is not None:
                msg["name"] = function_name

            # Don't use self._add_user_message_to_history here because we never want to skip this because of history limitations
            self.messages.append(msg)

        return instant_response

    def _summarize_function_calls(self):
        """Summarizes the function call responses using the GPT model specified for summarization in the configuration.

        Returns:
            The content of the GPT response to the function call summaries.
        """

        if self.summarize_provider == SummarizeProvider.AZURE:
            summarize_response = self.openai_azure.ask(
                messages=self.messages,
                api_key=self.azure_api_keys["summarize"],
                config=self.config.azure.summarize,
                model=self.config.openai.summarize_model,
            )
        else:
            summarize_response = self.openai.ask(
                messages=self.messages,
                model=self.config.openai.summarize_model,
            )

        if summarize_response is None:
            return None

        # do not tamper with this message as it will lead to 400 errors!
        message = summarize_response.choices[0].message
        self.messages.append(message)
        return message.content

    def _finalize_response(self, summarize_response: str) -> tuple[str, str]:
        """Finalizes the response based on the call of the second (summarize) GPT call.

        Args:
            summarize_response (str): The response content from the second GPT call.

        Returns:
            A tuple containing the final response to the user.
        """
        if summarize_response is None:
            return self.messages[-1]["content"], self.messages[-1]["content"]
        return summarize_response, summarize_response

    async def _execute_command_by_function_call(
        self, function_name: str, function_args: dict[str, any]
    ) -> tuple[str, str]:
        """
        Uses an OpenAI function call to execute a command. If it's an instant activation_command, one if its responses will be played.

        Args:
            function_name (str): The name of the function to be executed.
            function_args (dict[str, any]): The arguments to pass to the function being executed.

        Returns:
            A tuple containing two elements:
            - function_response (str): The text response or result obtained after executing the function.
            - instant_response (str): An immediate response or action to be taken, if any (e.g., play audio).
        """
        function_response = ""
        instant_response = ""
        if function_name == "execute_command":
            # get the command based on the argument passed by GPT
            command = self._get_command(function_args["command_name"])
            # execute the command
            function_response = self._execute_command(command)
            # if the command has responses, we have to play one of them
            if command and command.get("responses"):
                instant_response = self._select_command_response(command)
                await self._play_to_user(instant_response)

        return function_response, instant_response

    async def _play_to_user(self, text: str):
        """Plays audio to the user using the configured TTS Provider (default: OpenAI TTS).
        Also adds sound effects if enabled in the configuration.

        Args:
            text (str): The text to play as audio.
        """

        if self.tts_provider == TtsProvider.EDGE_TTS:
            await self.edge_tts.play_audio(
                text, self.config.edge_tts, self.config.sound
            )
        elif self.tts_provider == TtsProvider.ELEVENLABS:
            self.elevenlabs.play_audio(text, self.config.elevenlabs, self.config.sound)
        elif self.tts_provider == TtsProvider.AZURE:
            self.openai_azure.play_audio(
                text=text,
                api_key=self.azure_api_keys["tts"],
                config=self.config.azure.tts,
                sound_config=self.config.sound,
            )
        else:
            self.openai.play_audio(
                text=text,
                voice=self.config.openai.tts_voice,
                sound_config=self.config.sound,
            )

    def _execute_command(self, command: dict) -> str:
        """Does what Wingman base does, but always returns "Ok" instead of a command response.
        Otherwise the AI will try to respond to the command and generate a "duplicate" response for instant_activation commands.
        """
        super()._execute_command(command)
        return "Ok"

    def _build_tools(self) -> list[dict]:
        """
        Builds a tool for each command that is not instant_activation.

        Returns:
            list[dict]: A list of tool descriptors in OpenAI format.
        """
        commands = [
            command.name
            for command in self.config.commands
            if not command.instant_activation
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

    def __ask_gpt_for_locale(self, language: str) -> str:
        """OpenAI TTS returns a natural language name for the language of the transcript, e.g. "german" or "english".
        This method uses ChatGPT to find the corresponding locale, e.g. "de-DE" or "en-EN".

        Args:
            language (str): The natural, lowercase language name returned by OpenAI TTS. Thank you for that btw.. WTF OpenAI?
        """

        messages = (
            [
                {
                    "content": """
                        I'll say a natural language name in lowercase and you'll just return the IETF country code / locale for this language.
                        Your answer always has exactly 2 lowercase letters, a dash, then two more letters in uppercase.
                        If I say "german", you answer with "de-DE". If I say "russian", you answer with "ru-RU".
                        If it's ambiguous and you don't know which locale to pick ("en-GB" vs "en-US"), you pick the most commonly used one.
                        You only answer with valid country codes according to most common standards.
                        If you can't, you respond with "None".
                    """,
                    "role": "system",
                },
                {
                    "content": language,
                    "role": "user",
                },
            ],
        )
        model = OpenAiModel.GPT_35_TURBO_1106

        response = (
            self.openai.ask(model=model.value, messages=messages)
            if self.summarize_provider == ConversationProvider.OPENAI
            else self.openai_azure.ask(
                model=model.value,
                messages=messages,
                api_key=self.azure_api_keys["summarize"],
                config=self.config.azure.summarize,
            )
        )

        answer = response.choices[0].message.content
        if answer == "None":
            return None
        printr.print(
            f"ChatGPT says this language maps to locale '{answer}'.",
            color=LogType.INFO,
        )
        return answer

    def __get_message_role(self, message):
        """Helper method to get the role of the message regardless of its type."""
        if isinstance(message, Mapping):
            return message.get("role")
        elif hasattr(message, "role"):
            return message.role
        else:
            raise TypeError(
                f"Message is neither a mapping nor has a 'role' attribute: {message}"
            )
