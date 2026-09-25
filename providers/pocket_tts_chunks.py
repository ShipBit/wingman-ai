"""Text for Pocket TTS in pieces the model can speak cleanly.

The model is trained on short prompts; pocket-tts splits longer text at
sentence ends and, for a sentence over the limit, at commas. A long sentence
without commas stays one piece: a German answer with its numbers spelled out
("zwölftausendfünfhundert ...") reached 69 and 74 tokens in one sentence,
measured 2026-09-23, and long pieces are a known source of skipped words and
artifacts. What is still too long after pocket-tts's own split is cut here
into as few pieces as fit, in front of a conjunction or after a comma where
one is near.
"""

import math
import re
from typing import Callable, Iterable, Iterator

import torch

from api.enums import SpokenLanguage

MAX_TOKENS = 65
"""Longest piece. pocket-tts uses 50; the German model speaks up to about 65
tokens as cleanly (word error rate 2.3% at 46 and 59 tokens, 5.0% at 75) and
then starts skipping whole clauses (13% at 86, 34% at 117; measured
2026-09-24 with Juergen, Tabea and Rolf). Every piece starts afresh, so a
join inside a sentence can be heard; the longer limit keeps most sentences
in one piece."""

EXTRA_FRAMES_AFTER_EOS = 2
"""Frames (80 ms each) the model keeps generating after it signals the end
of a piece, on top of pocket-tts' own guess. With the guess alone, 4 of 40
German pieces stopped while the last syllable was still sounding, heard as
a word cut off at the join; with 2 more frames, 1 of 40, and more frames did
not help further (measured 2026-09-24 with Juergen, Tabea, Rolf, Eponine)."""


CLAUSE_MODELS = frozenset({"german"})
"""Models that get every clause as a piece of its own. The German 6-layer
model of pocket-tts 3.3 takes the pause after a comma for the end: whole
sentences with a comma came out complete 12 of 36 times, the same
sentences cut at their commas 35 of 36 (6 voices, 3 sentences, 2 seeds,
measured 2026-09-25). german_24l and the other languages finish them."""

MIN_CLAUSE_WORDS = 3
"""A clause shorter than this ("Ja,") stays with the next one."""


def frames_after_eos(piece: str) -> int:
    """pocket-tts' guess for ``piece`` (3 frames for up to four words, else
    1, plus 2; see prepare_text_prompt and generate_audio_stream), plus
    EXTRA_FRAMES_AFTER_EOS."""
    guess = 3 if len(piece.split()) <= 4 else 1
    return guess + 2 + EXTRA_FRAMES_AFTER_EOS


FADE_SECONDS = 0.01
"""Fade at the start and end of every piece. Each piece starts from a fresh
model state, and the German model with a voice recorded in English often
starts at full loudness on the first sample: 8 of 12 starts with Eponine, 0
with Juergen (measured 2026-09-23). Straight after the silence of the piece
before, that jump is a click across the whole spectrum, heard as a cut in
front of the word. 10 ms is too short to hear as a fade."""

# A clause usually starts here, so the voice can pause naturally in front.
_CONJUNCTIONS = {
    SpokenLanguage.DE: {"und", "dass", "oder", "aber", "weil", "wenn", "damit", "sodass", "während", "sowie", "denn"},
    SpokenLanguage.EN: {"and", "that", "or", "but", "because", "when", "while", "so", "which"},
    SpokenLanguage.FR: {"et", "que", "ou", "mais", "parce", "quand", "pendant", "donc", "qui"},
    SpokenLanguage.ES: {"y", "que", "o", "pero", "porque", "cuando", "mientras", "donde"},
    SpokenLanguage.IT: {"e", "che", "o", "ma", "perché", "quando", "mentre", "dove"},
    SpokenLanguage.PT: {"e", "que", "ou", "mas", "porque", "quando", "enquanto", "onde"},
    SpokenLanguage.NL: {"en", "dat", "of", "maar", "omdat", "als", "wanneer", "terwijl", "waar", "want"},
}


def split_long(
    piece: str, count_tokens: Callable[[str], int], language: SpokenLanguage
) -> list[str]:
    """``piece`` as it is when it fits, else in as few pieces as fit, each
    about as long as the others. A cut goes in front of a conjunction or
    after a comma when one is near, else between words.

    A cut in the middle of a sentence ends with a comma: pocket-tts appends a
    period to a piece ending in a letter, and the voice would drop as if the
    sentence were over.
    """
    total = count_tokens(piece)
    if total <= MAX_TOKENS:
        return [piece]
    words = piece.split(" ")
    if len(words) < 2:
        return [piece]

    target = len(words) / math.ceil(total / MAX_TOKENS)
    conjunctions = _CONJUNCTIONS.get(language, set())

    def natural(i: int) -> bool:
        return words[i].lower().strip(",.") in conjunctions or words[i - 1].endswith(",")

    fitting = [i for i in range(1, len(words)) if count_tokens(" ".join(words[:i])) <= MAX_TOKENS]
    # A natural cut up to a third of a piece away beats an exact one.
    cut = min(fitting or [1], key=lambda i: abs(i - target) - (target / 3 if natural(i) else 0))

    first = " ".join(words[:cut]).rstrip()
    if first and first[-1].isalnum():
        first += ","
    rest = " ".join(words[cut:])
    return [first] + split_long(rest, count_tokens, language)


def pieces_for_speech(
    text: str,
    split_sentences: Callable[[str], list[str]],
    count_tokens: Callable[[str], int],
    language: SpokenLanguage,
    by_clause: bool = False,
) -> list[str]:
    """pocket-tts's own split, then every piece still over the limit cut at
    word boundaries. With ``by_clause`` every clause is a piece
    (CLAUSE_MODELS)."""
    pieces: list[str] = []
    for piece in _rejoin_clauses(split_sentences(text)):
        for part in split_clauses(piece) if by_clause else [piece]:
            pieces.extend(split_long(part, count_tokens, language))
    return pieces


def split_clauses(sentence: str) -> list[str]:
    """``sentence`` cut after every comma, a clause under MIN_CLAUSE_WORDS
    words kept with the next. Numbers like "2,5" have no space after the
    comma and stay whole."""
    parts = [p for p in re.split(r"(?<=,)\s+", sentence.strip()) if p]
    out: list[str] = []
    carry = ""
    for part in parts:
        part = f"{carry} {part}".strip() if carry else part
        if len(part.split()) < MIN_CLAUSE_WORDS and part is not parts[-1]:
            carry = part
            continue
        carry = ""
        out.append(part)
    if carry:
        out.append(carry)
    if len(out) > 1 and len(out[-1].split()) < MIN_CLAUSE_WORDS:
        last = out.pop()
        out[-1] = f"{out[-1]} {last}"
    return out


def _rejoin_clauses(pieces: list[str]) -> list[str]:
    """pocket-tts cuts a sentence over its limit at every comma, which can
    leave four pieces where three would fit. Joins inside a sentence are the
    ones that can be heard, so a sentence is put back together here and
    split_long cuts it into as few pieces as fit."""
    out: list[str] = []
    for piece in pieces:
        if out and not out[-1].rstrip().endswith((".", "!", "?", "…")):
            out[-1] = f"{out[-1].rstrip()} {piece.lstrip()}"
        else:
            out.append(piece)
    return out


def faded_edges(chunks: Iterable[torch.Tensor], sample_rate: int) -> Iterator[torch.Tensor]:
    """The audio chunks of one piece, faded in at the start and out at the
    end. Holds back one chunk (80 ms) to know which one is the last."""
    fade = max(1, int(sample_rate * FADE_SECONDS))
    ramp = 0.5 - 0.5 * torch.cos(torch.linspace(0, torch.pi, fade))
    held = None
    first = True
    for chunk in chunks:
        if first:
            chunk = chunk.clone()
            n = min(fade, chunk.shape[-1])
            chunk[..., :n] *= ramp[:n].to(chunk.dtype)
            first = False
        if held is not None:
            yield held
        held = chunk
    if held is not None:
        held = held.clone()
        n = min(fade, held.shape[-1])
        held[..., held.shape[-1] - n :] *= ramp[:n].flip(0).to(held.dtype)
        yield held
