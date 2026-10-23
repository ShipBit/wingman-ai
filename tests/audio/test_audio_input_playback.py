"""A microphone that goes silent while the speakers play is reopened after
the playback, not during it (reopening reconfigures a combined device under
the playing speakers, heard as a crack)."""

import time

from services.audio import input as audio_input
from services.audio.input import AudioInput


def make(monkeypatch):
    mic = AudioInput(on_frame=lambda frame: None)
    restarts = []
    monkeypatch.setattr(mic, "restart", lambda: restarts.append(True))
    monkeypatch.setattr(audio_input.threading, "Thread", lambda target, **kw: type("T", (), {"start": lambda self: target()})())
    return mic, restarts


def test_a_microphone_silent_during_playback_is_reopened_when_it_ends(monkeypatch):
    mic, restarts = make(monkeypatch)
    mic.set_output_busy(True)
    mic._last_block = time.monotonic() - 3
    mic.set_output_busy(False)
    assert restarts == [True]


def test_a_microphone_that_kept_delivering_is_left_alone(monkeypatch):
    mic, restarts = make(monkeypatch)
    mic.set_output_busy(True)
    mic._last_block = time.monotonic()
    mic.set_output_busy(False)
    assert restarts == []
