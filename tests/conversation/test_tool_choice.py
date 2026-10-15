"""After an instant command the model is asked for words, not tools. The tools
still go along with tool_choice "none": they open the request, and a request
without them missed the provider's prompt cache every time."""

from types import SimpleNamespace

import providers.wingman_subscription as subscription_module
from providers.open_ai import OpenAi
from providers.wingman_subscription import WingmanSubscription

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
