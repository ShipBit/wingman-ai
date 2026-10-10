"""Numbers written out for Pocket TTS, per language."""

import pytest

from api.enums import SpokenLanguage as L
from services.spoken_numbers import safe_spell_out_numbers, spell_out_numbers


@pytest.mark.parametrize(
    "text, spoken",
    [
        ("Das kostet 1.234 Credits.", "Das kostet eintausend-zweihundert-vierunddreißig Credits."),
        ("Die Hermes hat 288 SCU.", "Die Hermes hat zweihundert-achtundachtzig SCU."),
        ("Die Reise dauert 3,5 Stunden.", "Die Reise dauert drei Komma fünf Stunden."),
        ("Das sind 3.5 Tonnen.", "Das sind drei Komma fünf Tonnen."),
        ("Die Schilde sind bei 75 %.", "Die Schilde sind bei fünfundsiebzig Prozent."),
        ("Wir landen um 14:30, spätestens 15:00.", "Wir landen um vierzehn Uhr dreißig, spätestens fünfzehn Uhr."),
        ("Am 3. Oktober 1984.", "Am dritten Oktober neunzehnhundert-vierundachtzig."),
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


# ───────────────────────── round_for_speech ───────────────────────── #

from services.spoken_numbers import round_for_speech


@pytest.mark.parametrize(
    "language, written, spoken",
    [
        (L.EN, "Buy for 6,894,720 aUEC.", "Buy for about 6.9 million aUEC."),
        (L.EN, "That is 689,482,137 in total.", "That is about 690 million in total."),
        (L.EN, "Sell for 565,632 aUEC.", "Sell for about 566,000 aUEC."),
        (L.EN, "Profit: ~270,000 aUEC.", "Profit: about 270,000 aUEC."),
        (L.EN, "about 637,000 an hour", "about 637,000 an hour"),
        (L.EN, "exactly 2,000,000", "exactly 2 million"),
        (L.EN, "1,234,567,890 total", "about 1.2 billion total"),
        (L.DE, "Kaufen für 6.894.720 aUEC.", "Kaufen für rund 6,9 Millionen aUEC."),
        (L.DE, "Gewinn rund 1.464.000.", "Gewinn rund 1,5 Millionen."),
        (L.DE, "1.000.000 Credits", "1 Million Credits"),
        (L.DE, "396.288 Credits", "rund 396.000 Credits"),
        (L.FR, "pour 6 894 720 aUEC", "pour environ 6,9 millions aUEC"),
        (L.FR, "1 464 000 de profit", "environ 1,5 million de profit"),
    ],
)
def test_long_amounts_are_rounded_for_the_voice(language, written, spoken):
    assert round_for_speech(written, language) == spoken


@pytest.mark.parametrize(
    "written",
    ["288 SCU", "1.964 aUEC pro SCU", "Marge 17,4 %", "Bestellnummer 1234567", "Version 3.2.7", "im Jahr 1984", "12.500 Credits"],
)
def test_short_numbers_and_ids_stay_as_written(written):
    assert round_for_speech(written, L.DE) == written
