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
            self.is_playing = False
            if callable(self.on_playback_finished):
                await self.on_playback_finished(self.wingman_name)

    def stream_with_effects(
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

        if callable(self.on_playback_started):
            self.on_playback_started(wingman_name)

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
