import io
from os import path
import numpy as np
import soundfile as sf
import sounddevice as sd
from scipy.signal import resample
from api.interface import SoundConfig
from services.sound_effects import get_sound_effects


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
        self, input_data: bytes | tuple, config: SoundConfig, wait: bool = False
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

        sd.play(audio, sample_rate)

        if wait:
            sd.wait()

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
