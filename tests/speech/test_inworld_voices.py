"""Inworld voices with the user's own key: gender and description, as in the
subscription's list."""

from api.enums import TtsVoiceGender
from providers.inworld import inworld_voice_gender


def test_the_gender_comes_from_the_field_first_then_from_the_description():
    neutral = {"gender": "neutral", "description": "A male voice"}
    assert inworld_voice_gender(neutral) == TtsVoiceGender.NEUTRAL
    female = {"description": "A warm, natural female voice"}
    assert inworld_voice_gender(female) == TtsVoiceGender.FEMALE
    assert inworld_voice_gender({"description": "A deep man's voice"}) == TtsVoiceGender.MALE
    assert inworld_voice_gender({"description": "A calm narrator"}) == TtsVoiceGender.UNKNOWN
    assert inworld_voice_gender({}) == TtsVoiceGender.UNKNOWN
