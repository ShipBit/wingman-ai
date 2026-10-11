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
    library_config_path,
    prefetch_urls_for_model,
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
