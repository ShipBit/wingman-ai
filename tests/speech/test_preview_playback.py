import asyncio
from types import SimpleNamespace

from services.voice_service import VoiceService


def test_preview_answers_only_when_the_voice_is_done():
    """Edge plays in a thread of its own and returns at once. The client
    shows Stop until the request answers, so it must wait for the audio."""
    player = SimpleNamespace(is_playing=False)
    service = SimpleNamespace(audio_player=player)

    async def start_playing():
        player.is_playing = True

    async def run():
        preview = asyncio.create_task(
            VoiceService._run_playback(service, start_playing())
        )
        await asyncio.sleep(0.3)
        still_waiting = not preview.done()
        player.is_playing = False
        await asyncio.wait_for(preview, timeout=1)
        return still_waiting

    assert asyncio.run(run())
