import json
from typing import Mapping
import azure.cognitiveservices.speech as speechsdk
from openai import AzureOpenAI
from services.open_ai import AzureConfig, OpenAi
from services.printr import Printr
from services.secret_keeper import SecretKeeper
from wingmen.wingman import Wingman
from groq import Groq
import os

printr = Printr()


class OpenAiWingman(Wingman):
    """Our OpenAI Wingman base gives you everything you need to interact with OpenAI's various APIs.

    It transcribes speech to text using Whisper, uses the Completion API for conversation and implements the Tools API to execute functions.
    """

    def __init__(
        self,
        name: str,
        config: dict[str, any],
        secret_keeper: SecretKeeper,
        app_root_dir: str,
    ):
        super().__init__(
            name=name,
            config=config,
            secret_keeper=secret_keeper,
            app_root_dir=app_root_dir,
        )

        self.openai: OpenAi = None  # validate will set this
        """Our OpenAI API wrapper"""

        # every conversation starts with the "context" that the user has configured
        self.messages = [
            {"role": "system", "content": self.config["openai"].get("context")}
        ]
        """The conversation history that is used for the GPT calls"""

        self.last_transcript_locale = None
        self.elevenlabs_api_key = None
        self.azure_keys = {
            "tts": None,
            "whisper": None,
            "conversation": None,
            "summarize": None,
        }
        self.stt_provider = self.config["features"].get("stt_provider", None)
        self.conversation_provider = self.config["features"].get(
            "conversation_provider", None
        )
        self.summarize_provider = self.config["features"].get(
            "summarize_provider", None
        )

    def validate(self):
        errors = super().validate()
        openai_api_key = self.secret_keeper.retrieve(
            requester=self.name,
            key="openai",
            friendly_key_name="OpenAI API key",
            prompt_if_missing=True,
        )
        if not openai_api_key:
            errors.append(
                "Missing 'openai' API key. Please provide a valid key in the settings."
            )
        else:
            openai_organization = self.config["openai"].get("organization")
            openai_base_url = self.config["openai"].get("base_url")
            self.openai = OpenAi(openai_api_key, openai_organization, openai_base_url)

        if self.stt_provider == "groq":
            self.groq_key = self.secret_keeper.retrieve(
                requester=self.name,
                key="groq_stt",
                friendly_key_name="Groq STT API key",
                prompt_if_missing=True,
            )
            if not self.groq_key:
                errors.append("Missing 'groq_stt' key.")

        self.__validate_elevenlabs_config(errors)

        self.__validate_azure_config(errors)

        return errors

    def __validate_elevenlabs_config(self, errors):
        if self.tts_provider == "elevenlabs":
            self.elevenlabs_api_key = self.secret_keeper.retrieve(
                requester=self.name,
                key="elevenlabs",
                friendly_key_name="Elevenlabs API key",
                prompt_if_missing=True,
            )
            if not self.elevenlabs_api_key:
                errors.append(
                    "Missing 'elevenlabs' API key. Please provide a valid key in the settings or use another tts_provider."
                )
                return
            elevenlabs_settings = self.config.get("elevenlabs")
            if not elevenlabs_settings:
                errors.append(
                    "Missing 'elevenlabs' section in config. Please provide a valid config or change the TTS provider."
                )
                return
            if not elevenlabs_settings.get("model"):
                errors.append("Missing 'model' setting in 'elevenlabs' config.")
                return
            voice_settings = elevenlabs_settings.get("voice")
            if not voice_settings:
                errors.append(
                    "Missing 'voice' section in 'elevenlabs' config. Please provide a voice configuration as shown in our example config."
                )
                return
            if not voice_settings.get("id") and not voice_settings.get("name"):
                errors.append(
                    "Missing 'id' or 'name' in 'voice' section of 'elevenlabs' config. Please provide a valid name or id for the voice in your config."
                )

    def __validate_azure_config(self, errors):
        if (
            self.tts_provider == "azure"
            or self.stt_provider == "azure"
            or self.conversation_provider == "azure"
            or self.summarize_provider == "azure"
        ):
            azure_settings = self.config.get("azure")
            if not azure_settings:
                errors.append(
                    "Missing 'azure' section in config. Please provide a valid config."
                )
                return

        if self.tts_provider == "azure":
            self.azure_keys["tts"] = self.secret_keeper.retrieve(
                requester=self.name,
                key="azure_tts",
                friendly_key_name="Azure TTS API key",
                prompt_if_missing=True,
            )
            if not self.azure_keys["tts"]:
                errors.append(
                    "Missing 'azure' tts API key. Please provide a valid key in the settings."
                )
                return

        if self.stt_provider == "azure":
            self.azure_keys["whisper"] = self.secret_keeper.retrieve(
                requester=self.name,
                key="azure_whisper",
                friendly_key_name="Azure Whisper API key",
                prompt_if_missing=True,
            )
            if not self.azure_keys["whisper"]:
                errors.append(
                    "Missing 'azure' whisper API key. Please provide a valid key in the settings."
                )
                return

        if self.conversation_provider == "azure":
            self.azure_keys["conversation"] = self.secret_keeper.retrieve(
                requester=self.name,
                key="azure_conversation",
                friendly_key_name="Azure Conversation API key",
                prompt_if_missing=True,
            )
            if not self.azure_keys["conversation"]:
                errors.append(
                    "Missing 'azure' conversation API key. Please provide a valid key in the settings."
                )
                return

        if self.summarize_provider == "azure":
            self.azure_keys["summarize"] = self.secret_keeper.retrieve(
                requester=self.name,
                key="azure_summarize",
                friendly_key_name="Azure Summarize API key",
                prompt_if_missing=True,
            )
            if not self.azure_keys["summarize"]:
                errors.append(
                    "Missing 'azure' summarize API key. Please provide a valid key in the settings."
                )
                return

    async def _transcribe(self, audio_input_wav: str) -> tuple[str | None, str | None]:
        """Transcribes the recorded audio to text using the OpenAI Whisper API.

        Args:
            audio_input_wav (str): The path to the audio file that contains the user's speech. This is a recording of what you you said.

        Returns:
            str | None: The transcript of the audio file or None if the transcription failed.
        """
        response_format = "json"

        if self.stt_provider == "groq":
            model_name = self.config.get("groq", {}).get("whisper_model", "whisper-large-v3-turbo")
            client = Groq(api_key=self.groq_key)
            with open(audio_input_wav, "rb") as file:
                result = client.audio.transcriptions.create(
                    file=(audio_input_wav, file.read()),
                    model=model_name,
                    # ...any extra params...
                )
            return result.text if result else None, None

        azure_config = None
        stt_model = None
        if self.stt_provider == "azure":
            azure_config = self._get_azure_config("whisper")

        if self.stt_provider == "openai":
            stt_model = self.config["openai"].get("stt_model")

        transcript = self.openai.transcribe(
            audio_input_wav, model=stt_model, response_format=response_format, azure_config=azure_config
        )

        return transcript.text if transcript else None, None

    def _get_azure_config(self, section: str):
        azure_api_key = self.azure_keys[section]
        azure_config = AzureConfig(
            api_key=azure_api_key,
            api_base_url=self.config["azure"]
            .get(section, {})
            .get("api_base_url", None),
            api_version=self.config["azure"].get(section, {}).get("api_version", None),
            deployment_name=self.config["azure"]
            .get(section, {})
            .get("deployment_name", None),
        )

        return azure_config

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
        self.last_transcript_locale = locale

        instant_response = self._try_instant_activation(transcript)
        if instant_response:
            return instant_response, instant_response
        
        # only if it is not an instant command, we add the user message to the history
        self._add_user_message(transcript)
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
        remember_messages = self.config.get("features", {}).get(
            "remember_messages", None
        )

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
                tags="warn",
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
                f"   Calling GPT with {(len(self.messages) - 1)} messages (excluding context)",
                tags="info",
            )

        azure_config = None
        if self.conversation_provider == "azure":
            azure_config = self._get_azure_config("conversation")

        return self.openai.ask(
            messages=self.messages,
            tools=self._build_tools(),
            model=self.config["openai"].get("conversation_model"),
            azure_config=azure_config,
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

            # Don't use self._add_user_message_to_history here because we never want to skip this because of history limitions
            self.messages.append(msg)

        return instant_response

    def _summarize_function_calls(self):
        """Summarizes the function call responses using the GPT model specified for summarization in the configuration.

        Returns:
            The content of the GPT response to the function call summaries.
        """
        azure_config = None
        if self.summarize_provider == "azure":
            azure_config = self._get_azure_config("summarize")

        summarize_model = self.config["openai"].get("summarize_model")
        summarize_response = self.openai.ask(
            messages=self.messages,
            model=summarize_model,
            azure_config=azure_config,
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
        Uses an OpenAI function call to execute a command. If it's an instant activation_command, one if its reponses will be played.

        Args:
            function_name (str): The name of the function to be executed.
            function_args (dict[str, any]): The arguments to pass to the function being executed.

        Returns:
            A tuple containing two elements:
            - function_response (str): The text response or result obtained after executing the function.
            - instant_response (str): An immediate response or action to be taken, if any (e.g., play audio).
        """
        function_response = ""
        instant_reponse = ""
        if function_name == "execute_command":
            # get the command based on the argument passed by GPT
            command = self._get_command(function_args["command_name"])
            # execute the command
            function_response = self._execute_command(command)
            # if the command has responses, we have to play one of them
            if command and command.get("responses"):
                instant_reponse = self._select_command_response(command)
                await self._play_to_user(instant_reponse)

        return function_response, instant_reponse

    async def _play_to_user(self, text: str):
        """Plays audio to the user using the configured TTS Provider (default: OpenAI TTS).
        Also adds sound effects if enabled in the configuration.

        Args:
            text (str): The text to play as audio.
        """
        # avoid playing anything, if the response is OK or if no text is provided
        if not text or text == "Ok":
            return

        if self.tts_provider == "azure":
            self._play_with_azure(text)
        else:
            self._play_with_openai(text)

    def _play_with_openai(self, text):
        response = self.openai.speak(text, self.config["openai"].get("tts_model"), self.config["openai"].get("tts_voice"))
        if response is not None:
            self.audio_player.stream_with_effects(response.content, self.config)

    def _play_with_azure(self, text):
        azure_config = self._get_azure_config("tts")
        voice = self.config["azure"].get("tts",{}).get("voice", "nova")
        client = AzureOpenAI(
                api_key=azure_config.api_key,
                azure_endpoint=azure_config.api_base_url,
                api_version=azure_config.api_version,
                azure_deployment=azure_config.deployment_name,
            )
        
        response = client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text
        )

        if response is not None:
            self.audio_player.stream_with_effects(response.content, self.config)

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
            command["name"]
            for command in self.config.get("commands", [])
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

    def _get_message_role(self, message):
        """Helper method to get the role of the message regardless of its type."""
        if isinstance(message, Mapping):
            return message.get("role")
        elif hasattr(message, "role"):
            return message.role
        else:
            raise TypeError(
                f"Message is neither a mapping nor has a 'role' attribute: {message}"
            )


