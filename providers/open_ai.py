from abc import ABC, abstractmethod
import json
import re
from typing import Literal
import httpx
from openai import NOT_GIVEN, OpenAI, APIStatusError, AzureOpenAI
from openai.types.chat import ChatCompletion
import azure.cognitiveservices.speech as speechsdk
from api.enums import AzureRegion, LogType
from services.openai_utils import get_minimal_reasoning_by_model

from api.interface import (
    AzureInstanceConfig,
    AzureSttConfig,
    AzureTtsConfig,
    OpenAiConfig,
    SoundConfig,
    VoiceInfo,
)
from providers.provider_base import (
    BaseProvider,
    ProviderCapability,
    capabilities,
    SttProvider,
    TtsProvider,
    LlmProvider,
)
from services.audio_player import AudioPlayer
from services.printr import Printr

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
            reasoning_params = get_minimal_reasoning_by_model(model) if model else {}

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


@capabilities(ProviderCapability.STT, ProviderCapability.TTS, ProviderCapability.LLM)
class OpenAi(BaseProvider, BaseOpenAi, SttProvider, TtsProvider, LlmProvider):
    """OpenAI provider supporting STT (Whisper), TTS, and LLM (GPT models).

    This provider implements all three capabilities using OpenAI's API.
    """

    def __init__(
        self,
        config: OpenAiConfig,
        api_key: str,
        base_url: str | None = None,
        organization: str | None = None,
    ):
        # Initialize BaseProvider with config and api_key
        BaseProvider.__init__(self, config=config, api_key=api_key)
        # Initialize BaseOpenAi (no __init__ but needed for MRO)
        BaseOpenAi.__init__(self)

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

    # Protocol implementation: SttProvider
    async def transcribe(self, audio_input_wav: str, **kwargs) -> str:
        """Transcribe audio file to text using Whisper.

        Args:
            audio_input_wav: Path to WAV audio file
            **kwargs: Additional parameters (model, prompt, language)

        Returns:
            Transcribed text string or None on failure
        """
        model = kwargs.get("model", "whisper-1")
        result = self._perform_transcription(
            client=self.client, filename=audio_input_wav, model=model
        )
        return result.text if result else None

    # Protocol implementation: LlmProvider
    async def complete(
        self, messages: list[dict], tools: list[dict] = None, **kwargs
    ) -> ChatCompletion | None:
        """Generate completion using GPT models.

        Args:
            messages: List of message dicts with 'role' and 'content'
            tools: Optional list of tool definitions for function calling
            **kwargs: Additional parameters (model, temperature, stream, etc.)

        Returns:
            ChatCompletion object from OpenAI API, or None on error
        """
        model = kwargs.get("model", self.config.conversation_model)
        stream = kwargs.get("stream", False)

        return self._perform_ask(
            client=self.client,
            messages=messages,
            model=model,
            stream=stream,
            tools=tools,
        )

    # Protocol implementation: TtsProvider
    async def synthesize(
        self,
        text: str,
        audio_player: AudioPlayer,
        sound_config: SoundConfig,
        wingman_name: str,
        **kwargs,
    ) -> None:
        """Synthesize speech from text using OpenAI TTS.

        Args:
            text: Text to convert to speech
            audio_player: AudioPlayer instance for playback
            sound_config: Sound configuration with voice settings
            wingman_name: Name of wingman (for audio file naming)
            **kwargs: Additional parameters (voice, model, speed, stream)

        Returns:
            None - Audio is played directly via audio_player
        """
        voice = kwargs.get("voice", self.config.tts_voice)
        model = kwargs.get("model", self.config.tts_model)
        speed = kwargs.get("speed", self.config.tts_speed)
        stream = kwargs.get("stream", self.config.output_streaming)

        try:
            if not stream:
                # Non-streaming implementation
                response = self.client.audio.speech.create(
                    input=text,
                    model=model,
                    voice=voice,
                    speed=speed,
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
                ) as response:
                    audio_stream_iterator = response.iter_bytes(chunk_size=1024)

                    def buffer_callback(audio_buffer):
                        try:
                            chunk = next(audio_stream_iterator)
                            chunk_size = len(chunk)
                            audio_buffer[:chunk_size] = chunk
                            return chunk_size
                        except StopIteration:
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
            self._handle_api_error(e)


@capabilities(ProviderCapability.LLM)
class OpenRouter(OpenAi):
    """OpenRouter provider extending OpenAi with tool support detection.

    OpenRouter models have varying tool/function calling support. This provider
    checks the model's capabilities during initialization and automatically
    strips tools from requests when the model doesn't support them.
    """

    def __init__(
        self,
        config: OpenAiConfig,
        api_key: str,
        base_url: str | None = None,
        organization: str | None = None,
    ):
        # Initialize parent OpenAi class
        super().__init__(
            config=config,
            api_key=api_key,
            base_url=base_url,
            organization=organization,
        )

        # Check if the configured model supports tools
        self.model_supports_tools = False
        self._check_tool_support()

    def _check_tool_support(self):
        """Check if the configured OpenRouter model supports tools."""
        import requests

        model_id = self.config.conversation_model
        if not model_id:
            return

        try:
            response = requests.get(
                url=f"https://openrouter.ai/api/v1/models/{model_id}/endpoints",
                timeout=10,
            )
            response.raise_for_status()

            # Parse the endpoint capabilities
            from api.interface import OpenRouterEndpointResult

            content = response.json()
            result = OpenRouterEndpointResult(**content.get("data", {}))

            # Check if any endpoint supports both tools and tool_choice parameters
            self.model_supports_tools = any(
                all(
                    p in endpoint.supported_parameters for p in ["tools", "tool_choice"]
                )
                for endpoint in result.endpoints
            )

            if not self.model_supports_tools:
                printr.print(
                    f"OpenRouter model {model_id} does not support tools, they will be omitted from calls.",
                    server_only=True,
                )
        except Exception as e:
            printr.print(
                f"Failed to check OpenRouter tool support: {str(e)}",
                server_only=True,
            )

    async def complete(
        self, messages: list[dict], tools: list[dict] = None, **kwargs
    ) -> ChatCompletion | None:
        """Generate completion, automatically stripping tools if model doesn't support them.

        Args:
            messages: List of message dicts with 'role' and 'content'
            tools: Optional list of tool definitions for function calling
            **kwargs: Additional parameters (model, temperature, stream, etc.)

        Returns:
            ChatCompletion object from OpenAI API, or None on error
        """
        # Strip tools if model doesn't support them
        if not self.model_supports_tools and tools:
            tools = None

        # Call parent implementation
        return await super().complete(messages=messages, tools=tools, **kwargs)


@capabilities(ProviderCapability.STT, ProviderCapability.TTS, ProviderCapability.LLM)
class OpenAiAzure(BaseProvider, BaseOpenAi, SttProvider, TtsProvider, LlmProvider):
    """Azure provider supporting STT (Whisper + Speech), TTS, and LLM.

    Azure has multiple services that can use different API keys:
    - Whisper STT (uses Azure OpenAI instance)
    - Speech STT (uses Azure Cognitive Services)
    - TTS (uses Azure Cognitive Services)
    - LLM (uses Azure OpenAI instance)

    This provider stores all configs and keys, selecting the appropriate one
    based on which method is called.
    """

    def __init__(
        self,
        config,  # Can be AzureConfig or just the parent config object
        whisper_api_key: str = None,
        speech_api_key: str = None,
        tts_api_key: str = None,
        llm_api_key: str = None,
    ):
        # Initialize BaseProvider (config can be complex Azure config)
        BaseProvider.__init__(self, config=config, api_key=None)
        BaseOpenAi.__init__(self)

        # Store individual service keys
        self.whisper_api_key = whisper_api_key
        self.speech_api_key = speech_api_key
        self.tts_api_key = tts_api_key
        self.llm_api_key = llm_api_key

        # Extract Azure-specific configs if available
        if hasattr(config, "azure") and config.azure:
            self.instance_config = (
                config.azure.instance if hasattr(config.azure, "instance") else None
            )
            self.stt_config = config.azure.stt if hasattr(config.azure, "stt") else None
            self.tts_config = config.azure.tts if hasattr(config.azure, "tts") else None
        else:
            self.instance_config = None
            self.stt_config = None
            self.tts_config = None

    def _create_client(self, api_key: str, config: AzureInstanceConfig):
        """Create an AzureOpenAI client with the given parameters."""
        return AzureOpenAI(
            api_key=api_key,
            azure_endpoint=config.api_base_url,
            api_version=config.api_version.value,
            azure_deployment=config.deployment_name,
        )

    # Protocol implementation: SttProvider
    async def transcribe(self, audio_input_wav: str, **kwargs) -> str:
        """Transcribe audio using Azure Whisper or Speech service.

        Args:
            audio_input_wav: Path to WAV audio file
            **kwargs: Additional parameters
                - use_speech: If True, use Azure Speech service instead of Whisper
                - model: Model name for Whisper

        Returns:
            Transcribed text string or None on failure
        """
        use_speech = kwargs.get("use_speech", False)

        if use_speech and self.speech_api_key and self.stt_config:
            # Use Azure Speech STT
            speech_config = speechsdk.SpeechConfig(
                subscription=self.speech_api_key,
                region=self.stt_config.region.value,
            )
            audio_config = speechsdk.AudioConfig(filename=audio_input_wav)

            auto_detect_source_language_config = (
                speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
                    languages=self.stt_config.languages
                )
                if len(self.stt_config.languages) > 1
                else None
            )

            language = (
                self.stt_config.languages[0]
                if len(self.stt_config.languages) == 1
                else None
            )

            speech_recognizer = speechsdk.SpeechRecognizer(
                speech_config=speech_config,
                audio_config=audio_config,
                language=language,
                auto_detect_source_language_config=auto_detect_source_language_config,
            )
            result = speech_recognizer.recognize_once_async().get()
            return result.text if result and hasattr(result, "text") else None
        else:
            # Use Azure Whisper STT
            if self.whisper_api_key and self.instance_config:
                model = kwargs.get("model", "whisper-1")
                whisper_client = self._create_client(
                    api_key=self.whisper_api_key, config=self.instance_config
                )
                result = self._perform_transcription(
                    client=whisper_client,
                    filename=audio_input_wav,
                    model=model,
                )
                return result.text if result else None
        return None

    # Protocol implementation: LlmProvider
    async def complete(
        self, messages: list[dict], tools: list[dict] = None, **kwargs
    ) -> ChatCompletion | None:
        """Generate completion using Azure GPT models.

        Args:
            messages: List of message dicts with 'role' and 'content'
            tools: Optional list of tool definitions for function calling
            **kwargs: Additional parameters (model, temperature, stream, etc.)

        Returns:
            ChatCompletion object from Azure OpenAI API, or None on error
        """
        stream = kwargs.get("stream", False)
        if self.llm_api_key and self.instance_config:
            azure_client = self._create_client(
                api_key=self.llm_api_key, config=self.instance_config
            )
            return self._perform_ask(
                client=azure_client,
                messages=messages,
                model=self.instance_config.deployment_name,
                stream=stream,
                tools=tools,
            )
        return None

    # Protocol implementation: TtsProvider
    async def synthesize(
        self,
        text: str,
        audio_player: AudioPlayer,
        sound_config: SoundConfig,
        wingman_name: str,
        **kwargs,
    ) -> None:
        """Synthesize speech from text using Azure TTS.

        Args:
            text: Text to convert to speech
            audio_player: AudioPlayer instance for playback
            sound_config: Sound configuration with voice settings
            wingman_name: Name of wingman (for audio file naming)

        Returns:
            None - Audio is played directly via audio_player
        """
        if not self.tts_api_key or not self.tts_config:
            return

        speech_config = speechsdk.SpeechConfig(
            subscription=self.tts_api_key,
            region=self.tts_config.region.value,
        )
        speech_config.speech_synthesis_voice_name = self.tts_config.voice

        speech_synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=None,
        )

        result = (
            speech_synthesizer.start_speaking_text_async(text).get()
            if self.tts_config.output_streaming
            else speech_synthesizer.speak_text_async(text).get()
        )

        if result is not None:
            if self.tts_config.output_streaming:
                audio_data_stream = speechsdk.AudioDataStream(result)

                def buffer_callback(audio_buffer):
                    buffer = bytes(2048)
                    size = audio_data_stream.read_data(buffer)
                    audio_buffer[:size] = buffer
                    return size

                await audio_player.stream_with_effects(
                    buffer_callback,
                    sound_config,
                    wingman_name,
                    use_gain_boost=True,
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


@capabilities(ProviderCapability.TTS)
class OpenAiCompatibleTts(BaseProvider, TtsProvider):
    """OpenAI-compatible TTS provider.

    Works with any TTS API that follows OpenAI's speech endpoint format.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
    ):
        super().__init__()
        self._api_key = api_key
        self._base_url = base_url
        # Create a minimal config object for BaseProvider
        from types import SimpleNamespace

        config = SimpleNamespace(base_url=base_url)
        BaseProvider.__init__(self, config=config, api_key=api_key)

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

    # Protocol implementation: TtsProvider
    async def synthesize(
        self,
        text: str,
        audio_player: AudioPlayer,
        sound_config: SoundConfig,
        wingman_name: str,
        **kwargs,
    ) -> None:
        """Synthesize speech from text using OpenAI-compatible API.

        Args:
            text: Text to convert to speech
            audio_player: AudioPlayer instance for playback
            sound_config: Sound configuration with voice settings
            wingman_name: Name of wingman (for audio file naming)
            **kwargs: Additional parameters (voice, model, speed, stream, response_format, extra_headers)

        Returns:
            None - Audio is played directly via audio_player
        """
        voice = kwargs.get("voice", "alloy")
        model = kwargs.get("model", "tts-1")
        speed = kwargs.get("speed", NOT_GIVEN)
        stream = kwargs.get("stream", False)
        response_format = kwargs.get("response_format", NOT_GIVEN)
        extra_headers = kwargs.get("extra_headers", None)

        try:
            if not stream:
                # Non-streaming implementation
                response = self.client.audio.speech.create(
                    input=text,
                    model=model,
                    voice=voice,
                    speed=speed,
                    response_format=response_format,
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
                    extra_headers=extra_headers,
                ) as response:
                    audio_stream_iterator = response.iter_bytes(chunk_size=1024)

                    def buffer_callback(audio_buffer):
                        try:
                            chunk = next(audio_stream_iterator)
                            chunk_size = len(chunk)
                            audio_buffer[:chunk_size] = chunk
                            return chunk_size
                        except StopIteration:
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
