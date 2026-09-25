"""Everything language-specific, derived from ``settings.spoken_language``.

The user picks one language, once. The answer language, the Pocket TTS model
and the language hints sent to the cloud transcription and to Inworld all
follow from it here, so the providers can never be set to languages that do
not match. Parakeet needs nothing: v3 detects the language itself. Until 3.2.4 each had its own setting, and the
default combination ("multilingual" with the English Pocket TTS model) read
German answers with an English voice.

With SpokenLanguage.OTHER the language is one of the rest, in
settings.other_language: no hint goes to transcription (it detects the
language), Inworld gets its code, prompts its name, and Pocket TTS keeps the
English model since it has none for it.
"""

from typing import Optional

from api.enums import PocketTtsQuality, SpokenLanguage
from api.interface import OtherLanguageSetting

LANGUAGE_NAMES = {
    SpokenLanguage.EN: "English",
    SpokenLanguage.DE: "German",
    SpokenLanguage.FR: "French",
    SpokenLanguage.ES: "Spanish",
    SpokenLanguage.IT: "Italian",
    SpokenLanguage.PT: "Portuguese",
    SpokenLanguage.NL: "Dutch",
}
"""The name prompts spell the language out with."""

POCKET_TTS_MODELS: dict[SpokenLanguage, dict[PocketTtsQuality, str]] = {
    # A model's voice-cloning weights have to be on our R2 mirror before it
    # goes in here (scripts/mirror_pocket_tts_r2.py), or no custom voice
    # could be cloned with it.
    SpokenLanguage.EN: {
        PocketTtsQuality.STANDARD: "english_2026-09",
        PocketTtsQuality.HIGH: "english_2026-09_24l",
    },
    SpokenLanguage.DE: {
        PocketTtsQuality.STANDARD: "german",
        PocketTtsQuality.HIGH: "german_24l",
    },
    SpokenLanguage.FR: {
        PocketTtsQuality.STANDARD: "french",
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
    # dutch (6L) loses parts of sentences: 13 of 36 test sentences came out
    # complete, 29 of 36 cut at their commas; dutch_24l spoke all 36
    # (6 voices, 3 sentences, 2 seeds, measured 2026-09-25).
    SpokenLanguage.NL: {
        PocketTtsQuality.STANDARD: "dutch_24l",
        PocketTtsQuality.HIGH: "dutch_24l",
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
    SpokenLanguage.NL: "nl-NL",
}
"""BCP-47 hint for the cloud transcription. The backend passes the full tag to
Inworld and the primary subtag to OpenAI."""


def language_name(
    language: SpokenLanguage, other: Optional[OtherLanguageSetting] = None
) -> str:
    """The language as prompts spell it out: "German", or for an other
    language its English name ("Dutch")."""
    if language == SpokenLanguage.OTHER:
        return other.english_name if other else "the language the user speaks"
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
    return POCKET_TTS_MODELS[_pocket_language(language)][quality]


def pocket_tts_has_high_quality(language: SpokenLanguage) -> bool:
    """Whether HIGH loads a different model than STANDARD for this language."""
    models = POCKET_TTS_MODELS[_pocket_language(language)]
    return models[PocketTtsQuality.HIGH] != models[PocketTtsQuality.STANDARD]


def _pocket_language(language: SpokenLanguage) -> SpokenLanguage:
    # Pocket TTS has no model for an other language; the English one loads,
    # and the user is told to pick a provider that speaks it.
    return SpokenLanguage.EN if language == SpokenLanguage.OTHER else language


def transcription_tag(language: SpokenLanguage) -> Optional[str]:
    """None for an other language: transcription detects it itself."""
    return TRANSCRIPTION_TAGS.get(language)


def inworld_language(
    language: SpokenLanguage, other: Optional[OtherLanguageSetting] = None
) -> Optional[str]:
    """Inworld takes a BCP-47 tag and uses the voice's localized prompt for it
    when there is one. The primary subtag keeps the voice's own accent. For an
    other language its code, None when it has none."""
    if language == SpokenLanguage.OTHER:
        return other.code if other else None
    return language.value
