"""ElevenLabs talks to the HTTP API directly: tier fallback for PCM streaming,
voice lookup by name, speed and the language hint."""

import pytest

import providers.elevenlabs as elevenlabs
from api.interface import ElevenlabsConfig


class FakeResponse:
    def __init__(self, status_code: int, body=None, content: bytes = b""):
        self.status_code = status_code
        self._body = body or {}
        self.content = content
        self.text = str(self._body)
        self.closed = False

    def json(self):
        return self._body

    def close(self):
        self.closed = True


def make_config(model: str = "eleven_v4", **voice) -> ElevenlabsConfig:
    return ElevenlabsConfig(
        model=model,
        voice=voice,
        voice_settings={
            "stability": 0.71,
            "similarity_boost": 0.8,
            "style": 0.1,
            "use_speaker_boost": True,
            "speed": 1.1,
        },
        output_streaming=True,
        use_tts_prompt=False,
        tts_prompt="",
    )


@pytest.fixture(autouse=True)
def clean_caches():
    elevenlabs._pcm_format_by_key.clear()
    elevenlabs._lookup_cache.clear()
    yield
    elevenlabs._pcm_format_by_key.clear()
    elevenlabs._lookup_cache.clear()


def test_stream_falls_back_to_24khz_below_pro_and_remembers_it(monkeypatch):
    asked: list[str] = []

    def fake_post(url, params, **kwargs):
        asked.append(params["output_format"])
        if params["output_format"] == "pcm_44100":
            return FakeResponse(
                403,
                {"detail": {"code": "subscription_required", "message": "Pro only"}},
            )
        return FakeResponse(200)

    monkeypatch.setattr(elevenlabs.requests, "post", fake_post)
    provider = elevenlabs.ElevenLabs("key", "Bob")

    _, sample_rate = provider._open_pcm_stream("Hi.", make_config(id="v1"), "v1")
    assert sample_rate == 24000

    _, sample_rate = provider._open_pcm_stream("Hi.", make_config(id="v1"), "v1")
    assert sample_rate == 24000
    assert asked == ["pcm_44100", "pcm_24000", "pcm_24000"]


def test_other_403_is_an_error(monkeypatch):
    monkeypatch.setattr(
        elevenlabs.requests,
        "post",
        lambda *a, **k: FakeResponse(
            403, {"detail": {"code": "quota_exceeded", "message": "No credits left"}}
        ),
    )
    provider = elevenlabs.ElevenLabs("key", "Bob")

    with pytest.raises(ValueError, match="No credits left"):
        provider._open_pcm_stream("Hi.", make_config(id="v1"), "v1")


def test_voice_found_by_name_across_pages(monkeypatch):
    pages = {
        None: {"voices": [{"voice_id": "a", "name": "Alice"}], "has_more": True, "next_page_token": "p2"},
        "p2": {"voices": [{"voice_id": "b", "name": "Bob"}], "has_more": False},
    }

    def fake_request(method, url, params=None, **kwargs):
        return FakeResponse(200, pages[params.get("next_page_token")])

    monkeypatch.setattr(elevenlabs.requests, "request", fake_request)
    provider = elevenlabs.ElevenLabs("key", "Bob")

    assert provider._get_voice_id(make_config(name="bob")) == "b"
    with pytest.raises(ValueError, match="not found"):
        provider._get_voice_id(make_config(name="Carol"))


def test_language_code_only_goes_to_a_model_that_lists_it(monkeypatch):
    models = [
        {"model_id": "eleven_v4", "languages": [{"language_id": "de", "name": "German"}]},
        {"model_id": "eleven_turbo_v2", "languages": [{"language_id": "en", "name": "English"}]},
    ]
    monkeypatch.setattr(
        elevenlabs.requests, "request", lambda *a, **k: FakeResponse(200, models)
    )
    provider = elevenlabs.ElevenLabs("key", "Bob")

    payload = provider._tts_payload("Hallo.", make_config(id="v1"), "de")
    assert payload["language_code"] == "de"
    assert payload["voice_settings"]["speed"] == 1.1

    payload = provider._tts_payload("Hallo.", make_config("eleven_turbo_v2", id="v1"), "de")
    assert "language_code" not in payload
    assert "style" not in payload["voice_settings"]
