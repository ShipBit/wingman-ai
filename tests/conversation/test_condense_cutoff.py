"""The cut keeps recent turns by token budget and must never tear a tool group apart.

A tool reply without its matching call is, depending on the model, a hard
failure. Measured 2026-09-14, same message list:

    google/gemini-2.5-flash   answers normally
    openai/gpt-4.1-mini       400 "No tool call found for function call output"

A forgiving model hides a mistake here day to day, which is why these tests
exist: it would only hit the users of a stricter model.

The budget is in tokens, not messages: twelve turns of trading play were 23,000
tokens and sat right under the trigger, so every condensation freed almost
nothing. Here every message counts as 10 tokens unless it says otherwise.
"""

import pytest

from services.conversation_condenser import find_cutoff


def role_of(msg):
    return msg.get("role")


def tokens_of(msg):
    return msg.get("tokens", 10)


def user(text="hi", tokens=10):
    return {"role": "user", "content": text, "tokens": tokens}


def assistant(text="ok", tokens=10):
    return {"role": "assistant", "content": text, "tokens": tokens}


def calls(call_id="c1"):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": call_id, "type": "function",
                            "function": {"name": "t", "arguments": "{}"}}]}


def result(call_id="c1", tokens=10):
    return {"role": "tool", "tool_call_id": call_id, "content": "done", "tokens": tokens}


def cut(messages, keep_tokens):
    return find_cutoff(messages, keep_tokens, role_of, tokens_of)


def orphans(messages, cutoff):
    """Tool replies in the kept part whose call was cut away."""
    kept = messages[cutoff:]
    announced = {
        c["id"]
        for m in kept
        for c in (m.get("tool_calls") or [])
    }
    return [m["tool_call_id"] for m in kept
            if m.get("role") == "tool" and m.get("tool_call_id") not in announced]


def test_a_plain_conversation_is_cut_at_a_user_message():
    messages = [user("1"), assistant(), user("2"), assistant(), user("3"), assistant()]

    cutoff = cut(messages, keep_tokens=40)  # two turns of 20

    assert messages[cutoff]["role"] == "user"
    assert messages[cutoff]["content"] == "2"


def test_the_budget_decides_how_many_turns_stay():
    messages = [user(str(i)) if i % 2 == 0 else assistant() for i in range(12)]

    assert messages[cut(messages, keep_tokens=20)]["content"] == "10"
    assert messages[cut(messages, keep_tokens=60)]["content"] == "6"
    assert messages[cut(messages, keep_tokens=100)]["content"] == "2"


def test_the_latest_turn_is_kept_even_when_it_is_over_budget():
    """A 78k-token tool table in the latest turn must not be condensed away
    before the follow-up question that needs it."""
    messages = [user("1"), assistant(), user("2"), calls("c2"), result("c2", tokens=5000), assistant()]

    cutoff = cut(messages, keep_tokens=100)

    assert messages[cutoff]["content"] == "2"
    assert orphans(messages, cutoff) == []


def test_a_tool_group_is_never_split():
    """The group sits between two user messages and the cut lands on a user
    message, so it cannot be torn apart in the first place."""
    messages = [
        user("1"), calls("c1"), result("c1"), assistant(),
        user("2"), calls("c2"), result("c2"), assistant(),
        user("3"), assistant(),
    ]

    cutoff = cut(messages, keep_tokens=60)

    assert orphans(messages, cutoff) == []


@pytest.mark.parametrize("keep_tokens", [0, 10, 25, 40, 55, 100, 200, 1000])
def test_no_orphans_at_any_budget(keep_tokens):
    """Across the whole range anyone can configure."""
    messages = []
    for i in range(8):
        messages.append(user(f"u{i}"))
        if i % 2 == 0:
            messages.append(calls(f"c{i}"))
            messages.append(result(f"c{i}"))
        messages.append(assistant())

    cutoff = cut(messages, keep_tokens=keep_tokens)

    assert orphans(messages, cutoff) == []
    if cutoff:
        assert messages[cutoff]["role"] == "user"


def test_several_results_for_one_turn_stay_together():
    """One turn can call several tools in parallel."""
    messages = [
        user("1"),
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "t", "arguments": "{}"}},
            {"id": "b", "type": "function", "function": {"name": "t", "arguments": "{}"}}]},
        result("a"), result("b"), assistant(),
        user("2"), assistant(),
        user("3"), assistant(),
    ]

    cutoff = cut(messages, keep_tokens=40)

    assert orphans(messages, cutoff) == []


def test_a_cut_landing_on_a_tool_response_moves_forward():
    """The case the second loop exists for. Constructed, because the normal path
    does not produce it — but a change to the cutoff could."""
    messages = [assistant(), result("c1"), result("c2"), user("2"), assistant()]

    cutoff = find_cutoff(messages, 0, role_of, tokens_of)

    assert messages[cutoff]["role"] != "tool"
    assert orphans(messages, cutoff) == []


def test_nothing_to_condense_answers_zero():
    messages = [user("1"), assistant()]

    assert cut(messages, keep_tokens=0) == 0
    assert cut(messages, keep_tokens=1000) == 0
    assert cut([], keep_tokens=20) == 0


def test_a_zero_budget_keeps_only_the_latest_turn():
    """The manual "summarize now" button: a clean slate, but the last exchange
    stays so the wingman does not lose the thread mid-question."""
    messages = [user("1"), assistant(), user("2"), assistant(), user("3"), assistant()]

    cutoff = cut(messages, keep_tokens=0)

    assert messages[cutoff]["content"] == "3"


def test_the_kept_part_always_starts_with_a_user_message():
    """Otherwise the history after the summary starts with an answer to a
    question that is no longer there."""
    messages = []
    for i in range(6):
        messages += [user(f"u{i}"), calls(f"c{i}"), result(f"c{i}"), assistant()]

    cutoff = cut(messages, keep_tokens=120)

    assert messages[cutoff]["role"] == "user"
