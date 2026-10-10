"""What a voice is handed: abbreviations, units, numbers and the user's rules."""

import os
import shutil
from types import SimpleNamespace as Rule

import pytest

from api.enums import SpokenLanguage as L
from services import speech_text

from tests.support import REPO_ROOT as ROOT
speech_text.configure(ROOT)


def say(text, language=L.DE, rules=(), presets=("sample",), reads_numbers=False):
    return speech_text.prepare_for_speech(
        text, language, list(rules), list(presets), reads_numbers=reads_numbers
    )


SAMPLE = """# Name: Sample
aUEC\tAlpha Juh-Ih-Ssi\tde
aUEC\tAlpha U E C
SCU\tEss Ssi Juh\tde
SCU\tS C U
QT\tQuantum
F7C\tF 7 C
CRU-L1\tKruh-Ell-Wann\tde
CRU-L1\tCrew L 1
"""


@pytest.fixture(autouse=True)
def sample_list(tmp_path):
    """A list of rules for the tests, next to the real bundled tables: the
    Star Citizen list is switched off while we listen to the model alone."""
    folder = tmp_path / "templates" / "pronunciation"
    folder.mkdir(parents=True)
    shutil.copytree(os.path.join(ROOT, "templates", "pronunciation", "builtin"), folder / "builtin")
    (folder / "sample.tsv").write_text(SAMPLE, encoding="utf-8")
    speech_text.configure(str(tmp_path))
    yield
    speech_text.configure(ROOT)


@pytest.mark.parametrize(
    "text, spoken",
    [
        ("Cptn. Kirk wartet.", "Captain Kirk wartet."),
        ("Lt. Cmdr. Data meldet sich.", "Lieutenant Commander Data meldet sich."),
        ("Treffpunkt: Sunshine Blvd.", "Treffpunkt: Sunshine Boulevard."),
        ("Das sind ca. 10 km, also 1 km weniger.", "Das sind circa zehn Kilometer, also ein Kilometer weniger."),
        ("Bei 20 °C, z.B. morgen.", "Bei zwanzig Grad Celsius, zum Beispiel morgen."),
        ("Das kostet 1.234,50 € bzw. $20.", "Das kostet eintausend-zweihundert-vierunddreißig Euro fünfzig beziehungsweise zwanzig Dollar."),
        ("Du hast 12.500 aUEC.", "Du hast zwölftausend-fünfhundert Alpha Juh-Ih-Ssi."),
        ("Der QT-Antrieb braucht 3 h.", "Der Quantum-Antrieb braucht drei Stunden."),
        ("Flieg die F7C nach CRU-L1.", "Flieg die F sieben C nach Kruh-Ell-Wann."),
    ],
)
def test_german(text, spoken):
    assert say(text) == spoken


def test_english():
    assert say("Cptn. Kirk paid $1,234.50 for 3 mph.", L.EN) == (
        "Captain Kirk paid one thousand two hundred and thirty-four dollars fifty "
        "for three miles per hour."
    )


def test_ambiguous_abbreviations_are_left_alone():
    assert say("Main St. in St. Louis.", L.EN) == "Main St. in St. Louis."


def test_a_rule_does_not_touch_a_longer_word():
    assert say("Die QTY bleibt.") == "Die QTY bleibt."


def test_markup_is_never_touched():
    assert say('<break time="500ms"/> Hallo [laughs] 3 km') == (
        '<break time="500ms"/> Hallo [laughs] drei Kilometer'
    )


def test_own_rules_win_over_the_bundled_list():
    assert say("Du hast 5 aUEC.", rules=[Rule(written="aUEC", spoken="Credits")]) == (
        "Du hast fünf Credits."
    )


def test_a_list_switched_off_does_nothing():
    assert say("5 aUEC", presets=()) == "fünf aUEC"


def test_every_bundled_table_loads():
    for language in [l for l in L if l != L.OTHER]:
        assert speech_text._abbreviations(ROOT, language.value)
        assert speech_text._units(ROOT, language.value)
    assert ("star_citizen", "Star Citizen") == speech_text.list_presets(ROOT)[0][:2]
    assert ("sample", "Sample", 8) == speech_text.list_presets(speech_text._app_root)[0]


def test_a_rule_for_one_language_only():
    # German voices would read "U E C" as German letters; players say them in English.
    assert say("5 aUEC", L.EN) == "five Alpha U E C"
    assert say("5 aUEC", L.DE) == "fünf Alpha Juh-Ih-Ssi"
    assert say("Lade 32 SCU.") == "Lade zweiunddreißig Ess Ssi Juh."
    assert say("Nach CRU-L1.", L.EN) == "Nach Crew L one."


def test_a_title_is_capitalized_only_where_a_sentence_starts():
    assert say("Ask Capt. Kirk. Capt. Kirk knows.", L.EN) == "Ask captain Kirk. Captain Kirk knows."


def test_a_voice_that_reads_numbers_gets_them_as_written():
    text = "Am 3. Oktober um 14:30 kostet es 1.234,50 € bei 20 °C, 3-4 km und 1 h, 5 aUEC."
    assert say(text, reads_numbers=True) == (
        "Am 3. Oktober um 14:30 kostet es 1.234,50 € bei 20 °C, 3 bis 4 Kilometer und eine Stunde, 5 Alpha Juh-Ih-Ssi."
    )


def test_a_range_before_a_unit():
    assert say("Sicht 3-4 km, 10–15 min.") == "Sicht drei bis vier Kilometer, zehn bis fünfzehn Minuten."


def test_a_list_as_it_applies_to_a_language():
    rules = speech_text.preset_rules_for(speech_text._app_root, "sample", L.DE)
    assert [(r.written, r.spoken) for r in rules if r.written == "aUEC"] == [("aUEC", "Alpha Juh-Ih-Ssi")]
    rules = speech_text.preset_rules_for(speech_text._app_root, "sample", L.EN)
    assert [(r.written, r.spoken) for r in rules if r.written == "aUEC"] == [("aUEC", "Alpha U E C")]
    assert len({r.written for r in rules}) == len(rules)


def test_an_other_language_gets_only_the_rules():
    rules = [Rule(written="aUEC", spoken="Credits")]
    assert say("5 aUEC, ca. 3 km", L.OTHER, rules=rules, presets=()) == "5 Credits, ca. 3 km"
