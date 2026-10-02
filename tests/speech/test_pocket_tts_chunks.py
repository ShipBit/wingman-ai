"""Long text is cut into pieces Pocket TTS speaks cleanly."""

from api.enums import SpokenLanguage as L
from providers.pocket_tts_chunks import MAX_TOKENS, pieces_for_speech, split_long

words = lambda t: len(t.split())  # one token per word is enough to test the cuts


def test_a_short_piece_stays_whole():
    assert split_long("Alles klar, Kommandant.", words, L.DE) == ["Alles klar, Kommandant."]


def test_a_long_piece_is_cut_in_front_of_a_conjunction():
    text = " ".join(["wort"] * 40) + " und " + " ".join(["wort"] * 40) + "."
    pieces = split_long(text, words, L.DE)
    assert all(words(p) <= MAX_TOKENS for p in pieces)
    assert pieces[1].startswith("und ")
    # Cut mid-sentence: ends with a comma, so no period is appended.
    assert pieces[0].endswith(",")


def test_without_a_conjunction_the_cut_is_near_the_middle():
    pieces = split_long(" ".join(["wort"] * 120) + ".", words, L.DE)
    assert all(words(p) <= MAX_TOKENS for p in pieces)
    assert " ".join(p.rstrip(",") for p in pieces).split() == (" ".join(["wort"] * 120) + ".").split()


def test_one_long_word_is_left_alone():
    word = "x" * 500
    assert split_long(word, lambda t: 999, L.DE) == [word]


# ───────────────────────── faded_edges ───────────────────────── #

import torch

from providers.pocket_tts_chunks import faded_edges


def test_faded_edges_fades_first_start_and_last_end_only():
    chunks = [torch.ones(1920) for _ in range(3)]
    out = list(faded_edges(iter(chunks), 24000))
    assert len(out) == 3
    assert out[0][0] == 0 and out[0][239] > 0.99  # 10 ms at 24 kHz
    assert out[0][-1] == 1 and out[1].eq(1).all()
    assert out[2][0] == 1 and out[2][-1] < 1e-6
    assert chunks[0][0] == 1  # the model's own tensors are left alone


def test_faded_edges_single_short_chunk_and_empty():
    out = list(faded_edges(iter([torch.ones(100)]), 24000))
    assert len(out) == 1 and out[0][0] == 0 and out[0][-1] < 1e-3
    assert list(faded_edges(iter([]), 24000)) == []


from providers.pocket_tts_chunks import EXTRA_FRAMES_AFTER_EOS, frames_after_eos


def test_frames_after_eos_add_to_pocket_tts_own_guess():
    assert frames_after_eos("Okay.") == 3 + 2 + EXTRA_FRAMES_AFTER_EOS
    assert frames_after_eos("Die Route nach Stanton ist frei.") == 1 + 2 + EXTRA_FRAMES_AFTER_EOS


def test_clauses_of_one_sentence_are_put_back_together():
    split = lambda t: ["eins zwei,", "drei vier,", "fünf sechs.", "Neuer Satz."]
    assert pieces_for_speech("x", split, words, L.DE) == ["eins zwei, drei vier, fünf sechs.", "Neuer Satz."]


def test_clauses_are_pieces_of_their_own_for_the_german_6l_model():
    from providers.pocket_tts_chunks import split_clauses

    assert split_clauses("Wir brauchen Credits für die Ladung, und der Hangar ist bereit.") == [
        "Wir brauchen Credits für die Ladung,",
        "und der Hangar ist bereit.",
    ]
    assert split_clauses("Ja, das mache ich sofort.") == ["Ja, das mache ich sofort."]
    assert split_clauses("Es sind 2,5 Tonnen, Commander.") == ["Es sind 2,5 Tonnen, Commander."]
