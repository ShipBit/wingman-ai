"""The listen controller derives one state from four facts. Every event from
every state, plus where utterances go."""

import time

import numpy as np

import services.audio.listen_controller as lc
from services.audio.listen_controller import ListenController, ListenState
from services.audio.voice_gate import FRAME_SAMPLES, GateParams, Utterance, VoiceGate


class Recorder:
    def __init__(self):
        self.utterances = []
        self.states = []

    def on_utterance(self, utterance, wingman, during_playback):
        self.utterances.append((utterance, wingman, during_playback))

    def on_state(self, state):
        self.states.append(state)


def make():
    rec = Recorder()
    gate = VoiceGate(lambda frame: 1.0 if frame.max() > 0.1 else 0.0,
                     GateParams(end_pause_ms=100, min_speech_ms=64, max_utterance_s=5, pre_roll_ms=64))
    controller = ListenController(gate, rec.on_utterance, rec.on_state)
    return controller, rec, gate


SPEECH = np.full(FRAME_SAMPLES, 0.3, dtype=np.float32)
SILENCE = np.zeros(FRAME_SAMPLES, dtype=np.float32)


def speak(controller, speech_frames=10, silence_frames=6):
    for _ in range(speech_frames):
        controller.feed(SPEECH)
    for _ in range(silence_frames):
        controller.feed(SILENCE)


def release(controller, source):
    """Key up, then the grace frames that let the last syllable in."""
    ok = controller.ptt_up(source)
    for _ in range(12):
        controller.feed(SILENCE)
    return ok


def test_starts_off_and_switching_on_means_listening():
    controller, rec, _ = make()
    assert controller.state == ListenState.OFF
    controller.set_voice_activation(True)
    assert controller.state == ListenState.ARMED
    assert rec.states == [ListenState.ARMED]


def test_mute_and_unmute():
    controller, _, _ = make()
    controller.set_voice_activation(True)
    controller.set_muted(True)
    assert controller.state == ListenState.MUTED
    controller.toggle_muted()
    assert controller.state == ListenState.ARMED


def test_switching_on_clears_an_old_mute():
    controller, _, _ = make()
    controller.set_voice_activation(True)
    controller.set_muted(True)
    controller.set_voice_activation(False)
    controller.set_voice_activation(True)
    assert controller.state == ListenState.ARMED


def test_playback_keeps_listening_by_default_and_marks_utterances():
    controller, rec, _ = make()
    controller.set_voice_activation(True)
    controller.playback_started()
    assert controller.state == ListenState.ARMED
    speak(controller)
    assert rec.utterances[-1][2] is True
    controller.playback_finished()
    controller._playback_ended_at = float("-inf")  # well past the tail
    speak(controller)
    assert rec.utterances[-1][2] is False


def test_playback_pauses_when_listening_while_speaking_is_off():
    controller, rec, _ = make()
    controller.set_voice_activation(True)
    controller.set_listen_while_speaking(False)
    controller.playback_started()
    assert controller.state == ListenState.PAUSED
    speak(controller)
    assert rec.utterances == []
    controller.playback_finished()
    assert controller.state == ListenState.ARMED


def test_playback_while_muted_stays_muted():
    controller, _, _ = make()
    controller.set_voice_activation(True)
    controller.set_muted(True)
    controller.playback_started()
    assert controller.state == ListenState.MUTED
    controller.playback_finished()
    assert controller.state == ListenState.MUTED


def test_ptt_returns_to_where_it_came_from():
    controller, rec, _ = make()
    wingman = object()
    assert controller.ptt_down("f1", wingman)
    assert controller.state == ListenState.HELD
    assert release(controller, "f1")  # nothing was said
    assert controller.state == ListenState.OFF
    assert rec.utterances == []

    controller.set_voice_activation(True)
    controller.ptt_down("f1", wingman)
    speak(controller, silence_frames=0)
    release(controller, "f1")
    assert controller.state == ListenState.ARMED
    assert rec.utterances[-1][1] is wingman


def test_the_grace_period_keeps_the_last_syllable():
    controller, rec, _ = make()
    wingman = object()
    controller.ptt_down("f1", wingman)
    speak(controller, speech_frames=6, silence_frames=0)
    controller.ptt_up("f1")
    # still speaking after the key went up: those frames belong to the clip
    for _ in range(4):
        controller.feed(SPEECH)
    for _ in range(12):
        controller.feed(SILENCE)
    assert len(rec.utterances) == 1
    assert rec.utterances[0][0].duration_s > 9 * FRAME_SAMPLES / 16000


def test_pressing_again_within_the_grace_keeps_holding():
    controller, rec, _ = make()
    controller.ptt_down("f1", object())
    speak(controller, speech_frames=6, silence_frames=0)
    controller.ptt_up("f1")
    controller.feed(SILENCE)
    assert controller.ptt_down("f1", object())
    assert controller.state == ListenState.HELD
    speak(controller, speech_frames=6, silence_frames=0)
    release(controller, "f1")
    assert len(rec.utterances) == 1


def test_second_source_cannot_take_the_gate():
    controller, _, _ = make()
    controller.ptt_down("f1", object())
    assert not controller.ptt_down("__gui__", object())
    assert controller.ptt_up("__gui__") is False
    assert controller.state == ListenState.HELD


def test_armed_utterances_carry_no_wingman():
    controller, rec, _ = make()
    controller.set_voice_activation(True)
    speak(controller)
    assert len(rec.utterances) == 1
    assert rec.utterances[0][1] is None


def test_capture_for_the_mic_test_keeps_the_clip():
    controller, rec, _ = make()
    controller.set_voice_activation(True)
    assert controller.capture_start("__test__")
    assert controller.state == ListenState.HELD
    speak(controller, silence_frames=0)
    utterance = controller.capture_stop("__test__")
    assert utterance is not None
    assert rec.utterances == []
    assert controller.state == ListenState.ARMED


def test_off_ignores_frames():
    controller, rec, _ = make()
    speak(controller)
    assert rec.utterances == []


def test_a_long_capture_keeps_every_piece():
    """The gate cuts at max_utterance_s. A mic test held longer than that must
    still come back whole, not just its tail."""
    controller, rec, _ = make()
    assert controller.capture_start("__test__")
    # 5 s at 32 ms a frame is 157 frames; twice that crosses the cut.
    for _ in range(320):
        controller.feed(SPEECH)
    utterance = controller.capture_stop("__test__")
    assert utterance is not None
    assert utterance.duration_s > 5.0
    assert rec.utterances == []


def test_a_dead_stream_does_not_wedge_push_to_talk():
    """No frames arrive after the key goes up: the release still happens, so
    the next press is taken and voice activation can arm again."""
    controller, _, _ = make()
    controller.set_voice_activation(True)
    controller.ptt_down("f1", object())
    for _ in range(4):
        controller.feed(SPEECH)
    assert controller.ptt_up("f1")
    controller._release_timer.join(lc.RELEASE_WATCHDOG_S + 1.0)
    assert controller.held_source is None
    assert controller.state == ListenState.ARMED


def test_a_second_key_inside_the_release_grace_is_taken():
    controller, rec, _ = make()
    first, second = object(), object()
    controller.ptt_down("f1", first)
    for _ in range(10):
        controller.feed(SPEECH)
    assert controller.ptt_up("f1")
    # Before the grace frames are in, the other key goes down.
    assert controller.ptt_down("f2", second)
    assert controller.held_wingman is second
    for _ in range(10):
        controller.feed(SPEECH)
    assert controller.ptt_up("f2")
    for _ in range(20):
        controller.feed(SILENCE)
    assert [u[1] for u in rec.utterances] == [first, second]


# --- said while a wingman speaks ---


def test_utterance_that_started_during_playback_is_flagged_even_if_playback_ended_first():
    controller, rec, _ = make()
    controller.set_voice_activation(True)
    controller.playback_started()
    for _ in range(4):
        controller.feed(SPEECH)
    # The wingman finishes while the user (or the echo) is still talking.
    controller.playback_finished()
    speak(controller, speech_frames=6, silence_frames=6)
    assert len(rec.utterances) == 1
    assert rec.utterances[0][2] is True


def test_utterance_right_after_playback_counts_as_during_it(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(lc.time, "monotonic", lambda: now[0])
    controller, rec, _ = make()
    controller.set_voice_activation(True)
    controller.playback_started()
    controller.playback_finished()
    now[0] += lc.PLAYBACK_TAIL_S / 2
    speak(controller)
    assert rec.utterances[0][2] is True


def test_utterance_long_after_playback_is_the_user(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(lc.time, "monotonic", lambda: now[0])
    controller, rec, _ = make()
    controller.set_voice_activation(True)
    controller.playback_started()
    controller.playback_finished()
    now[0] += 5.0
    speak(controller)
    assert rec.utterances[0][2] is False


def test_flag_does_not_leak_into_the_next_utterance():
    controller, rec, _ = make()
    controller.set_voice_activation(True)
    controller.playback_started()
    speak(controller)
    controller.playback_finished()
    controller._playback_ended_at = float("-inf")
    speak(controller)
    assert [u[2] for u in rec.utterances] == [True, False]


# --- a hold nobody released ---


def _wait_until(condition, timeout=2.0):
    end = time.monotonic() + timeout
    while not condition() and time.monotonic() < end:
        time.sleep(0.01)


def test_a_key_without_a_release_is_let_go_after_the_limit(monkeypatch):
    monkeypatch.setattr(lc, "MAX_HOLD_S", 0.05)
    expired = []
    rec = Recorder()
    gate = VoiceGate(lambda frame: 1.0 if frame.max() > 0.1 else 0.0,
                     GateParams(end_pause_ms=100, min_speech_ms=64, max_utterance_s=5, pre_roll_ms=64))
    controller = ListenController(gate, rec.on_utterance, rec.on_state, on_hold_expired=expired.append)
    controller.set_voice_activation(True)
    assert controller.ptt_down("key:1", "wingman")
    for _ in range(10):
        controller.feed(SPEECH)
    _wait_until(lambda: expired and controller.held_source is None)
    assert expired == ["key:1"]
    assert controller.held_source is None
    assert controller.state == ListenState.ARMED
    assert len(rec.utterances) == 1  # the clip still went out
    # and the next key is taken
    assert controller.ptt_down("key:2", "wingman")


def test_a_release_in_time_disarms_the_limit(monkeypatch):
    monkeypatch.setattr(lc, "MAX_HOLD_S", 0.05)
    expired = []
    rec = Recorder()
    gate = VoiceGate(lambda frame: 1.0 if frame.max() > 0.1 else 0.0,
                     GateParams(end_pause_ms=100, min_speech_ms=64, max_utterance_s=5, pre_roll_ms=64))
    controller = ListenController(gate, rec.on_utterance, rec.on_state, on_hold_expired=expired.append)
    controller.ptt_down("key:1", "wingman")
    release(controller, "key:1")
    time.sleep(0.15)
    assert expired == []


def test_a_forgotten_mic_test_is_dropped_after_the_limit(monkeypatch):
    monkeypatch.setattr(lc, "MAX_HOLD_S", 0.05)
    controller, rec, _ = make()
    controller.set_voice_activation(True)
    assert controller.capture_start("__test__")
    assert controller.state == ListenState.HELD
    _wait_until(lambda: controller.held_source is None)
    assert controller.held_source is None
    assert controller.state == ListenState.ARMED
    assert rec.utterances == []
