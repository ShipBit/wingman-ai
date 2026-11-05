"""The Parakeet model Core runs locally, and where it downloads it from.

Parakeet Ultra (moondream's post-trained parakeet-tdt-0.6b-v3: same architecture,
tokenizer and 25 languages) in the int8 ONNX export of Olicorne, which quantizes
only the weights (MatMulNBits, 8 bit, block 64) and computes in full precision.
Measured 2026-11-04 on 790 FLEURS and LibriSpeech clips in de, en, fr and es plus
150 under radio noise and 10 of 60-90 s, against the istupakov v3 export Core ran
before: word error rate 4.99 % instead of 6.02 % in German, 10.3 % instead of
11.7 % under radio noise, 5.2 % instead of 9.3 % on long audio, at 670 MB instead
of 2.5 GB. Its fp32 export was no more accurate. The stock dynamic int8 export of
istupakov dropped whole spans (41 % under radio noise) and must not come back.

The files sit unmodified on our R2 bucket (CC-BY-4.0 allows it, the NOTICE next
to them names the authors): one source that does not change under us, while the
upstream repo rebuilds its files in place. The revision is part of the path, so
a new revision is a new folder. ``scripts/mirror_parakeet_r2.py`` uploads them.
"""

PARAKEET_R2_BASE = "https://release.wingman-ai.com/models"

SOURCE_REPO = "Olicorne/parakeet-tdt-0.6b-v3-ultra-onnx"
REVISION = "b27f93c2238aa35e138996c005a62f1e8430f801"
QUANTIZATION = "int8"
"""onnx-asr picks `encoder-model.int8.onnx` and `decoder_joint-model.int8.onnx` by it."""

# File name in the model folder -> (path in the source repo, size in bytes, SHA256)
FILES: dict[str, tuple[str, int, str]] = {
    "encoder-model.int8.onnx": (
        "int8/encoder-model.int8.onnx",
        649431593,
        "714047d70be4b612dce02e0ab2f9e0d6552f78adc421f408d154070796bc2dcf",
    ),
    "decoder_joint-model.int8.onnx": (
        "int8/decoder_joint-model.int8.onnx",
        18203490,
        "667ffde2242a560923cba6bc7f69ef03d736f8a36ca9588f2e6f9fa818cf2fc1",
    ),
    "vocab.txt": (
        "vocab.txt",
        93939,
        "d58544679ea4bc6ac563d1f545eb7d474bd6cfa467f0a6e2c1dc1c7d37e3c35d",
    ),
    "config.json": (
        "config.json",
        97,
        "666903c76b9798caf2c210afd4f6cd60b08a8dbf9800ec8d7a3bc0d2148ac466",
    ),
}

MODEL_DIR = f"parakeet-ultra-{REVISION[:8]}"
"""The folder under models/. A new revision downloads into a new one."""

OLD_MODEL_DIR = "parakeet"
"""Where Core kept the istupakov v3 export (3.2 GB with its unused int8 files)."""


def r2_folder() -> str:
    return f"{PARAKEET_R2_BASE}/{SOURCE_REPO.lower()}/{REVISION[:8]}"


def file_url(name: str) -> str:
    return f"{r2_folder()}/{name}"
