import json
from elevenlabs import generate, stream, Voice, VoiceSettings, voices
from services.open_ai import OpenAi
from services.edge import EdgeTTS
from services.printr import Printr
from services.secret_keeper import SecretKeeper
from wingmen.wingman import Wingman

printr = Printr()


class OpenAiWingman(Wingman):
    """Our OpenAI Wingman base gives you everything you need to interact with OpenAI's various APIs.

    It transcribes speech to text using Whisper, uses the Completion API for conversation and implements the Tools API to execute functions.
    """

    def __init__(self, name: str, config: dict[str, any], secret_keeper: SecretKeeper):
        super().__init__(name, config, secret_keeper)

        self.openai: OpenAi = None  # validate will set this
        """Our OpenAI API wrapper"""

        # every conversation starts with the "context" that the user has configured
        self.messages = [
            {"role": "system", "content": self.config["openai"].get("context")}
        ]
        """The conversation history that is used for the GPT calls"""

        self.edge_tts = EdgeTTS()
        self.last_transcript_locale = None
        self.elevenlabs_api_key = None

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

        self.__validate_elevenlabs_config(errors)

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

    async def _transcribe(self, audio_input_wav: str) -> tuple[str | None, str | None]:
        """Transcribes the recorded audio to text using the OpenAI Whisper API.

        Args:
            audio_input_wav (str): The path to the audio file that contains the user's speech. This is a recording of what you you said.

        Returns:
            str | None: The transcript of the audio file or None if the transcription failed.
        """
        detect_language = self.config["edge_tts"].get("detect_language")

        response_format = (
            "verbose_json"  # verbose_json will return the language detected in the transcript.
            if self.tts_provider == "edge_tts" and detect_language
            else "json"
        )
        transcript = self.openai.transcribe(
            audio_input_wav, response_format=response_format
        )

        locale = None
        # skip the GPT call if we didn't change the language
        if (
            response_format == "verbose_json"
            and transcript
            and transcript.language != self.last_transcript_locale  # type: ignore
        ):
            printr.print(
                f"   EdgeTTS detected language '{transcript.language}'.", tags="info"  # type: ignore
            )
            locale = self.__ask_gpt_for_locale(transcript.language)  # type: ignore

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
        self.last_transcript_locale = locale
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
        remember_messages = self.config["features"].get("remember_messages", None)

        if remember_messages is None:
            return

        # Calculate the max number of messages to keep including the initial system message
        # `remember_messages * 2` pairs plus one system message.
        max_messages = (remember_messages * 2) + 1

        # every "AI interaction" is a pair of 2 messages: "user" and "assistant" or "tools"
        deleted_pairs = 0

        while len(self.messages) > max_messages:
            if remember_messages == 0:
                # Calculate pairs to be deleted, excluding the system message.
                deleted_pairs += (len(self.messages) - 1) // 2
                self.reset_conversation_history()
            else:
                while len(self.messages) > max_messages:
                    del self.messages[1:3]
                    deleted_pairs += 1

        if self.debug and deleted_pairs > 0:
            printr.print(
                f"   Deleted {deleted_pairs} pairs of messages from the conversation history.",
                tags="warn",
            )

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
                f"   Calling GPT with {(len(self.messages) - 1) // 2} message pairs (excluding context)",
                tags="info",
            )
        return self.openai.ask(
            messages=self.messages,
            tools=self._build_tools(),
            model=self.config["openai"].get("conversation_model"),
        )

    def _process_completion(self, completion):
        """Processes the completion returned by the GPT call.

        Args:
            completion: The completion object from an OpenAI call.

        Returns:
            A tuple containing the message response and tool calls from the completion.
        """
        response_message = completion.choices[0].message
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
        summarize_model = self.config["openai"].get("summarize_model")
        summarize_response = self.openai.ask(
            messages=self.messages,
            model=summarize_model,
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

        if self.tts_provider == "edge_tts":
            edge_config = self.config["edge_tts"]
            tts_voice = edge_config.get("tts_voice")
            gender = edge_config.get("gender")
            detect_language = edge_config.get("detect_language")

            if detect_language:
                tts_voice = await self.edge_tts.get_same_random_voice_for_language(
                    gender, self.last_transcript_locale
                )

            await self.edge_tts.generate_speech(
                text, filename="audio_output/edge_tts.mp3", voice=tts_voice
            )

            audio = self.audio_player.get_audio_from_file("audio_output/edge_tts.mp3")
            self.audio_player.stream_with_effects(
                audio,
                play_beep=self.config.get("features", {}).get("play_beep_on_receiving"),
                play_noise=self.config.get("features", {}).get(
                    "enable_radio_sound_effect"
                ),
                robot_effect=self.config.get("features", {}).get(
                    "enable_robot_sound_effect"
                ),
            )

        elif self.tts_provider == "elevenlabs":
            # already validated in validate():
            elevenlabs_config = self.config["elevenlabs"]
            voice_config = elevenlabs_config["voice"]
            # validate() already checked that at least one of these is set
            voice_id = voice_config.get("id")
            voice_name = voice_config.get("name")
            voice = (
                Voice(voice_id=voice_id)  # id takes precendence if set
                if voice_id
                else next(
                    (v for v in voices() if v.name == voice_name), None
                )  # else use the name
            )

            voice_setting = self._get_elevenlabs_settings(elevenlabs_config)
            if voice_setting:
                voice.settings = voice_setting

            response = generate(
                text,
                voice=voice,
                model=elevenlabs_config.get("model"),
                stream=True,
                api_key=self.elevenlabs_api_key,
                latency=elevenlabs_config.get("latency", 3),
            )
            stream(response)
        else:  # OpenAI TTS
            response = self.openai.speak(text, self.config["openai"].get("tts_voice"))
            if response is not None:
                self.audio_player.stream_with_effects(
                    response.content,
                    play_beep=self.config.get("features", {}).get(
                        "play_beep_on_receiving"
                    ),
                    play_noise=self.config.get("features", {}).get(
                        "enable_radio_sound_effect"
                    ),
                    robot_effect=self.config.get("features", {}).get(
                        "enable_robot_sound_effect"
                    ),
                )

    def _get_elevenlabs_settings(self, elevenlabs_config):
        settings = elevenlabs_config.get("voice_settings")
        if not settings:
            return None

        voice_settings = VoiceSettings(
            stability=settings.get("stability", 0.5),
            similarity_boost=settings.get("similarity_boost", 0.75),
        )
        style = settings.get("style", None)
        use_speaker_boost = settings.get("use_speaker_boost", None)

        if style is not None:
            voice_settings.style = style
        if use_speaker_boost is not None:
            voice_settings.use_speaker_boost = use_speaker_boost

        return voice_settings

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

    def __ask_gpt_for_locale(self, language: str) -> str:
        """OpenAI TTS returns a natural language name for the language of the transcript, e.g. "german" or "english".
        This method uses ChatGPT to find the corresponding locale, e.g. "de-DE" or "en-EN".

        Args:
            language (str): The natural, lowercase language name returned by OpenAI TTS. Thank you for that btw.. WTF OpenAI?
        """

        response = self.openai.ask(
            messages=[
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
            model="gpt-3.5-turbo-1106",
        )
        answer = response.choices[0].message.content

        if answer == "None":
            return None

        printr.print(
            f"   ChatGPT says this language maps to locale '{answer}'.", tags="info"
        )
        return answer
