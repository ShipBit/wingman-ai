"""What the main model call does with answers and setups it cannot use.

An answer without a single choice used to crash the turn on ``choices[0]``.
An endpoint the user typed in that is no URL is theirs to correct: a warning
and an initialization error, not an error report.
"""

import asyncio
from types import SimpleNamespace

import httpx

import wingmen.wingman as wingman_module
from api.enums import ConversationProvider, LogType, WingmanInitializationErrorType
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


def test_an_endpoint_that_is_no_url_is_a_config_error(monkeypatch):
    class Factory:
        def __init__(self, **kwargs):
            pass

        async def create_tts(self, errors):
            return None

        async def create_llm(self, errors):
            raise httpx.InvalidURL("Invalid port: '1234:1234'")

    monkeypatch.setattr(wingman_module, "ProviderFactory", Factory)
    wingman, lines = _wingman(monkeypatch)
    wingman.settings = wingman.secret_keeper = wingman._shared_providers = None

    errors = asyncio.run(wingman.validate())

    assert [e.error_type for e in errors] == [WingmanInitializationErrorType.INVALID_CONFIG]
    assert "1234:1234" in errors[0].message
    assert [color for _text, color in lines.lines] == [LogType.WARNING]
