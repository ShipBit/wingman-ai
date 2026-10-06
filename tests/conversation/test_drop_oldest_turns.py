"""The subscription's size brake removes whole turns from the front, never the latest.

The subscription refuses a conversation over 400 KB of JSON. With condensation off
nothing else shortens the history, so before the request goes out the oldest
turns are dropped. A tool response without its call is a hard 400 on some
models, which is why the cut always lands on a user message.
"""

from openai.types.chat import ChatCompletionMessage

from services.conversation_manager import ConversationManager


def manager():
    return ConversationManager(config=None, settings=None, wingman_name="test")


def turn(n, size=100):
    return [
        {"role": "user", "content": f"q{n}"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"c{n}", "type": "function", "function": {"name": "t", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": f"c{n}", "content": "x" * size},
        {"role": "assistant", "content": f"a{n}"},
    ]


def test_nothing_to_free_removes_nothing():
    m = manager()
    m.messages = turn(1) + turn(2)
    assert m.drop_oldest_turns(0) == 0
    assert len(m.messages) == 8


def test_removes_just_enough_whole_turns():
    m = manager()
    m.messages = turn(1, 1000) + turn(2, 1000) + turn(3, 1000)

    removed = m.drop_oldest_turns(500)

    assert removed == 4
    assert m.messages[0]["content"] == "q2"


def test_never_removes_the_latest_turn():
    m = manager()
    m.messages = turn(1) + turn(2) + turn(3, 50_000)

    removed = m.drop_oldest_turns(10**9)

    assert removed == 8
    assert [x["content"] for x in m.messages if x["role"] == "user"] == ["q3"]


def test_a_single_turn_is_left_alone():
    m = manager()
    m.messages = turn(1, 50_000)
    assert m.drop_oldest_turns(10**9) == 0


def test_cut_lands_on_a_user_message():
    m = manager()
    m.messages = turn(1) + turn(2) + turn(3)
    m.drop_oldest_turns(1)
    assert m.messages[0]["role"] == "user"
    ids = {c["id"] for x in m.messages for c in (x.get("tool_calls") or [])}
    assert all(x["tool_call_id"] in ids for x in m.messages if x["role"] == "tool")


def test_sdk_messages_are_measured():
    msg = ChatCompletionMessage(role="assistant", content="ü" * 100)
    assert 100 <= ConversationManager.message_chars(msg) < 200


import asyncio
from types import SimpleNamespace

from api.enums import ConversationProvider
from services.context_budget import ContextBudget
from wingmen import wingman as wingman_module
from wingmen.wingman import Wingman


def fake_wingman(provider, window=1_000_000):
    m = manager()

    async def add_context(messages):
        messages.insert(0, {"role": "system", "content": "s" * 1000})

    return SimpleNamespace(
        config=SimpleNamespace(features=SimpleNamespace(conversation_provider=provider)),
        conversation=m,
        add_context=add_context,
        name="test",
        context_budget=ContextBudget(window),
        _request_tokens=Wingman._request_tokens,
    ), m


def fit(fake):
    async def run():
        messages = fake.conversation.messages.copy()
        await fake.add_context(messages)
        return await Wingman._fit_request(fake, messages, None)
    return asyncio.run(run())


def capture(monkeypatch):
    logged = []

    async def fake_print_async(text, **kwargs):
        logged.append(text)

    monkeypatch.setattr(wingman_module.printr, "print_async", fake_print_async)
    return logged


def test_subscription_request_is_brought_under_its_size_limit(monkeypatch):
    monkeypatch.setattr(wingman_module, "SUBSCRIPTION_MAX_REQUEST_CHARS", 5_000)
    logged = capture(monkeypatch)
    fake, m = fake_wingman(ConversationProvider.WINGMAN_PRO)
    m.messages = turn(1, 3000) + turn(2, 3000) + turn(3, 100)

    sent = fit(fake)

    assert sum(ConversationManager.message_chars(x) for x in sent) <= 5_000
    assert sent[0]["role"] == "system"
    # Dropping the first turn is enough; the second one stays.
    assert [x["content"] for x in m.messages if x["role"] == "user"] == ["q2", "q3"]
    assert len(logged) == 1 and "size limit of the Wingman subscription" in logged[0]


def test_any_provider_is_kept_under_its_window(monkeypatch):
    logged = capture(monkeypatch)
    fake, m = fake_wingman(ConversationProvider.OPENAI, window=4_000)  # brake 3,600 tokens
    m.messages = turn(1) + turn(2) + turn(3)
    for msg, words in ((m.messages[2], 2000), (m.messages[6], 2000)):
        msg["content"] = "cargo " * words  # ~2,000 tokens each

    sent = fit(fake)

    assert Wingman._request_tokens(sent, None) <= 3_600
    # One turn of ~2,000 tokens is enough; the second one stays.
    assert [x["content"] for x in m.messages if x["role"] == "user"] == ["q2", "q3"]
    assert "what the model can take" in logged[0]


def test_under_both_limits_nothing_happens(monkeypatch):
    logged = capture(monkeypatch)
    fake, m = fake_wingman(ConversationProvider.WINGMAN_PRO)
    m.messages = turn(1, 3000) + turn(2, 3000) + turn(3, 100)
    fit(fake)
    assert len(m.messages) == 12 and logged == []


def test_tool_call_arguments_count_toward_the_size():
    """A HUD table lives in hud_add_info's arguments; leaving them out would
    undercount exactly the messages that grow."""
    msg = {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c", "type": "function", "function": {"name": "hud_add_info", "arguments": "x" * 4000}}]}
    assert len(ConversationManager.message_text(msg)) >= 4000
