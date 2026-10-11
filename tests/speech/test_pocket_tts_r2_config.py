"""The Pocket TTS config Wingman writes for a built-in model loads on Windows.

pocket_tts opens a config without an encoding, which is cp1252 on Windows,
and the German config has typographic quotes. It also downloaded the tokenizer
through the HuggingFace cache, whose symlinks Windows 11 refuses to follow
from some processes. Both stopped Pocket TTS on a fresh German install.
"""

import pytest
import yaml

from providers.pocket_tts_r2 import (
    build_r2_config,
    is_gated_uri,
    library_config_path,
    prefetch_urls_for_model,
    resolve_uri,
    rewrite_config_text,
)
from services.spoken_language import POCKET_TTS_MODEL_LANGUAGES

MODELS = sorted(POCKET_TTS_MODEL_LANGUAGES)


@pytest.mark.parametrize("model_id", MODELS)
def test_the_written_config_reads_the_same_in_cp1252(tmp_path, model_id):
    written = build_r2_config(model_id, str(tmp_path))

    with open(written, encoding="cp1252") as f:
        as_windows_reads_it = yaml.safe_load(f)
    original = library_config_path(model_id).read_text(encoding="utf-8")

    assert as_windows_reads_it == yaml.safe_load(rewrite_config_text(original))
    assert "hf://" not in open(written, encoding="ascii").read()


def test_german_needs_the_r2_weights_and_the_tokenizer_from_huggingface():
    urls = prefetch_urls_for_model("german")

    assert any(u.startswith("https://release.wingman-ai.com/") for u in urls)
    assert any(
        u.startswith("https://huggingface.co/") and u.endswith("tokenizer.json")
        for u in urls
    )
    # The non-cloning weights are only the fallback; the library fetches them.
    assert not any("without-voice-cloning" in u and u.endswith(".safetensors") for u in urls)


def test_offline_after_the_update_the_tokenizer_comes_from_the_hf_cache(tmp_path, monkeypatch):
    """Up to 3.2.8 the tokenizer was in the HuggingFace cache. An existing user
    starting offline has the weights in our cache but not the tokenizer under
    its new URL, and would lose Pocket TTS."""
    import huggingface_hub

    import providers.pocket_tts_r2 as r2

    cache = tmp_path / "pocket_tts"
    cache.mkdir()
    monkeypatch.setattr("pocket_tts.utils.utils.make_cache_directory", lambda: cache)
    for uri in r2._prefetch_uris("german"):
        if is_gated_uri(uri):
            r2._library_cache_path(resolve_uri(uri)).write_bytes(b"weights")
    in_hf_cache = tmp_path / "tokenizer.json"
    in_hf_cache.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        huggingface_hub, "try_to_load_from_cache", lambda *a, **k: str(in_hf_cache)
    )

    def offline(*args, **kwargs):
        raise AssertionError("no network")

    monkeypatch.setattr(r2, "_download_to_cache", offline)

    r2.prefetch_model_files("german")

    tokenizer = next(u for u in prefetch_urls_for_model("german") if u.endswith("tokenizer.json"))
    assert r2._library_cache_path(tokenizer).read_text(encoding="utf-8") == "{}"
