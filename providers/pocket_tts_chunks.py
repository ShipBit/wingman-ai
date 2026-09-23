"""Text for Pocket TTS in pieces the model can speak cleanly.

The model is trained on short prompts; pocket-tts splits longer text at
sentence ends and, for a sentence over 50 tokens, at commas. A long sentence
without commas stays one piece: a German answer with its numbers spelled out
("zwölftausendfünfhundert ...") reached 69 and 74 tokens in one sentence,
measured 2026-09-23, and long pieces are a known source of skipped words and
artifacts. What is still too long after pocket-tts's own split is cut here, in
front of a conjunction nearest the middle, else at the word nearest the
middle, until every piece fits.
"""

from typing import Callable, Iterable, Iterator

import torch

from api.enums import SpokenLanguage

MAX_TOKENS = 50
"""pocket-tts's own limit per piece (MAX_TOKEN_PER_CHUNK)."""

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
}


def split_long(
    piece: str, count_tokens: Callable[[str], int], language: SpokenLanguage
) -> list[str]:
    """``piece`` as it is when it fits, else cut in two and each half again.

    A cut in the middle of a sentence ends with a comma: pocket-tts appends a
    period to a piece ending in a letter, and the voice would drop as if the
    sentence were over.
    """
    if count_tokens(piece) <= MAX_TOKENS:
        return [piece]
    words = piece.split(" ")
    if len(words) < 2:
        return [piece]

    middle = len(words) / 2
    conjunctions = _CONJUNCTIONS.get(language, set())
    candidates = [i for i in range(1, len(words)) if words[i].lower().strip(",.") in conjunctions]
    if not candidates:
        candidates = list(range(1, len(words)))
    cut = min(candidates, key=lambda i: abs(i - middle))

    first = " ".join(words[:cut]).rstrip()
    if first and first[-1].isalnum():
        first += ","
    second = " ".join(words[cut:])
    return split_long(first, count_tokens, language) + split_long(second, count_tokens, language)


def pieces_for_speech(
    text: str,
    split_sentences: Callable[[str], list[str]],
    count_tokens: Callable[[str], int],
    language: SpokenLanguage,
) -> list[str]:
    """pocket-tts's own split, then every piece still over the limit cut at
    word boundaries."""
    pieces: list[str] = []
    for piece in split_sentences(text):
        pieces.extend(split_long(piece, count_tokens, language))
    return pieces


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
