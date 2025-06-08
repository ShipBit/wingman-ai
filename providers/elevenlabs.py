import asyncio
from typing import Optional
from elevenlabslib import User, GenerationOptions, PlaybackOptions, SFXOptions
from api.enums import SoundEffect, WingmanInitializationErrorType
from api.interface import ElevenlabsConfig, SoundConfig, WingmanInitializationError
from services.audio_player import AudioPlayer
from services.sound_effects import get_sound_effects
from services.websocket_user import WebSocketUser


class ElevenLabs:
    def __init__(self, api_key: str, wingman_name: str):
        self.wingman_name = wingman_name
        self.user = User(api_key)

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
        voice = (
            self.user.get_voice_by_ID(config.voice.id)
            if config.voice.id
            else self.user.get_voices_by_name_v2(config.voice.name)[0]
        )

        def notify_playback_finished():
            audio_player.playback_events.unsubscribe("finished", playback_finished)

            contains_high_end_radio = SoundEffect.HIGH_END_RADIO in sound_config.effects
            if contains_high_end_radio:
                audio_player.play_wav_sample(
                    "Radio_Static_Beep.wav", sound_config.volume
                )

            if sound_config.play_beep:
                audio_player.play_wav_sample("beep.wav", sound_config.volume)
            elif sound_config.play_beep_apollo:
                audio_player.play_wav_sample("Apollo_Beep.wav", sound_config.volume)

            WebSocketUser.ensure_async(
                audio_player.notify_playback_finished(wingman_name)
            )

        def notify_playback_started():
            if sound_config.play_beep:
                audio_player.play_wav_sample("beep.wav", sound_config.volume)
            elif sound_config.play_beep_apollo:
                audio_player.play_wav_sample("Apollo_Beep.wav", sound_config.volume)

            contains_high_end_radio = SoundEffect.HIGH_END_RADIO in sound_config.effects
            if contains_high_end_radio:
                audio_player.play_wav_sample(
                    "Radio_Static_Beep.wav", sound_config.volume
                )

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
            model=config.model,
            latencyOptimizationLevel=config.latency,
            use_speaker_boost=config.voice_settings.use_speaker_boost,
            stability=config.voice_settings.stability,
            similarity_boost=config.voice_settings.similarity_boost,
            style=(
                config.voice_settings.style
                if config.model != "eleven_turbo_v2"
                else None
            ),
        )

        if not stream:
            # play with our audio player so that we call our started and ended callbacks
            audio_bytes, generation_info = voice.generate_audio_v3(
                prompt=text,
                generation_options=generation_options,
            )
            if audio_bytes:
                await audio_player.play_with_effects(
                    input_data=audio_bytes.result(),
                    config=sound_config,
                    wingman_name=wingman_name,
                )
        else:
            # playback using elevenlabslib
            _, _, output_stream_future, _ = voice.stream_audio_v3(
                prompt=text,
                generation_options=generation_options,
                playback_options=playback_options,
            )

            # if the user cancels the playback...
            output_stream = output_stream_future.result()

            def playback_finished(wingman_name):
                output_stream.abort()

            audio_player.playback_events.subscribe("finished", playback_finished)

    async def generate_sound_effect(
        self,
        prompt: str,
        duration_seconds: Optional[float] = None,
        prompt_influence: Optional[float] = None,
    ):
        options = SFXOptions(
            duration_seconds=duration_seconds, prompt_influence=prompt_influence
        )
        req, _ = self.user.generate_sfx(prompt, options)

        result_ready = asyncio.Event()
        audio: bytes = None

        def get_result(future: asyncio.Future[bytes]):
            nonlocal audio
            audio = future.result()
            result_ready.set()  # Signal that the result is ready

        req.add_done_callback(get_result)

        # Wait for the result to be ready
        await result_ready.wait()
        return audio

    def get_available_voices(self):
        return self.user.get_available_voices()

    def get_available_models(self):
        return self.user.get_models()

    def get_subscription_data(self):
        return self.user.get_subscription_data()
