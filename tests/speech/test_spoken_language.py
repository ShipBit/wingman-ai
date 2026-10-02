"""One language for everything: what each provider gets from spoken_language,
and how a 3.2.3 settings.yaml is converted."""

import copy
from types import SimpleNamespace

import pytest

from api.enums import PocketTtsQuality, SpokenLanguage
from services.migrations.migration_323_to_324 import Migration323To324
from services.spoken_language import (
    inworld_language,
    pocket_tts_has_high_quality,
    pocket_tts_model,
    transcription_tag,
)


@pytest.mark.parametrize("language", [l for l in SpokenLanguage if l != SpokenLanguage.OTHER])
def test_every_language_has_a_model_and_hints(language):
    for quality in PocketTtsQuality:
        assert pocket_tts_model(language, quality)
    assert transcription_tag(language).startswith(language.value + "-")
    assert inworld_language(language) == language.value


def test_the_model_follows_the_language():
    assert pocket_tts_model(SpokenLanguage.DE, PocketTtsQuality.STANDARD) == "german"
    assert pocket_tts_model(SpokenLanguage.DE, PocketTtsQuality.HIGH) == "german_24l"
    assert pocket_tts_model(SpokenLanguage.FR, PocketTtsQuality.STANDARD) == "french"
    assert pocket_tts_model(SpokenLanguage.NL, PocketTtsQuality.HIGH) == "dutch_24l"
    assert pocket_tts_model(SpokenLanguage.EN, PocketTtsQuality.HIGH) == "english_2026-09_24l"


def test_a_custom_model_wins():
    assert pocket_tts_model(SpokenLanguage.DE, PocketTtsQuality.HIGH, "mine.yaml") == "mine.yaml"


def test_high_quality_is_only_offered_where_it_differs():
    assert pocket_tts_has_high_quality(SpokenLanguage.DE)
    assert pocket_tts_has_high_quality(SpokenLanguage.FR)
    assert pocket_tts_has_high_quality(SpokenLanguage.EN)


# ── migration ────────────────────────────────────────────────────────


def migrate(settings: dict) -> dict:
    migration = Migration323To324.__new__(Migration323To324)
    migration.log = lambda _: None
    migration.log_warning = lambda _: None
    return migration.migrate_settings(copy.deepcopy(settings))


def test_the_old_default_becomes_english_standard_unquantized():
    out = migrate({
        "spoken_language": "multilingual",
        "pocket_tts": {"enable": True, "model": "english_2026-04", "quantize": True},
        "stt": {"languages": ["en-US"], "parakeet": {"model_variant": "v3", "language": None}},
    })
    assert out["spoken_language"] == "en"
    assert out["pocket_tts"] == {
        "enable": True, "quality": "standard", "custom_model": None,
    }
    assert "languages" not in out["stt"]
    assert "language" not in out["stt"]["parakeet"]


def test_multilingual_takes_the_language_of_a_non_english_model():
    out = migrate({"spoken_language": "multilingual", "pocket_tts": {"model": "german_24l"}})
    assert out["spoken_language"] == "de"
    assert out["pocket_tts"]["quality"] == "high"


def test_an_explicit_language_is_kept():
    out = migrate({"spoken_language": "es", "pocket_tts": {"model": "english_2026-04"}})
    assert out["spoken_language"] == "es"


@pytest.mark.parametrize("variant", ["v2", "v3"])
def test_the_parakeet_variant_is_removed(variant):
    out = migrate({"spoken_language": "en", "stt": {"parakeet": {"model_variant": variant}}})
    assert "model_variant" not in out["stt"]["parakeet"]


def test_a_custom_yaml_model_is_kept():
    out = migrate({"spoken_language": "de", "pocket_tts": {"model": "czech.yaml"}})
    assert out["pocket_tts"]["custom_model"] == "czech.yaml"
    assert "model" not in out["pocket_tts"]


def test_french_is_standard_because_there_is_only_one_model():
    out = migrate({"spoken_language": "fr", "pocket_tts": {"model": "french_24l"}})
    assert out["pocket_tts"]["quality"] == "standard"


# ── Pocket TTS: a new language counts as a model switch ─────────────


def test_only_a_reload_with_another_model_counts_as_a_switch(tmp_path, monkeypatch):
    from api.interface import PocketTTSSettings
    import providers.pocket_tts as pocket

    monkeypatch.setattr(pocket, "use_r2_mirror", lambda: True)
    monkeypatch.setattr(pocket, "build_r2_config", lambda model_id, _dir: model_id)
    monkeypatch.setattr(pocket, "prefetch_gated_weights", lambda *a, **k: None)
    monkeypatch.setattr(pocket.TTSModel, "load_model", classmethod(lambda cls, **k: object()))
    monkeypatch.setattr(pocket, "get_pocket_tts_models_dir", lambda: str(tmp_path))
    monkeypatch.setattr(pocket, "get_custom_voices_dir", lambda: str(tmp_path))

    settings = PocketTTSSettings(
        enable=True, quality=PocketTtsQuality.STANDARD, host="x", port=1
    )
    provider = pocket.PocketTTS(settings, spoken_language=SpokenLanguage.EN, defer_load=True)

    provider.load_model()
    assert not provider.last_load_switched_model  # first load after start
    provider.load_model()
    assert not provider.last_load_switched_model  # same model again

    provider.spoken_language = SpokenLanguage.DE
    provider.load_model()
    assert provider.last_load_switched_model
    assert provider.model_id == "german"


def test_coreml_becomes_cpu():
    out = migrate({"spoken_language": "de", "stt": {"parakeet": {"execution_provider": "coreml"}}})
    assert out["stt"]["parakeet"]["execution_provider"] == "cpu"


def test_an_other_language_passes_its_code_and_no_transcription_hint():
    from api.interface import OtherLanguageSetting
    from services.spoken_language import language_name

    dutch = OtherLanguageSetting(code="nl", name="Nederlands", english_name="Dutch")
    assert transcription_tag(SpokenLanguage.OTHER) is None
    assert inworld_language(SpokenLanguage.OTHER, dutch) == "nl"
    assert language_name(SpokenLanguage.OTHER, dutch) == "Dutch"
    # Pocket TTS has no Dutch model; the English one stays loaded.
    assert pocket_tts_model(SpokenLanguage.OTHER, PocketTtsQuality.STANDARD) == "english_2026-09"


def _context(spoken_language, other_language=None):
    from wingmen.wingman_context import WingmanContext

    wingman = SimpleNamespace(
        settings=SimpleNamespace(spoken_language=spoken_language, other_language=other_language)
    )
    return WingmanContext(wingman), wingman


def test_skills_read_the_language_and_see_a_change():
    ctx, wingman = _context(SpokenLanguage.DE)
    assert (ctx.language.code, ctx.language.name, ctx.language.is_other) == ("de", "German", False)

    # update_settings swaps the settings object; the skill reads the new one.
    wingman.settings = SimpleNamespace(spoken_language=SpokenLanguage.FR, other_language=None)
    assert ctx.language.name == "French"


def test_skills_get_an_other_language_by_its_english_name():
    from api.interface import OtherLanguageSetting

    ctx, _ = _context(
        SpokenLanguage.OTHER, OtherLanguageSetting(code="pl", name="Polski", english_name="Polish")
    )
    assert (ctx.language.code, ctx.language.name, ctx.language.is_other) == ("pl", "Polish", True)

    ctx, _ = _context(
        SpokenLanguage.OTHER, OtherLanguageSetting(code=None, name="Elbisch", english_name="Elvish")
    )
    assert ctx.language.code is None
    assert ctx.language.name == "Elvish"
