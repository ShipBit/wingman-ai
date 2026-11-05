"""Parakeet on a server of the user's: the request names the configured model
and carries the API key only when one is set.

oMLX, for one, hosts several models and wants the model's own id and a key;
before, Wingman always sent "parakeet" without a key and got 404 and 401."""

from types import SimpleNamespace

import pytest

from api.interface import ParakeetSettings, ParakeetSttConfig
from providers import parakeet as parakeet_module
from providers.parakeet import Parakeet
from services.stt_service import SttService


@pytest.fixture
def sent(monkeypatch):
    """Records what would go to the server and answers like one."""
    calls = []

    def post(url, files, data, headers, timeout):
        calls.append({"url": url, "data": data, "headers": headers})
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"text": " hello "})

    monkeypatch.setattr(parakeet_module.requests, "post", post)
    return calls


def remote(model: str) -> Parakeet:
    return Parakeet(
        settings=ParakeetSettings(
            run_locally=False,
            execution_provider="cpu",
            host="127.0.0.1",
            port=8000,
            model=model,
        )
    )


def transcribe(parakeet: Parakeet, tmp_path, api_key: str = ""):
    audio = tmp_path / "recording.wav"
    audio.write_bytes(b"RIFF")
    return parakeet.transcribe(
        config=ParakeetSttConfig(temperature=0.0), filename=str(audio), api_key=api_key
    )


def test_the_configured_model_and_the_key_go_to_the_server(sent, tmp_path):
    result = transcribe(remote("parakeet-tdt-0.6b-v3"), tmp_path, api_key="sk-local")
    assert result.text == "hello"
    assert sent[0]["url"] == "http://127.0.0.1:8000/v1/audio/transcriptions"
    assert sent[0]["data"]["model"] == "parakeet-tdt-0.6b-v3"
    assert sent[0]["headers"] == {"Authorization": "Bearer sk-local"}


def test_without_a_key_no_authorization_header_is_sent(sent, tmp_path):
    transcribe(remote("parakeet"), tmp_path)
    assert sent[0]["headers"] == {}


def test_an_empty_model_name_falls_back_to_parakeet(sent, tmp_path):
    transcribe(remote("  "), tmp_path)
    assert sent[0]["data"]["model"] == "parakeet"


@pytest.mark.parametrize(
    ("secrets", "expected"),
    [({"parakeet": " sk-local "}, "sk-local"), ({"parakeet": "not-set"}, ""), ({}, "")],
)
def test_the_key_is_the_secret_parakeet(secrets, expected):
    service = SttService.__new__(SttService)
    service.secret_keeper = SimpleNamespace(secrets=secrets)
    assert service._parakeet_api_key() == expected
