"""Special words: the names a speech model cannot know.

Star Citizen players say "Hurston", "Crusader", "Port Olisar" all day, and
the model writes "Houston", "Crusade", "Port Olive". No provider we ship lets
us teach it those words at decoding time (FasterWhisper does, a little), so
the transcript is corrected afterwards: every word, and every group of two or
three words, that lies within a few letters of a vocabulary entry becomes that
entry.

The allowance grows with the length of the entry and the first letter has to
match unless the word is one edit away. That keeps "complete" from turning
into "Computer" while "Computa" still does.

Fuzzy matching corrects spellings, not hearing: a word the model dropped or
replaced with something unrelated stays wrong. For those there is the second
kind of entry, `heard=correct`: an exact replacement, "Jump down=Jumptown".
That is what a wingman writes when the user says "from now on spell it X".
"""

import re
from typing import Iterable

from rapidfuzz.distance import Levenshtein

# Entries shorter than this are not corrected: too many ordinary words are
# one letter away from "Ava".
MIN_WORD_LENGTH = 3
MAX_PHRASE_WORDS = 3

_TOKEN = re.compile(r"[\w'-]+|[^\w'-]+", re.UNICODE)
_WORD = re.compile(r"^[\w'-]+$", re.UNICODE)
_MAPPING = re.compile(r"^\s*(.+?)\s*(?:=|->|→)\s*(.+?)\s*$")


def parse_entry(entry: str) -> tuple[str, str | None]:
    """(correct spelling, what was heard or None) for one list entry."""
    entry = " ".join(str(entry).split())
    m = _MAPPING.match(entry)
    if m:
        return m.group(2), m.group(1)
    return entry, None


def format_entry(correct: str, heard: str | None = None) -> str:
    correct = " ".join(str(correct).split())
    heard = " ".join(str(heard).split()) if heard else ""
    return f"{heard}={correct}" if heard and heard.lower() != correct.lower() else correct


def edit_allowance(entry: str) -> int:
    """How many letters a heard word may differ by and still count: one for
    short entries, two for the usual length, three for long ones."""
    length = len(entry)
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
            if len(correct) >= MIN_WORD_LENGTH and _normalise(correct) not in seen:
                seen[_normalise(correct)] = correct
            if heard and len(heard.split()) <= MAX_PHRASE_WORDS:
                self._mappings[_normalise(heard)] = correct
        self.entries = sorted(seen.values(), key=lambda e: -len(e.split()))
        self._by_words: dict[int, list[tuple[str, str]]] = {}
        for entry in self.entries:
            n = len(entry.split())
            if n <= MAX_PHRASE_WORDS:
                self._by_words.setdefault(n, []).append((_normalise(entry), entry))

    def __bool__(self) -> bool:
        return bool(self.entries) or bool(self._mappings)

    def match(self, phrase: str) -> str | None:
        """The entry this phrase is a misspelling of, or None."""
        key = _normalise(phrase)
        mapped = self._mappings.get(key)
        if mapped is not None:
            return mapped
        n = len(key.split())
        best: tuple[int, str | None] = (10**6, None)
        for normalised, entry in self._by_words.get(n, ()):
            if key == normalised:
                return entry
            allowance = edit_allowance(normalised)
            distance = Levenshtein.distance(key, normalised, score_cutoff=allowance)
            if distance > allowance:
                continue
            if distance > 1 and key[0] != normalised[0]:
                continue
            if distance < best[0]:
                best = (distance, entry)
        return best[1]

    def correct(self, text: str) -> str:
        """The text with every recognisable misspelling replaced."""
        if not self or not text:
            return text
        tokens = _TOKEN.findall(text)
        word_positions = [i for i, t in enumerate(tokens) if _WORD.match(t)]
        out = list(tokens)
        i = 0
        while i < len(word_positions):
            replaced = False
            for n in range(min(MAX_PHRASE_WORDS, len(word_positions) - i), 0, -1):
                if n not in self._by_words and not self._mappings:
                    continue
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


# --- finding candidates in a configuration ---

# Where a capital letter says nothing about the word: sentence starts, line
# starts (with or without a bullet, number, markdown emphasis or quote), and
# the word in front of a colon, which is a heading.
_SENTENCE_START = re.compile(
    r"(?:^|[.!?\n]|:\s)[\s\-*#>\d.)\"“'(_]*([A-ZÄÖÜ][\w'-]*)|([A-ZÄÖÜ][\w'-]*)\s*:",
    re.MULTILINE,
)
_CAPITALISED = re.compile(r"\b([A-ZÄÖÜ][a-zäöüß'-]{2,}(?:\s+[A-ZÄÖÜ][a-zäöüß'-]{2,}){0,2})\b")

# Words that start sentences in prompts all the time and are not names.
_COMMON = {
    "the", "you", "your", "and", "always", "never", "when", "this", "that", "use", "only",
    "for", "with", "user", "wingman", "wingmen", "assistant", "example", "examples", "note",
    "important", "respond", "answer", "keep", "avoid", "der", "die", "das", "und", "du",
    "dein", "deine", "wenn", "immer", "nie", "nur", "mit", "für", "bitte",
}


def detect_from_text(text: str, titles: bool = False) -> list[str]:
    """Capitalised words that do not start a sentence: proper nouns, mostly.
    With `titles` the sentence-start rule is off: a spoken trigger like
    "Flight Ready" is a name as a whole."""
    if not text:
        return []
    starts = set() if titles else {m.group(1) or m.group(2) for m in _SENTENCE_START.finditer(text)}
    found: list[str] = []
    for m in _CAPITALISED.finditer(text):
        phrase = " ".join(m.group(1).split())
        words = phrase.split()
        # A phrase that starts a sentence loses its first word; what is left
        # may still be a name ("Reference Star Citizen" -> "Star Citizen").
        while words and words[0] in starts:
            words = words[1:]
        if not words:
            continue
        if len(words) == 1 and words[0].lower() in _COMMON:
            continue
        found.append(" ".join(words))
    return found


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


def detect_from_config(config) -> list[str]:
    """Special words a configuration suggests for the list: proper nouns from
    backstories and prompts. Names and spoken triggers are not offered, they
    count at runtime anyway (`spoken_names`)."""
    words: list[str] = []
    for wingman in (config.wingmen or {}).values():
        if wingman.disabled:
            continue
        prompts = wingman.prompts
        if prompts:
            words.extend(detect_from_text(prompts.backstory or ""))
            words.extend(detect_from_text(prompts.system_prompt or ""))
    unique: dict[str, str] = {}
    for w in words:
        w = " ".join(str(w).split())
        if len(w) >= MIN_WORD_LENGTH and w.lower() not in unique:
            unique[w.lower()] = w
    return list(unique.values())
