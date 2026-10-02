"""The voice gate turns frames into utterances; these pin its rules with a fake
detector so no model is needed.

A "speech" frame is one the fake detector rates 1.0, a "silence" frame 0.0.
The gate must: wait for min_speech before opening, keep the pre-roll, close
after end_pause, cut at max_utterance and go on, trim held clips, and drop
held clips without speech.
"""

import numpy as np
import pytest

from services.audio.voice_gate import FRAME_MS, FRAME_SAMPLES, GateParams, VoiceGate

SPEECH = np.full(FRAME_SAMPLES, 0.3, dtype=np.float32)
SILENCE = np.zeros(FRAME_SAMPLES, dtype=np.float32)


class FakeVad:
    """Rates a frame by its amplitude: our synthetic speech frames are loud."""

    def __init__(self):
        self.resets = 0

    def __call__(self, frame):
        return 1.0 if float(np.max(np.abs(frame))) > 0.1 else 0.0

    def reset(self):
        self.resets += 1


def frames_for(ms: int, frame: np.ndarray) -> list[np.ndarray]:
    return [frame] * int(round(ms / FRAME_MS))


def feed_all(gate: VoiceGate, frames):
    out = []
    for frame in frames:
        utterance = gate.feed(frame)
        if utterance is not None:
            out.append(utterance)
    return out


@pytest.fixture
def params():
    return GateParams(sensitivity=0.5, end_pause_ms=500, min_speech_ms=200,
                      max_utterance_s=3.0, pre_roll_ms=300)


def test_armed_emits_after_the_pause(params):
    vad = FakeVad()
    gate = VoiceGate(vad, params, on_reset=vad.reset)
    gate.arm()
    assert vad.resets == 1

    out = feed_all(gate, frames_for(1000, SILENCE) + frames_for(1000, SPEECH) + frames_for(600, SILENCE))

    assert len(out) == 1
    utterance = out[0]
    assert not utterance.truncated
    # pre-roll (300 ms) + speech (1000 ms) + tail (250 ms), give or take a frame
    assert 1.45 <= utterance.duration_s <= 1.65
    assert float(np.max(np.abs(utterance.samples))) == pytest.approx(0.9, abs=0.01)


def test_short_bursts_are_noise(params):
    gate = VoiceGate(FakeVad(), params)
    gate.arm()
    out = feed_all(gate, frames_for(100, SPEECH) + frames_for(1000, SILENCE))
    assert out == []


def test_long_speech_is_cut_and_continues(params):
    gate = VoiceGate(FakeVad(), params)
    gate.arm()
    out = feed_all(gate, frames_for(7000, SPEECH) + frames_for(600, SILENCE))
    assert [u.truncated for u in out] == [True, True, False]
    assert all(2.5 <= u.duration_s <= 3.3 for u in out[:2])


def test_closing_drops_what_was_in_flight(params):
    gate = VoiceGate(FakeVad(), params)
    gate.arm()
    feed_all(gate, frames_for(1000, SPEECH))
    assert gate.close() is None
    out = feed_all(gate, frames_for(1000, SILENCE))
    assert out == []


def test_held_clip_is_trimmed_to_the_speech(params):
    gate = VoiceGate(FakeVad(), params)
    gate.hold()
    out = feed_all(gate, frames_for(1000, SILENCE) + frames_for(800, SPEECH) + frames_for(1000, SILENCE))
    assert out == []
    utterance = gate.release()
    assert utterance is not None
    # not the 2.8 s that were held: pre-roll + 800 ms + tail
    assert 1.2 <= utterance.duration_s <= 1.5


def test_held_clip_without_speech_is_dropped(params):
    gate = VoiceGate(FakeVad(), params)
    gate.hold()
    feed_all(gate, frames_for(1500, SILENCE))
    assert gate.release() is None


def test_held_clip_is_cut_at_max_length_too(params):
    gate = VoiceGate(FakeVad(), params)
    gate.hold()
    out = feed_all(gate, frames_for(4000, SPEECH))
    assert len(out) == 1 and out[0].truncated
    rest = gate.release()
    assert rest is not None and not rest.truncated


def test_sensitivity_maps_onto_the_threshold():
    assert GateParams(sensitivity=0.0).threshold == pytest.approx(0.85)
    assert GateParams(sensitivity=1.0).threshold == pytest.approx(0.25)
    assert GateParams(sensitivity=0.5).threshold == pytest.approx(0.55)


def test_speech_right_after_a_split_is_not_lost(params):
    """The cut carries the frames after the last pause into the next
    utterance. If the speaker stops there, those frames still have to come
    out: the carry starts on speech, so the next utterance knows it."""
    vad = FakeVad()
    gate = VoiceGate(vad, params, on_reset=vad.reset)
    gate.arm()

    # Talk past max_utterance_s with one pause late enough to cut at. The
    # last burst ends exactly where the cut falls, so nothing but silence
    # follows it: all of that speech lives in the carry.
    out = feed_all(gate, frames_for(2000, SPEECH)
                   + frames_for(300, SILENCE)
                   + frames_for(700, SPEECH)
                   + frames_for(600, SILENCE))

    assert len(out) == 2, [u.duration_s for u in out]
    assert out[0].truncated
    assert not out[1].truncated
    assert out[1].duration_s > 0.2
