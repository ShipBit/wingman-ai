"""Each Wingman names its session to the backend, so the gateway keeps it on the
provider that holds its prompt cache. One session per Wingman: every turn of
the same Wingman sends the same one, two Wingmen never share it."""

import asyncio
from types import SimpleNamespace

import providers.wingman_subscription as subscription_module
from providers.wingman_subscription import WingmanSubscription, WingmanSubscriptionLlm


def _subscription(monkeypatch, sent: list):
    def post(url, headers, json, timeout):
        sent.append(headers)
        return SimpleNamespace(status_code=500)

    monkeypatch.setattr(subscription_module.requests, "post", post)
    ws = WingmanSubscription.__new__(WingmanSubscription)
    ws.settings = SimpleNamespace(base_url="http://backend")
    ws.secret_keeper = SimpleNamespace(secrets={})
    ws.timeout = 1
    ws.wingman_name = "Computer"
    ws.send_server_error = lambda response: None
    return ws


def _llm(ws):
    config = SimpleNamespace(wingman_pro=SimpleNamespace(conversation_deployment="fast"))
    return WingmanSubscriptionLlm(ws_instance=ws, config=config)


def test_one_wingman_keeps_its_session_and_two_do_not_share_one(monkeypatch):
    sent = []
    ws = _subscription(monkeypatch, sent)
    first, second = _llm(ws), _llm(ws)

    asyncio.run(first.ask(messages=[]))
    asyncio.run(first.ask(messages=[]))
    asyncio.run(second.ask(messages=[]))

    sessions = [headers.get("x-wingman-session") for headers in sent]
    assert sessions[0] and sessions[0] == sessions[1]
    assert sessions[2] and sessions[2] != sessions[0]
