"""The per-response cap must leave small responses alone and keep big ones
usable. Over the cap a response is cut, never summarized: in our measurements
a summary of real prose lost every concrete fact.

The cut is structural: JSON stays valid JSON with whole entries, text ends on a
line. The note at the end carries the real numbers, because that note is what
the model reads and what the client shows.
"""

import asyncio
import json

import pytest

from services.tool_response_limiter import ToolResponseLimiter, structural_cut
from services.token_utils import count_tokens

CAP = 8000


def limit(**kwargs):
    return asyncio.run(ToolResponseLimiter().limit(**kwargs))


def rows(n: int) -> list[dict]:
    return [
        {
            "commodity": "Laranite",
            "terminal": f"Admin Office HDMS-Oparei {i} (Hurston, Stanton system)",
            "bpft": 2600 + i,
            "sptt": 3100 + i,
            "bsis": i * 3,
            "sdis": i * 7,
        }
        for i in range(n)
    ]


def uex_shape(n: int) -> str:
    return json.dumps(
        {"keys": {"bpft": "buy_price_from_terminal"}, "data": rows(n)},
        separators=(",", ":"),
    )


BIG_LIST = json.dumps(rows(400), separators=(",", ":"))
BIG_TEXT = "\n".join(f"line {i}: " + "word " * 40 for i in range(600))
BIG_PAGE = "\n".join(
    f"Paragraph {i}. The Laranite market at terminal {i} moved by {i % 7} percent this week. " * 3
    for i in range(400)
)


# ── under the cap ─────────────────────────────────────────────────


def test_small_response_passes_through_untouched():
    text = json.dumps(rows(20))
    assert count_tokens(text) < CAP
    assert limit(response_text=text, cap=CAP) == text


# ── structural cut ────────────────────────────────────────────────


def test_list_is_cut_to_whole_entries_and_stays_json():
    cut, kept, total, kind = structural_cut(BIG_LIST, CAP)
    data = json.loads(cut)
    assert kind == "entries"
    assert total == 400
    assert kept == len(data) < 400
    assert data == rows(kept)
    assert count_tokens(cut) <= CAP


def test_minified_skill_shape_keeps_legend_and_cuts_data():
    text = uex_shape(400)
    cut, kept, total, kind = structural_cut(text, CAP)
    data = json.loads(cut)
    assert kind == "entries"
    assert data["keys"] == {"bpft": "buy_price_from_terminal"}
    assert len(data["data"]) == kept < total == 400
    assert count_tokens(cut) <= CAP


def test_text_is_cut_on_a_line_boundary():
    cut, kept, total, kind = structural_cut(BIG_TEXT, CAP)
    assert kind == "text"
    assert count_tokens(cut) <= CAP
    assert cut.endswith("word")  # ends on a whole line, not mid-word


def test_cut_note_carries_the_real_numbers():
    out = limit(response_text=BIG_LIST, cap=CAP, tool_name="uex")
    original = count_tokens(BIG_LIST)
    assert f"~{original:,} tokens" in out
    assert f"limit is ~{CAP:,}" in out
    assert "of 400 entries" in out
    assert count_tokens(out) <= CAP + 80  # note itself is budgeted for


# ── summarisation ─────────────────────────────────────────────────


def test_text_over_the_cap_is_cut_never_summarized():
    out = limit(response_text=BIG_PAGE, cap=CAP)
    assert "SUMMARY" not in out
    assert BIG_PAGE.startswith(out.split("\n\n[")[0][:500])
    assert count_tokens(out) <= CAP + 100
