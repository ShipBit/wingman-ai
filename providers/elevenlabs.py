import asyncio
from typing import Optional
import requests
from elevenlabslib import User, GenerationOptions, SFXOptions
from api.enums import LogType, WingmanInitializationErrorType
from api.interface import ElevenlabsConfig, SoundConfig, WingmanInitializationError
from services.audio_player import AudioPlayer
from services.printr import Printr


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
        stability = (self._quantize_stability(config.voice_settings.stability)
                     if config.model.startswith("eleven_v3") else config.voice_settings.stability)

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
        sound_config: SoundConfig,
    ) -> bool:
        stability = (self._quantize_stability(config.voice_settings.stability)
                     if config.model.startswith("eleven_v3") else config.voice_settings.stability)

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

        def read_audio(buffer):
            chunk = response.raw.read(len(buffer), decode_content=True)
            buffer[:len(chunk)] = chunk
            return len(chunk)

        try:
            await audio_player.stream_with_effects(
                read_audio, sound_config, wingman_name, sample_rate=44100, dtype="int16")
        finally:
            response.close()
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
        voice = (
            self.user.get_voice_by_ID(config.voice.id)
            if config.voice.id else self.user.get_voices_by_name_v2(config.voice.name)[0]
        )
        voice_id = self._get_voice_id(voice, config)
        if stream:
            # SDK-managed playback bypasses Core's device policy and recovery.
            # Use the same HTTP PCM stream for all ElevenLabs models.
            if await self._stream_audio_direct_v3(text, config, voice_id, audio_player,
                                                   wingman_name, sound_config):
                return
        if config.model.startswith("eleven_v3"):
            audio = await self._generate_audio_direct(text, config, voice_id)
        else:
            options = GenerationOptions(
                model=config.model,
                use_speaker_boost=config.voice_settings.use_speaker_boost,
                stability=config.voice_settings.stability,
                similarity_boost=config.voice_settings.similarity_boost,
                style=config.voice_settings.style if config.model != "eleven_turbo_v2" else None)
            def generate():
                audio_future, _ = voice.generate_audio_v3(prompt=text, generation_options=options)
                return audio_future.result()
            audio = await asyncio.to_thread(generate)
        if audio:
            await audio_player.play_with_effects(audio, sound_config, wingman_name)

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
