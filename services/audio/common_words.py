"""The most frequent words of a language, which the transcript correction
leaves alone.

The speech model writes the words it knows. When it writes a real word, it
decided on that word: "radar", "double", "degree". The fuzzy correction
used to treat every word that lies a letter or two from a name as misheard,
and turned those into "Yadar", "Dopple", "Dupree". Measured against the Star
Citizen list, 134 of 13,513 everyday English words were rewritten; with these
lists none are. A name the model did not know comes out as a spelling no
language has ("Hurstin", "lorvil"), and that is still corrected.

The lists are in templates/common_words, built by
scripts/build_common_words.py from wordfreq (CC BY-SA 4.0, see the
ATTRIBUTION.md next to them).
"""

from functools import lru_cache
from os import path

from api.enums import SpokenLanguage

COMMON_WORDS_DIR = path.join("templates", "common_words")


@lru_cache(maxsize=16)
def _load(app_root_path: str, language: str) -> frozenset[str]:
    file = path.join(app_root_path, COMMON_WORDS_DIR, f"{language}.txt")
    if not path.exists(file):
        return frozenset()
    with open(file, encoding="utf-8") as f:
        return frozenset(line.strip().lower() for line in f if line.strip())


@lru_cache(maxsize=8)
def common_words(app_root_path: str, spoken_language: SpokenLanguage) -> frozenset[str]:
    """The everyday words of the spoken language, and English: players say
    "shields" and "radar" in every language. OTHER has no list of its own."""
    languages = {"en"}
    if spoken_language != SpokenLanguage.OTHER:
        languages.add(spoken_language.value)
    words: frozenset[str] = frozenset()
    for language in sorted(languages):
        words |= _load(app_root_path, language)
    return words
