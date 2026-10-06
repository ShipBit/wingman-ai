"""Speech through the subscription: Azure and Inworld, the plan's locks and
the allowance. The backend is faked at the HTTP layer."""

import asyncio
from types import SimpleNamespace

import pytest

import providers.wingman_subscription as ws_module
from api.enums import LogType, SpokenLanguage, TtsVoiceGender, WingmanProTtsProvider
from api.interface import AzureTtsConfig, SoundConfig
from providers.wingman_subscription import WingmanSubscription, WingmanSubscriptionTts

SOUND = SoundConfig(play_beep=False, play_beep_apollo=False, effects=[], volume=1.0)


class FakeResponse:
    def __init__(self, status=200, body=None, content=b"", headers=None, chunks=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.content = content
        self.headers = headers or {}
        self._chunks = chunks or []

    def json(self):
        return self._body

    def iter_content(self, chunk_size=2048):
        yield from self._chunks

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakePrintr:
    def __init__(self):
        self.lines = []

    def print(self, text, **kwargs):
        self.lines.append((text, kwargs.get("color")))

    async def print_async(self, text, **kwargs):
        self.lines.append((text, kwargs.get("color")))


class FakeAudioPlayer:
    def __init__(self):
        self.streamed = b""
        self.stream_args = None
        self.played = None

    async def stream_with_effects(self, buffer_callback, config, wingman_name, **kwargs):
        self.stream_args = kwargs
        while True:
            buffer = bytearray(4096)
            n = buffer_callback(buffer)
            if not n:
                break
            self.streamed += bytes(buffer[:n])

    async def play_with_effects(self, input_data, config, wingman_name, **kwargs):
        self.played = input_data


@pytest.fixture
def backend(monkeypatch):
    """Records each request and answers with the next queued response."""
    state = SimpleNamespace(requests=[], responses=[])

    def post(url, json=None, **kwargs):
        state.requests.append((url, json, kwargs))
        return state.responses.pop(0)

    def get(url, params=None, **kwargs):
        state.requests.append((url, params, kwargs))
        return state.responses.pop(0)

    monkeypatch.setattr(ws_module.requests, "post", post)
    monkeypatch.setattr(ws_module.requests, "get", get)
    monkeypatch.setattr(ws_module, "_substitution_noted", False)
    return state


def subscription():
    ws = WingmanSubscription.__new__(WingmanSubscription)
    ws.wingman_name = "Computer"
    ws.settings = SimpleNamespace(base_url="https://backend")
    ws.printr = FakePrintr()
    ws.secret_keeper = SimpleNamespace(secrets={"wingman_pro": "token"})
    ws.timeout = 5
    return ws


def azure_speech(ws, player, streaming, voice="en-US-JennyMultilingualNeural"):
    asyncio.run(
        ws.generate_azure_speech(
            text="Hello",
            config=AzureTtsConfig(voice=voice, output_streaming=streaming),
            sound_config=SOUND,
            audio_player=player,
            wingman_name="Computer",
            language="de",
        )
    )


# ── Azure ──


def test_azure_streams_raw_pcm_at_24khz(backend):
    # An odd first chunk: the 2-byte remainder is carried to the next one.
    backend.responses.append(FakeResponse(chunks=[b"\x01\x02\x03", b"\x04\x05\x06"]))
    ws, player = subscription(), FakeAudioPlayer()

    azure_speech(ws, player, streaming=True)

    url, body, _ = backend.requests[0]
    assert url == "https://backend/api/v1/audio/speech"
    assert body == {"provider": "azure", "input": "Hello", "voice_id": "en-US-JennyMultilingualNeural",
                    "stream": True, "language": "de"}
    assert player.streamed == b"\x01\x02\x03\x04\x05\x06"
    assert player.stream_args["sample_rate"] == 24000
    assert player.stream_args["channels"] == 1 and player.stream_args["dtype"] == "int16"
    assert player.stream_args["use_gain_boost"] is True


def test_azure_without_streaming_plays_the_mp3(backend):
    backend.responses.append(FakeResponse(content=b"ID3mp3"))
    ws, player = subscription(), FakeAudioPlayer()

    azure_speech(ws, player, streaming=False)

    assert backend.requests[0][1]["stream"] is False
    assert player.played == b"ID3mp3"


@pytest.mark.parametrize("streaming", [True, False])
def test_a_used_up_allowance_says_so_instead_of_failing(backend, streaming):
    backend.responses.append(
        FakeResponse(429, {"error": "quota_exceeded", "message": "Allowance used up.", "resets_at": "2026-11-01"})
    )
    ws, player = subscription(), FakeAudioPlayer()

    azure_speech(ws, player, streaming=streaming)

    assert ws.printr.lines == [("Allowance used up.", LogType.ERROR)]
    assert player.played is None and player.streamed == b""


def test_inworld_handles_the_allowance_too(backend):
    backend.responses.append(FakeResponse(429, {"message": "Allowance used up."}))
    ws, player = subscription(), FakeAudioPlayer()
    config = SimpleNamespace(voice_id="Ashley", output_streaming=False, model_id="x",
                             temperature=1.0, audio_config=None)

    asyncio.run(ws.generate_inworld_speech("Hi", config, SOUND, player, "Computer"))

    assert ws.printr.lines == [("Allowance used up.", LogType.ERROR)]


def test_inworld_always_asks_for_flash(backend):
    """The backend rejects every other Inworld model for subscriptions."""
    backend.responses.append(FakeResponse(content=b"mp3"))
    ws, player = subscription(), FakeAudioPlayer()
    config = SimpleNamespace(voice_id="Ashley", output_streaming=False, model_id="inworld-tts-2",
                             temperature=1.0, audio_config=None)

    asyncio.run(ws.generate_inworld_speech("Hi", config, SOUND, player, "Computer"))

    assert backend.requests[0][1]["model_id"] == "inworld-tts-2-flash"


def test_a_substituted_voice_is_mentioned_once(backend):
    for _ in range(2):
        backend.responses.append(
            FakeResponse(content=b"mp3", headers={"x-voice-substituted": "en-US-AndrewMultilingualNeural"})
        )
    ws, player = subscription(), FakeAudioPlayer()

    azure_speech(ws, player, streaming=False, voice="de-DE-ConradNeural")
    azure_speech(ws, player, streaming=False, voice="de-DE-ConradNeural")

    assert ws.printr.lines == [
        ("This voice needs a higher plan. Playing en-US-AndrewMultilingualNeural instead.", LogType.INFO)
    ]


# ── voice lists ──


def test_voice_lists_carry_gender_locale_and_lock(backend):
    backend.responses.append(FakeResponse(body={"voices": [
        {"voiceId": "en-US-JennyMultilingualNeural", "displayName": "Jenny Multilingual",
         "localName": "Jenny Multilingual", "locale": "en-US", "gender": "Female",
         "languages": ["en-US", "de-DE"], "locked": False},
        {"voiceId": "de-DE-ConradNeural", "displayName": "Conrad", "localName": "Conrad",
         "locale": "de-DE", "gender": "Male", "languages": ["de-DE"], "locked": True},
    ]}))
    backend.responses.append(FakeResponse(body={"voices": [
        {"voiceId": "Ashley", "displayName": "Ashley", "locale": "", "gender": "Robot", "languages": ["en"]},
    ]}))
    ws = subscription()

    azure = ws.get_available_azure_voices("de")
    inworld = ws.get_available_inworld_voices()

    assert backend.requests[0][1] == {"provider": "azure", "language": "de"}
    assert [(v.id, v.gender, v.locale, v.locked) for v in azure] == [
        ("en-US-JennyMultilingualNeural", TtsVoiceGender.FEMALE, "en-US", False),
        ("de-DE-ConradNeural", TtsVoiceGender.MALE, "de-DE", True),
    ]
    assert azure[0].languages == ["en-US", "de-DE"]
    # An unknown gender and a missing lock are tolerated.
    assert (inworld[0].gender, inworld[0].locale, inworld[0].locked) == (TtsVoiceGender.UNKNOWN, None, False)


def test_tts_models_come_from_the_models_answer():
    body = {"plan": "free", "tts": {"default": "azure-neural", "models": [
        {"id": "azure-neural", "name": "Azure Neural", "provider": "azure", "available": True, "usage_factor": 3},
        {"id": "inworld-tts-2-flash", "name": "Inworld", "provider": "inworld", "available": False, "usage_factor": 1},
    ]}}
    models = ws_module.tts_models_from(body)
    assert models.default == "azure-neural"
    assert [(m.provider, m.available, m.usage_factor) for m in models.models] == [
        ("azure", True, 3), ("inworld", False, 1),
    ]
    assert ws_module.tts_models_from({"models": []}).models == []


# ── which provider speaks ──


@pytest.mark.parametrize("subprovider,called", [
    (WingmanProTtsProvider.AZURE, "azure"),
    (WingmanProTtsProvider.INWORLD, "inworld"),
])
def test_play_audio_dispatches_on_the_voice_provider(subprovider, called):
    calls = []

    class FakeWs:
        async def generate_azure_speech(self, **kwargs):
            calls.append(("azure", kwargs["config"]))

        async def generate_inworld_speech(self, **kwargs):
            calls.append(("inworld", kwargs["config"]))

    azure = AzureTtsConfig(voice="en-US-JennyMultilingualNeural", output_streaming=True)
    inworld = SimpleNamespace(voice_id="Ashley")
    config = SimpleNamespace(wingman_pro=SimpleNamespace(tts_provider=subprovider, azure=azure), inworld=inworld)
    settings = SimpleNamespace(spoken_language=SpokenLanguage.DE, other_language=None)

    tts = WingmanSubscriptionTts(FakeWs(), config, settings)
    asyncio.run(tts.play_audio("Hi", SOUND, None, "Computer"))

    assert calls == [(called, azure if called == "azure" else inworld)]
