import io
from os import path
import numpy as np
import soundfile as sf
import sounddevice as sd
from scipy.signal import resample
from services.sound_effects import get_sound_effects_from_config


class AudioPlayer:
    def __init__(self, sound_config: dict):
        self.sound_config = sound_config

    def play_file(self, filename: str):
        with open(filename, "rb") as f:
            audio_data = f.read()
        # Decode bytes before playing
        audio, sample_rate = self._get_audio_from_stream(audio_data)
        self._play_audio_array(audio, sample_rate)

    def play(self, stream: bytes):
        """Plays raw audio bytes."""
        audio, sample_rate = self._get_audio_from_stream(stream)
        self._play_audio_array(audio, sample_rate)

    def stream(self, stream: bytes):
        """Plays raw audio bytes (alias for play)."""
        self.play(stream)

    def _play_audio_array(self, audio: np.ndarray, sample_rate: int, wait: bool = True):
        """Plays a numpy audio array with configured volume and silence."""
        volume = self.sound_config.get("volume", 0.8)
        audio = audio * volume
        audio = np.clip(audio, -1.0, 1.0)  # Prevent clipping
        audio = self.prepend_silence(audio, sample_rate, ms=50)  # 50ms Stille am Anfang
        sd.play(audio, sample_rate)
        if wait:
            sd.wait()

    def prepend_silence(self, audio, sample_rate, ms=50):
        num_silence_samples = int(sample_rate * (ms / 1000.0))
        silence = np.zeros(num_silence_samples, dtype=audio.dtype)
        return np.concatenate([silence, audio])

    def stream_with_effects(
        self, input_data: bytes | tuple, config: dict, wait: bool = False
    ):
        """
        Plays audio with effects. Accepts raw bytes (e.g., from cache or TTS API)
        or a pre-decoded tuple (audio_array, sample_rate).
        """
        if isinstance(input_data, bytes):
            # Decode bytes first
            try:
                audio, sample_rate = self._get_audio_from_stream(input_data)
            except Exception as e:
                print(f"Error decoding audio stream: {e}")
                # Fallback: try reading as WAV if standard decode fails? Or just return.
                try:
                    # Attempt to read as WAV specifically
                    audio, sample_rate = sf.read(io.BytesIO(input_data), dtype="float32", format='WAV')
                except Exception as inner_e:
                    print(f"Error decoding audio stream as WAV: {inner_e}")
                    return  # Cannot process data
        elif isinstance(input_data, tuple) and len(input_data) == 2:
            # Assume it's (audio_array, sample_rate)
            audio, sample_rate = input_data
            if not isinstance(audio, np.ndarray) or not isinstance(sample_rate, int):
                print(f"Invalid tuple format for stream_with_effects: Expected (np.ndarray, int), got ({type(audio)}, {type(sample_rate)})")
                return
        else:
            print(f"Invalid input type for stream_with_effects: Expected bytes or (np.ndarray, int), got {type(input_data)}")
            return

        # Apply sound effects
        sound_effects = get_sound_effects_from_config(config)
        add_beep = config.get("sound", {}).get("play_beep", False)

        # --- Error Handling for Effects ---
        original_audio = audio.copy()  # Keep a copy in case effects fail
        try:
            for sound_effect in sound_effects:
                # Ensure effect returns valid audio or handle error
                processed_audio = sound_effect(audio, sample_rate)
                if isinstance(processed_audio, np.ndarray):
                    audio = processed_audio
                else:
                    print(f"Warning: Sound effect {sound_effect.__name__} did not return a numpy array. Skipping effect.")
                    # Optionally revert to audio before this effect: audio = previous_step_audio

            if add_beep:
                processed_audio = self._add_beep_effect(audio, sample_rate)
                if isinstance(processed_audio, np.ndarray):
                    audio = processed_audio
                else:
                    print("Warning: Beep effect failed. Skipping.")

        except Exception as e:
            print(f"Error applying sound effects: {e}. Playing original audio.")
            audio = original_audio  # Revert to original audio if effects fail
        # --- End Error Handling ---

        audio = self.prepend_silence(audio, sample_rate, ms=200)  # Longer silence before effects?

        volume = config.get("sound", {}).get("volume", 0.8)
        audio = audio * volume
        audio = np.clip(audio, -1.0, 1.0)  # Prevent clipping

        # Play the final audio
        sd.play(audio, sample_rate)

        if wait:
            sd.wait()

    def get_audio_from_file(self, filename: str) -> tuple:
        """Reads audio from a file."""
        try:
            audio, sample_rate = sf.read(filename, dtype="float32")
            return audio, sample_rate
        except Exception as e:
            print(f"Error reading audio file {filename}: {e}")
            return np.array([]), 0  # Return empty array and 0 sample rate on error

    def _get_audio_from_stream(self, stream: bytes) -> tuple:
        """Reads audio from a byte stream."""
        # SoundFile determines format automatically from the stream content
        try:
            audio, sample_rate = sf.read(io.BytesIO(stream), dtype="float32")
            return audio, sample_rate
        except Exception as e:
            print(f"Error reading audio stream: {e}")
            # Add specific format attempts if needed
            # try: sf.read(..., format='MP3') etc.
            raise  # Re-raise exception if decoding fails

    def _add_beep_effect(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        try:
            bundle_dir = path.abspath(path.dirname(__file__))
            beep_path = path.join(bundle_dir, "../audio_samples/beep.wav")
            if not path.exists(beep_path):
                print(f"Error: Beep file not found at {beep_path}")
                return audio  # Return original audio if beep file missing

            beep_audio, beep_sample_rate = self.get_audio_from_file(beep_path)

            if beep_audio.size == 0:  # Check if file reading failed
                print("Error: Failed to read beep audio file.")
                return audio

            # Resample the beep sound if necessary to match the sample rate of 'audio'
            if beep_sample_rate != sample_rate:
                beep_audio = self._resample_audio(beep_audio, beep_sample_rate, sample_rate)

            # Concatenate the beep sound to the start and end of the audio
            # Ensure beep_audio is 1D if audio is 1D
            if audio.ndim == 1 and beep_audio.ndim > 1:
                beep_audio = beep_audio[:, 0]  # Take first channel if necessary
            elif audio.ndim > 1 and beep_audio.ndim == 1:
                # If audio is stereo, make beep stereo (duplicate mono channel)
                beep_audio = np.column_stack((beep_audio, beep_audio))
            elif audio.ndim != beep_audio.ndim:
                print(f"Warning: Beep audio dimension ({beep_audio.ndim}D) mismatch with main audio ({audio.ndim}D). Skipping beep.")
                return audio

            audio_with_beeps = np.concatenate((beep_audio, audio, beep_audio), axis=0)
            return audio_with_beeps

        except Exception as e:
            print(f"Error adding beep effect: {e}")
            return audio  # Return original audio on error

    def _resample_audio(
        self, audio: np.ndarray, original_sample_rate: int, target_sample_rate: int
    ) -> np.ndarray:
        """Resamples audio using scipy."""
        try:
            # Calculate the number of samples after resampling
            num_original_samples = audio.shape[0]
            num_target_samples = int(
                round(num_original_samples * target_sample_rate / original_sample_rate)
            )
            # Use scipy.signal resample method to resample the audio to the target sample rate
            resampled_audio = resample(audio, num_target_samples)
            return resampled_audio
        except Exception as e:
            print(f"Error resampling audio: {e}")
            return audio  # Return original on error