from api.enums import TtsVoiceGender
from providers.edge import edge_voice_infos


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


def test_description_leaves_out_the_tags_every_voice_has():
    voices = edge_voice_infos(
        [
            raw_voice("en-IE-EmilyNeural", "en-IE"),
            raw_voice(
                "en-US-AvaNeural",
                "en-US",
                personalities=["Expressive", "Caring", "Friendly"],
                categories=["Conversation", "Copilot"],
            ),
        ]
    )

    assert voices[0].description is None
    assert voices[1].description == "Expressive, Caring, Conversation"


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
