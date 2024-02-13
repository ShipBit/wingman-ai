import openai
import requests
from api.enums import AzureRegion, LogType, OpenAiModel, OpenAiTtsVoice
from api.interface import (
    AzureSttConfig,
    AzureTtsConfig,
    SoundConfig,
    WingmanProConfig,
)
from services.audio_player import AudioPlayer
from services.printr import Printr

printr = Printr()


class WingmanPro:
    def __init__(self, wingman_name: str):
        self.wingman_name: str = wingman_name

    def transcribe(self, filename: str, api_key: str, config: AzureSttConfig):
        pass
        # speech_config = speechsdk.SpeechConfig(
        #     subscription=api_key,
        #     region=config.region.value,
        # )
        # audio_config = speechsdk.AudioConfig(filename=filename)

        # auto_detect_source_language_config = (
        #     (
        #         speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
        #             languages=config.languages
        #         )
        #     )
        #     if len(config.languages) > 1
        #     else None
        # )

        # language = config.languages[0] if len(config.languages) == 1 else None

        # speech_recognizer = speechsdk.SpeechRecognizer(
        #     speech_config=speech_config,
        #     audio_config=audio_config,
        #     language=language,
        #     auto_detect_source_language_config=auto_detect_source_language_config,
        # )
        # return speech_recognizer.recognize_once_async().get()

    def ask(
        self,
        messages: list[dict[str, str]],
        model: OpenAiModel,
        config: WingmanProConfig,
        stream: bool = False,
        tools: list[dict[str, any]] = None,
    ):
        data = {
            "messages": messages,
            "model": model.value,
            "stream": stream,
            "tools": tools,
        }
        response = requests.post(
            url=f"{config.base_url}/ask?region={config.region.value}",
            json=data,
            timeout=10,
        )
        response.raise_for_status()
        json = response.json()
        completion = openai.types.chat.ChatCompletion.model_validate(json)
        return completion

    def play_audio(
        self,
        text: str,
        api_key: str,
        config: AzureTtsConfig,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
    ):
        pass
        # speech_config = speechsdk.SpeechConfig(
        #     subscription=api_key,
        #     region=config.region.value,
        # )

        # speech_config.speech_synthesis_voice_name = config.voice

        # speech_synthesizer = speechsdk.SpeechSynthesizer(
        #     speech_config=speech_config,
        #     audio_config=None,
        # )

        # result = speech_synthesizer.speak_text_async(text).get()
        # if result is not None:
        #     audio_player.stream_with_effects(
        #         input_data=result.audio_data,
        #         config=sound_config,
        #         wingman_name=wingman_name,
        #     )

    def get_available_voices(self, api_key: str, region: AzureRegion, locale: str = ""):
        pass
        # speech_config = speechsdk.SpeechConfig(subscription=api_key, region=region)
        # speech_synthesizer = speechsdk.SpeechSynthesizer(
        #     speech_config=speech_config, audio_config=None
        # )
        # result = speech_synthesizer.get_voices_async(locale).get()

        # if result.reason == speechsdk.ResultReason.VoicesListRetrieved:
        #     return result.voices
        # if result.reason == speechsdk.ResultReason.Canceled:
        #     printr.toast_error(
        #         f"Unable to retrieve Azure voices: {result.error_details}"
        #     )
        # return None
