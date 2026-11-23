"""The cancel key stops a streamed ElevenLabs answer while its thread is
inside write(). macOS then fails that write ("cannot do in current
context", PaErrorCode -9986); the playback must end quietly, not as a
"TTS playback" error with a traceback."""

import asyncio
from types import SimpleNamespace

import pytest

from providers import elevenlabs as elevenlabs_module
from providers.elevenlabs import ElevenLabs
from services.audio_player import AudioPlayer


class FakeResponse:
    def iter_content(self, chunk_size):
        for _ in range(5):
            yield b"\x00\x00" * 512

    def close(self):
        pass


def _stream_class(on_write):
    class FakeRawOutputStream:
        def __init__(self, **kwargs):
            self.writes = 0

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

        def write(self, chunk):
            self.writes += 1
            on_write(self)

    return FakeRawOutputStream


async def _play(player: AudioPlayer, monkeypatch, on_write) -> list:
    monkeypatch.setattr(elevenlabs_module.sd, "RawOutputStream", _stream_class(on_write))
    tts = ElevenLabs("key", "Computer")
    monkeypatch.setattr(tts, "_open_pcm_stream", lambda *args: (FakeResponse(), 24000))
    finished = []
    await tts._stream_audio(
        "Hallo", None, "voice", player, "Computer", [], SimpleNamespace(volume=1.0),
        lambda: None, lambda: finished.append(True),
    )
    return finished


def test_cancel_during_a_write_ends_the_playback_quietly(monkeypatch):
    player = AudioPlayer(None, None, None)

    async def run():
        loop = asyncio.get_running_loop()

        def cancel_then_fail(stream):
            # The cancel key, on the event loop, while this write runs.
            asyncio.run_coroutine_threadsafe(player.stop_playback(), loop).result()
            raise elevenlabs_module.sd.PortAudioError("Internal PortAudio error", -9986)

        return await _play(player, monkeypatch, cancel_then_fail)

    asyncio.run(run())

    assert player.raw_stream is None
    assert not player.is_playing


def test_a_failed_write_without_a_cancel_is_still_an_error(monkeypatch):
    player = AudioPlayer(None, None, None)

    def fail(stream):
        raise elevenlabs_module.sd.PortAudioError("Internal PortAudio error", -9986)

    with pytest.raises(elevenlabs_module.sd.PortAudioError):
        asyncio.run(_play(player, monkeypatch, fail))
