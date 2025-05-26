import json
import os

from openai import AzureOpenAI

from services.open_ai import AzureConfig, OpenAi, STTConfig
from services.printr import Printr
from wingmen.wingman import Wingman

from wingmen.star_citizen_services.helper import find_best_match

printr = Printr()

DEBUG = True

DEBUG_LOG_PATH = os.path.join("debug_data", "openai", "debug.log")


def print_debug(message):
    """Prints debug messages if DEBUG is enabled."""
    if DEBUG:
        print(message)


def _ensure_debug_log():
    """Ensure debug log file exists and is empty (truncate)."""
    log_dir = os.path.dirname(DEBUG_LOG_PATH)
    os.makedirs(log_dir, exist_ok=True)
    with open(DEBUG_LOG_PATH, "w", encoding="utf-8") as f:
        pass  # Truncate file


def _default_json(obj):
    # Try Pydantic/BaseModel
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    # Try __dict__
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    # Try as string fallback
    return str(obj)


def _log_debug_entry(entry):
    """Append a formatted entry to the debug log file for better readability."""
    with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
        entry_type = entry.get("type", "")
        f.write("\n" + "=" * 30 + f" {entry_type.upper()} " + "=" * 30 + "\n")
        if entry_type == "request":
            # Pretty print messages and tools
            f.write("MESSAGES:\n")
            messages = entry.get("messages", [])
            for i, msg in enumerate(messages):
                try:
                    # Ensure msg is serializable, default to str if complex object
                    msg_serializable = (
                        msg
                        if isinstance(
                            msg, (dict, list, str, int, float, bool, type(None))
                        )
                        else _default_json(msg)
                    )
                    msg_str = json.dumps(
                        msg_serializable,
                        ensure_ascii=False,
                        indent=4,
                        default=_default_json,
                    )
                except Exception:
                    msg_str = str(msg)
                f.write(f"  [{i}] {msg_str}\n")
            f.write("\nTOOLS:\n")
            tools = entry.get("tools", [])
            for tool in tools:
                try:
                    tool_str = json.dumps(
                        tool, ensure_ascii=False, indent=4, default=_default_json
                    )
                except Exception:
                    tool_str = str(tool)
                f.write(f"  {tool_str}\n")
            f.write(f"\nMODEL: {entry.get('model')}\n")
            f.write(f"AZURE_CONFIG: {entry.get('azure_config')}\n")
        elif entry_type == "response":
            resp = entry.get("response")
            # Try to pretty print JSON string if possible
            try:
                # Handle case where resp might already be a string representing JSON
                if isinstance(resp, str):
                    try:
                        resp_obj = json.loads(resp)
                        resp_str = json.dumps(resp_obj, ensure_ascii=False, indent=4)
                    except json.JSONDecodeError:
                        resp_str = resp  # Keep as original string if not valid JSON
                else:
                    # Try to serialize non-string response directly
                    resp_str = json.dumps(
                        resp, ensure_ascii=False, indent=4, default=_default_json
                    )
            except Exception:
                resp_str = str(resp)  # Fallback
            f.write("RESPONSE:\n")
            f.write(resp_str + "\n")
        else:
            # Fallback: pretty print the whole entry
            f.write(
                json.dumps(entry, ensure_ascii=False, indent=4, default=_default_json)
                + "\n"
            )
        f.write("=" * 70 + "\n")


class OpenAiWingman(Wingman):
    """Our OpenAI Wingman base gives you everything you need to interact with OpenAI's various APIs.

    It transcribes speech to text using Whisper, uses the Completion API for conversation and implements the Tools API to execute functions.
    Includes LRU caching for instant commands (metadata) and TTS responses (metadata + separate audio files).
    """

    def __init__(
        self,
        name,
        config,
        secret_keeper,
        app_root_dir,
    ):
        super().__init__(
            name=name,
            config=config,
            secret_keeper=secret_keeper,
            app_root_dir=app_root_dir,
        )

        self.openai = None  # validate will set this
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
            "stt_model": None,
            "conversation": None,
            "summarize": None,
        }
        self.groq_keys = {
            "stt_model": None,
        }
        self.openai_api_key = None

        # STT Provider
        self.stt_provider = self.config["features"].get("stt_provider", None)
        self.stt_model = self.config.get(self.stt_provider, {}).get(
            "stt_model", None
        )  # Safer access

        self.conversation_provider = self.config["features"].get(
            "conversation_provider", None
        )
        self.summarize_provider = self.config["features"].get(
            "summarize_provider", None
        )

        if DEBUG:
            _ensure_debug_log()

    def validate(self):
        errors = super().validate()
        self.load_caches() 

        self.openai_api_key = self.secret_keeper.retrieve(
            requester=self.name,
            key="openai",
            friendly_key_name="OpenAI API key",
            prompt_if_missing=True,
        )
        if not self.openai_api_key:
            errors.append(
                "Missing 'openai' API key. Please provide a valid key in the settings."
            )
            # Return early if fundamental key is missing and other validations depend on it
            # return errors # Keep original behavior: continue validation

        openai_organization = self.config["openai"].get("organization")
        openai_base_url = self.config["openai"].get("base_url")

        self.__validate_elevenlabs_config(errors)
        self.__validate_azure_config(errors)
        self.__validate_groq_config(errors)

        # Keep original behavior: Check errors *before* initializing OpenAI client
        if not errors and self.openai_api_key:  # Check errors again
            try:
                self.openai = OpenAi(
                    organization=openai_organization,
                    api_key=self.openai_api_key,
                    base_url=openai_base_url,
                    stt_config=self.__build_stt_config(),
                )
            except Exception as e:
                # Catch potential errors during client initialization
                errors.append(f"Failed to initialize OpenAI client: {e}")
                printr.print_err(f"Failed to initialize OpenAI client: {e}")
        # No else needed here, errors are collected

        return errors

    def __build_stt_config(self):
        """Builds the STT configuration based on the provider specified in the config.

        Returns:
            STTConfig: The configuration object for the selected STT provider.
        """
        stt_config = STTConfig(
            stt_provider=self.stt_provider,
            stt_model=self.stt_model,
        )
        if self.stt_provider == "openai":
            pass  # keine weiteren informationen nötig
        elif self.stt_provider == "azure":
            stt_config.azure_config = self._get_azure_config("stt_model")
        elif self.stt_provider == "groq":
            stt_config.api_key = self.groq_keys["stt_model"]
            # >>> MODIFIED: Safer access to base_url <<<
            stt_config.base_url = self.config.get("groq", {}).get(
                "base_url", None
            )  # Safer access
        elif self.stt_provider == "local":
            stt_config.local = True
        else:
            # >>> MODIFIED: Handle potential misconfiguration gracefully <<<
            # Raise error only if provider is set but not recognized
            if self.stt_provider:
                raise ValueError(f"Unsupported STT provider: {self.stt_provider}")
            else:
                # If no provider is set, maybe default or log a warning?
                # For now, let it proceed, validation might catch downstream issues
                printr.print_warn("No STT provider specified in config features.")
                # Optionally set a default or return None if STT is mandatory
                # stt_config = None # Example if STT must be configured

        return stt_config

    def __validate_groq_config(self, errors):
        if self.stt_provider == "groq":
            self.groq_keys["stt_model"] = self.secret_keeper.retrieve(
                requester=self.name,
                key="groq_stt",
                friendly_key_name="Groq STT API key",
                prompt_if_missing=True,
            )
            if not self.groq_keys["stt_model"]:
                errors.append(
                    "Missing 'groq_stt' key for Groq STT provider."
                )  # More specific message

    def __validate_elevenlabs_config(self, errors):
        # >>> ADDED: Check if elevenlabs is actually the provider <<<
        if self.tts_provider != "elevenlabs":
            return  # Skip validation if not used

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
            return  # Stop validation for elevenlabs if key is missing

        elevenlabs_settings = self.config.get("elevenlabs")
        if not elevenlabs_settings:
            errors.append(
                "Missing 'elevenlabs' section in config. Please provide a valid config or change the TTS provider."
            )
            return  # Stop validation if section missing
        if not elevenlabs_settings.get("model"):
            errors.append("Missing 'model' setting in 'elevenlabs' config.")
            # Don't return, check voice too

        voice_settings = elevenlabs_settings.get("voice")
        if not voice_settings:
            errors.append(
                "Missing 'voice' section in 'elevenlabs' config. Please provide a voice configuration as shown in our example config."
            )
            # Don't return, allow other errors to surface
        elif not voice_settings.get("id") and not voice_settings.get("name"):
            errors.append(
                "Missing 'id' or 'name' in 'voice' section of 'elevenlabs' config. Please provide a valid name or id for the voice in your config."
            )

    def __validate_azure_config(self, errors):
        # >>> MODIFIED: Check if Azure is used for *any* service <<<
        is_azure_used = (
            self.tts_provider == "azure"
            or self.stt_provider == "azure"
            or self.conversation_provider == "azure"
            or self.summarize_provider == "azure"
        )

        if not is_azure_used:
            return  # No need to validate Azure config if not used

        azure_settings = self.config.get("azure")
        if not azure_settings:
            errors.append(
                "Missing 'azure' section in config, but Azure is selected as a provider. Please provide a valid config."
            )
            return  # Stop Azure validation if section is missing

        # Validate keys based on which Azure services are enabled
        if self.tts_provider == "azure":
            self.azure_keys["tts"] = self.secret_keeper.retrieve(
                requester=self.name,
                key="azure_tts",
                friendly_key_name="Azure TTS API key",
                prompt_if_missing=True,
            )
            if not self.azure_keys["tts"]:
                errors.append("Missing 'azure_tts' API key for Azure TTS provider.")

        if self.stt_provider == "azure":
            self.azure_keys["stt_model"] = self.secret_keeper.retrieve(
                requester=self.name,
                key="azure_whisper",
                friendly_key_name="Azure Whisper API key",
                prompt_if_missing=True,
            )
            if not self.azure_keys["stt_model"]:
                errors.append("Missing 'azure_whisper' API key for Azure STT provider.")

        if self.conversation_provider == "azure":
            self.azure_keys["conversation"] = self.secret_keeper.retrieve(
                requester=self.name,
                key="azure_conversation",
                friendly_key_name="Azure Conversation API key",
                prompt_if_missing=True,
            )
            if not self.azure_keys["conversation"]:
                errors.append(
                    "Missing 'azure_conversation' API key for Azure Conversation provider."
                )

        if self.summarize_provider == "azure":
            self.azure_keys["summarize"] = self.secret_keeper.retrieve(
                requester=self.name,
                key="azure_summarize",
                friendly_key_name="Azure Summarize API key",
                prompt_if_missing=True,
            )
            if not self.azure_keys["summarize"]:
                errors.append(
                    "Missing 'azure_summarize' API key for Azure Summarize provider."
                )

        # >>> ADDED: Validate specific Azure section configs (URL, version, deployment) <<<
        # Example for conversation, repeat for others if needed
        if self.conversation_provider == "azure":
            conv_config = azure_settings.get("conversation", {})
            if not all(
                [
                    conv_config.get("api_base_url"),
                    conv_config.get("api_version"),
                    conv_config.get("deployment_name"),
                ]
            ):
                errors.append(
                    "Azure 'conversation' config section is incomplete (missing api_base_url, api_version, or deployment_name)."
                )
        # Add similar checks for tts, stt_model, summarize sections if they have these fields

    async def _transcribe(self, audio_input_wav):
        """Transcribes the recorded audio to text using the configured STT provider."""
        # >>> MODIFIED: Check if OpenAI client (handling STT) is initialized <<<
        if not self.openai:
            printr.print_err(
                f"STT provider '{self.stt_provider}' selected, but OpenAI client failed to initialize. Cannot transcribe."
            )
            return None, None

        response_format = "json"  # Whisper JSON includes text

        transcript_obj = self.openai.transcribe(
            audio_input_wav, response_format=response_format
        )

        # Return transcript text and None for locale (as in original)
        return transcript_obj.text if transcript_obj else None, None

    def _get_azure_config(self, section):
        """Gets Azure configuration details for a specific service section."""
        # >>> MODIFIED: Return None early if key is missing <<<
        azure_api_key = self.azure_keys.get(section)
        if not azure_api_key:
            # printr.print_warn(f"Azure API key for section '{section}' not found or not configured.") # Optional warning
            return None

        section_config = self.config.get("azure", {}).get(section, {})
        api_base_url = section_config.get("api_base_url")
        api_version = section_config.get("api_version")
        deployment_name = section_config.get("deployment_name")

        # >>> ADDED: Basic validation of fetched Azure config values <<<
        if not all([api_base_url, api_version, deployment_name]):
            printr.print_warn(
                f"Azure configuration for section '{section}' is incomplete in config file."
            )
            return None

        azure_config = AzureConfig(
            api_key=azure_api_key,
            api_base_url=api_base_url,
            api_version=api_version,
            deployment_name=deployment_name,
        )

        return azure_config

    async def _get_response_for_transcript(
        self, transcript: str, locale: str | None
    ) -> tuple[str, str, str]:
        """
        Gets the response for a given transcript. Checks instant activation.
        Determines data for TTS cache key, generates key, and plays audio with caching.
        """
        if self.debug or DEBUG:
            printr.print(
                f"Received transcript in {self.__class__.__name__}: '{transcript}' (locale: {locale})", tags="info"
            )
        self.last_transcript_locale = locale
        normalized_transcript = transcript.lower().strip() if transcript else ""

        # 1. Check standard instant activation commands (using original transcript)
        instant_response_text = self._try_instant_activation(normalized_transcript)
        if instant_response_text:
            return instant_response_text, instant_response_text, None

        _, delete_last_cache_entry = find_best_match.find_best_match(
            normalized_transcript, self.cache_config["delete_last_cached_command_phrases"]
        )

        if delete_last_cache_entry:
            if self.debug or DEBUG:
                printr.print(
                    f"Deleting last cache entry for: '{normalized_transcript}'", tags="info"
                )
            key = self.instant_command_cache_manager.remove_last_added_entry()

            if key:
                msg = {
                        "role": "user",
                        "content": "Deleted last cache entry successfully",
                    }
                self.messages.append(msg)
                # Run summarization based on tool results
                summarize_response_content = self._summarize_function_calls()
                # Important: _summarize_function_calls *also* adds the summary message to self.messages in the original code
                final_text_to_speak, _ = self._finalize_response(
                    summarize_response_content
                )

                return final_text_to_speak, final_text_to_speak, None            
        
        _, do_not_cache_phrase = find_best_match.find_best_match(
            normalized_transcript, self.cache_config["do_not_cache_phrases"]
        )

        _, flag_for_removal = find_best_match.find_best_match(
            normalized_transcript, self.cache_config["short_memory_commands"]
        )

        call_cache_key = self._generate_cache_key(normalized_transcript)
        tts_cache_key = None
        final_text_to_speak = None
        instant_response = None

        # --- >>> ADDED: Instant Command Cache Check <<< ---
        # 2. Check cached instant commands (based on transcript)
        if self.instant_command_cache_manager and not do_not_cache_phrase:
            cached_command_data = self.instant_command_cache_manager.get(call_cache_key)
            if cached_command_data is None:
                fuzzy_key = self.instant_command_cache_manager.get_key_from_text(normalized_transcript)
                if fuzzy_key:
                    call_cache_key = fuzzy_key
                cached_command_data = self.instant_command_cache_manager.get(call_cache_key)

            if cached_command_data:
                printr.print(
                    f"Instant command cache hit for: '{normalized_transcript}':{call_cache_key}", tags="info"
                )

                instant_response, tts_cache_key = await self._handle_tool_calls(
                    None, call_cache_key, normalized_transcript
                )

                if not self.tts_cache_manager.exists(tts_cache_key):
                    # if the response of the function call is not cached, we should put the conversation into history
                    # such that we can summarize the response through ai calls.
                    self._add_user_message(normalized_transcript)
                    summarize_response_content = self._summarize_function_calls()
                    final_text_to_speak, _ = self._finalize_response(
                        summarize_response_content
                    )
                else:
                    # If TTS response is cached, we can directly use it
                    final_text_to_speak = self.tts_cache_manager.get_cached_text(tts_cache_key)

                return final_text_to_speak, instant_response, tts_cache_key
        
        if self.debug or DEBUG:
            printr.print("calling ai api...", tags="info")
        # 3. If no cache hit, proceed with LLM call (Original logic starts here)
        self._add_user_message(normalized_transcript)
        completion = self._gpt_call()

        if completion is None:
            return None, None, None

        response_message, tool_calls = self._process_completion(completion)

        # Add initial assistant response to history
        self.messages.append(response_message)

        if tool_calls:
            if self.debug or DEBUG:
                printr.print("Executing tool calls...", tags="info")
            
            if do_not_cache_phrase:
                call_cache_key = None  
            instant_response, tts_cache_key = await self._handle_tool_calls(
                tool_calls, call_cache_key, flag_for_removal=flag_for_removal, command_phrase=normalized_transcript
            )  # Pass transcript

            # Run summarization based on tool results
            summarize_response_content = self._summarize_function_calls()
            # Important: _summarize_function_calls *also* adds the summary message to self.messages in the original code
            final_text_to_speak, _ = self._finalize_response(
                summarize_response_content
            )

        else:
            # No tool calls, use the direct response content
            # Make sure response_message content is accessed correctly
            final_text_to_speak = getattr(response_message, "content", "")

        return final_text_to_speak, instant_response, tts_cache_key

    def _add_user_message(self, content):
        """Shortens the conversation history if needed and adds a user message to it."""
        # Keep original logic
        msg = {"role": "user", "content": content}
        self._cleanup_conversation_history()
        self.messages.append(msg)

    def _cleanup_conversation_history(self):
        """Cleans up the conversation history by removing messages that are too old."""
        # Keep original logic
        remember_messages = self.config.get("features", {}).get(
            "remember_messages", None
        )

        if remember_messages is None or len(self.messages) <= 1:  # Keep system message
            return 0

        context_offset = (
            1
            if self.messages and self._get_message_role(self.messages[0]) == "system"
            else 0
        )
        # Original logic counts user messages from the end
        num_messages_to_keep = remember_messages
        current_message_count = 0
        cutoff_index = len(
            self.messages
        )  # Start assuming we delete nothing before context

        for i in range(len(self.messages) - 1, context_offset - 1, -1):
            message = self.messages[i]
            if self._get_message_role(message) == "user":
                current_message_count += 1
                if current_message_count >= num_messages_to_keep:
                    cutoff_index = (
                        i  # This is the first message (from end) to potentially delete
                    )
                    break  # Found enough user messages to keep

        num_to_delete = cutoff_index - context_offset

        if num_to_delete <= 0:
            return 0  # Nothing to delete

        del self.messages[context_offset: context_offset + num_to_delete]

        if (self.debug or DEBUG) and num_to_delete > 0:
            printr.print(
                f"Deleted {num_to_delete} messages from the conversation history.",
                tags="warn",
            )
        return num_to_delete

    def reset_conversation_history(self):
        """Resets the conversation history by removing all messages except for the initial system message."""
        # Keep original logic
        del self.messages[1:]

    def _try_instant_activation(self, transcript):
        """Tries to execute an instant activation command if present in the transcript."""

        # Keep original logic
        command = self._execute_instant_activation_command(transcript)
        if command:
            response = self._select_command_response(command)
            return response
        return None

    def _gpt_call(self):
        """Makes the primary GPT call with the conversation history and tools enabled."""
        # Keep original logic (including Azure config handling)
        if not self.openai:  # Added check
            printr.print_err("OpenAI client not initialized. Cannot make GPT call.")
            return None

        if self.debug or DEBUG:
            printr.print(
                f"   Calling GPT with {(len(self.messages) - 1)} messages (excluding context)",
                tags="info",
            )

        azure_config = None
        if self.conversation_provider == "azure":
            azure_config = self._get_azure_config("conversation")
            # >>> Added check if Azure config is valid <<<
            if not azure_config:
                printr.print_err(
                    "Azure is conversation provider, but config is invalid. Aborting GPT call."
                )
                return None  # Abort if Azure config is bad

        tools_to_use = self._build_tools()

        # --- Debug logging: log request ---
        if DEBUG:
            _log_debug_entry(
                {
                    "type": "request",
                    "messages": self.messages,
                    "tools": tools_to_use,
                    "model": self.config["openai"].get("conversation_model"),
                    "azure_config": bool(azure_config),  # Log if Azure config was used
                }
            )

        result = self.openai.ask(
            messages=self.messages,
            tools=tools_to_use if tools_to_use else None,  # Pass None if no tools
            model=self.config["openai"].get("conversation_model"),
            azure_config=azure_config,
        )

        # --- Debug logging: log response ---
        if DEBUG and result is not None:
            try:
                # Try to serialize the result (may need to convert to dict)
                if hasattr(result, "model_dump_json"):
                    response_json = result.model_dump_json()
                elif hasattr(result, "model_dump"):  # Try model_dump before __dict__
                    response_json = json.dumps(
                        result.model_dump(), ensure_ascii=False, default=str
                    )
                elif hasattr(result, "__dict__"):
                    response_json = json.dumps(
                        result.__dict__, ensure_ascii=False, default=str
                    )
                else:
                    response_json = str(result)
            except Exception as e:
                printr.print_warn(
                    f"Could not serialize GPT response for debug log: {e}"
                )
                response_json = str(result)
            _log_debug_entry(
                {
                    "type": "response",
                    "response": response_json,
                }
            )

        return result

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

    async def _handle_tool_calls(self, tool_calls, call_cache_key, flag_for_removal=False, command_phrase=None):
        """Processes all the tool calls identified in the response message."""

        instant_response = None
        # function_response = "" # Variable not used in original return

        cached_function_calls = []
        caching_key_function_objects = []
        tool_call_response_cache_key = None

        if not tool_calls and call_cache_key:
            cached_function_calls = self.instant_command_cache_manager.get(
                call_cache_key
            )  # Check cache for instant command

            for function_call in cached_function_calls:
                function_name = function_call[0]
                function_args = function_call[1]

                # Pass transcript and is_cached_call=True
                function_response, instant_response_iter = (
                    await self._execute_command_by_function_call(
                        function_name, function_args
                    )
                )

                caching_key_function_objects.append((function_name, call_cache_key, function_response))

                if instant_response_iter:
                    instant_response = instant_response_iter

                msg = {
                    "role": "user",
                    "content": f"function '{function_name}' result: {function_response}",
                }
                self.messages.append(msg)
        elif not tool_calls:
            return None, None
        else:
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)

                cached_function_calls.append((function_name, function_args))

                # Pass transcript and is_cached_call=False
                function_response, instant_response_iter = (
                    await self._execute_command_by_function_call(
                        function_name, function_args
                    )
                )

                caching_key_function_objects.append((function_name, call_cache_key, function_response))

                if instant_response_iter:
                    instant_response = instant_response_iter

                msg = {"role": "tool", "content": function_response}
                if tool_call.id is not None:
                    msg["tool_call_id"] = tool_call.id
                # Original code added 'name', keep it for compatibility although 'tool_call_id' is primary
                if function_name is not None:
                    msg["name"] = function_name

                # Don't use self._add_user_message_to_history here because we never want to skip this because of history limitions
                self.messages.append(msg)

            if self.debug or DEBUG:
                printr.print(
                    f"Caching function call '{function_name}':#{call_cache_key}", tags="info"
                )
            self.instant_command_cache_manager.put(
                key=call_cache_key,
                data=cached_function_calls,
                storage_mode="json",
                file_extension=".json",
                flag_for_removal=flag_for_removal,
                key_text=command_phrase,
            )

        if len(caching_key_function_objects) > 0:
            tool_call_response_cache_key = self._generate_cache_key(caching_key_function_objects)
        # Return the *last* instant response encountered during the loop
        return (
            instant_response,
            tool_call_response_cache_key,
        )  # Return cache key for tool call responses to save the tts response

    def _summarize_function_calls(self):
        """Summarizes the function call responses using the configured summarize provider."""
        # Keep original logic (including Azure config handling)
        if not self.openai:  # Added check
            printr.print_err("OpenAI client not initialized. Cannot summarize.")
            return None

        azure_config = None
        # Do not modify the original messages list
        messages_for_summary = list(self.messages)  # Use copy for safety

        summarize_model = self.config["openai"].get(
            "summarize_model", self.config["openai"].get("conversation_model")
        )

        if self.summarize_provider == "azure":
            azure_config = self._get_azure_config("summarize")
            if not azure_config:
                printr.print_err(
                    "Azure is summarize provider, but config is invalid. Cannot summarize."
                )
                return None

        summarize_response = self.openai.ask(
            messages=messages_for_summary,
            model=summarize_model,
            azure_config=azure_config,
            # No tools needed for summarization
        )

        if summarize_response is None:
            printr.print_err("Summarization call failed.")
            return None

        # Process the summarization response
        # Use _process_completion to handle potential None content etc.
        summary_message, _ = self._process_completion(summarize_response)

        # Add the summary to the main conversation history
        # Ensure we add the correct type (original object or dict)
        self.messages.append(summary_message)
        # Return the content string
        return getattr(summary_message, "content", "")

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

    async def _play_to_user(self, text, tts_cache_key=None):
        """Plays audio using cache (metadata + file) or TTS API."""
        # Keep original checks
        if not text or text.strip().lower() == "ok":
            return

        # --- >>> ADDED: TTS Cache Logic <<< ---
        cached_audio_bytes = None
        cache_hit = False

        # Check TTS Cache using the provided key
        if self.tts_cache_manager and tts_cache_key:
            cached_audio_bytes = self.tts_cache_manager.get(tts_cache_key)
            if cached_audio_bytes:
                printr.print(
                    f"   TTS cache hit (key: {tts_cache_key[:8]}...).", tags="info"
                )
                cache_hit = True
                # we allow to regenerate the tts if needed. The text in the cache might have been adapted. 
                needs_update = self.tts_cache_manager.needs_tts_update(
                    tts_cache_key)
                if needs_update:
                    text = self.tts_cache_manager.get_cached_text(tts_cache_key)
            else:
                printr.print(
                    f"   TTS cache miss (key: {tts_cache_key[:8]}...). Calling API.",
                    tags="info",
                )
        # --- >>> END: TTS Cache Check <<< ---

        # If cache miss, generate audio
        if not cache_hit or needs_update:
            audio_bytes_generated = None
            if self.tts_provider == "azure":
                # Call original _play_with_azure but modify it to *return bytes*
                audio_bytes_generated = self._generate_with_azure(text)
            elif self.tts_provider == "elevenlabs":  # Added condition for elevenlabs
                audio_bytes_generated = self._generate_with_elevenlabs(text)
            else:  # Default to OpenAI
                # Call original _play_with_openai but modify it to *return bytes*
                audio_bytes_generated = self._generate_with_openai(text)

            if audio_bytes_generated:
                cached_audio_bytes = audio_bytes_generated

                if self.tts_cache_manager and tts_cache_key:
                    try:
                        self.tts_cache_manager.put(
                            key=tts_cache_key,
                            data=audio_bytes_generated,
                            storage_mode="bytes",
                            file_extension=".wav",
                            key_text=text
                        )
                        printr.print(
                            f"   Stored TTS response in cache (key: {tts_cache_key[:8]}...).",
                            tags="info",
                        )
                    except Exception as e:
                        printr.print_err(
                            f"Error storing TTS data in cache for key '{tts_cache_key}': {e}"
                        )
            else:
                printr.print_err(f"TTS generation failed for text: '{text[:50]}...'")
                return  # Don't attempt to play if generation failed

        # --- Play Audio (from cache or new generation) ---
        if cached_audio_bytes:
            self.audio_player.stream_with_effects(cached_audio_bytes, self.config)

    def _generate_with_openai(self, text):
        if not self.openai:
            return None
        try:
            response = self.openai.speak(
                text,
                self.config["openai"].get("tts_model"),
                self.config["openai"].get("tts_voice"),
                self.config["openai"].get("tts_voice_instructions", ""),
                self.config["openai"].get("player_language"),
            )
            # Return bytes directly
            return response.content if response else None
        except Exception as e:
            printr.print_err(f"Error generating OpenAI TTS: {e}")
            return None

    def _generate_with_azure(self, text):
        azure_config = self._get_azure_config("tts")
        if not azure_config:
            printr.print_err("Azure TTS selected, but config is invalid.")
            return None

        voice = self.config.get("azure", {}).get("tts", {}).get("voice", "nova")
        try:
            # Note: Azure TTS might use a different endpoint or client setup than completions.
            # Assuming AzureOpenAI client works for TTS based on original code structure.
            # If a dedicated SpeechSDK client is needed, instantiate it here.
            client = AzureOpenAI(
                api_key=azure_config.api_key,
                azure_endpoint=azure_config.api_base_url,
                api_version=azure_config.api_version,
                # Azure TTS API might not use deployment name like completions
                # If it does, add: azure_deployment=azure_config.deployment_name,
            )

            response = client.audio.speech.create(
                model=azure_config.deployment_name,  # Use deployment name as model for Azure Speech? Check API docs. Or a fixed model like "tts-1"?
                voice=voice,
                input=text,
            )
            # Return bytes directly
            return response.content if response else None
        except Exception as e:
            printr.print_err(f"Error generating Azure TTS: {e}")
            # Log more details if needed
            return None

    # --- >>> ADDED: ElevenLabs generation method <<< ---
    def _generate_with_elevenlabs(self, text):
        """Generates speech using ElevenLabs API and returns audio bytes."""
        if not self.elevenlabs_api_key:
            printr.print_err("ElevenLabs TTS selected, but API key is missing.")
            return None

        try:
            # Lazy import if needed, or import at top
            from elevenlabs.client import ElevenLabs
            from elevenlabs import (
                Voice,
                VoiceSettings,
            )  # Removed 'play' as we handle playback

            client = ElevenLabs(api_key=self.elevenlabs_api_key)
            elevenlabs_config = self.config.get("elevenlabs", {})
            voice_config = elevenlabs_config.get("voice", {})
            model = elevenlabs_config.get("model", "eleven_multilingual_v2")
            voice_id = voice_config.get("id")
            voice_name = voice_config.get(
                "name"
            )  # Keep name for potential future lookup
            stability = voice_config.get("stability", 0.7)
            similarity = voice_config.get("similarity_boost", 0.5)

            target_voice = None
            if voice_id:
                target_voice = voice_id
            elif voice_name:
                # Basic implementation: Log warning, use default. Real lookup needed if ID absent.
                printr.print_warn(
                    f"ElevenLabs voice name lookup not implemented, using default ID 'Rachel' for name '{voice_name}'. Provide voice 'id' in config for reliability."
                )
                target_voice = "Rachel"  # Example default ID

            if not target_voice:
                printr.print_err(
                    "No valid ElevenLabs voice ID found (or name lookup failed)."
                )
                return None

            audio_generator = client.generate(
                text=text,
                voice=Voice(
                    voice_id=target_voice,
                    settings=VoiceSettings(
                        stability=stability, similarity_boost=similarity
                    ),
                ),
                model=model,
            )
            # Consume the generator to get bytes
            full_audio = b"".join(audio_generator)
            return full_audio

        except ImportError:
            printr.print_err(
                "ElevenLabs library not installed. Please run 'pip install elevenlabs'"
            )
            return None
        except Exception as e:
            printr.print_err(f"Error generating ElevenLabs TTS: {e}")
            return None

    def _build_tools(self):
        """Builds a tool for each command that is not instant_activation."""
        # Keep original logic
        commands = [
            command["name"]
            for command in self.config.get("commands", [])
            if not command.get("instant_activation")
        ]
        # >>> Added check for empty commands list <<<
        if not commands:
            return []  # Return empty list if no non-instant commands

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "description": "Executes a predefined user command (like key presses).",  # Improved description
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command_name": {
                                "type": "string",
                                "description": "The specific command to execute from the available list.",  # Improved description
                                "enum": sorted(commands),
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
        # Keep original logic
        # >>> MODIFIED: Import Mapping locally to avoid top-level import when types removed <<<
        from collections.abc import Mapping  # Use collections.abc for Python 3.3+

        if isinstance(message, Mapping):
            return message.get("role")
        elif hasattr(message, "role"):
            return message.role
        else:
            # >>> MODIFIED: More informative error <<<
            # Handle potential SimpleNamespace from older completion processing?
            from types import SimpleNamespace

            if isinstance(message, SimpleNamespace) and hasattr(message, "role"):
                return message.role
            # Raise error if type is unexpected
            raise TypeError(
                f"Message is neither a mapping nor has a 'role' attribute: type={type(message)}, value={message}"
            )


# --- END OF FILE open_ai_wingman.py ---
