from elevenlabslib import (
    ElevenLabsUser,
    GenerationOptions,
    PlaybackOptions,
)
from api.enums import ElevenlabsModel, WingmanInitializationErrorType
from api.interface import ElevenlabsConfig, SoundConfig, WingmanInitializationError
from services.audio_player import AudioPlayer
from services.secret_keeper import SecretKeeper
from services.sound_effects import get_sound_effects


class ElevenLabs:
    def __init__(self, api_key: str, wingman_name: str):
        self.api_key = api_key
        self.wingman_name = wingman_name
        self.secret_keeper = SecretKeeper()

    def validate_config(
        self, config: ElevenlabsConfig, errors: list[WingmanInitializationError]
    ):
        if not errors:
            errors = []

        # TODO: Let Pydantic check that with a custom validator
        if not config.voice.id and not config.voice.name:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman_name,
                    message="Missing 'id' or 'name' in 'voice' section of 'elevenlabs' config. Please provide a valid name or id for the voice in your config.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        return errors

    def play_audio(
        self,
        text: str,
        config: ElevenlabsConfig,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
    ):
        user = ElevenLabsUser(self.api_key)
        voice = (
            user.get_voice_by_ID(config.voice.id)
            if config.voice.id
            else user.get_voices_by_name(config.voice.name)[0]
        )

        sound_effects = get_sound_effects(sound_config)

        def audio_post_processor(audio_chunk, sample_rate):
            for sound_effect in sound_effects:
                audio_chunk = sound_effect(audio_chunk, sample_rate, reset=False)

            return audio_chunk

        # todo: add start/end callbacks to play Quindar beep even if use_sound_effects is disabled
        playback_options = PlaybackOptions(runInBackground=True)
        if len(sound_effects) > 0:
            playback_options.audioPostProcessor = audio_post_processor

        generation_options = GenerationOptions(
            model=config.model.value,
            latencyOptimizationLevel=config.latency,
            use_speaker_boost=config.voice_settings.use_speaker_boost,
            stability=config.voice_settings.stability,
            similarity_boost=config.voice_settings.similarity_boost,
            style=(
                config.voice_settings.style
                if config.model != ElevenlabsModel.ELEVEN_TURBO_V2
                else None
            ),
        )

        voice.generate_stream_audio_v2(
            prompt=text,
            generationOptions=generation_options,
            playbackOptions=playback_options,
        )

        return

        if sound_config.play_beep or len(sound_config.effects) > 0:
            # play with effects - slower
            audio_bytes, _history_id = voice.generate_audio_v2(
                prompt=text,
                generationOptions=generation_options,
            )
            if audio_bytes:
                audio_player.stream_with_effects(
                    input_data=audio_bytes,
                    config=sound_config,
                    wingman_name=wingman_name,
                )
        else:
            voice.generate_stream_audio_v2(
                prompt=text,
                playbackOptions=playback_options,
                generationOptions=generation_options,
            )

    def get_available_voices(self):
        user = ElevenLabsUser(self.api_key)
        return user.get_available_voices()
