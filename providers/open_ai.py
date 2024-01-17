from abc import ABC, abstractmethod
import re
from typing import Literal
from openai import OpenAI, APIStatusError, AzureOpenAI
import azure.cognitiveservices.speech as speechsdk
from api.enums import AzureRegion, LogType, OpenAiModel, OpenAiTtsVoice
from api.interface import (
    AzureConfig,
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
            printr.print(message, color=LogType.ERROR)
        elif api_response.message:
            printr.print(api_response.message, color=LogType.ERROR)
        else:
            printr.print(
                "The API did not provide further information.", color=LogType.ERROR
            )

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
        model: OpenAiModel,
        stream: bool,
        tools: list[dict[str, any]],
    ):
        try:
            if not tools:
                completion = client.chat.completions.create(
                    stream=stream,
                    messages=messages,
                    model=model.value,
                )
            else:
                completion = client.chat.completions.create(
                    stream=stream,
                    messages=messages,
                    model=model.value,
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
        model: OpenAiModel,
        stream: bool = False,
        tools: list[dict[str, any]] = None,
    ):
        if not model:
            model = OpenAiModel.GPT_35_TURBO_1106
        return self._perform_ask(
            client=self.client,
            messages=messages,
            model=model,
            stream=stream,
            tools=tools,
        )

    def play_audio(
        self,
        text: str,
        voice: OpenAiTtsVoice,
        sound_config: SoundConfig,
    ):
        try:
            if not voice:
                voice = OpenAiTtsVoice.NOVA

            response = self.client.audio.speech.create(
                model="tts-1",
                voice=voice.value,
                input=text,
            )
            if response is not None:
                audio_player = AudioPlayer()
                audio_player.stream_with_effects(
                    input_data=response.content, config=sound_config
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

    def transcribe(
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

    def transcribe_with_azure(
        self, filename: str, api_key: str, config: AzureSttConfig
    ):
        speech_config = speechsdk.SpeechConfig(
            subscription=api_key,
            region=config.region.value,
        )
        audio_config = speechsdk.AudioConfig(filename=filename)

        auto_detect_source_language_config = (
            speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
                languages=config.languages
            )
        ) if len(config.languages) > 1 else None

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
        config: AzureConfig,
        model: OpenAiModel,
        stream: bool = False,
        tools: list[dict[str, any]] = None,
    ):
        azure_client = self._create_client(api_key=api_key, config=config)
        if not model:
            model = OpenAiModel.GPT_35_TURBO_1106
        return self._perform_ask(
            client=azure_client,
            messages=messages,
            model=model,
            stream=stream,
            tools=tools,
        )

    def play_audio(
        self,
        text: str,
        api_key: str,
        config: AzureTtsConfig,
        sound_config: SoundConfig,
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

        result = speech_synthesizer.speak_text_async(text).get()
        if result is not None:
            audio_player = AudioPlayer()
            audio_player.stream_with_effects(
                input_data=result.audio_data, config=sound_config
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
