from os import path
from edge_tts import Communicate
from api.interface import EdgeTtsConfig, SoundConfig
from providers.provider_base import (
    BaseProvider,
    ProviderCapability,
    capabilities,
    TtsProvider,
)
from services.audio_player import AudioPlayer
from services.file import get_writable_dir
from services.printr import Printr

RECORDING_PATH = "audio_output"
OUTPUT_FILE: str = "edge_tts.mp3"

printr = Printr()


@capabilities(ProviderCapability.TTS)
class Edge(BaseProvider, TtsProvider):
    """Edge TTS provider using Microsoft Edge's free text-to-speech."""

    def __init__(self, config: EdgeTtsConfig):
        BaseProvider.__init__(self, config=config, api_key=None)
        self.random_voices = {}

    # Protocol implementation: TtsProvider
    async def synthesize(
        self,
        text: str,
        audio_player: AudioPlayer,
        sound_config: SoundConfig,
        wingman_name: str,
        **kwargs
    ) -> None:
        """Synthesize speech using Edge TTS.

        Args:
            text: Text to convert to speech
            audio_player: AudioPlayer instance for playback
            sound_config: Sound configuration
            wingman_name: Name of wingman
            **kwargs: Unused (kept for protocol compatibility)

        Returns:
            None - Audio is played directly via audio_player
        """
        communicate, output_file = await self.__generate_speech(
            text=text, voice=self.config.voice
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
