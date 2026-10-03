import asyncio
import io
import wave
from os import path
from typing import Callable
import numpy as np
import soundfile as sf
from services import audio_backend as sd
from scipy.signal import resample
from api.enums import SoundEffect
from api.interface import SoundConfig
from services.pub_sub import PubSub
from services.sound_effects import (
    get_additional_layer_file,
    get_azure_workaround_gain_boost,
    get_sound_effects,
)

class AudioPlayer:
    def __init__(
        self,
        event_queue: asyncio.Queue,
        on_playback_started: Callable[[str], None],
        on_playback_finished: Callable[[str], None],
    ) -> None:
        self._playback_id = 0
        self._completed_id = 0
        self.is_playing = False
        self.event_queue = event_queue
        self.event_loop = None
        self.stream = None
        self.raw_stream = None
        self.wingman_name = ""
        self.playback_events = PubSub()
        self.stream_event = PubSub()
        self.on_playback_started = on_playback_started
        self.on_playback_finished = on_playback_finished
        self.sample_dir = path.join(
            path.abspath(path.dirname(__file__)), "../audio_samples"
        )

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self.event_loop = loop

    def start_playback(
        self,
        audio,
        sample_rate,
        channels,
        finished_callback,
        volume: list[float] | float,
        playback_token=None,
    ):
        playhead = 0
        token = playback_token
        def callback(outdata, frames, _time, _status):
            nonlocal playhead
            outdata.fill(0)
            chunk = audio[playhead:playhead + frames]
            if chunk.ndim == 1:
                chunk = chunk[:, None]
            level = volume[0] if isinstance(volume, list) else volume
            outdata[:len(chunk)] = chunk * level
            playhead += len(chunk)
            if playhead >= len(audio):
                raise sd.CallbackStop

        stream = None
        try:
            stream = sd.OutputStream(samplerate=sample_rate, channels=channels, callback=callback)
            if token is not None and (token != self._playback_id or self._completed_id == token):
                return
            self.stream = stream
            stream.start()
            while not stream.closed:
                sd.sleep(20)
            if stream.failed:
                raise sd.AudioUnavailable("Playback device interrupted")
        finally:
            if stream:
                stream.close()
            if self.stream is stream:
                self.stream = None
            if finished_callback:
                finished_callback()

    async def _begin_playback(self, wingman_name, publish_event=True):
        if self.is_playing or self.stream is not None or self.raw_stream is not None:
            await self.stop_playback()
        self._playback_id += 1
        token = self._playback_id
        self.wingman_name = wingman_name
        self.is_playing = True
        await self.notify_playback_started(wingman_name, publish_event)
        return token

    async def _finish_playback(self, token, wingman_name, publish_event=True):
        if token != self._playback_id or token == self._completed_id:
            return
        self._completed_id = token
        self.is_playing = False
        await self.notify_playback_finished(wingman_name, publish_event)

    async def stop_playback(self):
        for stream in (self.stream, self.raw_stream):
            if stream is not None:
                stream.close()
        self.stream = self.raw_stream = None
        await self._finish_playback(self._playback_id, self.wingman_name)

    async def pause_playback(self):
        for stream in (self.stream, self.raw_stream):
            if stream is not None:
                await asyncio.to_thread(stream.stop)
        self.is_playing = False

    async def resume_playback(self):
        for stream in (self.stream, self.raw_stream):
            if stream is not None and not stream.closed:
                await asyncio.to_thread(stream.start)
                self.is_playing = True

    async def play_with_effects(
        self,
        input_data: bytes | tuple,
        config: SoundConfig,
        wingman_name: str = None,
        mixed_layer_gain_boost_db: float = -9.0,
    ):
        if isinstance(input_data, bytes):
            audio, sample_rate = self._get_audio_from_stream(input_data)
        elif isinstance(input_data, tuple):
            audio, sample_rate = input_data
        else:
            raise TypeError("Invalid input type for stream_with_effects")

        if self.is_playing:
            await self.stop_playback()

        sound_effects = get_sound_effects(config)

        for sound_effect in sound_effects:
            audio = sound_effect(audio, sample_rate)

        mixed_layer_file = None
        for effect in config.effects:
            if not mixed_layer_file:
                mixed_layer_file = get_additional_layer_file(effect)

        if mixed_layer_file:
            audio = self._mix_in_layer(
                audio, sample_rate, mixed_layer_file, mixed_layer_gain_boost_db
            )

        contains_high_end_radio = SoundEffect.HIGH_END_RADIO in config.effects
        if contains_high_end_radio:
            audio = self._add_wav_effect(audio, sample_rate, "Radio_Static_Beep.wav")

        if config.play_beep:
            audio = self._add_wav_effect(audio, sample_rate, "beep.wav")
        elif config.play_beep_apollo:
            audio = self._add_wav_effect(audio, sample_rate, "Apollo_Beep.wav")

        channels = audio.shape[1] if audio.ndim > 1 else 1

        token = await self._begin_playback(wingman_name)

        async def playback():
            try:
                await asyncio.to_thread(self.start_playback, audio, sample_rate, channels, None, config.volume, token)
            except sd.AudioUnavailable as exc:
                sd.supervisor.report("output", f"recovering ({exc})")
            finally:
                await self._finish_playback(token, wingman_name)

        loop = self.event_loop or asyncio.get_running_loop()
        if loop is asyncio.get_running_loop():
            asyncio.create_task(playback())
        else:
            asyncio.run_coroutine_threadsafe(playback(), loop)

    async def notify_playback_started(
        self, wingman_name: str, publish_event: bool = True
    ):
        if publish_event:
            await self.playback_events.publish("started", wingman_name)
        if callable(self.on_playback_started):
            await self.on_playback_started(wingman_name)

    async def notify_playback_finished(
        self, wingman_name: str, publish_event: bool = True
    ):
        if publish_event:
            await self.playback_events.publish("finished", wingman_name)
        if callable(self.on_playback_finished):
            await self.on_playback_finished(wingman_name)

    def play_wav_sample(self, audio_sample_file: str, volume: float):
        file_path = path.join(self.sample_dir, audio_sample_file)
        self.play_wav(file_path, volume)

    def play_wav(self, audio_file: str, volume: list[float] | float):
        audio, sample_rate = self.get_audio_from_file(audio_file)
        with wave.open(audio_file, "rb") as audio_file:
            num_channels = audio_file.getnchannels()
        self.start_playback(audio, sample_rate, num_channels, None, volume)

    def play_mp3(self, audio_sample_file: str, volume: list[float] | float):
        audio, sample_rate = self.get_audio_from_file(audio_sample_file)
        self.start_playback(audio, sample_rate, 2, None, volume)

    async def play_audio_file(
        self,
        filename: str,
        volume: list[float] | float,
        wingman_name: str = None,
        publish_event: bool = True,
    ):
        token = await self._begin_playback(wingman_name, publish_event)
        try:
            audio, rate = self.get_audio_from_file(filename)
            channels = audio.shape[1] if audio.ndim > 1 else 1
            await asyncio.to_thread(self.start_playback, audio, rate, channels, None, volume, token)
        except sd.AudioUnavailable as exc:
            sd.supervisor.report("output", f"recovering ({exc})")
        finally:
            await self._finish_playback(token, wingman_name, publish_event)

    def get_audio_from_file(self, filename: str) -> tuple:
        audio, sample_rate = sf.read(filename, dtype="float32")
        return audio, sample_rate

    def _get_audio_from_stream(self, stream: bytes) -> tuple:
        audio, sample_rate = sf.read(io.BytesIO(stream), dtype="float32")
        return audio, sample_rate

    def _add_wav_effect(
        self, audio: np.ndarray, sample_rate: int, audio_sample_file: str
    ) -> np.ndarray:
        beep_audio, beep_sample_rate = self.get_audio_from_file(
            path.join(self.sample_dir, audio_sample_file)
        )

        # Resample the beep sound if necessary to match the sample rate of 'audio'
        if beep_sample_rate != sample_rate:
            beep_audio = self._resample_audio(beep_audio, beep_sample_rate, sample_rate)

        # Ensure beep_audio has the same number of channels as 'audio'
        if beep_audio.ndim == 1 and audio.ndim == 2:
            beep_audio = np.tile(beep_audio[:, np.newaxis], (1, audio.shape[1]))

        if beep_audio.ndim == 2 and audio.ndim == 1:
            audio = audio[:, np.newaxis]

        # Concatenate the beep sound to the start and end of the audio
        audio_with_beeps = np.concatenate((beep_audio, audio, beep_audio), axis=0)

        return audio_with_beeps

    def _resample_audio(
        self, audio: np.ndarray, original_sample_rate: int, target_sample_rate: int
    ) -> np.ndarray:
        # Calculate the number of samples after resampling
        num_original_samples = audio.shape[0]
        num_target_samples = int(
            round(num_original_samples * target_sample_rate / original_sample_rate)
        )
        # Use scipy.signal resample method to resample the audio to the target sample rate
        resampled_audio = resample(audio, num_target_samples)

        return resampled_audio

    def _mix_in_layer(
        self,
        audio: np.ndarray,
        sample_rate: int,
        mix_layer_file: str,
        mix_layer_gain_boost_db: float = 0.0,
    ) -> np.ndarray:
        noise_audio, noise_sample_rate = self.get_audio_from_file(
            path.join(self.sample_dir, mix_layer_file)
        )

        if noise_sample_rate != sample_rate:
            noise_audio = self._resample_audio(
                noise_audio, noise_sample_rate, sample_rate
            )

        # Ensure both audio and noise_audio have compatible shapes for addition
        if noise_audio.ndim == 1:
            noise_audio = noise_audio[:, None]

        if audio.ndim == 1:
            audio = audio[:, None]

        if noise_audio.shape[1] != audio.shape[1]:
            noise_audio = np.tile(noise_audio, (1, audio.shape[1]))

        # Ensure noise_audio length matches audio length
        if len(noise_audio) < len(audio):
            repeat_count = int(np.ceil(len(audio) / len(noise_audio)))
            noise_audio = np.tile(noise_audio, (repeat_count, 1))[: len(audio)]

        noise_audio = noise_audio[: len(audio)]

        # Convert gain boost from dB to amplitude factor
        amplitude_factor = 10 ** (mix_layer_gain_boost_db / 20)

        # Apply volume scaling to the mixed-in layer
        audio_with_noise = audio + amplitude_factor * noise_audio
        return audio_with_noise

    async def stream_with_effects(
        self,
        buffer_callback,
        config: SoundConfig,
        wingman_name: str,
        mix_layer_gain_boost_db: float = 0.0,
        buffer_size=2048,
        sample_rate=16000,
        channels=1,
        dtype="int16",
        use_gain_boost=False,
    ):
        token = await self._begin_playback(wingman_name)
        stream = None
        try:
            stream = await asyncio.to_thread(sd.RawOutputStream, samplerate=sample_rate,
                                             channels=channels, dtype=dtype)
            if token != self._playback_id or token == self._completed_id:
                return
            self.raw_stream = stream
            await asyncio.to_thread(stream.start)
            effects = get_sound_effects(config=config, use_gain_boost=use_gain_boost)
            noise = None
            position = 0
            for effect in config.effects:
                layer = get_additional_layer_file(effect)
                if layer:
                    noise, noise_rate = self.get_audio_from_file(path.join(self.sample_dir, layer))
                    if noise_rate != sample_rate:
                        noise = self._resample_audio(noise, noise_rate, sample_rate)
                    if noise.ndim == 1 and channels > 1:
                        noise = np.repeat(noise[:, None], channels, axis=1)
                    noise = noise.ravel()
                    if use_gain_boost:
                        mix_layer_gain_boost_db += get_azure_workaround_gain_boost(effect)
                    break
            sample = "beep.wav" if config.play_beep else ("Apollo_Beep.wav" if config.play_beep_apollo else None)

            async def beep(filename):
                if not filename:
                    return
                audio, rate = self.get_audio_from_file(path.join(self.sample_dir, filename))
                if rate != sample_rate:
                    audio = self._resample_audio(audio, rate, sample_rate)
                if audio.ndim > 1:
                    audio = audio.mean(axis=1)
                if channels > 1:
                    audio = np.repeat(audio[:, None], channels, axis=1)
                if np.issubdtype(np.dtype(dtype), np.integer):
                    audio = np.clip(audio * 32767 * config.volume, -32768, 32767).astype(dtype)
                else:
                    audio = (audio * config.volume).astype(dtype)
                await asyncio.to_thread(stream.write, audio.tobytes())

            await beep(sample)
            if SoundEffect.HIGH_END_RADIO in config.effects:
                await beep("Radio_Static_Beep.wav")
            buffer = bytearray(buffer_size)
            while token == self._playback_id and token != self._completed_id:
                filled = await asyncio.wait_for(asyncio.to_thread(buffer_callback, buffer), timeout=15)
                if not filled:
                    break
                if not 0 < filled <= buffer_size:
                    raise ValueError("Invalid provider audio block")
                data = np.frombuffer(buffer[:filled], dtype=dtype).astype(np.float32)
                for effect in effects:
                    data = effect(data, sample_rate, reset=False)
                if noise is not None and len(noise):
                    mixed = np.take(noise, np.arange(position, position + len(data)), mode="wrap")
                    if np.issubdtype(np.dtype(dtype), np.integer):
                        mixed = mixed * 32767
                    data += mixed * (10 ** (mix_layer_gain_boost_db / 20))
                    position = (position + len(data)) % len(noise)
                data *= config.volume
                if np.issubdtype(np.dtype(dtype), np.integer):
                    info = np.iinfo(dtype)
                    data = np.clip(data, info.min, info.max)
                processed = data.astype(dtype).tobytes()
                await asyncio.to_thread(stream.write, processed)
                await self.stream_event.publish("audio", processed)
            if token == self._playback_id and token != self._completed_id:
                if SoundEffect.HIGH_END_RADIO in config.effects:
                    await beep("Radio_Static_Beep.wav")
                await beep(sample)
                await asyncio.to_thread(stream.stop)
        except (sd.AudioUnavailable, asyncio.TimeoutError) as exc:
            sd.supervisor.report("output", f"recovering ({exc})")
        finally:
            if stream:
                stream.close()
            if self.raw_stream is stream:
                self.raw_stream = None
            await self._finish_playback(token, wingman_name)
