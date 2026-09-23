"""Numbers written out as words, before Pocket TTS reads the text.

Pocket TTS passes digits to the model as they are, and the model is too small
to read them: German "1.234" or "3,5" came out garbled. Kyutai does not plan to
normalize text in the library and asks users to do it before generation
(kyutai-labs/pocket-tts#234). This does the part Wingman's answers need:
plain numbers with the language's own separators, decimals, percentages,
clock times, years and, in German, the day in "am 3. Oktober".

Everything else is left as it is. A wrong guess is worse than digits: the
model at least reads a lone "7" correctly.
"""

import re
from decimal import InvalidOperation

from num2words import num2words

from api.enums import SpokenLanguage

_NUM2WORDS_LANG = {
    SpokenLanguage.EN: "en",
    SpokenLanguage.DE: "de",
    SpokenLanguage.FR: "fr",
    SpokenLanguage.ES: "es",
    SpokenLanguage.IT: "it",
    SpokenLanguage.PT: "pt_BR",
}

# Written ourselves: num2words drops the decimals in Italian ("2.5" -> "due").
_DECIMAL_WORD = {
    SpokenLanguage.EN: "point",
    SpokenLanguage.DE: "Komma",
    SpokenLanguage.FR: "virgule",
    SpokenLanguage.ES: "coma",
    SpokenLanguage.IT: "virgola",
    SpokenLanguage.PT: "vírgula",
}

_PERCENT_WORD = {
    SpokenLanguage.EN: "percent",
    SpokenLanguage.DE: "Prozent",
    SpokenLanguage.FR: "pour cent",
    SpokenLanguage.ES: "por ciento",
    SpokenLanguage.IT: "per cento",
    SpokenLanguage.PT: "por cento",
}

_RANGE_WORD = {
    SpokenLanguage.EN: "to",
    SpokenLanguage.DE: "bis",
    SpokenLanguage.FR: "à",
    SpokenLanguage.ES: "a",
    SpokenLanguage.IT: "a",
    SpokenLanguage.PT: "a",
}

_GERMAN_MONTHS = (
    "Januar|Jänner|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember"
)

# A number as people write it: optional minus, digits, and thousands or
# decimal separators between digit groups. Not part of a word ("A320", "3D")
# and not chained with hyphens (the ISO date 2026-09-23, IDs): left as they are.
NUMBER_PATTERN = r"(?<![\w.,])(?<!\d-)(-?)(\d+(?:[.,\u00a0\u202f ]\d+)*)"
"""Sign and digits of a written number; shared with the units in speech_text."""
_NUMBER = re.compile(NUMBER_PATTERN + r"(?![\w]|-\d)")
_TIME = re.compile(r"(?<![\w.:])([01]?\d|2[0-3]):([0-5]\d)(?![\w:])")
_PERCENT = re.compile(r"(\d)\s?%")
# "3-4 Stunden", "10–15 Minuten": a range, read "3 bis 4". Short numbers only,
# and not a chain like the ISO date 2026-09-23.
_RANGE = re.compile(r"(?<![\w.,-])(\d{1,4})\s?[-–]\s?(\d{1,4})(?![\w.,-]?\d)")
_GERMAN_DATE = re.compile(rf"(?<![\w.])(\d{{1,2}})\.\s+({_GERMAN_MONTHS})\b")


def spell_out_numbers(text: str, language: SpokenLanguage) -> str:
    """``text`` with its numbers written as words in ``language``."""
    lang = _NUM2WORDS_LANG[language]

    if language == SpokenLanguage.DE:
        # "am 3. Oktober" -> "am dritten Oktober": the dative, which is how an
        # assistant uses a date ("am", "bis zum", "vom").
        text = _GERMAN_DATE.sub(
            lambda m: f"{_words(num2words(int(m.group(1)), lang=lang, to='ordinal'))}n {m.group(2)}",
            text,
        )

    text = _TIME.sub(lambda m: _time(int(m.group(1)), int(m.group(2)), language), text)
    text = _RANGE.sub(lambda m: f"{m.group(1)} {_RANGE_WORD[language]} {m.group(2)}", text)
    text = _PERCENT.sub(lambda m: f"{m.group(1)} {_PERCENT_WORD[language]}", text)
    return _NUMBER.sub(lambda m: _number(m.group(1), m.group(2), language) or m.group(0), text)


def _number(sign: str, body: str, language: SpokenLanguage) -> str | None:
    lang = _NUM2WORDS_LANG[language]
    body = body.replace(" ", " ").replace(" ", " ")
    integer, decimals = split_number(body, language)
    if integer is None:
        return None

    # Phone numbers, codes, IDs: read digit by digit, as people do.
    if (len(integer) > 1 and integer.startswith("0") and decimals is None) or len(integer) > 12:
        words = " ".join(_words(num2words(int(d), lang=lang)) for d in integer)
    elif body.isdigit() and len(body) == 4 and 1100 <= int(body) <= 1999 and not sign:
        # Written without a separator, like a year is ("1984"). "1.234" is
        # an amount and stays "eintausendzweihundert...".
        words = _words(num2words(int(integer), lang=lang, to="year"))
    else:
        words = _words(num2words(int(integer), lang=lang))

    if decimals:
        digits = " ".join(_words(num2words(int(d), lang=lang)) for d in decimals)
        words = f"{words} {_DECIMAL_WORD[language]} {digits}"
    if sign:
        words = f"minus {words}" if language != SpokenLanguage.FR else f"moins {words}"
    return words


def split_number(body: str, language: SpokenLanguage) -> tuple[str | None, str | None]:
    """Integer digits and decimal digits of a written number, by the
    language's convention: English "1,234.5", the others "1.234,5" (French
    also "1 234,5"). A lone separator followed by exactly three digits is a
    thousands separator in that convention, anything else a decimal point."""
    thousands, decimal = (",", ".") if language == SpokenLanguage.EN else (".", ",")
    separators = [c for c in body if not c.isdigit()]
    if not separators:
        return body, None

    groups = re.split(r"[.,\s]", body)
    if len(set(separators)) > 1:
        # Both kinds: the last one is the decimal point.
        last = max(body.rfind("."), body.rfind(","))
        integer = re.sub(r"\D", "", body[:last])
        return integer, body[last + 1 :]

    sep = separators[0]
    if sep == " " or (len(separators) > 1 and all(len(g) == 3 for g in groups[1:])):
        return "".join(groups), None
    if len(separators) == 1:
        if sep == thousands and len(groups[1]) == 3:
            return "".join(groups), None
        if sep in (decimal, thousands):
            return groups[0], groups[1]
    return None, None


def _time(hours: int, minutes: int, language: SpokenLanguage) -> str:
    lang = _NUM2WORDS_LANG[language]
    h = _words(num2words(hours, lang=lang))
    m = _words(num2words(minutes, lang=lang))
    if language == SpokenLanguage.DE:
        return f"{h} Uhr" if minutes == 0 else f"{h} Uhr {m}"
    if language == SpokenLanguage.EN:
        return f"{h} o'clock" if minutes == 0 else f"{h} {m if minutes >= 10 else 'oh ' + m}"
    return f"{h} {m}" if minutes else h


def _words(spelled: str) -> str:
    """num2words puts commas into English and Portuguese numbers ("one
    thousand, two hundred"); read aloud they become pauses."""
    return spelled.replace(",", "")


def safe_spell_out_numbers(text: str, language: SpokenLanguage) -> str:
    """spell_out_numbers that never costs an answer: any failure keeps the
    text as it was."""
    try:
        return spell_out_numbers(text, language)
    except (InvalidOperation, ValueError, NotImplementedError, OverflowError, KeyError):
        return text
