"""Audio resampling: the microphone down to 16 kHz for the voice gate, and
speech up or down to the rate the speakers run at. Right length, right pitch,
no seams between blocks."""

import numpy as np

from services.audio.resample import FRAME_SAMPLES, RateConverter, Resampler


def tone(rate: int, seconds: float, hz: float) -> np.ndarray:
    t = np.arange(int(rate * seconds)) / rate
    return (0.5 * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def run(rate: int, block: int, seconds: float = 2.0, hz: float = 440.0) -> np.ndarray:
    r = Resampler(rate)
    src = tone(rate, seconds, hz)
    out = []
    for i in range(0, len(src), block):
        out += r.push(src[i : i + block])
    return np.concatenate(out) if out else np.zeros(0, np.float32)


def dominant_hz(signal: np.ndarray, rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(signal * np.hanning(len(signal))))
    return float(np.argmax(spectrum)) * rate / len(signal)


# ── input: Resampler ──────────────────────────────────────────────────


def test_48k_to_16k_keeps_length_and_pitch():
    out = run(48000, 1536)
    assert abs(len(out) - 32000) < 600  # 2 s at 16 kHz, minus filter warm-up
    assert abs(dominant_hz(out, 16000) - 440) < 5


def test_44k1_to_16k_keeps_length_and_pitch():
    out = run(44100, 1411)
    assert abs(len(out) - 32000) < 600
    assert abs(dominant_hz(out, 16000) - 440) < 5


def test_16k_passes_through_in_frames():
    r = Resampler(16000)
    frames = r.push(np.ones(1000, np.float32)) + r.push(np.ones(1000, np.float32))
    assert [len(f) for f in frames] == [512, 512, 512]


def test_no_seams_between_blocks():
    # A seam would show as a jump far larger than the tone's own slope.
    out = run(48000, 1536, seconds=1.0, hz=200.0)
    steps = np.abs(np.diff(out[200:]))
    assert float(steps.max()) < 0.06


def test_a_device_below_the_target_rate_still_opens():
    """An 8 kHz headset (Bluetooth HFP): the low-pass has to sit under the
    device's own Nyquist, not under the target's, or firwin raises and the
    microphone is switched off for the session."""
    resampler = Resampler(8000)
    frames = resampler.push(np.zeros(8000, dtype=np.float32))
    assert frames
    assert all(len(f) == FRAME_SAMPLES for f in frames)


# ── output: RateConverter ─────────────────────────────────────────────


def sine(rate, seconds=0.5, hz=440.0):
    t = np.arange(int(rate * seconds)) / rate
    return np.sin(2 * np.pi * hz * t).astype(np.float32)


def convert_in_blocks(converter, samples, block=1024):
    out = [converter.convert(samples[i : i + block]) for i in range(0, len(samples), block)]
    return np.concatenate(out)


def test_same_rate_is_untouched():
    c = RateConverter(48000, 48000)
    x = sine(48000)
    assert np.array_equal(c.convert(x), x)


def test_up_from_24k_to_48k_keeps_the_tone_and_doubles_the_length():
    x = sine(24000)
    y = convert_in_blocks(RateConverter(24000, 48000), x)
    assert abs(len(y) - 2 * len(x)) <= 2
    expected = sine(48000)[: len(y)]
    assert np.corrcoef(y[100:-100], expected[100:-100])[0, 1] > 0.999


def test_down_from_48k_to_44100_keeps_the_tone():
    x = sine(48000)
    y = convert_in_blocks(RateConverter(48000, 44100), x)
    assert abs(len(y) - len(x) * 44100 / 48000) <= 2
    expected = sine(44100)[: len(y)]
    # the low-pass delays the signal a little; compare against the best shift
    best = max(
        np.corrcoef(y[200 : -200], expected[200 - s : len(y) - 200 - s])[0, 1]
        for s in range(0, 40)
    )
    assert best > 0.99


def test_blocks_of_any_size_join_without_a_seam():
    x = sine(16000)
    whole = RateConverter(16000, 48000).convert(x)
    pieces = convert_in_blocks(RateConverter(16000, 48000), x, block=333)
    n = min(len(whole), len(pieces))
    assert np.allclose(whole[:n], pieces[:n], atol=1e-5)
