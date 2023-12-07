import io
import numpy as np
import soundfile as sf
import sounddevice as sd
from pedalboard import Pedalboard, Chorus, PitchShift, Reverb, Delay, Gain
from scipy.signal import butter, lfilter


class AudioPlayer:
    def play_file(self, filename: str):
        with open(filename, "rb") as f:
            audio_data = f.read()
        self.play(audio_data)

    def play(self, stream: bytes):
        audio, sample_rate = self._get_audio_from_stream(stream)
        sd.play(audio, sample_rate)
        sd.wait()

    def stream(self, stream: bytes):
        audio, sample_rate = self._get_audio_from_stream(stream)
        sd.play(audio, sample_rate)
        sd.wait()

    def stream_with_effects(
        self,
        stream: bytes,
        play_beep: bool = False,
        play_noise: bool = False,
        robot_effect: bool = False,
    ):
        audio, sample_rate = self._get_audio_from_stream(stream)

        # Apply effects as needed
        if play_noise:
            audio = self._add_noise_effect(audio, sample_rate)
        if play_beep:
            audio = self._add_beep_effect(audio, sample_rate)
        if robot_effect:
            audio = self._add_robot_effect(audio, sample_rate)

        # Play the audio
        sd.play(audio, sample_rate)
        sd.wait()

    def get_audio_from_file(self, filename: str) -> tuple:
        audio, sample_rate = sf.read(filename, dtype="float32")
        return audio, sample_rate

    def _get_audio_from_stream(self, stream: bytes) -> tuple:
        audio, sample_rate = sf.read(io.BytesIO(stream), dtype="float32")
        return audio, sample_rate

    # ────────────────────────────────── Sound Effects ───────────────────────────────── #

    def _add_robot_effect(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        board = Pedalboard(
            [
                PitchShift(semitones=-3),
                Delay(delay_seconds=0.01, feedback=0.5, mix=0.5),
                Chorus(
                    rate_hz=0.5, depth=0.8, mix=0.7, centre_delay_ms=2, feedback=0.3
                ),
                Reverb(
                    room_size=0.05,
                    dry_level=0.5,
                    wet_level=0.2,
                    freeze_mode=0.5,
                    width=0.5,
                ),
                Gain(gain_db=9),
            ]
        )
        return board(audio, sample_rate)

    def _add_noise_effect(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        # Create band-pass filter for audio
        low = 500.0 / (0.5 * sample_rate)
        high = 5000.0 / (0.5 * sample_rate)
        b, a = butter(5, [low, high], "band")
        filtered_audio = lfilter(b, a, audio)

        # Generate white noise
        noise = np.random.normal(0, 0.1, audio.shape)

        # Combine noise with filtered audio
        noisy_audio = filtered_audio + noise
        return noisy_audio

    def _add_beep_effect(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        # Generate beep signal
        duration = 0.2
        freq = 1000
        samples = int(sample_rate * duration)
        beep_signal = np.sin(2 * np.pi * np.arange(samples) * freq / sample_rate)

        # Add beeps at the start and end of the audio signal
        beeped_audio = np.concatenate([beep_signal, audio, beep_signal])
        return beeped_audio
