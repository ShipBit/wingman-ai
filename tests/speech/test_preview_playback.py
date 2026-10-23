import asyncio
from types import SimpleNamespace

from api.enums import SpokenLanguage, TtsProvider
from api.interface import PronunciationRule, PronunciationSettings
from services import speech_text
from services.voice_service import VoiceService
from tests.support import REPO_ROOT


def preview(player, playback):
    service = SimpleNamespace(audio_player=player)
    return asyncio.create_task(VoiceService._run_playback(service, playback))


def test_preview_answers_only_when_the_voice_is_done():
    """Edge plays in a thread of its own and returns at once. The client
    shows Stop until the request answers, so it must wait for the audio."""
    player = SimpleNamespace(is_playing=False, playback_count=0)

    async def start_playing():
        player.is_playing = True
        player.playback_count += 1

    async def run():
        task = preview(player, start_playing())
        await asyncio.sleep(0.3)
        still_waiting = not task.done()
        player.is_playing = False
        await asyncio.wait_for(task, timeout=1)
        return still_waiting

    assert asyncio.run(run())


def test_preview_answers_when_the_next_one_starts():
    """Clicking through the tiles: the first tile goes back to Play while
    the second one speaks."""
    player = SimpleNamespace(is_playing=False, playback_count=0)

    async def start_playing():
        player.is_playing = True
        player.playback_count += 1

    async def run():
        first = preview(player, start_playing())
        await asyncio.sleep(0.2)
        await start_playing()
        await asyncio.wait_for(first, timeout=1)

    asyncio.run(run())


def _spoken(text, as_written):
    speech_text.configure(REPO_ROOT)
    settings = SimpleNamespace(
        spoken_language=SpokenLanguage.DE,
        pronunciation=PronunciationSettings(
            rules=[PronunciationRule(written="aUEC", spoken="Alpha U E C")], presets=[]
        ),
    )
    service = SimpleNamespace(config_manager=SimpleNamespace(settings_config=settings))
    return VoiceService._spoken(service, text, TtsProvider.POCKET_TTS, as_written)


def test_a_preview_says_the_text_with_the_users_rules():
    assert _spoken("Fünf aUEC.", as_written=False) == "Fünf Alpha U E C."


def test_the_pronunciation_editor_hears_the_word_as_written():
    assert _spoken("aUEC", as_written=True) == "aUEC"
