"""Below the history limit nothing is touched; above it, old tool output goes
first and a summary only if that was not enough.

Measured 2026-09-28: once tool data was cleared, the model answered from memory
and invented prices; with the history left alone it did not. So the limit is
generous, and the cheap step comes before the lossy one.
"""

import asyncio
from types import SimpleNamespace

import pytest

from services import conversation_condenser as condenser_module
from services import conversation_manager as manager_module
from services.context_budget import ContextBudget
from services.conversation_condenser import ConversationCondenser
from services.conversation_manager import ConversationManager
from services.token_utils import count_tokens

BUDGET = ContextBudget(40_000)  # history_limit 20,000, keep 5,000
ROWS = "Ship data row. " * 600  # ~2,400 tokens


def config(condense=True):
    return SimpleNamespace(features=SimpleNamespace(condense_conversation=condense))


@pytest.fixture
def logged(monkeypatch):
    lines = []

    async def fake_print_async(text, **kwargs):
        lines.append(text)

    monkeypatch.setattr(manager_module.printr, "print_async", fake_print_async)
    monkeypatch.setattr(condenser_module.printr, "print_async", fake_print_async)
    return lines


class Support:
    def is_ready(self):
        return True


def setup(turns, condense=True, size=ROWS):
    mgr = ConversationManager(config=config(condense), settings=None, wingman_name="test")
    for n in range(turns):
        mgr.messages += [
            {"role": "user", "content": f"turn {n}"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": f"c{n}", "type": "function",
                 "function": {"name": "uex_get_commodity_information", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": f"c{n}", "content": size},
            {"role": "assistant", "content": "ok"},
        ]
    cond = ConversationCondenser(mgr, config(condense), "test")
    started = []

    async def fake_condense(local_ai_service=None, **kwargs):
        started.append(True)

    cond.condense = fake_condense
    return mgr, cond, started


def run(cond, prompt):
    async def go():
        await cond.maybe_condense(Support(), prompt, BUDGET)
        if cond._condense_task:
            await cond._condense_task
    asyncio.run(go())


def tools(mgr):
    return [m for m in mgr.messages if m["role"] == "tool"]


def test_below_the_limit_nothing_is_touched(logged):
    mgr, cond, started = setup(6)
    run(cond, prompt=15_000)
    assert all(m["content"] == ROWS for m in tools(mgr))
    assert logged == [] and started == []


def test_above_the_limit_old_tool_output_goes_first(logged):
    mgr, cond, started = setup(12)  # ~29k tokens of history
    run(cond, prompt=30_000)
    t = tools(mgr)
    cleared = [m for m in t if m["content"].startswith("[Tool output removed")]
    assert cleared and t[-1]["content"] == ROWS
    assert all(m["content"] == ROWS for m in t[-4:])  # at least the last 4 turns stay
    assert any("Removed" in line and "uex_get_commodity_information" in line for line in logged)
    assert started == []  # clearing was enough: no summary


def test_a_summary_only_when_clearing_is_not_enough(logged):
    mgr, cond, started = setup(12, size="Plain talk. " * 1500)  # no tool data worth clearing
    for m in tools(mgr):
        m["content"] = "ok"
    for m in mgr.messages:
        if m["role"] == "assistant" and m["content"] == "ok":
            m["content"] = "Plain talk. " * 800
    run(cond, prompt=30_000)
    assert started == [True]


def test_condensation_off_touches_nothing(logged):
    mgr, cond, started = setup(12, condense=False)
    run(cond, prompt=90_000)
    assert all(m["content"] == ROWS for m in tools(mgr))
    assert started == []


def test_a_big_prompt_with_a_small_history_says_why_and_does_nothing(logged):
    mgr, cond, started = setup(1)
    run(cond, prompt=30_000)
    assert started == []
    assert any("system prompt, memory and tool definitions" in line for line in logged)


def test_the_placeholder_tells_the_model_not_to_guess(logged):
    mgr, cond, _ = setup(12)
    run(cond, prompt=30_000)
    note = tools(mgr)[0]["content"]
    assert "call the tool again before stating" in note
    assert "uex_get_commodity_information" in note
    assert count_tokens(note) < 60


def test_clearing_twice_logs_once(logged):
    mgr, _, _ = setup(12)
    asyncio.run(mgr.clear_tool_responses(20))
    asyncio.run(mgr.clear_tool_responses(20))
    assert sum("Removed" in line for line in logged) == 1


def test_a_pending_response_is_left_alone(logged):
    mgr, _, _ = setup(6)
    mgr.pending_tool_calls = ["c0"]
    asyncio.run(mgr.clear_tool_responses(len(mgr.messages)))
    assert tools(mgr)[0]["content"] == ROWS
