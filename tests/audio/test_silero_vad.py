"""The detector on real audio. The speech clip is three seconds of a person
talking into an audio interface, 16 kHz mono, recorded with scripts/mic_check.py.
The first wrapper fed the model bare 512-sample frames and rated that clip
at 0.006; the model wants 64 samples of context in front."""

from os import path

import numpy as np
import soundfile

from services.audio.vad import FRAME_SAMPLES, SileroVad

from tests.support import REPO_ROOT as ROOT


def frames_of(file: str):
    wav, sr = soundfile.read(path.join(ROOT, file), dtype="float32")
    assert sr == 16000
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    return [wav[i : i + FRAME_SAMPLES] for i in range(0, len(wav) - FRAME_SAMPLES, FRAME_SAMPLES)]


def test_speech_is_speech():
    vad = SileroVad(ROOT)
    scores = [vad(f) for f in frames_of("tests/fixtures/speech_16k.wav")]
    assert max(scores) > 0.9
    assert sum(s > 0.5 for s in scores) > len(scores) / 3


def test_noise_is_not():
    vad = SileroVad(ROOT)
    from scipy.signal import resample_poly

    for file in ("audio_samples/White_Noise.wav", "audio_samples/Radio_Static.wav"):
        wav, sr = soundfile.read(path.join(ROOT, file), dtype="float32")
        if wav.ndim > 1:
            wav = wav.mean(axis=1)
        if sr != 16000:
            wav = resample_poly(wav, 16000, sr).astype(np.float32)
        vad.reset()
        scores = [vad(wav[i : i + FRAME_SAMPLES]) for i in range(0, len(wav) - FRAME_SAMPLES, FRAME_SAMPLES)]
        assert max(scores) < 0.3, file


def test_reset_forgets_the_context():
    vad = SileroVad(ROOT)
    frames = frames_of("tests/fixtures/speech_16k.wav")
    for f in frames[:20]:
        vad(f)
    vad.reset()
    assert np.all(vad._context == 0)
