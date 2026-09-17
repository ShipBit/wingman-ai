"""Special words: the names a speech model cannot know.

Star Citizen players say "Hurston", "Crusader", "Port Olisar" all day, and
the model writes "Houston", "Crusade", "Port Olive". No provider we ship lets
us teach it those words at decoding time, so the transcript is corrected
afterwards: every word, and every group of two or
three words, that lies within a few letters of a vocabulary entry becomes that
entry.

The allowance grows with the length of the entry and the first letter has to
match unless the word is one edit away. That keeps "complete" from turning
into "Computer" while "Computa" still does. Entries of up to four letters are
matched exactly only: "dir" must not become "Adir".

Fuzzy matching corrects spellings, not hearing: a word the model dropped or
replaced with something unrelated stays wrong. For those there is the second
kind of entry, `heard=correct`: an exact replacement, "Jump down=Jumptown".
That is what a wingman writes when the user says "from now on spell it X".
A third form, `"Crusader"` in quotes, is exact-only: the name is also an
ordinary word, so it fixes the casing when heard as such and never pulls
"crusade" in.
"""

import os
import re
from os import path
from typing import Iterable

from rapidfuzz.distance import Levenshtein

from services.audio.protected_words import PROTECTED_WORDS

# Entries shorter than this are not corrected: too many ordinary words are
# one letter away from "Ava".
MIN_WORD_LENGTH = 3
# Entries shorter than this are matched exactly, never by edit distance:
# one edit away from "Adir" is "dir", from "Dawu" is "dazu", and a short
# name misheard is rarer than a short everyday word said.
MIN_FUZZY_LENGTH = 5
MAX_PHRASE_WORDS = 3

_TOKEN = re.compile(r"[\w'-]+|[^\w'-]+", re.UNICODE)
_WORD = re.compile(r"^[\w'-]+$", re.UNICODE)
_MAPPING = re.compile(r"^\s*(.+?)\s*(?:=|->|→)\s*(.+?)\s*$")
# "h u r s t o n", "H-U-R-S-T-O-N", "a. t. c.": a word spelled letter by letter.
_SPELLED = re.compile(r"(?<![\w'-])(?:[A-Za-zÄÖÜäöü][ .\-]+){1,}[A-Za-zÄÖÜäöü]\.?(?![\w'-])")


def join_spelled(text: str) -> str:
    """Collapse letters spelled one by one into the word they make. Two
    single letters in a row already count, since "a t c" is how acronyms
    come out of a speech model."""
    def _join(m: re.Match) -> str:
        return "".join(re.findall(r"[A-Za-zÄÖÜäöü]", m.group(0)))
    return _SPELLED.sub(_join, text)


def parse_entry(entry: str) -> tuple[str, str | None]:
    """(correct spelling, what was heard or None) for one list entry. An
    exact-only entry `"Word"` comes back as ("Word", "Word")."""
    entry = " ".join(str(entry).split())
    if len(entry) >= 3 and entry[0] in "\"“" and entry[-1] in "\"”":
        word = entry[1:-1].strip()
        return word, word
    m = _MAPPING.match(entry)
    if m:
        return m.group(2), m.group(1)
    return entry, None


def format_entry(correct: str, heard: str | None = None) -> str:
    correct = " ".join(str(correct).split())
    heard = " ".join(str(heard).split()) if heard else ""
    return f"{heard}={correct}" if heard and heard.lower() != correct.lower() else correct


def edit_allowance(length: int) -> int:
    """How many letters a heard word may differ by and still count: one for
    short words, two for the usual length, three for long ones."""
    if length <= 5:
        return 1
    if length <= 9:
        return 2
    return 3


def _normalise(word: str) -> str:
    return word.lower().replace("’", "'")


class Vocabulary:
    def __init__(self, entries: Iterable[str]):
        # Longer phrases first so "Port Olisar" wins over "Port".
        seen: dict[str, str] = {}
        # heard (normalised) -> correct, for the exact replacements
        self._mappings: dict[str, str] = {}
        for raw in entries:
            correct, heard = parse_entry(raw)
            exact_only = heard is not None and _normalise(heard) == _normalise(correct)
            if not exact_only and len(correct) >= MIN_WORD_LENGTH and _normalise(correct) not in seen:
                seen[_normalise(correct)] = correct
            if heard and len(heard.split()) <= MAX_PHRASE_WORDS:
                self._mappings[_normalise(heard)] = correct
        self.entries = sorted(seen.values(), key=lambda e: -len(e.split()))
        # (entry without spaces, word count, entry) for the space-insensitive comparison
        self._joined: list[tuple[str, int, str]] = [
            (_normalise(e).replace(" ", ""), len(e.split()), e)
            for e in self.entries
            if len(e.split()) <= MAX_PHRASE_WORDS
        ]

    def __bool__(self) -> bool:
        return bool(self.entries) or bool(self._mappings)

    def match(self, phrase: str) -> str | None:
        """The entry this phrase is a misspelling of, or None.

        Compared without spaces: speech models split "Microtech" into "micro
        tech" and glue "Port Olisar" into "portolisar", so the word count of
        the transcript says nothing. The allowance follows the shorter side,
        so a four-letter word cannot reach a six-letter entry on two edits.
        """
        key = _normalise(phrase)
        mapped = self._mappings.get(key)
        if mapped is not None:
            return mapped
        words = key.split()
        if all(w in PROTECTED_WORDS for w in words):
            # Ordinary words of one of our languages. Only a pair may turn
            # them into a name; the fuzzy rule stays away.
            return None
        joined = key.replace(" ", "")
        best: tuple[int, str | None] = (10**6, None)
        for normalised, entry_words, entry in self._joined:
            if joined == normalised:
                return entry
            if len(normalised) < MIN_FUZZY_LENGTH:
                continue
            # A different word count is a split or a merge ("micro tech"):
            # allowed only when the letters themselves are all but the same,
            # otherwise a three-word window swallows a small word next to a
            # name ("new babbage on" -> "New Babbage").
            allowance = edit_allowance(min(len(joined), len(normalised)))
            if len(words) != entry_words:
                allowance = 1
            distance = Levenshtein.distance(joined, normalised, score_cutoff=allowance)
            if distance > allowance:
                continue
            if distance > 1 and joined[0] != normalised[0]:
                continue
            if distance < best[0]:
                best = (distance, entry)
        return best[1]

    def _join_spelled_names(self, text: str) -> str:
        """Letters spelled one by one become a word only when that word is
        in the list; "a b" in "plan a b" stays as it is."""
        def _maybe(m: re.Match) -> str:
            joined = "".join(re.findall(r"[A-Za-zÄÖÜäöü]", m.group(0)))
            return self.match(joined) or m.group(0)
        return _SPELLED.sub(_maybe, text)

    def correct(self, text: str) -> str:
        """The text with every recognisable misspelling replaced."""
        if not self or not text:
            return text
        text = self._join_spelled_names(text)
        tokens = _TOKEN.findall(text)
        word_positions = [i for i, t in enumerate(tokens) if _WORD.match(t)]
        out = list(tokens)
        i = 0
        while i < len(word_positions):
            replaced = False
            for n in range(min(MAX_PHRASE_WORDS, len(word_positions) - i), 0, -1):
                first, last = word_positions[i], word_positions[i + n - 1]
                phrase = "".join(tokens[first : last + 1])
                if n > 1 and not re.fullmatch(r"[\w'-]+(?: [\w'-]+)+", phrase):
                    continue  # words joined by more than a single space are not a phrase
                candidate = " ".join(phrase.split())
                if len(candidate.replace(" ", "")) < MIN_WORD_LENGTH:
                    continue
                entry = self.match(candidate)
                if entry is None:
                    continue
                # Keep the entry's own spelling and casing; drop the tokens it replaces.
                out[first] = entry
                for k in range(first + 1, last + 1):
                    out[k] = ""
                i += n
                replaced = True
                break
            if not replaced:
                i += 1
        return "".join(out)


# --- bundled presets ---

PRESET_DIR = path.join("templates", "vocabulary")


def list_presets(app_root_path: str) -> list[tuple[str, str, int]]:
    """(id, display name, entries) for every bundled word list."""
    folder = path.join(app_root_path, PRESET_DIR)
    if not path.isdir(folder):
        return []
    presets = []
    for file in sorted(os.listdir(folder)):
        if not file.endswith(".txt"):
            continue
        preset_id = file[:-4]
        words = load_preset(app_root_path, preset_id)
        presets.append((preset_id, preset_id.replace("_", " ").title(), len(words)))
    return presets


def apply_override(words: list[str], override) -> list[str]:
    """The bundled list with the user's edits: their removals taken out,
    their additions appended. `override` has `added` and `removed`."""
    if override is None:
        return list(words)
    removed = {w.lower() for w in (override.removed or [])}
    kept = [w for w in words if w.lower() not in removed]
    known = {w.lower() for w in kept}
    for w in override.added or []:
        if w.lower() not in known:
            kept.append(w)
            known.add(w.lower())
    return kept


def diff_override(bundled: list[str], wanted: list[str]) -> tuple[list[str], list[str]]:
    """(added, removed) that turn the bundled list into the wanted one."""
    have = {w.lower(): w for w in bundled}
    want = {w.lower(): w for w in wanted}
    added = [w for k, w in want.items() if k not in have]
    removed = [w for k, w in have.items() if k not in want]
    return added, removed


def load_preset(app_root_path: str, preset_id: str) -> list[str]:
    if not re.fullmatch(r"[a-z0-9_]+", preset_id):
        return []
    file = path.join(app_root_path, PRESET_DIR, f"{preset_id}.txt")
    if not path.isfile(file):
        return []
    with open(file, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


# --- names from the configuration ---


def spoken_names(config) -> list[str]:
    """What the active configuration says people will say: every wingman's
    name and every spoken command trigger. Applied at runtime, not stored."""
    words: list[str] = []
    for wingman in (config.wingmen or {}).values():
        if wingman.disabled:
            continue
        words.append(wingman.name)
        for command in wingman.commands or []:
            words.extend(command.instant_activation or [])
    return words
