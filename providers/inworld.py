import base64
from os import path
import requests
from typing import Optional
import aiofiles
from api.interface import (
    SoundConfig,
    VoiceInfo,
    WingmanInitializationError,
    InworldConfig,
)
from services.audio_player import AudioPlayer
from services.file import get_writable_dir
from services.printr import Printr
from services.secret_keeper import SecretKeeper

RECORDING_PATH = "audio_output"
OUTPUT_FILE: str = "inworld.mp3"


class Inworld:
    def __init__(self, api_key: str, wingman_name: str):
        self.wingman_name = wingman_name
        self.secret_keeper = SecretKeeper()
        self.printr = Printr()
        self.headers = {
            "Authorization": "Basic " + api_key,
            "Content-Type": "application/json",
        }

    def validate_config(
        self, config: InworldConfig, errors: list[WingmanInitializationError]
    ):
        return errors

    async def play_audio(
        self,
        text: str,
        config: InworldConfig,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
    ):
        payload = {
            "text": text,
            "voiceId": config.voice_id,
            "modelId": config.model_id,
            "audioConfig": config.audio_config,
            "temperature": config.temperature,
        }
        response = requests.request(
            "POST",
            config.tts_endpoint,
            headers=self.headers,
            json=payload,
        )
        output_file = await self.__write_result_to_file(response.text)
        audio, sample_rate = audio_player.get_audio_from_file(output_file)

        await audio_player.play_with_effects(
            input_data=(audio, sample_rate),
            config=sound_config,
            wingman_name=wingman_name,
        )

    async def get_available_voices(
        self, filter_language: Optional[str] = None
    ) -> list[VoiceInfo]:
        voices: list[VoiceInfo] = []
        params = None
        if filter_language:
            params = {"filter": f"language={filter}"}

        response = requests.get(
            "https://api.inworld.ai/tts/v1/voices", headers=self.headers, params=params
        )
        response_data = response.json()
        for voice in response_data.voices:
            voices.append(VoiceInfo(id=voice.voiceId, name=voice.voiceId))
        return voices

    async def __write_result_to_file(self, base64_encoded_audio: str):
        file_path = path.join(get_writable_dir(RECORDING_PATH), OUTPUT_FILE)
        audio_data = base64.b64decode(base64_encoded_audio)
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(audio_data)
        return file_path
