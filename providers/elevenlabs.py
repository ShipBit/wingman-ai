from elevenlabslib import (
    ElevenLabsUser,
    GenerationOptions,
    PlaybackOptions,
)
from api.enums import ElevenlabsModel, WingmanInitializationErrorType
from api.interface import ElevenlabsConfig, SoundConfig, WingmanInitializationError
from services.audio_player import AudioPlayer
from services.secret_keeper import SecretKeeper


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
        self, text: str, config: ElevenlabsConfig, sound_config: SoundConfig
    ):
        user = ElevenLabsUser(self.api_key)
        voice = (
            user.get_voice_by_ID(config.voice.id)
            if config.voice.id
            else user.get_voices_by_name(config.voice.name)[0]
        )

        # todo: add start/end callbacks to play Quindar beep even if use_sound_effects is disabled
        playback_options = PlaybackOptions(runInBackground=True)
        generation_options = GenerationOptions(
            model=config.model.value,
            latencyOptimizationLevel=config.latency,
            use_speaker_boost=config.voice_settings.use_speaker_boost,
            stability=config.voice_settings.stability,
            similarity_boost=config.voice_settings.similarity_boost,
            style=config.voice_settings.style
            if config.model != ElevenlabsModel.ELEVEN_TURBO_V2
            else None,
        )

        if config.use_sound_effects:
            audio_bytes, _history_id = voice.generate_audio_v2(
                prompt=text,
                generationOptions=generation_options,
            )
            if audio_bytes:
                audio_player = AudioPlayer()
                audio_player.stream_with_effects(
                    input_data=audio_bytes, config=sound_config
                )
        else:
            voice.generate_stream_audio_v2(
                prompt=text,
                playbackOptions=playback_options,
                generationOptions=generation_options,
            )
