import asyncio
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Optional
import requests
import numpy as np
import sounddevice as sd
from api.enums import LogType, SoundEffect, TtsProvider, WingmanInitializationErrorType
from api.interface import (
    ElevenlabsConfig,
    ElevenlabsModel,
    SoundConfig,
    WingmanInitializationError,
)
from providers.interfaces import TtsInterface, tts_provider
from services.audio_player import AudioPlayer
from services.printr import Printr
from services.spoken_language import elevenlabs_language
from services.sound_effects import get_sound_effects
from services.websocket_user import WebSocketUser

if TYPE_CHECKING:
    from api.interface import SettingsConfig, WingmanConfig


API_URL = "https://api.elevenlabs.io"

# The client asks for models, voices and subscription data at the same time.
# ElevenLabs answers a burst with 429, so all account lookups (not TTS) go
# through one lock, keep a gap between requests and reuse answers for a while.
_LOOKUP_LOCK = threading.RLock()
_LOOKUP_GAP_SECONDS = 0.3
_LOOKUP_CACHE_SECONDS = 60.0
# Every answer asks which languages its model speaks: the list barely changes.
_MODELS_CACHE_SECONDS = 3600.0
_lookup_cache: dict[tuple[str, str], tuple[float, Any]] = {}
_last_lookup_at = 0.0

# 44.1 kHz PCM needs the Pro tier. Accounts below it stream at 24 kHz, and
# after the first refusal we ask for 24 kHz right away.
_PCM_FORMATS = ("pcm_44100", "pcm_24000")
_pcm_format_by_key: dict[str, str] = {}

# mp3_44100_128 is the best MP3 every tier gets.
_MP3_FORMAT = "mp3_44100_128"


def _throttled_lookup(
    api_key: str,
    name: str,
    fetch: Callable[[], Any],
    max_age: float = _LOOKUP_CACHE_SECONDS,
) -> Any:
    global _last_lookup_at
    key = (api_key, name)
    # Holding the lock during the fetch makes concurrent callers wait for the
    # first one and then take its cached answer instead of asking again.
    with _LOOKUP_LOCK:
        cached = _lookup_cache.get(key)
        if cached and time.monotonic() - cached[0] < max_age:
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


def _error_message(response: requests.Response) -> str:
    """The readable part of an ElevenLabs error answer."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        return f"{response.status_code} {response.text[:300]}"
    if isinstance(detail, dict):
        return detail.get("message") or str(detail)
    return str(detail or response.status_code)


def _error_code(response: requests.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return ""
    if isinstance(detail, dict):
        return detail.get("code") or detail.get("status") or ""
    return ""


class ElevenLabs:
    def __init__(self, api_key: str, wingman_name: str):
        self.wingman_name = wingman_name
        self.printr = Printr()
        self.api_key = api_key

    # ─── HTTP ────────────────────────────────────────────────────────────

    def _request(
        self, method: str, path: str, retries: int = 2, **kwargs
    ) -> requests.Response:
        """One call to the ElevenLabs API. Retries a 429 with a short wait.
        Raises ValueError with ElevenLabs' message on any other error."""
        headers = {"xi-api-key": self.api_key, **kwargs.pop("headers", {})}
        kwargs.setdefault("timeout", 60)
        for attempt in range(retries + 1):
            response = requests.request(
                method, f"{API_URL}{path}", headers=headers, **kwargs
            )
            if response.status_code == 429 and attempt < retries:
                response.close()
                time.sleep(1.0 + attempt)
                continue
            if response.status_code >= 400:
                message = _error_message(response)
                response.close()
                raise ValueError(message)
            return response
        raise ValueError("Too many requests")

    def _get_json(self, path: str, **kwargs) -> Any:
        return self._request("GET", path, **kwargs).json()

    # ─── Account lookups ─────────────────────────────────────────────────

    def get_subscription_data(self) -> dict:
        return _throttled_lookup(
            self.api_key,
            "subscription",
            lambda: self._get_json("/v1/user/subscription"),
        )

    def get_available_voices(self) -> list[dict]:
        def fetch():
            voices: list[dict] = []
            params: dict[str, Any] = {"page_size": 100}
            while True:
                page = self._get_json("/v2/voices", params=params)
                voices.extend(page.get("voices", []))
                token = page.get("next_page_token")
                if not page.get("has_more") or not token:
                    return voices
                params["next_page_token"] = token

        return _throttled_lookup(self.api_key, "voices", fetch)

    def get_available_models(self) -> list[dict]:
        return _throttled_lookup(
            self.api_key,
            "models",
            lambda: self._get_json("/v1/models"),
            max_age=_MODELS_CACHE_SECONDS,
        )

    def get_models(self) -> list[ElevenlabsModel]:
        """The text to speech models, with the request limit of this account."""
        free = self.get_subscription_data().get("tier") == "free"
        return [
            ElevenlabsModel(
                name=model["name"],
                model_id=model["model_id"],
                description=model.get("description", ""),
                max_characters=model[
                    (
                        "max_characters_request_free_user"
                        if free
                        else "max_characters_request_subscribed_user"
                    )
                ],
                cost_factor=model["token_cost_factor"],
                supported_languages=[
                    {"language_id": l["language_id"], "name": l["name"]}
                    for l in model.get("languages", [])
                ],
                metadata=model,
            )
            for model in self.get_available_models()
            if model.get("can_do_text_to_speech", True)
        ]

    def _forget_subscription(self):
        with _LOOKUP_LOCK:
            _lookup_cache.pop((self.api_key, "subscription"), None)

    # ─── Text to speech ──────────────────────────────────────────────────

    def _get_voice_id(self, config: ElevenlabsConfig) -> str:
        """The configured ID, or the voice with that name. ElevenLabs names
        voices "Adam - Dominant, Firm", while configs say "Adam": the part
        before " - " counts too, an ElevenLabs voice before one of the
        user's own."""
        if config.voice.id:
            return config.voice.id
        name = (config.voice.name or "").strip().lower()
        voices = self.get_available_voices()
        for voice in voices:
            if voice.get("name", "").strip().lower() == name:
                return voice["voice_id"]
        matches = [
            voice
            for voice in voices
            if voice.get("name", "").split(" - ")[0].strip().lower() == name
        ]
        matches.sort(key=lambda voice: voice.get("category") != "premade")
        if matches:
            return matches[0]["voice_id"]
        raise ValueError(f"ElevenLabs voice '{config.voice.name}' not found.")

    def _speaks(self, model_id: str, language: str) -> bool:
        """Whether the model lists the language. ElevenLabs answers 400 when a
        request names one it doesn't."""
        for model in self.get_available_models():
            if model.get("model_id") == model_id:
                return any(
                    l.get("language_id") == language for l in model.get("languages", [])
                )
        return False

    def _tts_payload(
        self, text: str, config: ElevenlabsConfig, language: Optional[str] = None
    ) -> dict:
        settings = config.voice_settings
        voice_settings = {
            "stability": settings.stability,
            "similarity_boost": settings.similarity_boost,
            "use_speaker_boost": settings.use_speaker_boost,
            "speed": settings.speed,
        }
        if config.model != "eleven_turbo_v2":
            voice_settings["style"] = settings.style
        payload = {"text": text, "model_id": config.model, "voice_settings": voice_settings}
        if language:
            try:
                if self._speaks(config.model, language):
                    payload["language_code"] = language
            except (ValueError, requests.RequestException):
                pass  # without the hint the model detects the language itself
        return payload

    def _generate_audio(
        self,
        text: str,
        config: ElevenlabsConfig,
        voice_id: str,
        language: Optional[str] = None,
    ) -> bytes:
        response = self._request(
            "POST",
            f"/v1/text-to-speech/{voice_id}",
            params={"output_format": _MP3_FORMAT},
            json=self._tts_payload(text, config, language),
            headers={"accept": "audio/mpeg"},
        )
        return response.content

    def _open_pcm_stream(
        self,
        text: str,
        config: ElevenlabsConfig,
        voice_id: str,
        language: Optional[str] = None,
    ) -> tuple[requests.Response, int]:
        """Starts a PCM stream and returns it with its sample rate. Falls back
        to 24 kHz when the account's tier doesn't get 44.1 kHz."""
        preferred = _pcm_format_by_key.get(self.api_key, _PCM_FORMATS[0])
        formats = _PCM_FORMATS[_PCM_FORMATS.index(preferred) :]
        payload = self._tts_payload(text, config, language)
        for output_format in formats:
            response = requests.post(
                f"{API_URL}/v1/text-to-speech/{voice_id}/stream",
                headers={"xi-api-key": self.api_key, "accept": "audio/pcm"},
                params={"output_format": output_format},
                json=payload,
                stream=True,
                timeout=60,
            )
            if response.status_code == 403 and output_format != formats[-1]:
                code = _error_code(response)
                response.close()
                if code in ("subscription_required", "output_format_not_allowed"):
                    _pcm_format_by_key[self.api_key] = formats[-1]
                    continue
                raise ValueError(_error_message(response))
            if response.status_code >= 400:
                message = _error_message(response)
                response.close()
                raise ValueError(message)
            _pcm_format_by_key[self.api_key] = output_format
            return response, int(output_format.split("_")[1])
        raise ValueError("No PCM output format available.")

    async def _stream_audio(
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
        language: Optional[str] = None,
    ):
        response, sample_rate = await asyncio.to_thread(
            self._open_pcm_stream, text, config, voice_id, language
        )

        if audio_player.is_playing:
            await audio_player.stop_playback()

        audio_player.is_playing = True
        audio_player.wingman_name = wingman_name

        def stream_audio():
            my_stream = None
            try:
                on_playback_started()
                my_stream = sd.RawOutputStream(
                    samplerate=sample_rate,
                    channels=1,
                    dtype="int16",
                )
                audio_player.raw_stream = my_stream
                my_stream.start()

                volume = sound_config.volume
                # int16 samples are 2 bytes: a chunk can end in the middle of one.
                leftover = b""
                for chunk in response.iter_content(chunk_size=4096):
                    # raw_stream replaced by stop_playback() or a newer playback: stop.
                    if audio_player.raw_stream is not my_stream:
                        break
                    if not chunk:
                        continue
                    chunk = leftover + chunk
                    usable = len(chunk) - len(chunk) % 2
                    chunk, leftover = chunk[:usable], chunk[usable:]
                    if not chunk:
                        continue

                    audio_chunk = (
                        np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
                        / 32768.0
                    )
                    audio_chunk = audio_chunk.reshape(-1, 1)
                    for sound_effect in sound_effects:
                        audio_chunk = sound_effect(audio_chunk, sample_rate, reset=False)
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
        language: Optional[str] = None,
    ):
        """language: ISO 639-1 code of the spoken language, sent when the
        model speaks it (services/spoken_language.elevenlabs_language)."""
        try:
            voice_id = await asyncio.to_thread(self._get_voice_id, config)
            if stream:
                await self._play_streamed(
                    text,
                    config,
                    voice_id,
                    sound_config,
                    audio_player,
                    wingman_name,
                    language,
                )
            else:
                audio_bytes = await asyncio.to_thread(
                    self._generate_audio, text, config, voice_id, language
                )
                if audio_bytes:
                    await audio_player.play_with_effects(
                        input_data=audio_bytes,
                        config=sound_config,
                        wingman_name=wingman_name,
                    )
        except (ValueError, requests.RequestException) as e:
            self.printr.toast_error(f"ElevenLabs: {e}")

    async def _play_streamed(
        self,
        text: str,
        config: ElevenlabsConfig,
        voice_id: str,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
        language: Optional[str],
    ):
        def notify_playback_started():
            if sound_config.play_beep:
                audio_player.play_wav_sample("beep.wav", sound_config.volume)
            elif sound_config.play_beep_apollo:
                audio_player.play_wav_sample("Apollo_Beep.wav", sound_config.volume)

            if SoundEffect.HIGH_END_RADIO in sound_config.effects:
                audio_player.play_wav_sample(
                    "Radio_Static_Beep.wav", sound_config.volume
                )

            WebSocketUser.ensure_async(
                audio_player.notify_playback_started(wingman_name)
            )

        def handle_playback_finished():
            if SoundEffect.HIGH_END_RADIO in sound_config.effects:
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

        await self._stream_audio(
            text=text,
            config=config,
            voice_id=voice_id,
            audio_player=audio_player,
            wingman_name=wingman_name,
            sound_effects=get_sound_effects(sound_config),
            sound_config=sound_config,
            on_playback_started=notify_playback_started,
            on_playback_finished=handle_playback_finished,
            language=language,
        )

    # ─── Sound effects ───────────────────────────────────────────────────

    async def generate_sound_effect(
        self,
        prompt: str,
        duration_seconds: Optional[float] = None,
        prompt_influence: Optional[float] = None,
    ) -> bytes:
        payload: dict[str, Any] = {"text": prompt}
        if duration_seconds is not None:
            payload["duration_seconds"] = duration_seconds
        if prompt_influence is not None:
            payload["prompt_influence"] = prompt_influence

        response = await asyncio.to_thread(
            self._request,
            "POST",
            "/v1/sound-generation",
            params={"output_format": _MP3_FORMAT},
            json=payload,
            timeout=120,
        )
        # The effect used up credits: the Audio Library reloads the count next.
        self._forget_subscription()
        return response.content


@tts_provider(TtsProvider.ELEVENLABS)
class ElevenLabsTts(TtsInterface):
    def __init__(
        self,
        elevenlabs_instance: "ElevenLabs",
        config: "WingmanConfig",
        settings: "SettingsConfig",
    ):
        self._elevenlabs = elevenlabs_instance
        self._config = config
        self._settings = settings

    async def play_audio(self, text, sound_config, audio_player, wingman_name):
        await self._elevenlabs.play_audio(
            text=text,
            config=self._config.elevenlabs,
            sound_config=sound_config,
            audio_player=audio_player,
            wingman_name=wingman_name,
            stream=self._config.elevenlabs.output_streaming,
            language=elevenlabs_language(
                self._settings.spoken_language, self._settings.other_language
            ),
        )
