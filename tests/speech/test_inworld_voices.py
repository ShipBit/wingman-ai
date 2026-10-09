"""Inworld voices with the user's own key: gender and description, as in the
subscription's list."""

import asyncio

from api.enums import TtsVoiceGender
from providers import inworld
from providers.inworld import Inworld, inworld_voice_gender


def test_the_gender_comes_from_the_field_first_then_from_the_description():
    neutral = {"gender": "neutral", "description": "A male voice"}
    assert inworld_voice_gender(neutral) == TtsVoiceGender.NEUTRAL
    female = {"description": "A warm, natural female voice"}
    assert inworld_voice_gender(female) == TtsVoiceGender.FEMALE
    assert inworld_voice_gender({"description": "A deep man's voice"}) == TtsVoiceGender.MALE
    assert inworld_voice_gender({"description": "A calm narrator"}) == TtsVoiceGender.UNKNOWN
    assert inworld_voice_gender({}) == TtsVoiceGender.UNKNOWN


def test_the_voice_list_keeps_gender_and_description(monkeypatch):
    class Response:
        def json(self):
            return {
                "voices": [
                    {
                        "voiceId": "Ashley",
                        "displayName": "Ashley",
                        "description": "A warm, natural female voice",
                        "languages": ["en"],
                    },
                    {"voiceId": "custom-1", "languages": ["de"]},
                ]
            }

    monkeypatch.setattr(inworld.requests, "get", lambda *a, **kw: Response())
    voices = asyncio.run(Inworld(api_key="key", wingman_name="").get_available_voices())

    ashley, custom = voices
    assert ashley.gender == TtsVoiceGender.FEMALE
    assert ashley.description == "A warm, natural female voice"
    assert ashley.provider == "inworld"
    assert custom.name == "custom-1"
    assert custom.gender == TtsVoiceGender.UNKNOWN
    assert custom.description is None
