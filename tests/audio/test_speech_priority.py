"""Answers > events > radio chatter. A line that is less important than what
plays, or than the user talking, does not cut it off when its audio is
ready: the radio used to take ten seconds to synthesize and then stop the
answer the user had asked for meanwhile."""

import asyncio

import numpy as np

from api.enums import SpeechPriority
from services import audio_player as audio_player_module
from services.audio_player import AudioPlayer
from services.speech_priority import SpeechSlot, current_speech, must_yield


def test_an_event_waits_for_the_user_and_for_answers_but_talks_over_radio():
    assert must_yield(SpeechPriority.EVENT, False, SpeechPriority.ANSWER, True)
    assert must_yield(SpeechPriority.EVENT, True, SpeechPriority.ANSWER, False)
    assert must_yield(SpeechPriority.EVENT, True, SpeechPriority.EVENT, False)
    assert not must_yield(SpeechPriority.EVENT, True, SpeechPriority.BACKGROUND, False)
    assert not must_yield(SpeechPriority.EVENT, False, SpeechPriority.ANSWER, False)


def test_radio_never_talks_over_anything():
    assert must_yield(SpeechPriority.BACKGROUND, True, SpeechPriority.BACKGROUND, False)
    assert must_yield(SpeechPriority.BACKGROUND, False, SpeechPriority.ANSWER, True)
    assert not must_yield(SpeechPriority.BACKGROUND, False, SpeechPriority.ANSWER, False)


def _play(player, priority):
    slot = SpeechSlot(priority)

    async def run():
        current_speech.set(slot)
        await player.play_with_effects((np.zeros(160, dtype=np.float32), 16000), None)

    asyncio.run(run())
    return slot


def test_radio_audio_that_is_ready_while_an_answer_plays_does_not_stop_it(monkeypatch):
    monkeypatch.setattr(audio_player_module.user_activity, "_holding", False)
    player = AudioPlayer(None, None, None)
    player.is_playing = True
    player.playing_priority = SpeechPriority.ANSWER
    stopped = []

    async def stop_playback():
        stopped.append(True)

    player.stop_playback = stop_playback

    slot = _play(player, SpeechPriority.BACKGROUND)

    assert slot.yielded
    assert not stopped
    assert player.playing_priority == SpeechPriority.ANSWER


def test_radio_audio_waits_while_the_user_holds_the_key(monkeypatch):
    monkeypatch.setattr(audio_player_module.user_activity, "_holding", True)
    player = AudioPlayer(None, None, None)

    slot = _play(player, SpeechPriority.BACKGROUND)

    assert slot.yielded
    assert not player.is_playing
