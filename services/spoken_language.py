"""Everything language-specific, derived from ``settings.spoken_language``.

The user picks one language, once. The answer language, the Pocket TTS model,
the Parakeet model and the language hints sent to the cloud transcription and
to Inworld all follow from it here, so the providers can never be set to
languages that do not match. Until 3.2.4 each had its own setting, and the
default combination ("multilingual" with the English Pocket TTS model) read
German answers with an English voice.
"""

from typing import Optional

from api.enums import PocketTtsQuality, SpokenLanguage

LANGUAGE_NAMES = {
    SpokenLanguage.EN: "English",
    SpokenLanguage.DE: "German",
    SpokenLanguage.FR: "French",
    SpokenLanguage.ES: "Spanish",
    SpokenLanguage.IT: "Italian",
    SpokenLanguage.PT: "Portuguese",
}
"""The name prompts spell the language out with."""

POCKET_TTS_MODELS: dict[SpokenLanguage, dict[PocketTtsQuality, str]] = {
    # english_2026-04_24l exists since pocket-tts 3.0, but its voice-cloning
    # weights are not on our R2 mirror yet; without them no custom voice
    # could be cloned. Run scripts/mirror_pocket_tts_r2.py for it first.
    SpokenLanguage.EN: {
        PocketTtsQuality.STANDARD: "english_2026-04",
        PocketTtsQuality.HIGH: "english_2026-04",
    },
    SpokenLanguage.DE: {
        PocketTtsQuality.STANDARD: "german",
        PocketTtsQuality.HIGH: "german_24l",
    },
    # French only comes as a 24-layer model.
    SpokenLanguage.FR: {
        PocketTtsQuality.STANDARD: "french_24l",
        PocketTtsQuality.HIGH: "french_24l",
    },
    SpokenLanguage.ES: {
        PocketTtsQuality.STANDARD: "spanish",
        PocketTtsQuality.HIGH: "spanish_24l",
    },
    SpokenLanguage.IT: {
        PocketTtsQuality.STANDARD: "italian",
        PocketTtsQuality.HIGH: "italian_24l",
    },
    SpokenLanguage.PT: {
        PocketTtsQuality.STANDARD: "portuguese",
        PocketTtsQuality.HIGH: "portuguese_24l",
    },
}

POCKET_TTS_MODEL_LANGUAGES: dict[str, SpokenLanguage] = {
    model_id: language
    for language, models in POCKET_TTS_MODELS.items()
    for model_id in models.values()
}
"""Built-in Pocket TTS model ID -> the language it speaks."""

TRANSCRIPTION_TAGS = {
    SpokenLanguage.EN: "en-US",
    SpokenLanguage.DE: "de-DE",
    SpokenLanguage.FR: "fr-FR",
    SpokenLanguage.ES: "es-ES",
    SpokenLanguage.IT: "it-IT",
    SpokenLanguage.PT: "pt-BR",
}
"""BCP-47 hint for the cloud transcription. The backend passes the full tag to
Inworld and the primary subtag to OpenAI."""


def language_name(language: SpokenLanguage) -> str:
    return LANGUAGE_NAMES[language]


def pocket_tts_model(
    language: SpokenLanguage,
    quality: PocketTtsQuality,
    custom_model: Optional[str] = None,
) -> str:
    """The Pocket TTS model to load: the user's own YAML config if one is set,
    otherwise the built-in model for the language in the chosen size."""
    if custom_model:
        return custom_model
    return POCKET_TTS_MODELS[language][quality]


def pocket_tts_has_high_quality(language: SpokenLanguage) -> bool:
    """Whether HIGH loads a different model than STANDARD for this language."""
    models = POCKET_TTS_MODELS[language]
    return models[PocketTtsQuality.HIGH] != models[PocketTtsQuality.STANDARD]


def parakeet_variant(language: SpokenLanguage, chosen: str) -> str:
    """Parakeet v2 transcribes English only. Anything else needs v3, whatever
    the settings say."""
    if language != SpokenLanguage.EN and chosen == "v2":
        return "v3"
    return chosen


def transcription_tag(language: SpokenLanguage) -> str:
    return TRANSCRIPTION_TAGS[language]


def inworld_language(language: SpokenLanguage) -> str:
    """Inworld takes a BCP-47 tag and uses the voice's localized prompt for it
    when there is one. The primary subtag keeps the voice's own accent."""
    return language.value
