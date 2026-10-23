import asyncio
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Optional
import requests
from threading import Event
import numpy as np
import sounddevice as sd
from elevenlabslib import User, GenerationOptions, PlaybackOptions, SFXOptions
from api.enums import LogType, SoundEffect, TtsProvider, WingmanInitializationErrorType
from api.interface import ElevenlabsConfig, SoundConfig, WingmanInitializationError
from providers.interfaces import TtsInterface, tts_provider
from services.audio_player import AudioPlayer
from services.printr import Printr
from services.sound_effects import get_sound_effects
from services.websocket_user import WebSocketUser

if TYPE_CHECKING:
    from api.interface import WingmanConfig


# The client asks for models, voices and subscription data at the same time, and
# elevenlabslib turns that into a burst: every Model.maxCharacters and every
# get_available_voices() fetches /v1/user/subscription again. ElevenLabs answers
# the burst with 429. So all account lookups (not TTS) go through one lock, keep a
# gap between requests and reuse answers for a short while.
_LOOKUP_LOCK = threading.RLock()
_LOOKUP_GAP_SECONDS = 0.3
_LOOKUP_CACHE_SECONDS = 60.0
_lookup_cache: dict[tuple[str, str], tuple[float, Any]] = {}
_last_lookup_at = 0.0


def _throttled_lookup(api_key: str, name: str, fetch: Callable[[], Any]) -> Any:
    global _last_lookup_at
    key = (api_key, name)
    # Holding the lock during the fetch makes concurrent callers wait for the
    # first one and then take its cached answer instead of asking again.
    with _LOOKUP_LOCK:
        cached = _lookup_cache.get(key)
        if cached and time.monotonic() - cached[0] < _LOOKUP_CACHE_SECONDS:
            return cached[1]

        wait = _last_lookup_at + _LOOKUP_GAP_SECONDS - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            result = fetch()
        finally:
            _last_lookup_at = time.monotonic()
        _lookup_cache[key] = (time.monotonic(), result)
        return result


class _ThrottledUser(User):
    """elevenlabslib's User with the account lookups routed through the throttle.
    Model and Voice objects call back into their linked User, so the overrides
    also cover the lookups the library makes internally."""

    def get_subscription_data(self) -> dict:
        return _throttled_lookup(
            self.xi_api_key, "subscription", super().get_subscription_data
        )

    def get_models(self):
        return _throttled_lookup(self.xi_api_key, "models", super().get_models)

    def get_available_voices(self, show_legacy: bool = True):
        return _throttled_lookup(
            self.xi_api_key,
            f"voices:{show_legacy}",
            lambda: super(_ThrottledUser, self).get_available_voices(show_legacy),
        )


class ElevenLabs:
    def __init__(self, api_key: str, wingman_name: str):
        self.wingman_name = wingman_name
        self.user = _ThrottledUser(api_key)
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
        sound_config: SoundConfig,
        on_playback_started: Callable[[], None],
        on_playback_finished: Callable[[], None],
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

        if audio_player.is_playing:
            await audio_player.stop_playback()

        audio_player.is_playing = True
        audio_player.wingman_name = wingman_name

        def stream_audio():
            my_stream = None
            try:
                on_playback_started()
                my_stream = sd.RawOutputStream(
                    samplerate=44100,
                    channels=1,
                    dtype="int16",
                )
                audio_player.raw_stream = my_stream
                my_stream.start()

                volume = sound_config.volume
                for chunk in response.iter_content(chunk_size=4096):
                    # raw_stream replaced by stop_playback() or a newer playback: stop.
                    if audio_player.raw_stream is not my_stream:
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

                    my_stream.write(chunk)
            finally:
                if my_stream is not None:
                    try:
                        my_stream.stop()
                        my_stream.close()
                    except Exception:
                        pass
                try:
                    response.close()
                except Exception as exc:
                    self.printr.print(
                        f"Failed to close ElevenLabs streaming response: {exc}",
                        color=LogType.WARNING,
                        server_only=True,
                    )
                # Re-read AFTER the teardown above: if a newer playback superseded us in
                # the meantime it now owns raw_stream / is_playing - don't clobber it.
                if audio_player.raw_stream is my_stream:
                    audio_player.raw_stream = None
                    on_playback_finished()

        # await the blocking stream (on a worker thread) so callers serialize playback
        await asyncio.to_thread(stream_audio)
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

        # signals playback end (natural or interrupt) for the streaming await below
        playback_complete = Event()
        # Set to the lib output stream in the lib path below. Used to detect when this
        # playback has already been superseded before its (async) onPlaybackEnd fires.
        lib_owned_stream = {"stream": None}

        def handle_playback_finished():
            # lib path only: if a newer playback already took over the shared audio
            # state, don't clear is_playing / notify Core for a playback that's gone -
            # that would clobber the successor and resume VA mid-playback. Still release
            # our own waiter. (The direct path leaves lib_owned_stream None and is
            # guarded by its caller's raw_stream identity check instead.)
            if (
                lib_owned_stream["stream"] is not None
                and audio_player.raw_stream is not lib_owned_stream["stream"]
            ):
                playback_complete.set()
                return

            contains_high_end_radio = SoundEffect.HIGH_END_RADIO in sound_config.effects
            if contains_high_end_radio:
                audio_player.play_wav_sample(
                    "Radio_Static_Beep.wav", sound_config.volume
                )

            if sound_config.play_beep:
                audio_player.play_wav_sample("beep.wav", sound_config.volume)
            elif sound_config.play_beep_apollo:
                audio_player.play_wav_sample("Apollo_Beep.wav", sound_config.volume)

            audio_player.is_playing = False

            WebSocketUser.ensure_async(
                audio_player.notify_playback_finished(wingman_name)
            )
            playback_complete.set()

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
                onPlaybackEnd=handle_playback_finished,
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
                sound_config=sound_config,
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
            if audio_player.is_playing:
                await audio_player.stop_playback()
            audio_player.is_playing = True
            audio_player.wingman_name = wingman_name
            output_stream = None
            try:
                _, _, output_stream_future, _ = voice.stream_audio_v3(
                    prompt=text,
                    generation_options=generation_options,
                    playback_options=playback_options,
                )
                output_stream = output_stream_future.result()
                # Register the lib's stream as raw_stream so stop_playback() halts it and
                # a superseding playback is detectable by identity (same contract as the
                # direct path). onPlaybackEnd sets playback_complete on natural end.
                audio_player.raw_stream = output_stream
                # After raw_stream: a stray onPlaybackEnd in the gap then sees
                # lib_owned_stream still None and finishes normally, never mis-guards.
                lib_owned_stream["stream"] = output_stream
                # playback_complete is set by onPlaybackEnd, which fires on every real
                # stream termination (natural end, CallbackStop, abort, stop). The
                # raw_stream identity check exits if a newer playback supersedes us.
                while (
                    not playback_complete.is_set()
                    and audio_player.raw_stream is output_stream
                ):
                    await asyncio.sleep(0.1)
            finally:
                if audio_player.raw_stream is output_stream:
                    audio_player.raw_stream = None
                    audio_player.is_playing = False

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
        # The effect used up characters: the Audio Library reloads the count next.
        with _LOOKUP_LOCK:
            _lookup_cache.pop((self.api_key, "subscription"), None)
        return audio

    def get_available_voices(self):
        return self.user.get_available_voices()

    def get_available_models(self):
        return self.user.get_models()

    def get_subscription_data(self):
        return self.user.get_subscription_data()


@tts_provider(TtsProvider.ELEVENLABS)
class ElevenLabsTts(TtsInterface):
    def __init__(self, elevenlabs_instance: "ElevenLabs", config: "WingmanConfig"):
        self._elevenlabs = elevenlabs_instance
        self._config = config

    async def play_audio(self, text, sound_config, audio_player, wingman_name):
        await self._elevenlabs.play_audio(
            text=text,
            config=self._config.elevenlabs,
            sound_config=sound_config,
            audio_player=audio_player,
            wingman_name=wingman_name,
            stream=self._config.elevenlabs.output_streaming,
        )
