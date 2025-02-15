import asyncio
import io
import wave
from os import path
from threading import Thread
from typing import Callable
import numpy as np
import soundfile as sf
import sounddevice as sd
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
    ):
        def callback(outdata, frames, time, status):
            # this is a super hacky way to update volume while the playback is running
            local_volume = volume[0] if isinstance(volume, list) else volume
            nonlocal playhead
            chunksize = frames * channels

            # If we are at the end of the audio buffer, stop playback
            if playhead >= len(audio):
                if np.issubdtype(outdata.dtype, np.floating):
                    outdata.fill(0.0)  # Fill with zero for floats
                else:
                    outdata[:] = bytes(
                        len(outdata)
                    )  # Fill with zeros for buffer of int types
                raise sd.CallbackStop

            # Define the end of the current chunk
            end = min(playhead + chunksize, len(audio))
            current_chunk = audio[playhead:end]

            # Handle multi-channel conversion if necessary
            if channels > 1 and current_chunk.ndim == 1:
                current_chunk = np.tile(current_chunk[:, np.newaxis], (1, channels))

            # Flatten the chunk
            current_chunk = current_chunk.ravel()

            required_length = chunksize

            # Ensure current_chunk has the required length
            if len(current_chunk) < required_length:
                padding_length = required_length - len(current_chunk)
                current_chunk = np.pad(current_chunk, (0, padding_length), "constant")
            else:
                current_chunk = current_chunk[:required_length]

            # Reshape current_chunk to match outdata's shape, only if size matches
            try:
                current_chunk = current_chunk.reshape((frames, channels))
                current_chunk = current_chunk * local_volume
                if np.issubdtype(outdata.dtype, np.floating):
                    outdata[:] = current_chunk.astype(outdata.dtype)
                else:
                    outdata_bytes = current_chunk.astype(outdata.dtype).tobytes()
                    outdata_flat = np.frombuffer(outdata_bytes, dtype=outdata.dtype)
                    outdata[:] = outdata_flat.reshape(outdata.shape)
            except ValueError as e:
                print(f"Reshape error: {e}")
                outdata.fill(
                    0.0 if np.issubdtype(outdata.dtype, np.floating) else 0
                )  # Safely fill zero to avoid noise

            # Update playhead
            playhead += frames

            # Check if playback should stop (end of audio)
            if playhead >= len(audio):
                if np.issubdtype(outdata.dtype, np.floating):
                    outdata.fill(0.0)  # Fill with zero for floats
                else:
                    outdata[:] = bytes(len(outdata))
                raise sd.CallbackStop

        # Initial playhead position
        playhead = 0
        self.is_playing = True

        # Create and start the audio stream
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

    async def pause_playback(self):
        if self.stream is not None:
            self.stream.stop()
        if self.raw_stream is not None:
            self.raw_stream.stop()
        self.is_playing = False

    async def resume_playback(self):
        if self.stream is not None:
            self.stream.start()
        if self.raw_stream is not None:
            self.raw_stream.start()
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
            args=(audio, sample_rate, channels, finished_callback, config.volume),
        )
        playback_thread.start()

        self.is_playing = True
        self.wingman_name = wingman_name

        await self.notify_playback_started(wingman_name)

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
        await self.notify_playback_started(wingman_name, publish_event)
        if filename.endswith(".mp3"):
            self.play_mp3(filename, volume)
        elif filename.endswith(".wav"):
            self.play_wav(filename, volume)
        await self.notify_playback_finished(wingman_name, publish_event)

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
        buffer = bytearray()
        stream_finished = False
        data_received = False
        mixed_pos = 0

        mix_layer_file = None
        for effect in config.effects:
            if not mix_layer_file:
                mix_layer_file = get_additional_layer_file(effect)
                # if we boost the actual audio, we need to boost the mixed layer as well
                if use_gain_boost:
                    mix_layer_gain_boost_db += get_azure_workaround_gain_boost(effect)

        if mix_layer_file:
            noise_audio, noise_sample_rate = self.get_audio_from_file(
                path.join(self.sample_dir, mix_layer_file)
            )
            if noise_sample_rate != sample_rate:
                noise_audio = self._resample_audio(
                    noise_audio, noise_sample_rate, sample_rate
                )
            if channels > 1 and noise_audio.ndim == 1:
                noise_audio = np.tile(noise_audio[:, None], (1, channels))
            noise_audio = noise_audio.flatten()

        def get_mixed_chunk(length):
            nonlocal mixed_pos, noise_audio
            chunk = np.zeros(length, dtype=np.float32)
            remaining = length
            while remaining > 0:
                if mixed_pos >= len(noise_audio):
                    mixed_pos = 0
                end_pos = min(len(noise_audio), mixed_pos + remaining)

                num_samples_to_copy = end_pos - mixed_pos
                if num_samples_to_copy > remaining:
                    num_samples_to_copy = remaining

                chunk[length - remaining : length - remaining + num_samples_to_copy] = (
                    noise_audio[mixed_pos : (mixed_pos + num_samples_to_copy)]
                )
                remaining -= num_samples_to_copy
                mixed_pos = mixed_pos + num_samples_to_copy
            return chunk

        def callback(outdata, frames, time, status):
            nonlocal buffer, stream_finished, data_received, mixed_pos
            if data_received and len(buffer) == 0:
                stream_finished = True
                outdata[:] = bytes(len(outdata))  # Fill the buffer with zeros
                return

            if len(buffer) > 0:
                num_elements = frames * channels
                byte_size = np.dtype(dtype).itemsize
                data_chunk = np.frombuffer(
                    buffer[: num_elements * byte_size], dtype=dtype
                ).astype(np.float32)

                if len(data_chunk) < num_elements:
                    data_chunk = np.pad(
                        data_chunk, (0, num_elements - len(data_chunk)), "constant"
                    )

                if channels > 1 and data_chunk.ndim == 1:
                    data_chunk = np.tile(data_chunk[:, None], (1, channels)).flatten()

                data_chunk = data_chunk[: frames * channels]

                if mix_layer_file:
                    mix_chunk = get_mixed_chunk(len(data_chunk))
                    # Convert gain boost from dB to amplitude factor
                    amplitude_factor = 10 ** (mix_layer_gain_boost_db / 20)
                    data_chunk = (
                        data_chunk + mix_chunk[: len(data_chunk)] * amplitude_factor
                    )

                data_chunk = data_chunk.flatten()
                data_chunk = data_chunk * config.volume
                data_chunk_bytes = data_chunk.astype(dtype).tobytes()
                outdata[: len(data_chunk_bytes)] = data_chunk_bytes[: len(outdata)]
                buffer = buffer[num_elements * byte_size :]

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
                self.play_wav_sample("beep.wav", config.volume)
            elif config.play_beep_apollo:
                self.play_wav_sample("Apollo_Beep.wav", config.volume)

            contains_high_end_radio = SoundEffect.HIGH_END_RADIO in config.effects
            if contains_high_end_radio:
                self.play_wav_sample("Radio_Static_Beep.wav", config.volume)

            self.raw_stream.start()

            sound_effects = get_sound_effects(
                config=config, use_gain_boost=use_gain_boost
            )
            audio_buffer = bytearray(buffer_size)
            filled_size = buffer_callback(audio_buffer)
            while filled_size > 0:
                data_in_numpy = np.frombuffer(
                    audio_buffer[:filled_size], dtype=dtype
                ).astype(np.float32)

                for sound_effect in sound_effects:
                    data_in_numpy = sound_effect(
                        data_in_numpy, sample_rate, reset=False
                    )

                if mix_layer_file:
                    noise_chunk = get_mixed_chunk(len(data_in_numpy))
                    # Convert gain boost from dB to amplitude factor
                    amplitude_factor = 10 ** (mix_layer_gain_boost_db / 20)
                    data_in_numpy = data_in_numpy + noise_chunk * amplitude_factor

                data_in_numpy = data_in_numpy * config.volume
                processed_buffer = data_in_numpy.astype(dtype).tobytes()
                buffer.extend(processed_buffer)
                await self.stream_event.publish("audio", processed_buffer)
                filled_size = buffer_callback(audio_buffer)

            data_received = True
            while not stream_finished:
                sd.sleep(100)

            contains_high_end_radio = SoundEffect.HIGH_END_RADIO in config.effects
            if contains_high_end_radio:
                self.play_wav_sample("Radio_Static_Beep.wav", config.volume)

            if config.play_beep:
                self.play_wav_sample("beep.wav", config.volume)
            elif config.play_beep_apollo:
                self.play_wav_sample("Apollo_Beep.wav", config.volume)

            self.is_playing = False
            await self.notify_playback_finished(wingman_name)
