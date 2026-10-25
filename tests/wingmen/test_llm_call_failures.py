"""What the main model call does with answers it cannot use.

An answer without a single choice used to crash the turn on ``choices[0]``.
"""

import asyncio
from types import SimpleNamespace

import wingmen.wingman as wingman_module
from api.enums import ConversationProvider, LogType
from wingmen.wingman import Wingman


class Lines:
    def __init__(self):
        self.lines = []

    def print(self, text, color=None, **kwargs):
        self.lines.append((text, color))

    async def print_async(self, text, color=None, **kwargs):
        self.lines.append((text, color))


def _wingman(monkeypatch, llm=None):
    lines = Lines()
    monkeypatch.setattr(wingman_module, "printr", lines)
    wingman = Wingman.__new__(Wingman)
    wingman.name = "Computer"
    wingman.llm = llm
    wingman.config = SimpleNamespace(
        features=SimpleNamespace(conversation_provider=ConversationProvider.OPENAI)
    )
    return wingman, lines


class Llm:
    def __init__(self, completion):
        self.completion = completion

    async def ask(self, messages, tools=None, tool_choice="auto"):
        return self.completion


def test_an_answer_without_choices_is_no_answer(monkeypatch):
    for completion in (SimpleNamespace(choices=None), SimpleNamespace(choices=[])):
        wingman, lines = _wingman(monkeypatch, Llm(completion))

        assert asyncio.run(wingman.actual_llm_call([{"role": "user", "content": "Hi"}])) is None
        assert [color for _text, color in lines.lines] == [LogType.WARNING]


def test_an_answer_with_a_choice_is_passed_on(monkeypatch):
    completion = SimpleNamespace(choices=[SimpleNamespace(message="Hello")])
    wingman, lines = _wingman(monkeypatch, Llm(completion))

    assert asyncio.run(wingman.actual_llm_call([])) is completion
    assert lines.lines == []

