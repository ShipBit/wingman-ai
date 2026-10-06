"""Numbers written out for Pocket TTS, per language."""

import pytest

from api.enums import SpokenLanguage as L
from services.spoken_numbers import safe_spell_out_numbers, spell_out_numbers


@pytest.mark.parametrize(
    "text, spoken",
    [
        ("Das kostet 1.234 Credits.", "Das kostet eintausendzweihundertvierunddreißig Credits."),
        ("Die Reise dauert 3,5 Stunden.", "Die Reise dauert drei Komma fünf Stunden."),
        ("Das sind 3.5 Tonnen.", "Das sind drei Komma fünf Tonnen."),
        ("Die Schilde sind bei 75 %.", "Die Schilde sind bei fünfundsiebzig Prozent."),
        ("Wir landen um 14:30, spätestens 15:00.", "Wir landen um vierzehn Uhr dreißig, spätestens fünfzehn Uhr."),
        ("Am 3. Oktober 1984.", "Am dritten Oktober neunzehnhundertvierundachtzig."),
        ("Es sind -5 Grad, 3-4 Stunden.", "Es sind minus fünf Grad, drei bis vier Stunden."),
        ("Ruf 0151 an.", "Ruf null eins fünf eins an."),
    ],
)
def test_german(text, spoken):
    assert spell_out_numbers(text, L.DE) == spoken


@pytest.mark.parametrize(
    "text",
    ["Der A320 mit 3D-Grafik.", "Version 3.1.0 ist raus.", "Stand: 2026-09-23.", "Am 23.09.2026."],
)
def test_what_is_not_a_plain_number_stays(text):
    assert spell_out_numbers(text, L.DE) == text


def test_english_uses_its_own_separators():
    assert spell_out_numbers("It costs 1,234.5 credits, 42% more.", L.EN) == (
        "It costs one thousand two hundred and thirty-four point five credits, forty-two percent more."
    )


def test_italian_keeps_its_decimals():
    # num2words alone drops them ("2.5" -> "due").
    assert spell_out_numbers("Sono 2,5 euro.", L.IT) == "Sono due virgola cinque euro."


@pytest.mark.parametrize("language", [l for l in L if l != L.OTHER])
def test_every_language_works(language):
    assert "12" not in safe_spell_out_numbers("12 und 3,5 und 50 % um 10:15", language)
