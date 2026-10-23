"""Text for Pocket TTS in pieces the model can speak cleanly.

The model is trained on short prompts; pocket-tts splits longer text at
sentence ends and, for a sentence over the limit, at commas. A long sentence
without commas stays one piece: a German answer with its numbers spelled out
("zwölftausendfünfhundert ...") reached 69 and 74 tokens in one sentence,
measured 2026-09-23, and long pieces are a known source of skipped words and
artifacts. What is still too long after pocket-tts's own split is cut here
into as few pieces as fit, in front of a conjunction or after a comma where
one is near, and never inside a spoken number.
"""

import math
import re
from typing import Callable, Iterable, Iterator

import torch

from api.enums import SpokenLanguage
from services.spoken_numbers import number_words

MAX_TOKENS = 65
"""Longest piece. pocket-tts uses 50; the German model speaks up to about 65
tokens as cleanly (word error rate 2.3% at 46 and 59 tokens, 5.0% at 75) and
then starts skipping whole clauses (13% at 86, 34% at 117; measured
2026-09-24 with Juergen, Tabea and Rolf). Every piece starts afresh, so a
join inside a sentence can be heard; the longer limit keeps most sentences
in one piece."""

_PAUSE_TAG = re.compile(r"<break\b[^>]*>", re.IGNORECASE)
# A dash or an arrow between words. pocket-tts' models stop early or garble
# the words after one (kyutai-labs/pocket-tts#346: German "Tom – nach
# Berlin" cut off in 19 of 28 samples); a comma is the pause they mean.
# An ellipsis inside a sentence ("liefert... eine Botschaft") is a pause.
# german_24l took it for the end of a 61-token piece and dropped the rest in
# 4 of 50 runs, 0 of 50 with a comma (2026-10-09).
_INNER_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|\u2026)\s+(?=[^\W\d_A-ZÄÖÜÀ-Þ])")
_DASH = re.compile(r"\s*(?:\s[-\u2013\u2014]\s|[\u2013\u2014\u2192])\s*")


def text_for_pocket(text: str) -> str:
    """``text`` the way Pocket TTS reads it cleanly.

    A line without a sentence mark at its end (a heading, a list turned into
    a sentence) ends with a period: pocket-tts only splits at sentence marks
    and runs it into the next line as one sentence, measured up to 69 tokens
    where it speaks 50 cleanly, and the cuts inside it fell into numbers
    ("full two hundred," / "and eighty-eight SCU"). Dashes and arrows become
    commas. Pause tags are dropped: the prompt asks other voices for them,
    but Pocket TTS would read them out as words. So is a tilde ("~17,4 %"),
    heard as "Geben siebzehn" and "Stimmt siebzehn" (2026-10-09). An
    ellipsis inside a sentence becomes a comma, one at its end stays.
    """
    # "~17,4 %" for "about": the model reads a tilde as a syllable of its own.
    text = _DASH.sub(", ", _PAUSE_TAG.sub(" ", text)).replace("~", "")
    text = _INNER_ELLIPSIS.sub(", ", text)
    lines = []
    for line in text.splitlines():
        line = " ".join(line.split()).rstrip(",;:")
        if not line:
            continue
        if not line.rstrip("\"')]\u201d\u2019\u00bb")[-1:] in (".", "!", "?", "\u2026"):
            line += "."
        lines.append(line)
    return " ".join(lines)


FADE_SECONDS = 0.01
"""Fade at the start and end of every piece. Each piece starts from a fresh
model state, and the German model with a voice recorded in English often
starts at full loudness on the first sample: 8 of 12 starts with Eponine, 0
with Juergen (measured 2026-09-23). Straight after the silence of the piece
before, that jump is a click across the whole spectrum, heard as a cut in
front of the word. 10 ms is too short to hear as a fade."""

JOIN_SECONDS = 0.35
"""Pause between two pieces, the pause the model leaves between two
sentences inside a piece (0.28 to 0.46 s, measured 2026-10-09). Left to the
model, a join was its silence after the end of one piece plus its silence
before the first word of the next, 0.6 s in English and 0.85 s in German,
heard as the answer stopping and starting at every join; cut to a fixed
lead instead, a join shrank to 0.07 s when a piece ended quickly. So both
silences are cut and the pause put in between (see _speech_stream)."""

EDGE_SECONDS = 0.02
"""Silence kept before the first and after the last sound of a piece."""

CONTEXT_SECONDS = 3.0
"""How much of the piece before the next piece hears after the voice. Every
piece starts from the voice alone, and the German model gave every piece of
an answer another tone, heard as a new speaker at every join. With the end
of the piece before in its voice prompt the pieces sound like one speaker
(speaker similarity piece to piece 0.909 -> 0.931 over 10 answers, heard
2026-10-09), at a price: they move away from the recording (0.825 -> 0.737)
and get darker. Kyutai's own idea, kyutai-labs/pocket-tts#151."""

CONTINUATION_PROMPT_SECONDS = 9.0
"""The voice's recording in a continuing prompt, so voice and the end of the
piece before stay under the 12 s the models handle (PROMPT_MAX_SECONDS)."""

_SILENCE_RMS = 10 ** (-50 / 20)

LIMIT_KNEE = 0.9
"""Above this the audio is rounded off instead of cut. The models overshoot
full scale on a loud first syllable: German "Hallo, Commander" with Ibrahim
peaked at 1.14 to 1.33 in 4 of 4 runs (2026-10-10), and the int16
conversion cut it off, heard as a crackle."""


def soft_limit(chunk: torch.Tensor) -> torch.Tensor:
    """``chunk`` unchanged below LIMIT_KNEE, above it bent smoothly towards
    full scale instead of running into it."""
    over = chunk.abs() > LIMIT_KNEE
    if not bool(over.any()):
        return chunk
    room = 1.0 - LIMIT_KNEE
    bent = torch.sign(chunk) * (LIMIT_KNEE + room * torch.tanh((chunk.abs() - LIMIT_KNEE) / room))
    return torch.where(over, bent, chunk)


def continuation_prompt(voice: torch.Tensor, previous: torch.Tensor, sample_rate: int) -> torch.Tensor:
    """One voice prompt [1, samples]: the voice's recording, a short pause,
    and CONTEXT_SECONDS of the piece before up to its last pause between
    words, the way the version heard and measured did it: the end of a piece
    is the end of a sentence, said lower, and pocket-tts ends the prompt on
    its own pause."""
    from services.voice_preprocessing import end_at_word_gap

    played = previous.reshape(-1)
    spoken = end_at_word_gap(played.numpy(), sample_rate, played.shape[-1] / sample_rate)
    tail = torch.from_numpy(spoken)[-int(sample_rate * CONTEXT_SECONDS) :].to(played.dtype)
    gap = tail.new_zeros(int(sample_rate * 0.3))
    return torch.cat([voice.reshape(-1).to(tail.dtype), gap, tail]).unsqueeze(0)


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
    after a comma when one is near, else between words, and never between
    two words of a number: "two hundred and eighty-eight" cut in front of
    "and" was heard as "two hundred. Eighty eighty".

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
    numbers = number_words(language)
    fitting = [i for i in fitting if not _inside_number(words, i, numbers)] or fitting
    # A natural cut up to a third of a piece away beats an exact one.
    cut = min(fitting or [1], key=lambda i: abs(i - target) - (target / 3 if natural(i) else 0))

    first = " ".join(words[:cut]).rstrip()
    if first and first[-1].isalnum():
        first += ","
    rest = " ".join(words[cut:])
    return [first] + split_long(rest, count_tokens, language)


def _inside_number(words: list[str], i: int, numbers: frozenset[str]) -> bool:
    """A cut in front of ``words[i]`` would split a number."""

    def is_number(word: str) -> bool:
        parts = [p for p in re.split(r"-", word.lower().strip("()")) if p]
        return bool(parts) and all(p in numbers for p in parts)

    before = words[i - 1]
    return not before.endswith((",", ".", ";", ":")) and is_number(before) and is_number(words[i].rstrip(",.;:"))


def pieces_for_speech(
    text: str,
    split_sentences: Callable[[str], list[str]],
    count_tokens: Callable[[str], int],
    language: SpokenLanguage,
) -> list[str]:
    """pocket-tts's own split, then every piece still over the limit cut at
    word boundaries."""
    pieces: list[str] = []
    for piece in _rejoin_clauses(split_sentences(text)):
        pieces.extend(split_long(piece, count_tokens, language))
    return pieces


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


def piece_audio(chunks: Iterable[torch.Tensor], sample_rate: int) -> Iterator[torch.Tensor]:
    """The audio chunks of one piece without the silence before its first
    and after its last sound (EDGE_SECONDS kept), faded in and out.

    Silent chunks are held back until the next sound or the end, which costs
    no time: the speakers still have the audio before them to play.
    """
    fade = max(1, int(sample_rate * FADE_SECONDS))
    ramp = 0.5 - 0.5 * torch.cos(torch.linspace(0, torch.pi, fade))
    edge = int(sample_rate * EDGE_SECONDS)
    window = max(1, int(sample_rate * 0.01))
    started = False
    pending: list[torch.Tensor] = []  # the last chunk with sound and the silent ones after it
    for chunk in chunks:
        if not started:
            pending.append(chunk)
            audio = torch.cat(pending, dim=-1)
            onset = _first_sound(audio, window)
            if onset is None:
                pending = [audio[..., -edge:]] if edge else []
                continue
            audio = audio[..., max(0, onset - edge) :].clone()
            n = min(fade, audio.shape[-1])
            audio[..., :n] *= ramp[:n].to(audio.dtype)
            pending, started = [audio], True
        elif _first_sound(chunk, window) is not None:
            yield from pending
            pending = [chunk]
        else:
            pending.append(chunk)
    if not started:
        return
    audio = torch.cat(pending, dim=-1)
    end = _last_sound(audio, window)
    audio = audio[..., : min(audio.shape[-1], end + edge)].clone()
    n = min(fade, audio.shape[-1])
    audio[..., audio.shape[-1] - n :] *= ramp[:n].flip(0).to(audio.dtype)
    yield audio


def _last_sound(audio: torch.Tensor, window: int) -> int:
    """Sample where the last window louder than -50 dBFS ends; a piece
    shorter than a window counts as all sound."""
    n = audio.shape[-1] // window
    if n == 0:
        return audio.shape[-1]
    rms = audio[..., : n * window].reshape(-1, n, window).float().square().mean(dim=(0, 2)).sqrt()
    loud = torch.nonzero(rms > _SILENCE_RMS).flatten()
    return (int(loud[-1]) + 1) * window if loud.numel() else audio.shape[-1]


def _first_sound(audio: torch.Tensor, window: int) -> int | None:
    """Sample where the first 10 ms window louder than -50 dBFS starts."""
    n = audio.shape[-1] // window
    if n == 0:
        # Shorter than a window: loud or not as a whole.
        return 0 if audio.numel() and float(audio.float().square().mean().sqrt()) > _SILENCE_RMS else None
    rms = audio[..., : n * window].reshape(-1, n, window).float().square().mean(dim=(0, 2)).sqrt()
    loud = torch.nonzero(rms > _SILENCE_RMS).flatten()
    return int(loud[0]) * window if loud.numel() else None
