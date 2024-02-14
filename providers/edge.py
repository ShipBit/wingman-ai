from os import path
from edge_tts import Communicate
from api.interface import EdgeTtsConfig, SoundConfig
from services.audio_player import AudioPlayer
from services.file import get_writable_dir
from services.printr import Printr

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
