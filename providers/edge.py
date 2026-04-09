from os import path
from typing import TYPE_CHECKING
from edge_tts import Communicate
from api.enums import TtsProvider
from api.interface import EdgeTtsConfig, SoundConfig
from providers.interfaces import TtsInterface, tts_provider
from services.audio_player import AudioPlayer
from services.file import get_writable_dir
from services.printr import Printr

if TYPE_CHECKING:
    from api.interface import WingmanConfig

RECORDING_PATH = "audio_output"
OUTPUT_FILE: str = "edge_tts.mp3"

printr = Printr()


class Edge:
    def __init__(self):
        self.random_voices = {}

    async def play_audio(
        self,
        text: str,
        config: EdgeTtsConfig,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
    ):
        communicate, output_file = await self.__generate_speech(
            text=text, voice=config.voice
        )
        audio, sample_rate = audio_player.get_audio_from_file(output_file)

        await audio_player.play_with_effects(
            input_data=(audio, sample_rate),
            config=sound_config,
            wingman_name=wingman_name,
        )

    async def __generate_speech(
        self,
        text: str,
        voice: str = "en-US-GuyNeural",
        rate: str = "+0%",
    ):
        if not text:
            return

        communicate = Communicate(text=text, voice=voice, rate=rate)
        file_path = path.join(get_writable_dir(RECORDING_PATH), OUTPUT_FILE)
        await communicate.save(file_path)

        return communicate, file_path


@tts_provider(TtsProvider.EDGE_TTS)
class EdgeTts(TtsInterface):
    def __init__(self, config: "WingmanConfig"):
        self._edge = Edge()
        self._config = config

    async def play_audio(self, text, sound_config, audio_player, wingman_name):
        await self._edge.play_audio(
            text=text,
            config=self._config.edge_tts,
            sound_config=sound_config,
            audio_player=audio_player,
            wingman_name=wingman_name,
        )
