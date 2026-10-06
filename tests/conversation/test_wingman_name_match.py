"""Which wingman a sentence addresses. The speech model misspells names, so
the match tolerates a letter or two, and only near the start of the sentence."""

from types import SimpleNamespace

from services.tower import Tower


def tower_with(*names, default=None):
    tower = Tower.__new__(Tower)
    tower.wingmen = [
        SimpleNamespace(config=SimpleNamespace(name=name, is_voice_activation_default=(name == default)))
        for name in names
    ]
    return tower


def name_of(wingman):
    return wingman.config.name if wingman else None


def test_exact_name_still_wins():
    tower = tower_with("Computer", "Ava")
    assert name_of(tower.get_wingman_from_text("Computer, open the map")) == "Computer"


def test_a_letter_off_is_fine():
    tower = tower_with("Computer", "Ava")
    assert name_of(tower.get_wingman_from_text("Computa, open the map")) == "Computer"
    assert name_of(tower.get_wingman_from_text("Hey Eva, how are you")) == "Ava"


def test_a_different_word_is_not_a_name():
    tower = tower_with("Computer", default="Computer")
    # "complete" is three edits away; falls through to the default, not a match
    assert name_of(tower.get_wingman_from_text("complete the mission")) == "Computer"
    tower = tower_with("Computer")
    assert tower.get_wingman_from_text("complete the mission") is None


def test_name_late_in_the_sentence_does_not_count():
    tower = tower_with("Ava")
    text = "please could you tell me what the weather is like today ava"
    assert tower.get_wingman_from_text(text) is None


def test_multi_word_names():
    tower = tower_with("Star Citizen", "Ava")
    assert name_of(tower.get_wingman_from_text("star citizen status report")) == "Star Citizen"


def test_default_wingman_answers_when_nobody_is_named():
    tower = tower_with("Computer", "Ava", default="Ava")
    assert name_of(tower.get_wingman_from_text("what time is it")) == "Ava"


def test_a_common_word_is_not_a_misheard_short_name():
    """"at" is one edit from the shipped "ATC" wingman. Routing "Take a look
    at the map" to ATC because of it would be worse than missing a name."""
    from services.name_match import find_name, words_of

    assert find_name(words_of("Take a look at the map"), "ATC") is None
    assert find_name(words_of("ATC, request landing"), "ATC") == (0, 1, 0)
    # A misspelling that is not a common word still counts.
    assert find_name(words_of("Eva, status report"), "Ava") is not None
