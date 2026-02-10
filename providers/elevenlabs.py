import asyncio
from typing import Callable, Optional
import requests
from threading import Event, Thread
import numpy as np
import sounddevice as sd
from elevenlabslib import User, GenerationOptions, PlaybackOptions, SFXOptions
from api.enums import LogType, SoundEffect, WingmanInitializationErrorType
from api.interface import ElevenlabsConfig, SoundConfig, WingmanInitializationError
from services.audio_player import AudioPlayer
from services.printr import Printr
from services.sound_effects import get_sound_effects
from services.websocket_user import WebSocketUser


class ElevenLabs:
    def __init__(self, api_key: str, wingman_name: str):
        self.wingman_name = wingman_name
        self.user = User(api_key)
        self.printr = Printr()
        self.api_key = api_key

    def _quantize_stability(self, stability: float) -> float:
        if stability <= 0.25:
            return 0.0
        if stability <= 0.75:
            return 0.5
        return 1.0

    def _get_voice_id(self, voice, config: ElevenlabsConfig) -> str:
        if config.voice.id:
            return config.voice.id

        voice_id = getattr(voice, "voiceID", None) or getattr(voice, "voice_id", None)
        if not voice_id:
            raise ValueError("Unable to resolve ElevenLabs voice ID.")

        return voice_id

    async def _generate_audio_direct(
        self,
        text: str,
        config: ElevenlabsConfig,
        voice_id: str,
    ) -> bytes:
        stability = self._quantize_stability(config.voice_settings.stability)

        payload = {
            "text": text,
            "model_id": config.model,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": config.voice_settings.similarity_boost,
                "style": config.voice_settings.style,
                "use_speaker_boost": config.voice_settings.use_speaker_boost,
            },
        }

        headers = {
            "xi-api-key": self.api_key,
            "accept": "audio/mpeg",
            "content-type": "application/json",
        }

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        params = {"output_format": "mp3_44100_192"}

        response = await asyncio.to_thread(
            requests.post,
            url,
            headers=headers,
            json=payload,
            params=params,
            timeout=60,
        )
        if response.status_code >= 400:
            self.printr.print(
                f"ElevenLabs direct TTS failed: {response.status_code} {response.text}",
                color=LogType.ERROR,
                server_only=True,
            )
        response.raise_for_status()
        return response.content

    async def _stream_audio_direct_v3(
        self,
        text: str,
        config: ElevenlabsConfig,
        voice_id: str,
        audio_player: AudioPlayer,
        wingman_name: str,
        sound_effects: list,
        on_playback_started: Callable[[], None],
        on_playback_finished: Callable[[Optional[Callable]], None],
    ) -> bool:
        stability = self._quantize_stability(config.voice_settings.stability)

        payload = {
            "text": text,
            "model_id": config.model,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": config.voice_settings.similarity_boost,
                "style": config.voice_settings.style,
                "use_speaker_boost": config.voice_settings.use_speaker_boost,
            },
        }

        headers = {
            "xi-api-key": self.api_key,
            "accept": "audio/pcm",
            "content-type": "application/json",
        }

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
        params = {"output_format": "pcm_44100"}

        response = await asyncio.to_thread(
            requests.post,
            url,
            headers=headers,
            json=payload,
            params=params,
            stream=True,
            timeout=60,
        )
        if response.status_code >= 400:
            self.printr.print(
                f"ElevenLabs direct streaming failed: {response.status_code} {response.text}",
                color=LogType.ERROR,
                server_only=True,
            )
            if (
                response.status_code == 403
                and "output_format_not_allowed" in response.text
            ):
                self.printr.print(
                    "ElevenLabs PCM streaming is not available for this account tier. Falling back to non-streaming playback.",
                    color=LogType.WARNING,
                    server_only=True,
                )
                response.close()
                return False
        response.raise_for_status()

        stop_event = Event()

        def stop_stream(_: str):
            stop_event.set()

        audio_player.playback_events.subscribe("finished", stop_stream)
        audio_player.is_playing = True
        audio_player.wingman_name = wingman_name

        def stream_audio():
            try:
                on_playback_started()
                audio_player.raw_stream = sd.RawOutputStream(
                    samplerate=44100,
                    channels=1,
                    dtype="int16",
                )
                audio_player.raw_stream.start()

                volume = sound_config.volume
                for chunk in response.iter_content(chunk_size=4096):
                    if stop_event.is_set():
                        break
                    if not chunk:
                        continue

                    audio_chunk = (
                        np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
                        / 32768.0
                    )
                    audio_chunk = audio_chunk.reshape(-1, 1)
                    for sound_effect in sound_effects:
                        audio_chunk = sound_effect(audio_chunk, 44100, reset=False)
                    if volume != 1.0:
                        audio_chunk = audio_chunk * volume
                    audio_chunk = np.clip(audio_chunk, -1.0, 1.0)
                    chunk = (
                        (audio_chunk.reshape(-1) * 32767.0).astype(np.int16).tobytes()
                    )

                    audio_player.raw_stream.write(chunk)
            finally:
                if audio_player.raw_stream is not None:
                    audio_player.raw_stream.stop()
                    audio_player.raw_stream.close()
                    audio_player.raw_stream = None
                audio_player.is_playing = False
                audio_player.playback_events.unsubscribe("finished", stop_stream)
                try:
                    response.close()
                except Exception as exc:
                    self.printr.print(
                        f"Failed to close ElevenLabs streaming response: {exc}",
                        color=LogType.WARNING,
                        server_only=True,
                    )
                on_playback_finished()

        Thread(target=stream_audio, daemon=True).start()
        return True

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
        use_stream = stream
        use_direct_api = config.model.startswith("eleven_v3")

        voice = (
            self.user.get_voice_by_ID(config.voice.id)
            if config.voice.id
            else self.user.get_voices_by_name_v2(config.voice.name)[0]
        )

        def handle_playback_finished(unsubscribe_callback=None):
            if unsubscribe_callback:
                audio_player.playback_events.unsubscribe(
                    "finished", unsubscribe_callback
                )
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

        def notify_playback_finished():
            handle_playback_finished(playback_finished)

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
            if use_stream
            else PlaybackOptions(runInBackground=True)
        )

        if use_stream and len(sound_effects) > 0:
            playback_options.audioPostProcessor = audio_post_processor

        generation_options = GenerationOptions(
            model=config.model,
            use_speaker_boost=config.voice_settings.use_speaker_boost,
            stability=config.voice_settings.stability,
            similarity_boost=config.voice_settings.similarity_boost,
            style=(
                config.voice_settings.style
                if config.model != "eleven_turbo_v2"
                else None
            ),
        )

        if use_direct_api and use_stream:
            voice_id = self._get_voice_id(voice, config)
            stream_ok = await self._stream_audio_direct_v3(
                text=text,
                config=config,
                voice_id=voice_id,
                audio_player=audio_player,
                wingman_name=wingman_name,
                sound_effects=sound_effects,
                on_playback_started=notify_playback_started,
                on_playback_finished=handle_playback_finished,
            )
            if not stream_ok:
                audio_bytes = await self._generate_audio_direct(text, config, voice_id)
                if audio_bytes:
                    await audio_player.play_with_effects(
                        input_data=audio_bytes,
                        config=sound_config,
                        wingman_name=wingman_name,
                    )
        elif use_direct_api:
            voice_id = self._get_voice_id(voice, config)
            audio_bytes = await self._generate_audio_direct(text, config, voice_id)
            if audio_bytes:
                await audio_player.play_with_effects(
                    input_data=audio_bytes,
                    config=sound_config,
                    wingman_name=wingman_name,
                )
        elif not use_stream:
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
