"""Unloading the PocketTTS model while a line is being synthesized.

The settings reload, "stop" in the client and disabling Pocket TTS all unload
the model. Generation reads it the whole time, so the unload waits for it, and
a line that starts after the unload is told, not reported as a bug.
"""

import asyncio
import threading
from types import SimpleNamespace

from api.enums import LogType, PocketTtsQuality, SpokenLanguage
from api.interface import PocketTTSConfig, PocketTTSSettings, SoundConfig
from providers.pocket_tts import PocketTTS

SOUND = SoundConfig(play_beep=False, play_beep_apollo=False, effects=[], volume=1.0)


def make_provider(tmp_path, monkeypatch):
    monkeypatch.setattr("providers.pocket_tts.get_custom_voices_dir", lambda: str(tmp_path))
    monkeypatch.setattr("providers.pocket_tts.get_pocket_tts_models_dir", lambda: str(tmp_path))
    settings = PocketTTSSettings(
        enable=True,
        run_locally=True,
        quality=PocketTtsQuality.STANDARD,
        custom_model=None,
        host="localhost",
        port=5002,
    )
    provider = PocketTTS(settings=settings, spoken_language=SpokenLanguage.EN, defer_load=True)
    lines = []
    provider.printr = SimpleNamespace(
        print=lambda text, color=None, **kw: lines.append((text, color)),
        toast_error=lambda text: lines.append((text, "toast_error")),
    )
    return provider, lines


def test_unload_waits_for_the_line_being_synthesized(tmp_path, monkeypatch):
    provider, _ = make_provider(tmp_path, monkeypatch)
    provider.model = object()
    generating, done = threading.Event(), threading.Event()

    def generate():
        with provider._model_swap_lock:
            generating.set()
            done.wait(timeout=5)
            # Still there for the whole line.
            assert provider.model is not None

    generator = threading.Thread(target=generate)
    generator.start()
    generating.wait(timeout=5)
    unloader = threading.Thread(target=provider.unload_model)
    unloader.start()
    unloader.join(timeout=0.2)

    assert unloader.is_alive()
    assert provider.model is not None

    done.set()
    generator.join(timeout=5)
    unloader.join(timeout=5)
    assert provider.model is None


def test_the_reload_can_unload_while_it_holds_the_lock(tmp_path, monkeypatch):
    provider, _ = make_provider(tmp_path, monkeypatch)
    provider.model = object()

    with provider._model_swap_lock:
        provider.unload_model()

    assert provider.model is None


def test_a_line_after_the_model_was_unloaded_is_told_not_reported(tmp_path, monkeypatch):
    provider, lines = make_provider(tmp_path, monkeypatch)
    provider.model = object()

    def voice_state_then_unload(voice_id):
        provider.model = None  # unloaded right after the line started
        return {}

    monkeypatch.setattr(provider, "get_voice_state", voice_state_then_unload)

    for streaming in (False, True):
        lines.clear()
        provider.model = object()
        asyncio.run(
            provider.play_audio(
                text="Hello there.",
                config=PocketTTSConfig(voice="alba", output_streaming=streaming, speed=1.0),
                sound_config=SOUND,
                audio_player=None,
                wingman_name="Computer",
            )
        )

        assert ("Computer: PocketTTS model is not loaded.", "toast_error") in lines
        assert not [line for line in lines if line[1] == LogType.ERROR]
