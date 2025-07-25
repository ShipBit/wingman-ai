from abc import ABC, abstractmethod
import re
from typing import Literal, Mapping, Union
from openai import NOT_GIVEN, NotGiven, Omit, OpenAI, APIStatusError, AzureOpenAI
import azure.cognitiveservices.speech as speechsdk
from api.enums import AzureRegion

from api.interface import (
    AzureInstanceConfig,
    AzureSttConfig,
    AzureTtsConfig,
    SoundConfig,
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
            if not tools:
                completion = client.chat.completions.create(
                    stream=stream,
                    messages=messages,
                    model=model,
                )
            else:
                completion = client.chat.completions.create(
                    stream=stream,
                    messages=messages,
                    model=model,
                    tools=tools,
                    tool_choice="auto",
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
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )

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
                        sample_rate=22050,  # OpenAI TTS default for PCM is 24000 so potential incompatibility here specifically with XTTS2
                        dtype="int16",
                        channels=1,
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
