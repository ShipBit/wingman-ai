"""The enhanced backstory reaches the client as two strings, whatever the model sent."""

from services.backstory import parse_enhanced_backstory


def test_a_summary_sent_as_a_list_becomes_lines():
    backstory, summary = parse_enhanced_backstory(
        '{"backstory": "Zoe is a pilot.", "summary": ["Shorter intro", "Added tone rules"]}'
    )

    assert backstory == "Zoe is a pilot."
    assert summary == "- Shorter intro\n- Added tone rules"


def test_json_in_a_code_fence_is_read():
    backstory, summary = parse_enhanced_backstory('```json\n{"backstory": "B", "summary": "S"}\n```')

    assert (backstory, summary) == ("B", "S")


def test_plain_text_is_the_backstory():
    assert parse_enhanced_backstory("Just a backstory.") == ("Just a backstory.", "")


def test_json_that_is_not_an_object_is_the_backstory():
    assert parse_enhanced_backstory('["a", "b"]') == ('["a", "b"]', "")


def test_a_null_backstory_keeps_the_raw_text():
    raw = '{"backstory": null, "summary": "S"}'

    assert parse_enhanced_backstory(raw) == (raw, "S")
