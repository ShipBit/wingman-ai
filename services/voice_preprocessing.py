"""Voice audio preprocessing for PocketTTS voice cloning.

Cleans up arbitrary user-uploaded audio so cloning produces consistent results:
- Decode via soundfile (native WAV/MP3/FLAC/OGG, no ffmpeg required)
- Mono downmix
- Resample to PocketTTS's native 24 kHz
- Trim leading/trailing silence
- Peak-normalize to -1 dBFS
- Cap duration to ~20 s (PocketTTS v2 rejects very long prompts, and short clean clips clone better)
- Write as int16 mono WAV

Pure-Python stack: soundfile + numpy + scipy. No external binaries.
"""

import math
import os
from dataclasses import dataclass
from typing import Optional

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


TARGET_SAMPLE_RATE = 24000  # PocketTTS v2 mimi sample rate
DEFAULT_MAX_DURATION_S = 20.0
SILENCE_RMS_THRESHOLD = 0.005  # -46 dBFS; anything below counts as silence
SILENCE_WINDOW_MS = 20
PEAK_NORMALIZE_DBFS = -1.0


@dataclass
class PreprocessResult:
    path: str
    sample_rate: int
    duration_seconds: float
    channels: int
    original_sample_rate: int
    original_channels: int
    original_duration_seconds: float
    trimmed_silence_ms: int
    truncated: bool


def _load_audio(src_path: str) -> tuple[np.ndarray, int]:
    """Return (samples [float32, shape=(n,) or (n,channels)], sample_rate)."""
    data, sr = sf.read(src_path, dtype="float32", always_2d=False)
    return data, sr


def _to_mono(samples: np.ndarray) -> np.ndarray:
    if samples.ndim == 1:
        return samples
    return samples.mean(axis=1).astype(np.float32)


def _resample(samples: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    if from_rate == to_rate:
        return samples
    gcd = math.gcd(from_rate, to_rate)
    up = to_rate // gcd
    down = from_rate // gcd
    resampled = resample_poly(samples, up, down)
    return resampled.astype(np.float32)


def _trim_silence(
    samples: np.ndarray,
    sample_rate: int,
    threshold: float = SILENCE_RMS_THRESHOLD,
    window_ms: int = SILENCE_WINDOW_MS,
) -> tuple[np.ndarray, int]:
    """Trim leading/trailing silence via RMS gating. Returns (trimmed, trimmed_ms)."""
    if samples.size == 0:
        return samples, 0

    window = max(1, int(sample_rate * window_ms / 1000))
    n_windows = samples.size // window
    if n_windows == 0:
        return samples, 0

    framed = samples[: n_windows * window].reshape(n_windows, window)
    rms = np.sqrt((framed.astype(np.float64) ** 2).mean(axis=1))
    active = rms > threshold
    if not active.any():
        return samples, 0

    first = int(np.argmax(active))
    last = int(n_windows - np.argmax(active[::-1]))
    start_sample = first * window
    end_sample = min(samples.size, last * window)

    trimmed = samples[start_sample:end_sample]
    trimmed_ms = int((samples.size - trimmed.size) * 1000 / sample_rate)
    return trimmed, trimmed_ms


def _normalize_peak(samples: np.ndarray, target_dbfs: float = PEAK_NORMALIZE_DBFS) -> np.ndarray:
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak < 1e-9:
        return samples
    target_linear = 10.0 ** (target_dbfs / 20.0)
    gain = target_linear / peak
    return (samples * gain).astype(np.float32)


def _truncate(samples: np.ndarray, sample_rate: int, max_seconds: float) -> tuple[np.ndarray, bool]:
    max_samples = int(max_seconds * sample_rate)
    if samples.size <= max_samples:
        return samples, False
    return samples[:max_samples], True


def _to_int16(samples: np.ndarray) -> np.ndarray:
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16)


def preprocess_voice_audio(
    src_path: str,
    dst_path: str,
    max_duration_s: float = DEFAULT_MAX_DURATION_S,
    target_sample_rate: int = TARGET_SAMPLE_RATE,
    trim_silence: bool = True,
    normalize: bool = True,
) -> PreprocessResult:
    """Preprocess arbitrary audio for PocketTTS voice cloning.

    Writes a cleaned-up mono 24 kHz 16-bit WAV to ``dst_path`` and returns metadata.

    Raises ValueError if the resulting audio is too short (< 1 s of speech) to be usable.
    """
    if not os.path.isfile(src_path):
        raise FileNotFoundError(f"Audio file not found: {src_path}")

    data, original_sr = _load_audio(src_path)
    original_channels = 1 if data.ndim == 1 else data.shape[1]
    original_duration = float(data.shape[0]) / original_sr

    mono = _to_mono(data)
    resampled = _resample(mono, original_sr, target_sample_rate)

    trimmed_ms = 0
    if trim_silence:
        resampled, trimmed_ms = _trim_silence(resampled, target_sample_rate)

    resampled, truncated = _truncate(resampled, target_sample_rate, max_duration_s)

    if resampled.size < target_sample_rate:
        raise ValueError(
            "Resulting audio is shorter than 1 second after silence trimming; "
            "please provide a longer / louder source clip."
        )

    if normalize:
        resampled = _normalize_peak(resampled)

    dst_dir = os.path.dirname(dst_path) or "."
    os.makedirs(dst_dir, exist_ok=True)
    sf.write(dst_path, _to_int16(resampled), target_sample_rate, subtype="PCM_16")

    return PreprocessResult(
        path=os.path.abspath(dst_path),
        sample_rate=target_sample_rate,
        duration_seconds=float(resampled.size) / target_sample_rate,
        channels=1,
        original_sample_rate=original_sr,
        original_channels=original_channels,
        original_duration_seconds=original_duration,
        trimmed_silence_ms=trimmed_ms,
        truncated=truncated,
    )


_SUPPORTED_INPUT_EXT: Optional[set[str]] = None


def supported_input_extensions() -> set[str]:
    """Return lowercase file extensions (with dot) soundfile can decode on this system."""
    global _SUPPORTED_INPUT_EXT
    if _SUPPORTED_INPUT_EXT is None:
        formats = {k.lower() for k in sf.available_formats().keys()}
        # soundfile format keys map to common extensions; keep the practical ones
        ext_map = {
            "wav": ".wav",
            "flac": ".flac",
            "ogg": ".ogg",
            "mp3": ".mp3",
            "aiff": ".aiff",
            "w64": ".w64",
        }
        _SUPPORTED_INPUT_EXT = {ext for fmt, ext in ext_map.items() if fmt in formats}
        # Accept AIF as an alias for AIFF
        if ".aiff" in _SUPPORTED_INPUT_EXT:
            _SUPPORTED_INPUT_EXT.add(".aif")
    return _SUPPORTED_INPUT_EXT
