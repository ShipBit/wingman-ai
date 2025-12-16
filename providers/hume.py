import base64
from os import path
import aiofiles
from hume.client import AsyncHumeClient
from hume.tts import (
    PostedUtterance,
    PostedUtteranceVoiceWithId,
    PostedContextWithGenerationId,
)
from api.interface import (
    HumeConfig,
    SoundConfig,
    VoiceInfo,
    WingmanInitializationError,
)
from providers.provider_base import (
    BaseProvider,
    ProviderCapability,
    capabilities,
    TtsProvider,
)
from services.audio_player import AudioPlayer
from services.file import get_writable_dir
from services.printr import Printr
from services.secret_keeper import SecretKeeper

RECORDING_PATH = "audio_output"
OUTPUT_FILE: str = "hume.mp3"


@capabilities(ProviderCapability.TTS)
class Hume(BaseProvider, TtsProvider):
    """Hume AI TTS provider with emotional expression."""

    def __init__(self, config: HumeConfig, api_key: str, wingman_name: str):
        BaseProvider.__init__(self, config=config, api_key=api_key)
        self.hume = AsyncHumeClient(api_key=api_key)
        self.wingman_name = wingman_name
        self.secret_keeper = SecretKeeper()
        self.printr = Printr()
        # needed for continuity in the TTS voice output
        self.generation_id = ""

    async def __aenter__(self):
        return self

    def validate_config(
        self, config: HumeConfig, errors: list[WingmanInitializationError]
    ):
        return errors

    # Protocol implementation: TtsProvider
    async def synthesize(
        self,
        text: str,
        audio_player: AudioPlayer,
        sound_config: SoundConfig,
        wingman_name: str,
        **kwargs
    ) -> None:
        """Synthesize speech using Hume AI.

        Args:
            text: Text to convert to speech
            audio_player: AudioPlayer instance for playback
            sound_config: Sound configuration
            wingman_name: Name of wingman
            **kwargs: Unused (kept for protocol compatibility)

        Returns:
            None - Audio is played directly via audio_player
        """
        config = self.config
        speech = await self.hume.tts.synthesize_json(
            utterances=[
                PostedUtterance(
                    text=text,
                    description=(config.description if config.description else None),
                    voice=PostedUtteranceVoiceWithId(
                        id=config.voice.id,
                        provider=config.voice.provider,
                    ),
                )
            ],
            context=(
                PostedContextWithGenerationId(generation_id=self.generation_id)
                if self.generation_id
                else None
            ),
        )
        self.generation_id = speech.generations[0].generation_id

        output_file = await self.__write_result_to_file(speech.generations[0].audio)
        audio, sample_rate = audio_player.get_audio_from_file(output_file)

        await audio_player.play_with_effects(
            input_data=(audio, sample_rate),
            config=sound_config,
            wingman_name=wingman_name,
        )

    async def get_available_voices(self):
        voices: list[VoiceInfo] = []

        custom_voices = await self.hume.tts.voices.list(provider="CUSTOM_VOICE")
        for voice in custom_voices.items:
            voices.append(
                VoiceInfo(
                    id=voice.id,
                    name=voice.name,
                    provider=voice.provider,
                )
            )

        default_voices = await self.hume.tts.voices.list(provider="HUME_AI")
        for voice in default_voices.items:
            voices.append(
                VoiceInfo(
                    id=voice.id,
                    name=voice.name,
                    provider=voice.provider,
                )
            )

        return voices

    async def __write_result_to_file(self, base64_encoded_audio: str):
        file_path = path.join(get_writable_dir(RECORDING_PATH), OUTPUT_FILE)
        audio_data = base64.b64decode(base64_encoded_audio)
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(audio_data)
        return file_path
