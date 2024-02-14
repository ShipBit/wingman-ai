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
from services.websocket_user import WebSocketUser


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

    async def play_audio(
        self,
        text: str,
        config: ElevenlabsConfig,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
        stream: bool,
    ):
        user = ElevenLabsUser(self.api_key)
        voice = (
            user.get_voice_by_ID(config.voice.id)
            if config.voice.id
            else user.get_voices_by_name(config.voice.name)[0]
        )

        def notify_playback_finished():
            if sound_config.play_beep:
                audio_player.play_beep()
            WebSocketUser.ensure_async(
                audio_player.notify_playback_finished(wingman_name)
            )

        def notify_playback_started():
            if sound_config.play_beep:
                audio_player.play_beep()
            WebSocketUser.ensure_async(
                audio_player.notify_playback_started(wingman_name)
            )

        sound_effects = get_sound_effects(sound_config)

        def audio_post_processor(audio_chunk, sample_rate):
            for sound_effect in sound_effects:
                audio_chunk = sound_effect(audio_chunk, sample_rate, reset=False)

            return audio_chunk

        playback_options = (
            PlaybackOptions(
                runInBackground=True,
                onPlaybackStart=notify_playback_started,
                onPlaybackEnd=notify_playback_finished,
            )
            if stream
            else PlaybackOptions(runInBackground=True)
        )

        if stream and len(sound_effects) > 0:
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

        if not stream and (sound_config.play_beep or len(sound_config.effects) > 0):
            # play with effects - slower
            audio_bytes, _history_id = voice.generate_audio_v2(
                prompt=text,
                generationOptions=generation_options,
            )
            if audio_bytes:
                await audio_player.play_with_effects(
                    input_data=audio_bytes,
                    config=sound_config,
                    wingman_name=wingman_name,
                )
        else:
            voice.generate_stream_audio_v2(
                prompt=text,
                generationOptions=generation_options,
                playbackOptions=playback_options,
            )

    def get_available_voices(self):
        user = ElevenLabsUser(self.api_key)
        return user.get_available_voices()
