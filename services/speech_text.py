"""What the chat shows, rewritten the way it is spoken, for every TTS provider.

Speech models read abbreviations, units and digits badly: "Cptn. Kirk" came
out "TPTN Kirk", "Main St." "Mainsaint", "10 km" "K10 Cam", and German "75 %"
"fünf sieben Prozent" (measured 2026-09-23 with Pocket TTS and Parakeet). The
chat keeps what the Wingman wrote; only the text handed to the voice changes.

Applied in this order, each step on what the previous one left:

1. the user's own rules (Settings > TTS), which always win,
2. the bundled lists the user switched on, one per game
   (templates/pronunciation/<id>.tsv), e.g. "aUEC" -> "A U E C",
3. abbreviations of the spoken language ("z.B.", "Lt.", "Blvd."),
4. units after a number ("10 km", "$20"),
5. numbers (services/spoken_numbers.py).

Rules may leave digits in what they write ("F7C" -> "F 7 C"): step 5 reads
them in the spoken language. Markup in angle or square brackets (Inworld's
<break>, audio markups like [laughs]) is never touched.

A full text normalizer (NVIDIA NeMo) would do more, but needs pynini, which
has no Windows or macOS wheels. This covers what Wingman's answers contain.
"""

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Optional

from api.enums import SpokenLanguage
from services.printr import Printr
from services.spoken_numbers import NUMBER_PATTERN, safe_spell_out_numbers, split_number

PRONUNCIATION_DIR = os.path.join("templates", "pronunciation")
BUILTIN_DIR = os.path.join(PRONUNCIATION_DIR, "builtin")

_app_root: Optional[str] = None


def configure(app_root_path: str) -> None:
    """Where the bundled tables live. Called once by Core at start."""
    global _app_root
    _app_root = app_root_path


@dataclass(frozen=True)
class Rule:
    written: str
    spoken: str
    languages: Optional[frozenset[str]] = None
    """Only for these spoken languages; None for all."""


# ───────────────────────── tables ───────────────────────── #


def _rows(path: str) -> list[list[str]]:
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            cells = [c.strip() for c in line.rstrip("\n").split("\t")]
            if len(cells) >= 2 and cells[0] and cells[1]:
                rows.append(cells)
    return rows


@lru_cache(maxsize=None)
def _abbreviations(app_root: str, language: str) -> tuple[Rule, ...]:
    path = os.path.join(app_root, BUILTIN_DIR, f"abbreviations.{language}.tsv")
    return tuple(Rule(r[0], r[1]) for r in _rows(path))


@lru_cache(maxsize=None)
def _units(app_root: str, language: str) -> tuple[tuple[str, str, str], ...]:
    path = os.path.join(app_root, BUILTIN_DIR, f"units.{language}.tsv")
    return tuple((r[0], r[1], r[2] if len(r) > 2 else r[1]) for r in _rows(path))


def list_presets(app_root: str) -> list[tuple[str, str, int]]:
    """(id, name, number of rules) of every bundled list."""
    folder = os.path.join(app_root, PRONUNCIATION_DIR)
    if not os.path.isdir(folder):
        return []
    presets = []
    for entry in sorted(os.listdir(folder)):
        if not entry.endswith(".tsv"):
            continue
        preset_id = entry[: -len(".tsv")]
        name = preset_id.replace("_", " ").title()
        with open(os.path.join(folder, entry), encoding="utf-8") as f:
            for line in f:
                if line.startswith("# Name:"):
                    name = line.split(":", 1)[1].strip()
                    break
        presets.append((preset_id, name, len(load_preset(app_root, preset_id))))
    return presets


@lru_cache(maxsize=None)
def load_preset(app_root: str, preset_id: str) -> tuple[Rule, ...]:
    if not re.fullmatch(r"[a-z0-9_]+", preset_id):
        return ()
    path = os.path.join(app_root, PRONUNCIATION_DIR, f"{preset_id}.tsv")
    rules = []
    for r in _rows(path):
        languages = frozenset(c.strip() for c in r[2].split(",")) if len(r) > 2 and r[2] else None
        rules.append(Rule(r[0], r[1], languages))
    return tuple(rules)


# ───────────────────────── rewriting ───────────────────────── #

# Markup the providers read themselves: <break time="1s"/>, [laughs].
_MARKUP = re.compile(r"(<[^<>]+>|\[[^\[\]]+\])")
_CURRENCY_FIRST = re.compile(r"(?<![\w.,])([$€£])\s?(\d+(?:[.,]\d+)*)")


@lru_cache(maxsize=64)
def _rule_pattern(writtens: tuple[str, ...]) -> re.Pattern:
    # Longest first, so "CRU-L1" wins over a shorter rule inside it. Not in
    # the middle of a word: "QT" must not touch "QTY".
    alternation = "|".join(re.escape(w) for w in sorted(writtens, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternation})(?!\w)")


def _apply_rules(text: str, rules: Iterable[Rule]) -> str:
    table = {}
    for rule in rules:
        table.setdefault(rule.written, rule.spoken)  # the first one wins
    if not table:
        return text

    def spoken(m: re.Match) -> str:
        said = table[m.group(0)]
        # "Sunshine Blvd." at the end: the dot also ended the sentence.
        rest = text[m.end() :]
        if m.group(0).endswith(".") and (not rest.strip() or rest.startswith("\n")):
            said += "."
        return said

    return _rule_pattern(tuple(table)).sub(spoken, text)


@lru_cache(maxsize=16)
def _unit_pattern(units: tuple[tuple[str, str, str], ...]) -> re.Pattern:
    alternation = "|".join(
        re.escape(u[0]) for u in sorted(units, key=lambda u: len(u[0]), reverse=True)
    )
    return re.compile(rf"{NUMBER_PATTERN}\s?({alternation})(?!\w)")


_CURRENCIES = frozenset("$€£")


def _apply_units(
    text: str, units: tuple[tuple[str, str, str], ...], language: SpokenLanguage
) -> str:
    if not units:
        return text
    forms = {u[0]: (u[1], u[2]) for u in units}

    def spoken(m: re.Match) -> str:
        sign, number, unit = m.group(1), m.group(2), m.group(3)
        one, many = forms[unit]
        if unit in _CURRENCIES:
            # "15,50 €" is said "fünfzehn Euro fünfzig", not "Komma fünf null".
            whole, cents = split_number(number, language)
            if whole is not None and cents is not None and len(cents) == 2:
                # The whole part as written, separators included: bare
                # "1234" would be read as a year.
                written_whole = number[: len(number) - len(cents) - 1]
                return f"{sign}{written_whole} {many} {int(cents)}"
        if not sign and number == "1":
            return one
        return f"{sign}{number} {many}"

    return _unit_pattern(units).sub(spoken, text)


def _speak_segment(segment: str, language: SpokenLanguage, rules: list[Rule]) -> str:
    code = language.value
    segment = _apply_rules(segment, rules)
    if _app_root:
        segment = _apply_rules(segment, _abbreviations(_app_root, code))
        segment = _CURRENCY_FIRST.sub(lambda m: f"{m.group(2)} {m.group(1)}", segment)
        segment = _apply_units(segment, _units(_app_root, code), language)
    return safe_spell_out_numbers(segment, language)


def active_rules(language: SpokenLanguage, own: Iterable, presets: Iterable[str]) -> list[Rule]:
    """The user's rules, then those of the lists they switched on that fit
    the spoken language. A user rule for the same text replaces the list's."""
    rules = [Rule(r.written.strip(), r.spoken.strip()) for r in own if r.written.strip()]
    if _app_root:
        for preset_id in presets:
            for rule in load_preset(_app_root, preset_id):
                if rule.languages is None or language.value in rule.languages:
                    rules.append(rule)
    return rules


def prepare_for_speech(
    text: str, language: SpokenLanguage, own_rules: Iterable = (), presets: Iterable[str] = ()
) -> str:
    """``text`` as it should be spoken. Never raises: on any error the text
    is returned as it came, an unreadable number beats a lost answer."""
    try:
        rules = active_rules(language, own_rules, presets)
        parts = _MARKUP.split(text)
        return "".join(
            part if i % 2 else _speak_segment(part, language, rules)
            for i, part in enumerate(parts)
        )
    except Exception as e:
        Printr().print(
            f"Could not prepare text for speech, speaking it as written: {e}",
            server_only=True,
        )
        return text
