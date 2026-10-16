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


def test_a_call_without_a_session_sends_no_header(monkeypatch):
    sent = []
    ws = _subscription(monkeypatch, sent)
    ws.ask(messages=[], deployment="fast")
    assert "x-wingman-session" not in sent[0]


def test_each_answered_request_logs_its_generation_id(monkeypatch):
    answer = {
        "id": "gen_01TEST",
        "object": "chat.completion",
        "created": 0,
        "model": "test/model",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "ok"},
            }
        ],
        "usage": {
            "prompt_tokens": 9214,
            "completion_tokens": 64,
            "total_tokens": 9278,
            "prompt_tokens_details": {"cached_tokens": 9000},
        },
    }
    logged = []
    ws = _subscription(monkeypatch, [])
    monkeypatch.setattr(
        subscription_module.requests,
        "post",
        lambda url, headers, json, timeout: SimpleNamespace(
            status_code=200,
            headers={"x-wingman-model": "test/served"},
            json=lambda: answer,
            raise_for_status=lambda: None,
        ),
    )
    ws.printr = SimpleNamespace(print=lambda text, **kwargs: logged.append((text, kwargs)))

    ws.ask(messages=[], deployment="fast")

    assert logged == [
        (
            "Gateway request gen_01TEST (test/served): 9214 in (9000 cached) / 64 out",
            {"server_only": True, "source_name": "Computer"},
        )
    ]
