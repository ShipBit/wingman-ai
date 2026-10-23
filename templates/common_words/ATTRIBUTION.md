# Common words

The files in this folder list the most frequent words of each language Wingman
speaks. The transcript correction never rewrites one of them into a name from
a vocabulary list.

They are taken from **wordfreq** by Robyn Speer, version 3.1.1
(https://github.com/rspeer/wordfreq), and are licensed under the
**Creative Commons Attribution-ShareAlike 4.0** license
(https://creativecommons.org/licenses/by-sa/4.0/). wordfreq's data is built
from Wikipedia, subtitles (OpenSubtitles, SUBTLEX), news, books (Google Books
Ngrams), web text (OSCAR) and social media; see its README for the full list
of sources and their credits.

Changes: only the 30,000 most frequent entries per language were kept, and of
those only words made of letters. `scripts/build_common_words.py` produces the
files.
