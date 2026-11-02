"""A microphone that delivers nothing is reopened, but each reopen that
brings no audio waits longer before the next: a headset that needs more than
a few seconds to start would otherwise be reopened forever and never start."""

import numpy as np

from services.audio.input import STALL_SECONDS, STALL_SECONDS_MAX, AudioInput


def make(monkeypatch):
    mic = AudioInput(on_frame=lambda frame: None)
    mic.available = True
    restarts = []
    monkeypatch.setattr(mic, "restart", lambda: restarts.append(True))
    return mic, restarts


def test_each_fruitless_reopen_waits_longer_up_to_a_limit(monkeypatch):
    mic, restarts = make(monkeypatch)
    waits = []
    for _ in range(8):
        waits.append(mic._stall_seconds)
        mic._on_stall()
    assert len(restarts) == 8
    assert waits[:3] == [STALL_SECONDS, STALL_SECONDS * 2, STALL_SECONDS * 4]
    assert waits == sorted(waits)
    assert waits[-1] == STALL_SECONDS_MAX


def test_audio_arriving_resets_the_wait(monkeypatch):
    mic, _ = make(monkeypatch)
    for _ in range(4):
        mic._on_stall()
    mic._on_block(np.zeros(512, dtype=np.float32))
    assert mic._stall_seconds == STALL_SECONDS


def test_a_silent_microphone_during_playback_is_not_reopened(monkeypatch):
    mic, restarts = make(monkeypatch)
    mic.set_output_busy(True)
    mic._on_stall()
    assert restarts == []
    assert mic._stall_seconds == STALL_SECONDS
