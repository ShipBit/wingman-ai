"""Finding a wingman's name in what the user said.

The speech model misspells names: "Eva" for Ava, "Computa" for Computer. So
a name is matched by sound, with a letter or two of slack, and only near the
start of the sentence, where people put a name.
"""

import re
from typing import Optional

from rapidfuzz.distance import Levenshtein

from services.audio.protected_words import PROTECTED_WORDS

# How much of a sentence may carry the wingman's name.
NAME_WINDOW_WORDS = 8


def words_of(text: str) -> list[str]:
    """The words of the text, lowercased, without punctuation."""
    return re.findall(r"[\w'-]+", text.lower())


def name_edit_allowance(name: str) -> int:
    """How many letters a heard name may differ by and still count.

    One for short names ("Ava" heard as "Eva"), two for the usual length
    ("Computer" heard as "Computa"), three for long ones. "Complete" is three
    edits from "Computer" and is rejected at that length.
    """
    length = len(name)
    if length <= 5:
        return 1
    if length <= 9:
        return 2
    return 3


def find_name(words: list[str], name: str) -> Optional[tuple[int, int, int]]:
    """Where the name sits in the first words: (start, end, distance), with
    end exclusive, or None. The closest sounding spot wins."""
    name = " ".join(name.lower().split())
    name_words = name.split()
    window = words[:NAME_WINDOW_WORDS]
    if not name_words or len(name_words) > len(window):
        return None
    allowance = name_edit_allowance(name)
    best: Optional[tuple[int, int, int]] = None
    for i in range(len(window) - len(name_words) + 1):
        candidate = " ".join(window[i : i + len(name_words)])
        distance = Levenshtein.distance(candidate, name, score_cutoff=allowance)
        if distance > allowance:
            continue
        if distance and candidate in PROTECTED_WORDS:
            # A word people say all the time is not a misheard name: "at" is
            # one edit from the "ATC" wingman, and "Take a look at the map"
            # must not be routed to it. Only an exact hit counts here.
            continue
        if best is None or distance < best[2]:
            best = (i, i + len(name_words), distance)
    return best


def without_name(words: list[str], name: str) -> list[str]:
    """The words after the name, or all of them when the name is not there.
    What is said before the name ("hey") is dropped with it."""
    found = find_name(words, name)
    if found is None:
        return words
    return words[found[1] :]
