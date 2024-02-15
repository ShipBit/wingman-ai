import openai
import requests
from api.enums import (
    LogType,
    OpenAiModel,
)
from api.interface import (
    SoundConfig,
    WingmanProConfig,
    WingmanProSettings,
)
from services.printr import Printr


class WingmanPro:
    def __init__(self, wingman_name: str, settings: WingmanProSettings):
        self.wingman_name: str = wingman_name
        self.settings: WingmanProSettings = settings
        self.printr = Printr()

    def transcribe(self, filename: str, config: WingmanProConfig):
        with open(filename, "rb") as audio_input:
            files = {"audio_file": (filename, audio_input)}
            response = requests.post(
                url=f"{self.settings.base_url}/transcribe-{config.stt_provider.value}",
                params={"region": self.settings.region.value},
                files=files,
                # timeout=30,
            )
            response.raise_for_status()
            json = response.json()
            transcription = openai.types.audio.Transcription.model_validate(json)
            return transcription

    def ask(
        self,
        messages: list[dict[str, str]],
        model: OpenAiModel,
        stream: bool = False,
        tools: list[dict[str, any]] = None,
    ):
        serialized_messages = []
        for message in messages:
            if isinstance(message, openai.types.chat.ChatCompletionMessage):
                message_dict = self.__remove_nones(message.dict())
                serialized_messages.append(message_dict)
            else:
                serialized_messages.append(message)

        data = {
            "messages": serialized_messages,
            "model": model.value,
            "stream": stream,
            "tools": tools,
        }
        response = requests.post(
            url=f"{self.settings.base_url}/ask",
            params={"region": self.settings.region.value},
            json=data,
            timeout=10,
        )
        response.raise_for_status()

        json_response = response.json()
        completion = openai.types.chat.ChatCompletion.model_validate(json_response)
        return completion

    def __remove_nones(self, obj):
        """Recursive function to remove None values from a data structure."""
        if isinstance(obj, (list, tuple, set)):
            return type(obj)(self.__remove_nones(x) for x in obj if x is not None)
        elif isinstance(obj, dict):
            return type(obj)(
                (k, self.__remove_nones(v)) for k, v in obj.items() if v is not None
            )
        else:
            return obj

    # def play_audio(
    #     self,
    #     text: str,
    #     api_key: str,
    #     config: AzureTtsConfig,
    #     sound_config: SoundConfig,
    #     audio_player: AudioPlayer,
    #     wingman_name: str,
    # ):
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

    # def get_available_voices(self, api_key: str, region: AzureRegion, locale: str = ""):
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
