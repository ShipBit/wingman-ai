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

import math
import re
from decimal import InvalidOperation
from functools import lru_cache

from num2words import num2words

from api.enums import SpokenLanguage

_NUM2WORDS_LANG = {
    SpokenLanguage.EN: "en",
    SpokenLanguage.DE: "de",
    SpokenLanguage.FR: "fr",
    SpokenLanguage.ES: "es",
    SpokenLanguage.IT: "it",
    SpokenLanguage.PT: "pt_BR",
    SpokenLanguage.NL: "nl",
}

# Written ourselves: num2words drops the decimals in Italian ("2.5" -> "due").
_DECIMAL_WORD = {
    SpokenLanguage.EN: "point",
    SpokenLanguage.DE: "Komma",
    SpokenLanguage.FR: "virgule",
    SpokenLanguage.ES: "coma",
    SpokenLanguage.IT: "virgola",
    SpokenLanguage.PT: "vírgula",
    SpokenLanguage.NL: "komma",
}

_PERCENT_WORD = {
    SpokenLanguage.EN: "percent",
    SpokenLanguage.DE: "Prozent",
    SpokenLanguage.FR: "pour cent",
    SpokenLanguage.ES: "por ciento",
    SpokenLanguage.IT: "per cento",
    SpokenLanguage.PT: "por cento",
    SpokenLanguage.NL: "procent",
}

_RANGE_WORD = {
    SpokenLanguage.EN: "to",
    SpokenLanguage.DE: "bis",
    SpokenLanguage.FR: "à",
    SpokenLanguage.ES: "a",
    SpokenLanguage.IT: "a",
    SpokenLanguage.PT: "a",
    SpokenLanguage.NL: "tot",
}

_MINUS_WORD = {
    SpokenLanguage.FR: "moins",
    SpokenLanguage.ES: "menos",
    SpokenLanguage.IT: "meno",
    SpokenLanguage.PT: "menos",
    SpokenLanguage.NL: "min",
}


@lru_cache(maxsize=None)
def number_words(language: SpokenLanguage) -> frozenset[str]:
    """Lower-case words spell_out_numbers writes for ``language``: "two",
    "hundred", "and", "eighty", "point". Empty for a language num2words does
    not know."""
    lang = _NUM2WORDS_LANG.get(language)
    if not lang:
        return frozenset()
    samples = [*range(101), *range(100, 1000, 100), *range(1000, 10000, 1000), 10**6, 2 * 10**6, 10**9, 2 * 10**9]
    out = {_DECIMAL_WORD[language].lower(), *_PERCENT_WORD[language].lower().split()}
    for n in samples:
        out.update(re.split(r"[\s-]+", num2words(n, lang=lang).lower()))
    out.discard("")
    return frozenset(out)

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
    text = expand_ranges(text, language)
    text = _PERCENT.sub(lambda m: f"{m.group(1)} {_PERCENT_WORD[language]}", text)
    return _NUMBER.sub(lambda m: _number(m.group(1), m.group(2), language) or m.group(0), text)


_APPROX_WORD = {
    SpokenLanguage.EN: "about",
    SpokenLanguage.DE: "rund",
    SpokenLanguage.FR: "environ",
    SpokenLanguage.ES: "aproximadamente",
    SpokenLanguage.IT: "circa",
    SpokenLanguage.PT: "cerca de",
    SpokenLanguage.NL: "ongeveer",
}

# Words that already say a number is not exact; no second one in front.
_APPROX_BEFORE = re.compile(
    r"(?:\b(?:about|around|roughly|approximately|nearly|almost|some|rund|etwa|ungefähr|ca\.|circa|knapp|fast|"
    r"environ|près de|presque|aproximadamente|unos|unas|casi|cerca de|quase|ongeveer|bijna|zo'n)|~)\s*$",
    re.IGNORECASE,
)

# Million and billion words: (singular, plural, plural from 2 on). French and
# Portuguese keep the singular below two ("1,5 million"), the others only
# for exactly one.
_SCALE_WORDS = {
    SpokenLanguage.EN: (("million", "million"), ("billion", "billion"), False),
    SpokenLanguage.DE: (("Million", "Millionen"), ("Milliarde", "Milliarden"), False),
    SpokenLanguage.FR: (("million", "millions"), ("milliard", "milliards"), True),
    SpokenLanguage.ES: (("millón", "millones"), ("mil millones", "mil millones"), False),
    SpokenLanguage.IT: (("milione", "milioni"), ("miliardo", "miliardi"), False),
    SpokenLanguage.PT: (("milhão", "milhões"), ("bilhão", "bilhões"), True),
    SpokenLanguage.NL: (("miljoen", "miljoen"), ("miljard", "miljard"), False),
}

ROUND_FROM = 10_000
"""Spoken amounts from here on are rounded (round_for_speech). Below it are
prices per unit, quantities, years and times, which are short and often
meant exactly."""

_TILDE_NUMBER = re.compile(r"~\s?(?=-?\d)")


def round_for_speech(text: str, language: SpokenLanguage) -> str:
    """Long amounts in ``text`` rounded the way a person says them, for the
    voice only: "689,482,137 aUEC" -> "about 690 million aUEC", "396.288" ->
    "rund 396.000". Two digits from a million on, three from ROUND_FROM.
    Only numbers written with a separator: a bare "1234567" may be an ID.
    "about" goes in front only where rounding changed the number and no
    such word is there yet; a "~" in front becomes the word."""
    if language not in _APPROX_WORD:
        return text
    approx = _APPROX_WORD[language]
    text = _TILDE_NUMBER.sub(f"{approx} ", text)

    def spoken(m: re.Match) -> str:
        sign, body = m.group(1), m.group(2)
        if not re.search(r"\D", body):
            return m.group(0)
        integer, decimals = split_number(body.replace("\u00a0", " ").replace("\u202f", " "), language)
        if integer is None or integer.startswith("0"):
            return m.group(0)
        value = float(f"{integer}.{decimals or 0}")
        if value < ROUND_FROM:
            return m.group(0)
        rounded, words = _rounded(value, language)
        if rounded == value:
            # Exact already ("2,000,000"): said in the short form, no "about".
            return f"{sign}{words}" if value >= 1_000_000 else m.group(0)
        before = text[: m.start()]
        prefix = "" if _APPROX_BEFORE.search(before) else f"{approx} "
        return f"{prefix}{sign}{words}"

    return _NUMBER.sub(spoken, text)


def _rounded(value: float, language: SpokenLanguage) -> tuple[float, str]:
    """``value`` rounded, and written for the voice in ``language``."""
    decimal = "." if language == SpokenLanguage.EN else ","
    if value >= 1_000_000:
        (million, millions), (billion, billions), singular_below_two = _SCALE_WORDS[language]
        scale, one, many = (1e9, billion, billions) if value >= 1e9 else (1e6, million, millions)
        mantissa = _significant(value / scale, 2)
        singular = mantissa < 2 if singular_below_two else mantissa == 1
        number = f"{mantissa:g}".replace(".", decimal)
        return mantissa * scale, f"{number} {one if singular else many}"
    rounded = _significant(value, 3)
    thousands = "," if language == SpokenLanguage.EN else "."
    return rounded, f"{int(rounded):,}".replace(",", thousands)


def _significant(value: float, digits: int) -> float:
    """``value`` to ``digits`` significant digits: 689.48 -> 690, 6.8947 -> 6.9."""
    if value == 0:
        return 0.0
    magnitude = math.floor(math.log10(abs(value)))
    return round(value, digits - 1 - magnitude)


def expand_ranges(text: str, language: SpokenLanguage) -> str:
    """"3-4 km" -> "3 bis 4 km". Its own step so the units can run after it:
    a number right after a hyphen is left alone there (ISO dates), which would
    leave the "km" of "3-4 km" unread."""
    return _RANGE.sub(lambda m: f"{m.group(1)} {_RANGE_WORD[language]} {m.group(2)}", text)


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
    if language == SpokenLanguage.DE:
        words = _german_parts(words)

    if decimals:
        digits = " ".join(_words(num2words(int(d), lang=lang)) for d in decimals)
        words = f"{words} {_DECIMAL_WORD[language]} {digits}"
    if sign:
        words = f"{_MINUS_WORD.get(language, 'minus')} {words}"
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
    if language == SpokenLanguage.NL:
        return f"{h} uur" if minutes == 0 else f"{h} uur {m}"
    if language == SpokenLanguage.EN:
        return f"{h} o'clock" if minutes == 0 else f"{h} {m if minutes >= 10 else 'oh ' + m}"
    return f"{h} {m}" if minutes else h


_GERMAN_PART = re.compile(
    r"(hundert|tausend)(?=ein|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn|elf|zwölf|zwanzig|dreißig)"
)


def _german_parts(spelled: str) -> str:
    """A German number as hyphenated parts: "zweihundert-achtundachtzig".
    In one word the German model lost its place in the repeated "acht":
    "zweihundertachtundachtundachtzig" in 4 of 60 runs, 0 of 60 with the
    hyphen; still read as one number (2026-10-10)."""
    return _GERMAN_PART.sub(r"\1-", spelled)


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
