"""A model that cannot call tools (gemma3 on Ollama) answered every message of
a wingman with skills with a 400, an error toast and a Sentry event. The
request now goes again without tools, and later ones leave them out."""

from types import SimpleNamespace

import httpx
import pytest
from openai import BadRequestError

import providers.open_ai as open_ai_module
from providers.open_ai import BaseOpenAi, OpenAi

TOOLS = [{"type": "function", "function": {"name": "execute_command", "parameters": {}}}]


def bad_request(message: str) -> BadRequestError:
    request = httpx.Request("POST", "http://localhost:11434/v1/chat/completions")
    response = httpx.Response(400, request=request)
    return BadRequestError(message, response=response, body={"message": message})


@pytest.fixture(autouse=True)
def toasts(monkeypatch):
    """The module's Printr swapped out whole: patching the shared singleton
    left its methods shadowing other tests' patches on the class."""
    shown = []
    monkeypatch.setattr(BaseOpenAi, "_models_without_tools", set())
    monkeypatch.setattr(
        open_ai_module,
        "printr",
        SimpleNamespace(print=lambda *a, **k: None, toast_error=shown.append),
    )
    return shown


def provider(create, base_url="http://localhost:11434/v1/"):
    openai = OpenAi.__new__(OpenAi)
    openai.client = SimpleNamespace(
        base_url=base_url,
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )
    return openai


def refusing_tools(calls):
    def create(**kwargs):
        calls.append(kwargs)
        if "tools" in kwargs:
            raise bad_request(
                "registry.ollama.ai/library/gemma3:4b does not support tools"
            )
        return "answer"

    return create


def test_a_model_that_refuses_tools_is_asked_again_without_them(toasts):
    calls = []
    openai = provider(refusing_tools(calls))

    assert openai.ask(messages=[], model="gemma3:4b", tools=TOOLS) == "answer"
    assert ["tools" in c for c in calls] == [True, False]
    assert toasts == []


def test_later_requests_leave_the_tools_out_at_once():
    calls = []
    openai = provider(refusing_tools(calls))
    openai.ask(messages=[], model="gemma3:4b", tools=TOOLS)
    calls.clear()

    assert openai.ask(messages=[], model="gemma3:4b", tools=TOOLS) == "answer"
    assert ["tools" in c for c in calls] == [False]


def test_the_same_model_on_another_server_still_gets_its_tools():
    provider(refusing_tools([])).ask(messages=[], model="gemma3:4b", tools=TOOLS)
    sent = {}
    other = provider(
        lambda **kwargs: sent.update(kwargs) or "answer",
        base_url="http://192.168.0.10:11434/v1/",
    )

    other.ask(messages=[], model="gemma3:4b", tools=TOOLS)
    assert sent["tools"] == TOOLS


def test_other_bad_requests_still_reach_the_user(toasts):
    def create(**kwargs):
        raise bad_request("messages: field required")

    assert provider(create).ask(messages=[], model="gemma3:4b", tools=TOOLS) is None
    assert toasts
    assert BaseOpenAi._models_without_tools == set()
