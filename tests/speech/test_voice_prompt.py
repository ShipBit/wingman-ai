"""A voice is cloned from a recording that ends on a pause between words."""

import numpy as np

from services.voice_preprocessing import end_at_word_gap

SR = 24000


def speech(seconds):
    return np.sin(np.arange(int(seconds * SR)) / 5.0).astype(np.float32)


def silence(seconds):
    return np.zeros(int(seconds * SR), dtype=np.float32)


def test_a_long_recording_ends_at_the_last_pause_before_the_limit():
    rec = np.concatenate([speech(5), silence(0.3), speech(4), silence(0.3), speech(6)])
    out = end_at_word_gap(rec, SR, max_seconds=12)
    assert abs(out.size / SR - 9.3) < 0.03  # in front of the second pause


def test_a_recording_that_stops_mid_word_loses_the_cut_off_word():
    rec = np.concatenate([speech(3), silence(0.2), speech(2)])
    assert abs(end_at_word_gap(rec, SR, max_seconds=12).size / SR - 3.0) < 0.03


def test_trailing_silence_is_the_pause_it_ends_on():
    rec = np.concatenate([speech(2), silence(0.2), speech(3), silence(1)])
    assert abs(end_at_word_gap(rec, SR).size / SR - 5.2) < 0.03


def test_without_any_pause_the_limit_cuts():
    assert end_at_word_gap(speech(20), SR, max_seconds=12).size == 12 * SR
    assert end_at_word_gap(speech(3), SR, max_seconds=12).size == 3 * SR
