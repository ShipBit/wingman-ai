"""A line said on the wingman's own initiative whose audio is ready while
the user got an answer: an event is said after the answer, radio chatter is
not said at all."""

import asyncio
from types import SimpleNamespace

from api.enums import SpeechPriority, SpokenLanguage, TtsProvider
from api.interface import PronunciationSettings
from services import user_activity as user_activity_module
from services.speech_priority import current_speech
from wingmen.wingman import Wingman


class FakePlayer:
    def __init__(self):
        self.is_playing = False
        self.playing_priority = SpeechPriority.ANSWER
        self.speaking_text = ""


class FakeTts:
    """The first line comes out while an answer plays: the player refuses
    it. The answer ends a moment later."""

    def __init__(self, player):
        self.player = player
        self.calls = 0

    async def play_audio(self, text, sound_config, audio_player, wingman_name):
        self.calls += 1
        if self.calls == 1:
            current_speech.get().yielded = True
            self.player.is_playing = True
            asyncio.get_running_loop().call_later(0.2, self._answer_ends)

    def _answer_ends(self):
        self.player.is_playing = False


def _wingman():
    player = FakePlayer()
    wingman = SimpleNamespace(
        _unloaded=False,
        name="Angel",
        skills=[],
        audio_player=player,
        config=SimpleNamespace(
            sound=SimpleNamespace(volume=1.0),
            features=SimpleNamespace(tts_provider=TtsProvider.EDGE_TTS),
        ),
        settings=SimpleNamespace(
            spoken_language=SpokenLanguage.EN, pronunciation=PronunciationSettings(rules=[], presets=[])
        ),
    )
    wingman.tts = FakeTts(player)
    wingman._wait_for_turn = Wingman._wait_for_turn.__get__(wingman)
    return wingman


def _say(wingman, priority):
    return asyncio.run(
        Wingman.play_to_user(wingman, "Arrived at Orison.", priority=priority)
    )


def test_an_event_is_said_after_the_answer_that_came_first(monkeypatch):
    monkeypatch.setattr(user_activity_module.user_activity, "_holding", False)
    wingman = _wingman()

    assert _say(wingman, SpeechPriority.EVENT) is True
    assert wingman.tts.calls == 2


def test_radio_chatter_that_came_second_is_dropped(monkeypatch):
    monkeypatch.setattr(user_activity_module.user_activity, "_holding", False)
    wingman = _wingman()

    assert _say(wingman, SpeechPriority.BACKGROUND) is False
    assert wingman.tts.calls == 1
