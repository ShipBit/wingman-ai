"""Standalone test for the ctx.tts voice mapping (apply_voice_to_current_provider).

Run: PYTHONPATH=. venv/bin/python tests/test_skill_tts.py
Expected last line: ALL OK

Uses lightweight fake config objects so we test the field-mapping logic without the
real provider stack (TTS rebuild is exercised at runtime/boot, not here).
"""

from types import SimpleNamespace

from api.enums import TtsProvider, WingmanProTtsProvider
from wingmen.facade import apply_voice_to_current_provider


def make_config(provider, wp_sub=None):
    """A fake config exposing only the fields the mapping touches."""
    return SimpleNamespace(
        features=SimpleNamespace(tts_provider=provider),
        wingman_pro=SimpleNamespace(tts_provider=wp_sub),
        openai=SimpleNamespace(tts_voice=None),
        azure=SimpleNamespace(tts=SimpleNamespace(voice=None)),
        elevenlabs=SimpleNamespace(voice=None, output_streaming=True),
        xvasynth=SimpleNamespace(voice=None),
        edge_tts=SimpleNamespace(voice=None),
        hume=SimpleNamespace(voice=None),
        inworld=SimpleNamespace(voice_id=None, output_streaming=True),
        pocket_tts=SimpleNamespace(voice=None, output_streaming=True),
        openai_compatible_tts=SimpleNamespace(voice=None, output_streaming=True),
    )


def main():
    # OpenAI: voice with .value (enum-like) -> openai.tts_voice, name from .value
    cfg = make_config(TtsProvider.OPENAI)
    enum_voice = SimpleNamespace(value="nova")
    name, label = apply_voice_to_current_provider(cfg, enum_voice)
    assert cfg.openai.tts_voice is enum_voice, "openai field not set"
    assert name == "nova" and label == "OpenAI", (name, label)

    # ElevenLabs: object voice (.name) -> elevenlabs.voice, streaming forced off
    cfg = make_config(TtsProvider.ELEVENLABS)
    el_voice = SimpleNamespace(name="Rachel", id="abc")
    name, label = apply_voice_to_current_provider(cfg, el_voice)
    assert cfg.elevenlabs.voice is el_voice
    assert cfg.elevenlabs.output_streaming is False, "streaming must be forced off"
    assert name == "Rachel" and label == "Elevenlabs"

    # ElevenLabs fallback to .id when no name
    cfg = make_config(TtsProvider.ELEVENLABS)
    name, _ = apply_voice_to_current_provider(cfg, SimpleNamespace(name=None, id="xyz"))
    assert name == "xyz", name

    # Azure: nested azure.tts.voice
    cfg = make_config(TtsProvider.AZURE)
    name, label = apply_voice_to_current_provider(cfg, "en-US-JennyNeural")
    assert cfg.azure.tts.voice == "en-US-JennyNeural"
    assert label == "Azure TTS"

    # XVASynth: name from .voice_name
    cfg = make_config(TtsProvider.XVASYNTH)
    name, label = apply_voice_to_current_provider(cfg, SimpleNamespace(voice_name="Ada"))
    assert cfg.xvasynth.voice.voice_name == "Ada"
    assert name == "Ada" and label == "XVASynth"

    # Edge / Hume: plain string voices
    cfg = make_config(TtsProvider.EDGE_TTS)
    _, label = apply_voice_to_current_provider(cfg, "en-GB-RyanNeural")
    assert cfg.edge_tts.voice == "en-GB-RyanNeural" and label == "Edge TTS"

    cfg = make_config(TtsProvider.HUME)
    _, label = apply_voice_to_current_provider(cfg, "voice-id-1")
    assert cfg.hume.voice == "voice-id-1" and label == "Hume"

    # Inworld / PocketTTS / OpenAI-compatible: voice_id/voice + streaming off
    cfg = make_config(TtsProvider.INWORLD)
    apply_voice_to_current_provider(cfg, "Ashley")
    assert cfg.inworld.voice_id == "Ashley" and cfg.inworld.output_streaming is False

    cfg = make_config(TtsProvider.POCKET_TTS)
    apply_voice_to_current_provider(cfg, "pck")
    assert cfg.pocket_tts.voice == "pck" and cfg.pocket_tts.output_streaming is False

    cfg = make_config(TtsProvider.OPENAI_COMPATIBLE)
    apply_voice_to_current_provider(cfg, "v")
    assert cfg.openai_compatible_tts.voice == "v" and cfg.openai_compatible_tts.output_streaming is False

    # Wingman Pro subproviders route to the right underlying field (Azure/Inworld only)
    cfg = make_config(TtsProvider.WINGMAN_PRO, WingmanProTtsProvider.AZURE)
    _, label = apply_voice_to_current_provider(cfg, "az")
    assert cfg.azure.tts.voice == "az" and label == "Wingman Pro / Azure TTS"

    cfg = make_config(TtsProvider.WINGMAN_PRO, WingmanProTtsProvider.INWORLD)
    _, label = apply_voice_to_current_provider(cfg, "iw")
    assert cfg.inworld.voice_id == "iw" and cfg.inworld.output_streaming is False
    assert label == "Wingman Pro / Inworld"

    test_tts_speak_and_voice()

    print("ALL OK")


def test_tts_speak_and_voice():
    """SkillTts.speak() flips interrupt->no_interrupt and delegates to play_to_user;
    voice/voices are present. Build a tiny fake wingman inline (this file has no helper)."""
    import asyncio
    from wingmen.facade import SkillTts

    # voice reads config.features.tts_provider + per-provider fields; use OpenAI here.
    config = SimpleNamespace(
        features=SimpleNamespace(tts_provider=TtsProvider.OPENAI),
        openai=SimpleNamespace(tts_voice="nova"),
    )

    class _FakeWingman:
        pass

    w = _FakeWingman()
    w.config = config

    spoken = {}

    async def _p2u(text, no_interrupt=False, sound_config=None):
        spoken["text"], spoken["no_interrupt"] = text, no_interrupt

    w.play_to_user = _p2u
    tts = SkillTts(w)

    asyncio.get_event_loop().run_until_complete(tts.speak("hello", interrupt=False))
    assert spoken["text"] == "hello" and spoken["no_interrupt"] is True, spoken

    # voice reads the configured OpenAI voice; voices() is a coroutine method.
    assert tts.voice == "nova", tts.voice
    assert hasattr(tts, "voices") and hasattr(type(tts), "voice")
    print("PASS: tts speak (interrupt->no_interrupt) + voice/voices present")


if __name__ == "__main__":
    main()
