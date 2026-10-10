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


# ───────────────────────── piece_audio ───────────────────────── #

import torch

from providers.pocket_tts_chunks import EDGE_SECONDS, piece_audio


def test_piece_audio_fades_first_start_and_last_end_only():
    chunks = [torch.ones(1920) for _ in range(3)]
    out = list(piece_audio(iter(chunks), 24000))
    assert len(out) == 3
    assert out[0][0] == 0 and out[0][239] > 0.99  # 10 ms at 24 kHz
    assert out[0][-1] == 1 and out[1].eq(1).all()
    assert out[2][0] == 1 and out[2][-1] < 1e-6
    assert chunks[0][0] == 1  # the model's own tensors are left alone


def test_piece_audio_single_short_chunk_and_empty():
    out = list(piece_audio(iter([torch.ones(100)]), 24000))
    assert len(out) == 1 and out[0][0] == 0 and out[0][-1] < 1e-3
    assert list(piece_audio(iter([]), 24000)) == []


def test_the_silence_around_a_piece_is_cut_short():
    sr = 24000
    edge = int(EDGE_SECONDS * sr)
    silent = [torch.zeros(1920) for _ in range(5)]  # 0.4 s
    voice = [torch.full((1920,), 0.5) for _ in range(3)]
    out = torch.cat(list(piece_audio(iter(silent + voice + silent), sr)))
    assert out.shape[-1] == edge + 3 * 1920 + edge
    assert out[edge + 300] == 0.5


def test_a_pause_inside_a_piece_stays():
    voice, pause = torch.full((1920,), 0.5), torch.zeros(1920)
    out = torch.cat(list(piece_audio(iter([voice, pause, pause, voice]), 24000)))
    assert out.shape[-1] == 4 * 1920


def test_a_silent_piece_plays_nothing():
    assert list(piece_audio(iter([torch.zeros(1920) for _ in range(4)]), 24000)) == []


def test_a_cut_never_splits_a_spoken_number():
    text = " ".join(["word"] * 55) + " for two hundred and eighty-eight SCU, " + " ".join(["word"] * 20) + "."
    pieces = split_long(text, words, L.EN)
    assert all(words(p) <= MAX_TOKENS for p in pieces)
    assert any("two hundred and eighty-eight SCU" in p for p in pieces)


def test_a_spanish_number_with_y_stays_whole():
    text = " ".join(["palabra"] * 56) + " treinta y dos " + " ".join(["palabra"] * 30) + "."
    assert any("treinta y dos" in p for p in split_long(text, words, L.ES))


def test_clauses_of_one_sentence_are_put_back_together():
    split = lambda t: ["eins zwei,", "drei vier,", "fünf sechs.", "Neuer Satz."]
    assert pieces_for_speech("x", split, words, L.DE) == ["eins zwei, drei vier, fünf sechs.", "Neuer Satz."]


from providers.pocket_tts_chunks import text_for_pocket


def test_lines_without_a_sentence_mark_end_with_a_period():
    assert text_for_pocket("Top pick, Bexalite\nBuy at Hurston for six million\nDone.") == (
        "Top pick, Bexalite. Buy at Hurston for six million. Done."
    )
    assert text_for_pocket("Runners-up, same cargo:\nWhy? (Ask me.)") == "Runners-up, same cargo. Why? (Ask me.)"


def test_dashes_and_arrows_become_commas_and_hyphens_stay():
    assert text_for_pocket("Top pick — Bexalite") == "Top pick, Bexalite."
    assert text_for_pocket("Sell at TDD - Area eighteen") == "Sell at TDD, Area eighteen."
    assert text_for_pocket("MicroTech → Admin ARC-L4, Stanton-only") == "MicroTech, Admin ARC-L4, Stanton-only."


def test_an_ellipsis_inside_a_sentence_becomes_a_comma():
    assert text_for_pocket("Die Hermes liefert... eine Botschaft.") == "Die Hermes liefert, eine Botschaft."
    assert text_for_pocket("Delivering\u2026 a message.") == "Delivering, a message."
    assert text_for_pocket("Na ja... Soll ich?") == "Na ja... Soll ich?"
    assert text_for_pocket("Warte...") == "Warte..."


def test_a_tilde_is_not_read_out():
    assert text_for_pocket("Marge ~siebzehn Prozent") == "Marge siebzehn Prozent."


def test_pause_tags_are_not_read_out():
    assert text_for_pocket('Why? <break time="400ms" /> He heard it.') == "Why? He heard it."
    assert text_for_pocket('<break time="1s"/>') == ""


from providers.pocket_tts_chunks import CONTEXT_SECONDS, continuation_prompt


def test_the_next_piece_hears_the_voice_then_the_piece_before_up_to_its_last_pause():
    sr = 24000
    voice = torch.full((9 * sr,), 0.5)
    speech = lambda n: torch.full((int(n * sr),), 0.4)
    # 5 s spoken, a pause, the last 1 s sentence of the piece
    previous = torch.cat([speech(5), torch.zeros(int(0.3 * sr)), speech(1)])
    out = continuation_prompt(voice, previous, sr)
    tail = int(CONTEXT_SECONDS * sr)
    gap = int(0.3 * sr)
    assert out.shape == (1, 9 * sr + gap + tail)
    assert torch.equal(out[0, : 9 * sr], voice)
    assert out[0, 9 * sr : 9 * sr + gap].abs().max() == 0
    assert out[0, -tail:].eq(0.4).all()  # spoken audio, from before the pause
