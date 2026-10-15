"""What happens to a transcript: stop, echo, or a real request."""

from types import SimpleNamespace

import wingman_core
from api.interface import VoiceActivationSettings
from wingman_core import _words


def _core():
    core = wingman_core.WingmanCore.__new__(wingman_core.WingmanCore)
    va = VoiceActivationSettings(enabled=True, mute_toggle_key="x")
    core.settings_service = SimpleNamespace(settings=SimpleNamespace(voice_activation=va))
    return core


def test_default_stop_words_cover_the_ways_people_say_it():
    core = _core()
    for text in ("Stop.", "Stopp!", "shut up", "Halt, bitte", "okay stop", "stop please"):
        assert core._is_stop(_words(text)), text


def test_a_request_is_not_a_stop():
    core = _core()
    for text in ("Stop the engines", "please open the map", "Computer, stop the timer"):
        assert not core._is_stop(_words(text)), text


def test_a_word_that_only_appears_inside_a_phrase_is_not_a_stop():
    """"stop please" must not make "please" alone a stop command, and neither
    "okay", "up" nor "it" - each of them is part of some default phrase."""
    core = _core()
    for text in ("Okay.", "Please", "Up!", "It.", "Bitte"):
        assert not core._is_stop(_words(text)), text


class _Player:
    def __init__(self, speaking_text):
        self.speaking_text = speaking_text


def _core_with(speaking_text):
    core = _core()
    core.audio_player = _Player(speaking_text)
    return core


def test_the_wingmans_own_sentence_is_an_echo():
    core = _core_with("Ja, ich bin hier. Bitte geben Sie Ihre Anweisung.")
    assert core._is_echo(_words("ich bin hier bitte geben sie ihre Anweisung"))
    assert core._is_echo(_words("bin hier, bitte geben"))


def test_the_user_talking_over_it_is_not():
    core = _core_with("Ja, ich bin hier. Bitte geben Sie Ihre Anweisung.")
    assert not core._is_echo(_words("ATC, ich habe eine Frage zum Landeanflug"))


def test_a_sentence_that_only_shares_words_is_not_an_echo():
    """The same words in another order are the user talking, not the
    microphone hearing the speakers."""
    core = _core_with("The landing gear is down and the target is locked.")
    assert not core._is_echo(_words("is the target the gear or the landing"))
    assert core._is_echo(_words("the landing gear is down"))


# --- said over the wingman, heard through speakers ---

ANSWER = "Guten Morgen, Shackles. Alle Systeme sind online und bereit für Ihre Befehle."


def test_the_tail_of_the_answer_is_an_echo():
    core = _core_with(ANSWER)
    words = _words("Systeme sind online und bereit für ihre Befehle.")
    assert core._without_echo(words) == []
    assert core._is_echo(words)


def test_a_misheard_word_or_two_is_still_an_echo():
    core = _core_with(ANSWER)
    words = _words("Systeme sind online und bereit für Ihre Befehle, Schäckles.")
    assert core._without_echo(words) == ["schäckles"]
    assert core._is_echo(words)


def test_stop_said_over_the_answer_is_a_stop():
    core = _core_with(ANSWER)
    for text in ("bereit für ihre Befehle. Stop.", "Befehle, stopp", "Stop"):
        own = core._without_echo(_words(text))
        assert core._is_stop(own) or core._has_stop_word(own), text


def test_stop_among_the_users_protest_is_a_stop():
    core = _core_with(ANSWER)
    text = "Stopp. Es geht mir wie immer hervorragender. Stopp. funktionslos. Interessiert mich nicht."
    own = core._without_echo(_words(text))
    assert not core._is_stop(own)
    assert core._has_stop_word(own)


def test_talking_over_the_answer_keeps_only_the_users_words():
    core = _core_with(ANSWER)
    words = _words("online und bereit für Ihre Befehle. Computer, öffne die Karte bitte.")
    assert not core._is_echo(words)
    assert core._without_echo(words) == ["computer", "öffne", "die", "karte", "bitte"]


# --- the user's own words that the answer happens to contain ---

THRUSTERS = (
    "Landing thrusters deployed - assuming \"lineing\" meant landing, unless you've "
    "invented a new kind of maneuvering. You're cleared to set her down whenever "
    "the tower waves you in."
)


def test_single_shared_words_stay_with_the_user():
    core = _core_with(THRUSTERS)
    text = "Well I meant landing but you did exactly what I wanted, so that's fine."
    words = _words(text)
    assert core._without_echo(words) == words
    assert not core._is_echo(words)


def test_a_short_command_keeps_its_small_words():
    core = _core_with("Armistice zone entered, Logan - try not to start a diplomatic incident.")
    words = _words("Switch to Navigation mode.")
    assert core._without_echo(words) == words


def test_a_short_answer_heard_back_whole_is_an_echo():
    core = _core_with("Copy that.")
    assert core._is_echo(_words("copy that"))


def test_the_users_words_keep_their_capitals_and_commas():
    core = _core_with("Panel's on the glass. That's a proper day's work, Logan.")
    text = "Panels on the glass. No, change the full spec max to the Yadar."
    hits = core._echo_hits(_words(text))
    assert core._text_without_echo(text, hits) == "Panels. No, change the full spec max to the Yadar"
