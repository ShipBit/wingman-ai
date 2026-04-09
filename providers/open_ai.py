from abc import ABC, abstractmethod
import json
import re
from typing import TYPE_CHECKING, Literal, Mapping, Union
import httpx
from openai import NOT_GIVEN, NotGiven, Omit, OpenAI, APIStatusError, AzureOpenAI
import azure.cognitiveservices.speech as speechsdk
from api.enums import AzureRegion, ConversationProvider, LogType, SttProvider, TtsProvider

from api.interface import (
    AzureInstanceConfig,
    AzureSttConfig,
    AzureTtsConfig,
    SoundConfig,
    VoiceInfo,
)
from providers.interfaces import (
    SttInterface, TtsInterface, LlmInterface,
    Transcript, stt_provider, tts_provider, llm_provider,
)
from services.audio_player import AudioPlayer
from services.openai_utils import get_minimal_reasoning_by_model
from services.printr import Printr

if TYPE_CHECKING:
    from api.interface import WingmanConfig

printr = Printr()


class BaseOpenAi(ABC):
    @abstractmethod
    def _create_client(self, *args, **kwargs):
        """Subclasses should implement this method to create their specific client."""

    def _handle_key_error(self):
        printr.toast_error(
            "The OpenAI API key you provided is invalid. Please check the GUI settings or your 'secrets.yaml'"
        )

    def _handle_api_error(self, api_response):
        printr.toast_error(
            f"The OpenAI API sent the following error code {api_response.status_code} ({api_response.type})"
        )
        m = re.search(
            r"'message': (?P<quote>['\"])(?P<message>.+?)(?P=quote)",
            api_response.message,
        )
        if m is not None:
            message = m["message"].replace(". ", ".\n")
            printr.toast_error(message)
        elif api_response.message:
            printr.toast_error(api_response.message)
        else:
            printr.toast_error("The API did not provide further information.")

    def _perform_transcription(
        self,
        client: OpenAI | AzureOpenAI,
        filename: str,
        model: Literal["whisper-1"],
    ):
        try:
            with open(filename, "rb") as audio_input:
                transcript = client.audio.transcriptions.create(
                    model=model, file=audio_input
                )
                return transcript
        except APIStatusError as e:
            self._handle_api_error(e)
        except UnicodeEncodeError:
            self._handle_key_error()

        return None

    def get_minimal_reasoning_by_model(self, model_name: str) -> dict:
        """
        Returns the minimal reasoning effort setting based on the model name.
        This helps reduce latency by setting the lowest supported reasoning effort.
        See https://platform.openai.com/docs/api-reference/chat/create#chat_create-reasoning_effort

        Args:
            model_name: The name of the OpenAI model

        Returns:
            dict: Dictionary with reasoning_effort key if applicable, empty dict otherwise
        """
        # Models that don't support reasoning effort parameter
        if model_name in ["o1-mini", "gpt-5.2-chat-latest"]:
            return {}

        # o-series models (o1, o3, etc.) support "low" as minimal
        if model_name.startswith("o"):
            return {"reasoning_effort": "low"}

        # gpt-5.x models (5.1, 5.2, etc.) support "none" as minimal
        if model_name.startswith("gpt-5."):
            return {"reasoning_effort": "none"}

        # gpt-5 base models support "minimal" as lowest effort
        if model_name.startswith("gpt-5"):
            return {"reasoning_effort": "minimal"}

        # Other models don't support reasoning effort
        return {}

    def _perform_ask(
        self,
        client: OpenAI | AzureOpenAI,
        messages: list[dict[str, str]],
        stream: bool,
        tools: list[dict[str, any]],
        model: str = None,
    ):
        try:
            # Get minimal reasoning effort for the model to reduce latency
            reasoning_params = (
                self.get_minimal_reasoning_by_model(model) if model else {}
            )

            if not tools:
                completion = client.chat.completions.create(
                    stream=stream,
                    messages=messages,
                    model=model,
                    **reasoning_params,
                )
            else:
                completion = client.chat.completions.create(
                    stream=stream,
                    messages=messages,
                    model=model,
                    tools=tools,
                    tool_choice="auto",
                    **reasoning_params,
                )
            return completion
        except APIStatusError as e:
            self._handle_api_error(e)
            return None
        except UnicodeEncodeError:
            self._handle_key_error()
            return None


class OpenAi(BaseOpenAi):
    def __init__(
        self,
        api_key: str = "",
        organization: str | None = None,
        base_url: str | None = None,
    ):
        super().__init__()
        self.api_key = api_key
        self.client = self._create_client(
            api_key=api_key,
            organization=organization,
            base_url=base_url,
        )

    def _create_client(
        self,
        api_key: str,
        organization: str | None = None,
        base_url: str | None = None,
    ):
        """Create an OpenAI client with the given parameters."""
        return OpenAI(
            api_key=api_key,
            organization=organization,
            base_url=base_url,
        )

    def transcribe(self, filename: str, model: str = "whisper-1"):
        return self._perform_transcription(
            client=self.client, filename=filename, model=model
        )

    def ask(
        self,
        messages: list[dict[str, str]],
        model: str = None,
        stream: bool = False,
        tools: list[dict[str, any]] = None,
    ):
        return self._perform_ask(
            client=self.client,
            messages=messages,
            model=model,
            stream=stream,
            tools=tools,
        )

    async def play_audio(
        self,
        text: str,
        voice: str,
        model: str,
        speed: float,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
        stream: bool,
    ):
        # instructions = config.instructions # Instructions are for gpt-4o-mini-tts model only
        try:
            if not stream:
                # Non-streaming implementation
                response = self.client.audio.speech.create(
                    input=text,
                    model=model,
                    voice=voice,
                    speed=speed,
                    # instructions=instructions,
                )
                if response is not None:
                    await audio_player.play_with_effects(
                        input_data=response.content,
                        config=sound_config,
                        wingman_name=wingman_name,
                    )
            else:
                # Streaming implementation
                with self.client.audio.speech.with_streaming_response.create(
                    input=text,
                    model=model,
                    voice=voice,
                    speed=speed,
                    response_format="pcm",
                    # instructions=instructions,
                ) as response:
                    # Create an iterator for the audio chunks. We can set the chunk size here.
                    audio_stream_iterator = response.iter_bytes(chunk_size=1024)

                    # This callback is passed to the audio_player and called repeatedly to fill its buffer.
                    def buffer_callback(audio_buffer):
                        """
                        Fetches the next chunk from the audio stream and loads it
                        into the player's buffer.
                        """
                        try:
                            # Get the next chunk of audio data from the iterator
                            chunk = next(audio_stream_iterator)
                            chunk_size = len(chunk)

                            # Copy the received audio data into the buffer provided by the audio player
                            audio_buffer[:chunk_size] = chunk

                            # Return the number of bytes written
                            return chunk_size
                        except StopIteration:
                            # When the iterator is exhausted, it raises StopIteration.
                            # We catch it and return 0 to signal the end of the stream.
                            return 0

                    # OpenAI's PCM output is 24kHz, 16-bit, single-channel.
                    await audio_player.stream_with_effects(
                        buffer_callback=buffer_callback,
                        config=sound_config,
                        wingman_name=wingman_name,
                        sample_rate=24000,
                        dtype="int16",
                        channels=1,
                        use_gain_boost=True,  # All streaming PCM TTS providers need this
                    )

        except APIStatusError as e:
            self._handle_api_error(e)
        except UnicodeEncodeError:
            self._handle_key_error()


class OpenAiAzure(BaseOpenAi):
    def _create_client(self, api_key: str, config: AzureInstanceConfig):
        """Create an AzureOpenAI client with the given parameters."""
        return AzureOpenAI(
            api_key=api_key,
            azure_endpoint=config.api_base_url,
            api_version=config.api_version.value,
            azure_deployment=config.deployment_name,
        )

    def transcribe_whisper(
        self,
        filename: str,
        api_key: str,
        config: AzureInstanceConfig,
        model: str = "whisper-1",
    ):
        azure_client = self._create_client(api_key=api_key, config=config)
        return self._perform_transcription(
            client=azure_client,
            filename=filename,
            model=model,
        )

    def transcribe_azure_speech(
        self, filename: str, api_key: str, config: AzureSttConfig
    ):
        speech_config = speechsdk.SpeechConfig(
            subscription=api_key,
            region=config.region.value,
        )
        audio_config = speechsdk.AudioConfig(filename=filename)

        auto_detect_source_language_config = (
            (
                speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
                    languages=config.languages
                )
            )
            if len(config.languages) > 1
            else None
        )

        language = config.languages[0] if len(config.languages) == 1 else None

        speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
            language=language,
            auto_detect_source_language_config=auto_detect_source_language_config,
        )
        return speech_recognizer.recognize_once_async().get()

    def ask(
        self,
        messages: list[dict[str, str]],
        api_key: str,
        config: AzureInstanceConfig,
        stream: bool = False,
        tools: list[dict[str, any]] = None,
    ):
        azure_client = self._create_client(api_key=api_key, config=config)
        return self._perform_ask(
            client=azure_client,
            messages=messages,
            # Azure uses the deployment name as the model
            model=config.deployment_name,
            stream=stream,
            tools=tools,
        )

    async def play_audio(
        self,
        text: str,
        api_key: str,
        config: AzureTtsConfig,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
    ):
        speech_config = speechsdk.SpeechConfig(
            subscription=api_key,
            region=config.region.value,
        )

        speech_config.speech_synthesis_voice_name = config.voice

        speech_synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=None,
        )

        result = (
            speech_synthesizer.start_speaking_text_async(text).get()
            if config.output_streaming
            else speech_synthesizer.speak_text_async(text).get()
        )

        def buffer_callback(audio_buffer):
            buffer = bytes(2048)
            size = audio_data_stream.read_data(buffer)
            audio_buffer[:size] = buffer
            return size

        if result is not None:
            if config.output_streaming:
                audio_data_stream = speechsdk.AudioDataStream(result)

                await audio_player.stream_with_effects(
                    buffer_callback,
                    sound_config,
                    wingman_name=wingman_name,
                    use_gain_boost=True,  # "Azure Streaming" low gain workaround
                )
            else:
                await audio_player.play_with_effects(
                    input_data=result.audio_data,
                    config=sound_config,
                    wingman_name=wingman_name,
                )

    def get_available_voices(self, api_key: str, region: AzureRegion, locale: str = ""):
        speech_config = speechsdk.SpeechConfig(subscription=api_key, region=region)
        speech_synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config, audio_config=None
        )
        result = speech_synthesizer.get_voices_async(locale).get()

        if result.reason == speechsdk.ResultReason.VoicesListRetrieved:
            return result.voices
        if result.reason == speechsdk.ResultReason.Canceled:
            printr.toast_error(
                f"Unable to retrieve Azure voices: {result.error_details}"
            )
        return None


class OpenAiCompatibleTts:
    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
    ):
        super().__init__()
        self._api_key = api_key
        self._base_url = base_url
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    async def get_available_voices(
        self, voices_endpoint: str | None
    ) -> list[VoiceInfo]:
        """Retrieve available voices from an OpenAI-compatible endpoint.

        If `voices_endpoint` is not provided, or the request fails for any reason,
        returns an empty list.
        """

        if not voices_endpoint:
            return []

        if not self._base_url:
            return []

        url = f"{self._base_url.rstrip('/')}/{voices_endpoint.lstrip('/')}"

        try:
            headers: dict[str, str] = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()

            try:
                payload = response.json()
            except json.JSONDecodeError as e:
                printr.print(
                    f"OpenAI-compatible voices: invalid JSON from {url}: {e}",
                    color=LogType.WARNING,
                    server_only=True,
                )
                return []

            items = payload.get("data", []) if isinstance(payload, dict) else []
            if not isinstance(items, list):
                return []

            voices: list[VoiceInfo] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                voice_id = item.get("id")
                if not voice_id:
                    continue
                voices.append(VoiceInfo(id=str(voice_id), name=str(voice_id)))
            return voices
        except httpx.HTTPStatusError as e:
            # Non-2xx response
            printr.print(
                f"OpenAI-compatible voices: HTTP {e.response.status_code} from {url}: {e}",
                color=LogType.WARNING,
                server_only=True,
            )
            return []
        except httpx.RequestError as e:
            # Intentionally silent for UI polling; callers expect [] on failures.
            printr.print(
                f"OpenAI-compatible voices: request failed for {url}: {e}",
                color=LogType.WARNING,
                server_only=True,
            )
            return []

    async def play_audio(
        self,
        text: str,
        voice: str,
        model: str,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
        stream: bool,
        speed: float | NotGiven = NOT_GIVEN,
        response_format: (
            NotGiven | Literal["mp3", "opus", "aac", "flac", "wav", "pcm"]
        ) = NOT_GIVEN,
        extra_headers: Mapping[str, Union[str, Omit]] | None = None,
    ):
        # instructions = config.instructions # No current open source model supports this but adding for full compatibility

        # Should sample rate and response format be configurable in UI to ensure widest compatibilty?

        try:
            if not stream:
                # Non-streaming implementation
                response = self.client.audio.speech.create(
                    input=text,
                    model=model,
                    voice=voice,
                    speed=speed,
                    response_format=response_format,
                    # instructions=instructions,
                    extra_headers=extra_headers,
                )
                if response is not None:
                    await audio_player.play_with_effects(
                        input_data=response.content,
                        config=sound_config,
                        wingman_name=wingman_name,
                    )
            else:
                # Streaming implementation
                with self.client.audio.speech.with_streaming_response.create(
                    input=text,
                    model=model,
                    voice=voice,
                    speed=speed,
                    response_format="pcm",
                    # instructions=instructions,
                    extra_headers=extra_headers,
                ) as response:
                    # Create an iterator for the audio chunks. We can set the chunk size here.
                    audio_stream_iterator = response.iter_bytes(chunk_size=1024)

                    # This callback is passed to the audio_player and called repeatedly
                    # to fill its buffer.
                    def buffer_callback(audio_buffer):
                        """
                        Fetches the next chunk from the audio stream and loads it
                        into the player's buffer.
                        """
                        try:
                            # Get the next chunk of audio data from the iterator
                            chunk = next(audio_stream_iterator)
                            chunk_size = len(chunk)

                            # Copy the received audio data into the buffer provided by the audio player
                            audio_buffer[:chunk_size] = chunk

                            # Return the number of bytes written
                            return chunk_size
                        except StopIteration:
                            # When the iterator is exhausted, it raises StopIteration.
                            # We catch it and return 0 to signal the end of the stream.
                            return 0

                    await audio_player.stream_with_effects(
                        buffer_callback=buffer_callback,
                        config=sound_config,
                        wingman_name=wingman_name,
                        sample_rate=24000,
                        dtype="int16",
                        channels=1,
                        use_gain_boost=True,  # All streaming PCM TTS providers need this
                    )

        except APIStatusError as e:
            printr.toast_error(
                f"OpenAI-compatible TTS error: {e.status_code} ({e.type})"
            )
            m = re.search(
                r"'message': (?P<quote>['\"])(?P<message>.+?)(?P=quote)",
                e.message,
            )
            if m is not None:
                message = m["message"].replace(". ", ".\n")
                printr.toast_error(message)
            elif e.message:
                printr.toast_error(e.message)
            else:
                printr.toast_error(
                    "An unknown OpenAI-compatible TTS error has occurred."
                )


@stt_provider(SttProvider.OPENAI)
class OpenAiStt(SttInterface):
    """OpenAI Whisper STT via the unified interface."""

    def __init__(self, openai_instance: "OpenAi"):
        self._openai = openai_instance

    async def transcribe(self, filename: str) -> Transcript | None:
        result = self._openai.transcribe(filename=filename)
        if result is None:
            return None
        return Transcript(text=result.text)


@tts_provider(TtsProvider.OPENAI)
class OpenAiTts(TtsInterface):
    """OpenAI TTS via the unified interface."""

    def __init__(self, openai_instance: "OpenAi", config: "WingmanConfig"):
        self._openai = openai_instance
        self._config = config

    async def play_audio(self, text, sound_config, audio_player, wingman_name):
        await self._openai.play_audio(
            text=text,
            voice=self._config.openai.tts_voice,
            model=self._config.openai.tts_model,
            speed=self._config.openai.tts_speed,
            sound_config=sound_config,
            audio_player=audio_player,
            wingman_name=wingman_name,
            stream=self._config.openai.output_streaming,
        )


@llm_provider(ConversationProvider.OPENAI)
class OpenAiLlm(LlmInterface):
    """OpenAI chat completions via the unified interface."""

    def __init__(self, openai_instance: "OpenAi", config: "WingmanConfig"):
        self._openai = openai_instance
        self._config = config

    async def ask(self, messages, tools=None):
        return self._openai.ask(
            messages=messages,
            tools=tools,
            model=self._config.openai.conversation_model,
        )


@stt_provider(SttProvider.GROQ)
class GroqStt(SttInterface):
    """Groq Whisper STT (uses OpenAi-compatible client)."""

    def __init__(self, openai_instance: "OpenAi"):
        self._openai = openai_instance

    async def transcribe(self, filename: str) -> Transcript | None:
        result = self._openai.transcribe(
            filename=filename, model="whisper-large-v3-turbo"
        )
        if result is None:
            return None
        return Transcript(text=result.text)


@llm_provider(ConversationProvider.MISTRAL)
class MistralLlm(LlmInterface):
    def __init__(self, openai_instance: "OpenAi", config: "WingmanConfig"):
        self._openai = openai_instance
        self._config = config

    async def ask(self, messages, tools=None):
        return self._openai.ask(
            messages=messages, tools=tools,
            model=self._config.mistral.conversation_model,
        )


@llm_provider(ConversationProvider.GROQ)
class GroqLlm(LlmInterface):
    def __init__(self, openai_instance: "OpenAi", config: "WingmanConfig"):
        self._openai = openai_instance
        self._config = config

    async def ask(self, messages, tools=None):
        return self._openai.ask(
            messages=messages, tools=tools,
            model=self._config.groq.conversation_model,
        )


@llm_provider(ConversationProvider.CEREBRAS)
class CerebrasLlm(LlmInterface):
    def __init__(self, openai_instance: "OpenAi", config: "WingmanConfig"):
        self._openai = openai_instance
        self._config = config

    async def ask(self, messages, tools=None):
        return self._openai.ask(
            messages=messages, tools=tools,
            model=self._config.cerebras.conversation_model,
        )


@llm_provider(ConversationProvider.OPENROUTER)
class OpenRouterLlm(LlmInterface):
    def __init__(self, openai_instance: "OpenAi", config: "WingmanConfig",
                 supports_tools: bool = False):
        self._openai = openai_instance
        self._config = config
        self.supports_tools = supports_tools

    async def ask(self, messages, tools=None):
        effective_tools = tools if self.supports_tools else None
        return self._openai.ask(
            messages=messages, tools=effective_tools,
            model=self._config.openrouter.conversation_model,
        )


@llm_provider(ConversationProvider.LOCAL_LLM)
class LocalLlm(LlmInterface):
    def __init__(self, openai_instance: "OpenAi | None", config: "WingmanConfig"):
        self._openai = openai_instance
        self._config = config

    async def ask(self, messages, tools=None):
        if not self._openai:
            raise RuntimeError(
                f"Local LLM provider is not initialized. "
                f"Please check your Local LLM endpoint configuration "
                f"({self._config.local_llm.endpoint})."
            )
        return self._openai.ask(
            messages=messages, tools=tools,
            model=self._config.local_llm.conversation_model,
        )


@llm_provider(ConversationProvider.PERPLEXITY)
class PerplexityLlm(LlmInterface):
    def __init__(self, openai_instance: "OpenAi", config: "WingmanConfig"):
        self._openai = openai_instance
        self._config = config

    async def ask(self, messages, tools=None):
        return self._openai.ask(
            messages=messages, tools=tools,
            model=self._config.perplexity.conversation_model.value,
        )


@stt_provider(SttProvider.AZURE)
class AzureWhisperStt(SttInterface):
    def __init__(self, azure_instance: "OpenAiAzure", api_key: str, config: "WingmanConfig"):
        self._azure = azure_instance
        self._api_key = api_key
        self._config = config

    async def transcribe(self, filename: str) -> Transcript | None:
        result = self._azure.transcribe_whisper(
            filename=filename,
            api_key=self._api_key,
            config=self._config.azure.whisper,
        )
        if result is None:
            return None
        return Transcript(text=result.text)


@stt_provider(SttProvider.AZURE_SPEECH)
class AzureSpeechStt(SttInterface):
    def __init__(self, azure_instance: "OpenAiAzure", api_key: str, config: "WingmanConfig"):
        self._azure = azure_instance
        self._api_key = api_key
        self._config = config

    async def transcribe(self, filename: str) -> Transcript | None:
        result = self._azure.transcribe_azure_speech(
            filename=filename,
            api_key=self._api_key,
            config=self._config.azure.stt,
        )
        if result is None:
            return None
        text = result.get("_text") if isinstance(result, dict) else result.text
        return Transcript(text=text) if text else None


@tts_provider(TtsProvider.AZURE)
class AzureTts(TtsInterface):
    def __init__(self, azure_instance: "OpenAiAzure", api_key: str, config: "WingmanConfig"):
        self._azure = azure_instance
        self._api_key = api_key
        self._config = config

    async def play_audio(self, text, sound_config, audio_player, wingman_name):
        await self._azure.play_audio(
            text=text,
            api_key=self._api_key,
            config=self._config.azure.tts,
            sound_config=sound_config,
            audio_player=audio_player,
            wingman_name=wingman_name,
        )


@llm_provider(ConversationProvider.AZURE)
class AzureLlm(LlmInterface):
    def __init__(self, azure_instance: "OpenAiAzure", api_key: str, config: "WingmanConfig"):
        self._azure = azure_instance
        self._api_key = api_key
        self._config = config

    async def ask(self, messages, tools=None):
        return self._azure.ask(
            messages=messages,
            api_key=self._api_key,
            config=self._config.azure.conversation,
            tools=tools,
        )


@tts_provider(TtsProvider.OPENAI_COMPATIBLE)
class OpenAiCompatibleTtsAdapter(TtsInterface):
    def __init__(self, tts_instance: "OpenAiCompatibleTts", config: "WingmanConfig"):
        self._tts = tts_instance
        self._config = config

    async def play_audio(self, text, sound_config, audio_player, wingman_name):
        from openai import NOT_GIVEN
        await self._tts.play_audio(
            text=text,
            voice=self._config.openai_compatible_tts.voice,
            model=self._config.openai_compatible_tts.model,
            speed=(
                self._config.openai_compatible_tts.speed
                if self._config.openai_compatible_tts.speed
                else NOT_GIVEN
            ),
            sound_config=sound_config,
            audio_player=audio_player,
            wingman_name=wingman_name,
            stream=self._config.openai_compatible_tts.output_streaming,
        )
