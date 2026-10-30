"""After an instant command the model is asked for words, not tools. The tools
still go along with tool_choice "none": they open the request, and a request
without them missed the provider's prompt cache every time.

Some models still try to call one and write the call out as text in their own
tool-call tokens. That text is no answer: it is not spoken and not kept."""

import asyncio
from types import SimpleNamespace

import pytest

import providers.wingman_subscription as subscription_module
import wingmen.wingman as wingman_module
from providers.open_ai import OpenAi
from providers.wingman_subscription import WingmanSubscription
from wingmen.wingman import Wingman

TOOLS = [{"type": "function", "function": {"name": "execute_command", "parameters": {}}}]


def test_the_openai_request_keeps_its_tools_and_calls_none():
    sent = {}
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: sent.update(kwargs) or "ok")
        )
    )
    openai = OpenAi.__new__(OpenAi)
    openai.client = client
    assert openai.ask(messages=[], model="gpt-4.1-nano", tools=TOOLS, tool_choice="none") == "ok"
    assert sent["tools"] == TOOLS
    assert sent["tool_choice"] == "none"


def test_the_subscription_request_keeps_its_tools_and_calls_none(monkeypatch):
    sent = {}

    def post(url, headers, json, timeout):
        sent.update(json)
        return SimpleNamespace(status_code=500)

    monkeypatch.setattr(subscription_module.requests, "post", post)
    ws = WingmanSubscription.__new__(WingmanSubscription)
    ws.settings = SimpleNamespace(base_url="http://backend")
    ws.secret_keeper = SimpleNamespace(secrets={})
    ws.timeout = 1
    ws.send_server_error = lambda response: None
    ws.ask(messages=[], deployment="fast", tools=TOOLS, tool_choice="none")
    assert sent["tools"] == TOOLS
    assert sent["tool_choice"] == "none"


def _answer(monkeypatch, content, allow_tool_calls):
    monkeypatch.setattr(
        wingman_module, "printr", SimpleNamespace(print=lambda *args, **kwargs: None)
    )
    wingman = Wingman.__new__(Wingman)
    wingman.name = "Computer"
    message = SimpleNamespace(content=content, tool_calls=None)
    completion = SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)
    response, _tool_calls, _usage = asyncio.run(
        wingman._process_completion(completion, allow_tool_calls)
    )
    return response.content


# Answers a model gave after an instant command, as the user heard them.
@pytest.mark.parametrize(
    "content",
    [
        "<｜tool_call｜>get_ship_status",
        "<｜tool_call_start｜>get_ship_status<｜tool_call_end｜>",
        '<正parameter name="command_name"｜>Toggle Landing System',
        "<key>Quantum mode disengaged.</code>",
        "<#INVALID#>\n\n<#INVALID#>\n\n<#INVALID#>",
    ],
)
def test_a_tool_call_written_out_as_text_is_not_said(monkeypatch, content):
    assert _answer(monkeypatch, content, allow_tool_calls=False) == ""


@pytest.mark.parametrize(
    "content",
    ["One point added to shields, Captain.", "Fuel is at 3 < 5 percent, Captain."],
)
def test_words_after_an_instant_command_are_said(monkeypatch, content):
    assert _answer(monkeypatch, content, allow_tool_calls=False) == content
