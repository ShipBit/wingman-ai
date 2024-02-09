import json
import time
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
from providers.xvasynth import XVASynth
from providers.whispercpp import Whispercpp
from services.audio_player import AudioPlayer
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
        audio_player: AudioPlayer,
    ):
        super().__init__(
            name=name,
            config=config,
            audio_player=audio_player,
        )

        self.edge_tts = Edge()

        # validate will set these:
        self.openai: OpenAi = None
        self.openai_azure: OpenAiAzure = None
        self.elevenlabs: ElevenLabs = None
        self.xvasynth: XVASynth = None
        self.whispercpp: Whispercpp = None

        self.pending_tool_calls = []
        self.last_gpt_call = None

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

        if self.uses_provider("xvasynth"):
            await self.validate_and_set_xvasynth(errors)

        if self.uses_provider("whispercpp"):
            await self.validate_and_set_whispercpp(errors)

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
        elif provider_type == "xvasynth":
            return self.tts_provider == TtsProvider.XVASYNTH
        elif provider_type == "whispercpp":
            return self.stt_provider == SttProvider.WHISPERCPP
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

    async def validate_and_set_xvasynth(self, errors: list[WingmanInitializationError]):
        self.xvasynth = XVASynth(
            wingman_name=self.name,
        )
        self.xvasynth.validate_config(config=self.config.xvasynth, errors=errors)

    async def validate_and_set_whispercpp(
        self, errors: list[WingmanInitializationError]
    ):
        self.whispercpp = Whispercpp(
            wingman_name=self.name,
        )
        self.whispercpp.validate_config(config=self.config.whispercpp, errors=errors)

    async def _transcribe(self, audio_input_wav: str) -> str | None:
        """Transcribes the recorded audio to text using the OpenAI Whisper API.

        Args:
            audio_input_wav (str): The path to the audio file that contains the user's speech. This is a recording of what you you said.

        Returns:
            str | None: The transcript of the audio file or None if the transcription failed.
        """

        if self.stt_provider == SttProvider.AZURE:
            transcript = self.openai_azure.transcribe(
                filename=audio_input_wav,
                api_key=self.azure_api_keys["whisper"],
                config=self.config.azure.whisper,
            )
        elif self.stt_provider == SttProvider.AZURE_SPEECH:
            transcript = self.openai_azure.transcribe_with_azure(
                filename=audio_input_wav,
                api_key=self.azure_api_keys["tts"],
                config=self.config.azure.stt,
            )
        elif self.stt_provider == SttProvider.WHISPERCPP:
            transcript = self.whispercpp.transcribe(
                filename=audio_input_wav, config=self.config.whispercpp
            )
        else:
            transcript = self.openai.transcribe(filename=audio_input_wav)

        return transcript.text if transcript else None

    async def _get_response_for_transcript(self, transcript: str) -> tuple[str, str]:
        """Gets the response for a given transcript.

        This function interprets the transcript, runs instant commands if triggered,
        calls the OpenAI API when needed, processes any tool calls, and generates the final response.

        Args:
            transcript (str): The user's spoken text transcribed.

        Returns:
            A tuple of strings representing the response to a function call and an instant response.
        """
        await self._add_user_message(transcript)

        instant_response, instant_command_executed = await self._try_instant_activation(
            transcript
        )
        if instant_response:
            self._add_assistant_message(instant_response)
            return instant_response, instant_response

        # make a GPT call with the conversation history
        # if an instant command got executed, prevent tool calls to avoid duplicate executions
        completion = await self._gpt_call(instant_command_executed is False)

        if completion is None:
            return None, None

        response_message, tool_calls = await self._process_completion(completion)

        # add message and dummy tool responses to conversation history
        self._add_gpt_response(response_message, tool_calls)

        if tool_calls:
            instant_response = await self._handle_tool_calls(tool_calls)
            if instant_response:
                return None, instant_response

            summarize_response = self._summarize_function_calls()
            return self._finalize_response(str(summarize_response))

        return response_message.content, response_message.content

    async def _fix_tool_calls(self, tool_calls):
        """Fixes tool calls that have a command name as function name.

        Args:
            tool_calls (list): The tool calls to fix.

        Returns:
            list: The fixed tool calls.
        """
        if tool_calls and len(tool_calls) > 0:
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)

                # try to resolve function name to a command name
                if len(function_args) == 0 and self._get_command(function_name):
                    function_args["command_name"] = function_name
                    function_name = "execute_command"

                    # update the tool call
                    tool_call.function.name = function_name
                    tool_call.function.arguments = json.dumps(function_args)

                    if self.debug:
                        await printr.print_async(
                            "Applied command call fix.", color=LogType.WARNING
                        )

        return tool_calls

    def _add_gpt_response(self, message, tool_calls) -> None:
        """Adds a message from GPT to the conversation history as well as adding dummy tool responses for any tool calls.

        Args:
            message (dict): The message to add.
            tool_calls (list): The tool calls associated with the message.
        """
        # do not tamper with this message as it will lead to 400 errors!
        self.messages.append(message)

        # adding dummy tool responses to prevent corrupted message history on parallel requests
        if tool_calls:
            for tool_call in tool_calls:
                if not tool_call.id:
                    continue
                # adding a dummy tool response to get updated later
                self._add_tool_response(tool_call, "Loading..", False)

    def _add_tool_response(self, tool_call, response: str, completed: bool = True):
        """Adds a tool response to the conversation history.

        Args:
            tool_call (dict): The tool call to add the dummy response for.
        """
        msg = {"role": "tool", "content": response}
        if tool_call.id is not None:
            msg["tool_call_id"] = tool_call.id
        if tool_call.function.name is not None:
            msg["name"] = tool_call.function.name
        self.messages.append(msg)

        if tool_call.id and not completed:
            self.pending_tool_calls.append(tool_call.id)

    async def _update_tool_response(self, tool_call_id, response) -> bool:
        """Updates a tool response in the conversation history. This also moves the message to the end of the history if all tool responses are given.

        Args:
            tool_call_id (str): The identifier of the tool call to update the response for.
            response (str): The new response to set.

        Returns:
            bool: True if the response was updated, False if the tool call was not found.
        """
        if not tool_call_id:
            return False

        completed = False
        index = len(self.messages)

        # go through message history to find and update the tool call
        for message in reversed(self.messages):
            index -= 1
            if (
                self.__get_message_role(message) == "tool"
                and message.get("tool_call_id") == tool_call_id
            ):
                message["content"] = str(response)
                if tool_call_id in self.pending_tool_calls:
                    self.pending_tool_calls.remove(tool_call_id)
                break
        if not index:
            return False

        # find the assistant message that triggered the tool call
        for message in reversed(self.messages[:index]):
            index -= 1
            if self.__get_message_role(message) == "assistant":
                break

        # check if all tool calls are completed
        completed = True
        for tool_call in self.messages[index].tool_calls:
            if tool_call.id in self.pending_tool_calls:
                completed = False
                break
        if not completed:
            return True

        # find the first user message(s) that triggered this assistant message
        index -= 1  # skip the assistant message
        for message in reversed(self.messages[:index]):
            index -= 1
            if self.__get_message_role(message) != "user":
                index += 1
                break

        # built message block to move
        start_index = index
        end_index = start_index
        reached_tool_call = False
        for message in self.messages[start_index:]:
            if not reached_tool_call and self.__get_message_role(message) == "tool":
                reached_tool_call = True
            if reached_tool_call and self.__get_message_role(message) == "user":
                end_index -= 1
                break
            end_index += 1
        if end_index == len(self.messages):
            end_index -= 1  # loop ended at the end of the message history, so we have to go back one index
        message_block = self.messages[start_index : end_index + 1]

        # check if the message block is already at the end
        if end_index == len(self.messages) - 1:
            return True

        # move message block to the end
        del self.messages[start_index : end_index + 1]
        self.messages.extend(message_block)

        if self.debug:
            await printr.print_async(
                "Moved message block to the end.", color=LogType.INFO
            )

        return True

    async def _add_user_message(self, content: str):
        """Shortens the conversation history if needed and adds a user message to it.

        Args:
            content (str): The message content to add.
            role (str): The role of the message sender ("user", "assistant", "function" or "tool").
            tool_call_id (Optional[str]): The identifier for the tool call, if applicable.
            name (Optional[str]): The name of the function associated with the tool call, if applicable.
        """
        msg = {"role": "user", "content": content}
        await self._cleanup_conversation_history()
        self.messages.append(msg)

    def _add_assistant_message(self, content: str):
        """Adds an assistant message to the conversation history.

        Args:
            content (str): The message content to add.
        """
        msg = {"role": "assistant", "content": content}
        self.messages.append(msg)

    async def _cleanup_conversation_history(self):
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

        # Remove the pending tool calls that are no longer needed.
        for mesage in self.messages[context_offset:cutoff_index]:
            if (
                self.__get_message_role(mesage) == "tool"
                and mesage.get("tool_call_id") in self.pending_tool_calls
            ):
                self.pending_tool_calls.remove(mesage.get("tool_call_id"))
                if self.debug:
                    await printr.print_async(
                        f"Removing pending tool call {mesage.get('tool_call_id')} due to message history clean up.",
                        color=LogType.WARNING,
                    )

        # Remove the messages before the cutoff index, exclusive of the system message.
        del self.messages[context_offset:cutoff_index]

        # Optional debugging printout.
        if self.debug and total_deleted_messages > 0:
            await printr.print_async(
                f"Deleted {total_deleted_messages} messages from the conversation history.",
                color=LogType.WARNING,
            )

        return total_deleted_messages

    def reset_conversation_history(self):
        """Resets the conversation history by removing all messages except for the initial system message."""
        del self.messages[1:]

    async def _try_instant_activation(self, transcript: str) -> str:
        """Tries to execute an instant activation command if present in the transcript.

        Args:
            transcript (str): The transcript to check for an instant activation command.

        Returns:
            tuple[str, bool]: A tuple containing the response to the instant command and a boolean indicating whether an instant command was executed.
        """
        command = await self._execute_instant_activation_command(transcript)
        if command:
            if command.responses:
                response = self._select_command_response(command)
                return response, True
            return None, True
        return None, False

    async def _gpt_call(self, allow_tool_calls: bool = True):
        """Makes the primary GPT call with the conversation history and tools enabled.

        Returns:
            The GPT completion object or None if the call fails.
        """
        if self.debug:
            await printr.print_async(
                f"Calling GPT with {(len(self.messages) - 1)} messages (excluding context)",
                color=LogType.INFO,
            )

        # save request time for later comparison
        thiscall = time.time()
        self.last_gpt_call = thiscall

        # build tools
        if allow_tool_calls:
            tools = self._build_tools()
        else:
            tools = None

        if self.conversation_provider == ConversationProvider.AZURE:
            completion = self.openai_azure.ask(
                messages=self.messages,
                api_key=self.azure_api_keys["conversation"],
                config=self.config.azure.conversation,
                tools=tools,
                model=self.config.openai.conversation_model,
            )
        else:
            completion = self.openai.ask(
                messages=self.messages,
                tools=tools,
                model=self.config.openai.conversation_model,
            )

        # if request isnt most recent, ignore the response
        if self.last_gpt_call != thiscall:
            await printr.print_async(
                "GPT call was cancelled due to a new call.", color=LogType.WARNING
            )
            return None

        return completion

    async def _process_completion(self, completion):
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

        # temporary fix for tool calls that have a command name as function name
        if response_message.tool_calls:
            response_message.tool_calls = await self._fix_tool_calls(
                response_message.tool_calls
            )

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

            if tool_call.id:
                # updating the dummy tool response with the actual response
                await self._update_tool_response(tool_call.id, function_response)
            else:
                # adding a new tool response
                self._add_tool_response(tool_call, function_response)

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
            function_response = await self._execute_command(command)
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
                text=text,
                config=self.config.edge_tts,
                sound_config=self.config.sound,
                audio_player=self.audio_player,
                wingman_name=self.name,
            )
        elif self.tts_provider == TtsProvider.ELEVENLABS:
            self.elevenlabs.play_audio(
                text=text,
                config=self.config.elevenlabs,
                sound_config=self.config.sound,
                audio_player=self.audio_player,
                wingman_name=self.name,
            )
        elif self.tts_provider == TtsProvider.AZURE:
            self.openai_azure.play_audio(
                text=text,
                api_key=self.azure_api_keys["tts"],
                config=self.config.azure.tts,
                sound_config=self.config.sound,
                audio_player=self.audio_player,
                wingman_name=self.name,
            )
        elif self.tts_provider == TtsProvider.XVASYNTH:
            self.xvasynth.play_audio(
                text=text,
                config=self.config.xvasynth,
                sound_config=self.config.sound,
                audio_player=self.audio_player,
                wingman_name=self.name,
            )
        elif self.tts_provider == TtsProvider.OPENAI:
            self.openai.play_audio(
                text=text,
                voice=self.config.openai.tts_voice,
                sound_config=self.config.sound,
                audio_player=self.audio_player,
                wingman_name=self.name,
            )
        else:
            printr.toast_error(f"Unsupported TTS provider: {self.tts_provider}")

    async def _execute_command(self, command: dict) -> str:
        """Does what Wingman base does, but always returns "Ok" instead of a command response.
        Otherwise the AI will try to respond to the command and generate a "duplicate" response for instant_activation commands.
        """
        await super()._execute_command(command)
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
            if not command.force_instant_activation
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

    async def __ask_gpt_for_locale(self, language: str) -> str:
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
        await printr.print_async(
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
