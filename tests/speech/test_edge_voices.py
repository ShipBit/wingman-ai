import asyncio

from edge_tts.exceptions import NoAudioReceived

from api.enums import TtsVoiceGender
from api.interface import EdgeTtsConfig
from providers import edge as edge_module
from providers.edge import Edge, edge_voice_infos


def raw_voice(short_name, locale, gender="Female", personalities=None, categories=None):
    return {
        "ShortName": short_name,
        "Locale": locale,
        "Gender": gender,
        "VoiceTag": {
            "VoicePersonalities": personalities or ["Friendly", "Positive"],
            "ContentCategories": categories or ["General"],
        },
    }


def test_edge_voices_become_tiles_with_readable_names():
    voices = edge_voice_infos(
        [
            raw_voice("en-IE-EmilyNeural", "en-IE"),
            raw_voice("zh-CN-liaoning-XiaobeiNeural", "zh-CN-liaoning", "Male"),
        ]
    )

    assert [(v.id, v.name, v.locale) for v in voices] == [
        ("en-IE-EmilyNeural", "Emily", "en-IE"),
        ("zh-CN-liaoning-XiaobeiNeural", "Xiaobei", "zh-CN-liaoning"),
    ]
    assert voices[1].gender == TtsVoiceGender.MALE


def test_multilingual_voice_speaks_every_language_its_own_first():
    voices = edge_voice_infos(
        [
            raw_voice("en-US-AvaMultilingualNeural", "en-US"),
            raw_voice("de-DE-KatjaNeural", "de-DE"),
            raw_voice("fr-FR-DeniseNeural", "fr-FR"),
        ]
    )

    assert voices[0].name == "Ava Multilingual"
    assert voices[0].languages == ["en-US", "de", "fr"]
    assert voices[1].languages == ["de-DE"]


def test_voices_edge_tts_refuses_are_left_out():
    voices = edge_voice_infos(
        [
            raw_voice("iu-Latn-CA-SiqiniqNeural", "iu-Latn-CA"),
            raw_voice("de-DE-KatjaNeural", "de-DE"),
        ]
    )

    assert [v.id for v in voices] == ["de-DE-KatjaNeural"]


def test_a_voice_without_audio_is_reported_not_raised(monkeypatch):
    class SilentCommunicate:
        def __init__(self, **kwargs):
            pass

        async def save(self, file_path):
            raise NoAudioReceived("No audio was received.")

    toasts = []
    monkeypatch.setattr(edge_module, "Communicate", SilentCommunicate)
    monkeypatch.setattr(edge_module.printr, "toast_error", toasts.append)

    asyncio.run(
        Edge().play_audio(
            text="Hallo",
            config=EdgeTtsConfig(voice="en-US-EmmaNeural"),
            sound_config=None,
            audio_player=None,
            wingman_name="system",
        )
    )

    assert "en-US-EmmaNeural" in toasts[0]
