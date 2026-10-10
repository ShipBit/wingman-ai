"""What the voice is handed after a reply is cleaned for speech.

Code, tables, URLs, Markdown marks and emojis do not survive being read
aloud; short lists become a spoken enumeration, link text stays. Text in any
script has to come through: the emoji filter once covered a range that held
every Chinese, Japanese and Korean character, and those replies were silent.
"""

import pytest

from services.markdown import MAX_LIST_ITEMS_FOR_TTS, cleanup_text, strip_edge_breaks


def spoken(text: str) -> str:
    return cleanup_text(text)[0]


@pytest.mark.parametrize(
    "text",
    [
        "こんにちは、司令官。",
        "안녕하세요 사령관님",
        "你好，指挥官",
        "Привет, командир.",
        "Ünïcödé — „ok“ – 5 € ← → ─",
    ],
)
def test_text_in_any_script_is_spoken(text):
    assert spoken(text) == text


def test_emojis_are_dropped():
    assert spoken("Hallo 🚀🔥 ✅ ☀️ Ⓜ 🅰 Commander") == "Hallo Commander"


def test_markdown_marks_are_dropped():
    assert spoken("# Status\nShields at **forty** percent.") == "Status\nShields at forty percent."


@pytest.mark.parametrize(
    "text, expected",
    [
        ("*seufzt* Na gut, ich mache es.", "Na gut, ich mache es."),
        ("Sure. *checks the scanner* Two contacts.", "Sure. Two contacts."),
        ("Na gut *seufzt*", "Na gut"),
        ("*leans back in the pilot seat*\nAll systems green.", "All systems green."),
    ],
)
def test_an_action_between_asterisks_is_not_read_aloud(text, expected):
    assert spoken(text) == expected


def test_emphasis_in_a_sentence_stays_a_word():
    assert spoken("Two contacts, *very* close. That is *important*.") == (
        "Two contacts, very close. That is important."
    )
    assert spoken("2 * 3 = 6") == "2 * 3 = 6"


def test_a_link_keeps_its_text_and_loses_its_url():
    text, has_links, _ = cleanup_text("See [the wiki](https://example.org/x) or https://example.org/y")
    assert text == "See the wiki or"
    assert has_links


def test_code_is_not_read_aloud():
    text, _, has_code = cleanup_text("```py\nprint(1)\n```\nThat is the code.")
    assert text == "That is the code."
    assert has_code


def test_a_table_is_not_read_aloud():
    assert spoken("| Ship | Price |\n|---|---|\n| Aurora | 20 |\nThat is all.") == "That is all."


def test_a_short_list_becomes_an_enumeration():
    assert spoken("Do this:\n\n1. Gear down\n2. Lights on\n\nDone.") == "Do this:\nGear down and Lights on.\nDone."


def test_a_list_is_joined_in_the_spoken_language():
    from api.enums import SpokenLanguage

    text = "- Kaufen\n- Verkaufen\n- Gewinn"
    assert cleanup_text(text, SpokenLanguage.DE)[0] == "Kaufen, Verkaufen und Gewinn."
    assert cleanup_text(text, SpokenLanguage.OTHER)[0] == "Kaufen, Verkaufen, Gewinn."


def test_a_long_list_is_left_out():
    items = "\n".join(f"- Item {i}" for i in range(MAX_LIST_ITEMS_FOR_TTS + 1))
    assert spoken(f"Here:\n{items}\nThat was it.") == "Here:\nThat was it."


# ── pause tags ──────────────────────────────────────────────────────
# A pause tag at the edge of a reply is not a pause, it is latency.


def test_a_break_at_either_edge_is_dropped():
    assert spoken('<break time="400ms" /> Hull breach detected.') == "Hull breach detected."
    assert spoken('Copy that, LOST-1. <break time="1s"/>') == "Copy that, LOST-1."


def test_a_break_between_sentences_stays():
    text = 'Shields at forty percent. <break time="400ms" /> I would not stay here.'
    assert spoken(text) == text


def test_several_edge_breaks_in_any_case():
    assert strip_edge_breaks('<BREAK time="1s" /> <break time="2s"/> Hello. <break time="300ms" />') == "Hello."
