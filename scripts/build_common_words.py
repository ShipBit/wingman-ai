#!/usr/bin/env python3
"""Write templates/common_words/<language>.txt: the most frequent words of
every spoken language, which the transcript correction leaves alone.

    pip install wordfreq==3.1.1
    python scripts/build_common_words.py

Only needed to refresh the lists; Core reads the text files and does not
depend on wordfreq. The data is from wordfreq by Robyn Speer, CC BY-SA 4.0
(see templates/common_words/ATTRIBUTION.md).
"""

import sys
from os import makedirs, path

from wordfreq import top_n_list

REPO_ROOT = path.dirname(path.dirname(path.abspath(__file__)))
OUT_DIR = path.join(REPO_ROOT, "templates", "common_words")
# Every SpokenLanguage except OTHER.
LANGUAGES = ("en", "de", "fr", "es", "it", "pt", "nl")
WORDS_PER_LANGUAGE = 30000


def main() -> int:
    makedirs(OUT_DIR, exist_ok=True)
    for language in LANGUAGES:
        words = [w for w in top_n_list(language, WORDS_PER_LANGUAGE) if w.isalpha()]
        with open(path.join(OUT_DIR, f"{language}.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(words) + "\n")
        print(f"{language}: {len(words)} words")
    return 0


if __name__ == "__main__":
    sys.exit(main())
