import asyncio
import io
from os import path
from threading import Thread
from typing import Callable, Optional
import numpy as np
import soundfile as sf
import sounddevice as sd
from scipy.signal import resample
from api.interface import SoundConfig
from services.sound_effects import get_sound_effects


class AudioPlayer:
    on_playback_started: Optional[Callable[[str], None]] = None
    on_playback_finished: Optional[Callable[[str], None]] = None

    def __init__(self) -> None:
        self.is_playing = False
        self.event_queue = None
        self.event_loop = None
        self.stream = None
        self.raw_stream = None
        self.wingman_name = ""

    def set_event_loop(self, loop):
        self.event_loop = loop

    def start_playback(self, audio, sample_rate, channels, finished_callback):
        def callback(outdata, frames, time, status):
            nonlocal playhead
            chunksize = frames * channels
            current_chunk = audio[playhead : playhead + chunksize].reshape(-1, channels)
            if current_chunk.shape[0] < frames:
                outdata[: current_chunk.shape[0]] = current_chunk
                outdata[current_chunk.shape[0] :] = 0  # Fill the rest with zeros
                raise sd.CallbackStop  # Stop the stream after playing the current chunk
            else:
                outdata[:] = current_chunk
                playhead += chunksize  # Advance the playhead

        playhead = 0  # Tracks the position in the audio

        self.stream = sd.OutputStream(
            samplerate=sample_rate,
            channels=channels,
            callback=callback,
            finished_callback=finished_callback,
        )
        self.stream.start()
        sd.sleep(int(len(audio) / sample_rate * 1000))

    async def stop_playback(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream = None

        if self.raw_stream is not None:
            self.raw_stream.stop()
            self.raw_stream = None

        self.is_playing = False
        await self.notify_playback_finished(self.wingman_name)

    async def play_with_effects(
        self,
        input_data: bytes | tuple,
        config: SoundConfig,
        wingman_name: str = None,
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

        if config.play_beep:
            audio = self._add_beep_effect(audio, sample_rate)

        channels = audio.shape[1] if audio.ndim > 1 else 1

        def finished_callback():
            if self.stream is not None:
                self.stream.close()
                self.stream = None
            self.is_playing = False
            if self.event_queue is not None and callable(self.on_playback_finished):
                finished_event = (self.on_playback_finished, wingman_name)
                coroutine = self.event_queue.put(finished_event)
                if self.event_loop:
                    asyncio.run_coroutine_threadsafe(coroutine, self.event_loop)

        playback_thread = Thread(
            target=self.start_playback,
            args=(audio, sample_rate, channels, finished_callback),
        )
        playback_thread.start()

        self.is_playing = True
        self.wingman_name = wingman_name

        await self.notify_playback_started(wingman_name)

    async def notify_playback_started(self, wingman_name: str):
        if callable(self.on_playback_started):
            await self.on_playback_started(wingman_name)

    async def notify_playback_finished(self, wingman_name: str):
        if callable(self.on_playback_finished):
            await self.on_playback_finished(wingman_name)

    def play_beep(self):
        bundle_dir = path.abspath(path.dirname(__file__))
        beep_audio, beep_sample_rate = self.get_audio_from_file(
            path.join(bundle_dir, "../audio_samples/beep.wav")
        )
        self.start_playback(beep_audio, beep_sample_rate, 1, None)

    def get_audio_from_file(self, filename: str) -> tuple:
        audio, sample_rate = sf.read(filename, dtype="float32")
        return audio, sample_rate

    def _get_audio_from_stream(self, stream: bytes) -> tuple:
        audio, sample_rate = sf.read(io.BytesIO(stream), dtype="float32")
        return audio, sample_rate

    def _add_beep_effect(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        bundle_dir = path.abspath(path.dirname(__file__))
        beep_audio, beep_sample_rate = self.get_audio_from_file(
            path.join(bundle_dir, "../audio_samples/beep.wav")
        )

        # Resample the beep sound if necessary to match the sample rate of 'audio'
        if beep_sample_rate != sample_rate:
            beep_audio = self._resample_audio(beep_audio, beep_sample_rate, sample_rate)

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

    async def stream_with_effects(
        self,
        buffer_callback,
        config: SoundConfig,
        wingman_name: str,
        buffer_size=2048,
        sample_rate=16000,
        channels=1,
        dtype="int16",
    ):
        buffer = bytearray()
        stream_finished = False
        data_received = False

        def callback(outdata, frames, time, status):
            nonlocal buffer, stream_finished, data_received

            if data_received and len(buffer) == 0:
                stream_finished = True
            outdata[: len(buffer)] = buffer[: len(outdata)]
            buffer = buffer[len(outdata) :]

        with sd.RawOutputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype=dtype,
            callback=callback,
        ) as stream:
            if self.is_playing:
                await self.stop_playback()

            self.raw_stream = stream
            self.is_playing = True
            await self.notify_playback_started(wingman_name)

            if config.play_beep:
                self.play_beep()
            self.raw_stream.start()

            audio_buffer = bytes(buffer_size)
            sound_effects = get_sound_effects(config)
            filled_size = buffer_callback(audio_buffer)
            while filled_size > 0:
                data_in_numpy = np.frombuffer(audio_buffer, dtype=dtype).astype(
                    np.float32
                )

                for sound_effect in sound_effects:
                    data_in_numpy = sound_effect(
                        data_in_numpy, sample_rate, reset=False
                    )

                audio_buffer = data_in_numpy.astype(dtype).tobytes()

                buffer += audio_buffer[:filled_size]
                filled_size = buffer_callback(audio_buffer)

            data_received = True
            while not stream_finished:
                sd.sleep(100)

            if config.play_beep:
                self.play_beep()
            self.is_playing = False
            await self.notify_playback_finished(wingman_name)
