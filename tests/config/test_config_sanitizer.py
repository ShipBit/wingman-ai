"""A config naming something that no longer exists must still load.

Every value used here was valid in a shipped version: `azure` and `azure_speech`
come from 2.1.1 and 3.1.6, `whisper` was the Wingman Pro transcription provider
until 3.2.0, and `default`/`fast` were the model aliases until
2026-09-11. All of them are gone, and a user upgrading today still has them in
their YAML.
"""

from api.enums import (
    ConversationProvider,
    TtsProvider,
    WingmanProTtsProvider,
)
from api.interface import (
    FeaturesConfig,
    NestedConfig,
    VoiceSelection,
    WingmanConfig,
    WingmanProConfig,
)
from services.config_sanitizer import sanitize


def _features(**overrides):
    data = {
        "tts_provider": "azure",
        "conversation_provider": "azure",
        "image_generation_provider": "wingman_pro",
        "condense_conversation": True,
        "compress_tool_responses": True,
        "condense_max_messages": 50,
        "condense_keep_recent_tokens": 8000,
        "skill_max_input_tokens": 16000,
    }
    data.update(overrides)
    return data


def test_azure_providers_become_loadable():
    data = _features()
    changes = sanitize(FeaturesConfig, data)

    config = FeaturesConfig(**data)
    assert config.tts_provider in TtsProvider
    assert config.conversation_provider in ConversationProvider
    assert len(changes) == 2
    assert all("azure" in line for line in changes)


def test_the_default_config_decides_the_replacement():
    """A repaired config should look like a fresh install, not like a guess."""
    data = _features()
    fallback = {"tts_provider": "pocket_tts", "conversation_provider": "wingman_pro"}

    sanitize(FeaturesConfig, data, fallback)

    assert data["tts_provider"] == "pocket_tts"
    assert data["conversation_provider"] == "wingman_pro"


def test_a_nonsense_fallback_is_not_trusted():
    data = _features()
    sanitize(FeaturesConfig, data, {"tts_provider": "also-not-a-provider"})

    assert data["tts_provider"] != "also-not-a-provider"
    FeaturesConfig(**data)


def test_wingman_pro_section_from_316():
    data = {
        "tts_provider": "azure",
        "conversation_deployment": "gpt-4o-mini",
    }
    sanitize(WingmanProConfig, data)

    config = WingmanProConfig(**data)
    assert config.tts_provider in WingmanProTtsProvider
    # The model name is free text on purpose: an unknown one gets the plan's
    # default model instead of an error.
    assert config.conversation_deployment == "gpt-4o-mini"


def test_valid_values_are_left_alone():
    data = _features(tts_provider="edge_tts", conversation_provider="openai")
    before = dict(data)

    assert sanitize(FeaturesConfig, data) == []
    assert data == before


def test_an_optional_enum_may_stay_empty():
    """None means "not set", which is a state, not damage."""
    data = {"provider": "azure", "subprovider": None, "voice": "nova"}
    changes = sanitize(VoiceSelection, data)

    assert data["subprovider"] is None
    assert data["provider"] != "azure"
    assert len(changes) == 1
    VoiceSelection(**data)


def test_a_voice_inside_a_skill_property_is_repaired_too():
    """The voice changer skill keeps its voices in a custom property, typed as a
    union of eleven things. That is where a 2.1.1 user's Azure voices survive —
    the one place a naive walk would miss."""
    data = {
        "skills": [
            {
                "name": "VoiceChanger",
                "module": "skills.voice_changer.main",
                "display_name": "Voice Changer",
                "description": {"en": "x"},
                "custom_properties": [
                    {
                        "id": "voices",
                        "name": "Voices",
                        "property_type": "voice_selection",
                        "value": [
                            {"provider": "azure", "voice": "de-DE-KatjaNeural"},
                            {"provider": "openai", "voice": "nova"},
                        ],
                    }
                ],
            }
        ]
    }
    changes = sanitize(WingmanConfig, data)

    voices = data["skills"][0]["custom_properties"][0]["value"]
    assert voices[0]["provider"] != "azure"
    assert voices[1]["provider"] == "openai"
    assert any("provider" in line for line in changes), changes


def test_it_walks_into_nested_models():
    data = {"features": _features(), "wingman_pro": {"tts_provider": "azure"}}
    changes = sanitize(NestedConfig, data)

    assert data["wingman_pro"]["tts_provider"] in {e.value for e in WingmanProTtsProvider}
    assert any("wingman_pro.tts_provider" in line for line in changes)


def test_it_never_raises_on_junk():
    """Called on every load, so it has to survive a hand-mangled file."""
    for junk in [None, [], "text", 42, {"features": "not-a-dict"}]:
        assert sanitize(NestedConfig, junk) == []


def test_a_repaired_copy_does_not_help_the_original():
    """The bug from 2026-09-11, as a test.

    `parse_config` hands the very dict from `read_default_config()` to
    `Config(**default_config)`. Sanitising a merged copy downstream logged a
    repair and left that dict untouched, so startup still died on
    `wingman_pro.tts_provider: 'openai'` — a value that was valid until the
    OpenAI voices were dropped.
    """
    original = {"wingman_pro": {"stt_provider": "cloud", "tts_provider": "openai"}}
    merged_copy = {"wingman_pro": dict(original["wingman_pro"])}

    sanitize(NestedConfig, merged_copy)

    assert merged_copy["wingman_pro"]["tts_provider"] == "inworld"
    # The original is still broken, which is why the repair has to happen where
    # the dict is read, not where a copy of it is validated.
    assert original["wingman_pro"]["tts_provider"] == "openai"

    sanitize(NestedConfig, original)
    assert original["wingman_pro"]["tts_provider"] == "inworld"
