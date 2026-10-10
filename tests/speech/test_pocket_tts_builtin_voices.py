"""Built-in PocketTTS voices are downloaded per language into custom_voices.

pocket-tts ships per-language voice-state safetensors for its predefined
voices (alba, marius, ...); embeddings from different models are mutually
incompatible. The provider downloads the file matching the *active* model as
``<voice>.<model_id>.safetensors`` into the custom voices directory and
resolves it exactly like a cloned custom voice from there on. Built-in names
must never resolve to raw audio or an untagged legacy file.
"""

import asyncio

import pytest

from api.enums import PocketTtsQuality, SpokenLanguage
from api.interface import PocketTTSSettings
from providers.pocket_tts import PocketTTS
from providers.pocket_tts_r2 import hf_uri_to_https_url


def write_voice(path, **metadata):
    """A real (tiny) voice file, stamped like Wingman stamps them."""
    import torch
    from safetensors.torch import save_file

    save_file({"transformer.layers.0.self_attn/cache": torch.zeros(1)}, str(path),
              metadata=metadata or None)


def current_clone(path):
    from providers.pocket_tts import CLONE_STAMP, PocketTTS

    write_voice(path, **{PocketTTS._CLONED_BY: CLONE_STAMP})


def make_provider(tmp_path, monkeypatch, model="german"):
    voices_dir = tmp_path / "custom_voices"
    voices_dir.mkdir(exist_ok=True)
    models_dir = tmp_path / "models"
    models_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(
        "providers.pocket_tts.get_custom_voices_dir", lambda: str(voices_dir)
    )
    monkeypatch.setattr(
        "providers.pocket_tts.get_pocket_tts_models_dir", lambda: str(models_dir)
    )
    # The model follows the spoken language; a YAML file is a custom model.
    custom = model if model.endswith(".yaml") else None
    language = {"german": SpokenLanguage.DE}.get(model, SpokenLanguage.EN)
    settings = PocketTTSSettings(
        enable=True,
        run_locally=True,
        quality=PocketTtsQuality.STANDARD,
        custom_model=custom,
        host="localhost",
        port=5002,
    )
    provider = PocketTTS(settings=settings, spoken_language=language, defer_load=True)
    return provider, voices_dir


@pytest.fixture
def recorded_downloads(monkeypatch):
    """Replace the real downloader with one that records URLs and writes a stub."""
    calls = []

    def fake_download(url, dest, log=None):
        calls.append(url)
        write_voice(dest)  # as Kyutai ships them: no Wingman metadata

    monkeypatch.setattr("providers.pocket_tts.download_url_to_path", fake_download)
    return calls


def test_hf_uri_to_https_url():
    assert hf_uri_to_https_url(
        "hf://kyutai/pocket-tts-without-voice-cloning/languages/german/embeddings/alba.safetensors@abc123"
    ) == (
        "https://huggingface.co/kyutai/pocket-tts-without-voice-cloning"
        "/resolve/abc123/languages/german/embeddings/alba.safetensors"
    )
    # No revision -> main; non-hf URIs pass through untouched.
    assert hf_uri_to_https_url("hf://kyutai/tts-voices/alba-mackenna/casual.wav") == (
        "https://huggingface.co/kyutai/tts-voices/resolve/main/alba-mackenna/casual.wav"
    )
    assert hf_uri_to_https_url("https://example.com/x.wav") == "https://example.com/x.wav"


def test_builtin_resolves_strictly_to_tagged_file(tmp_path, monkeypatch):
    provider, voices_dir = make_provider(tmp_path, monkeypatch, model="german")
    # Decoys that must all be ignored for a built-in name: raw audio, a legacy
    # untagged file, and another language's embedding.
    (voices_dir / "alba.wav").write_bytes(b"x")
    (voices_dir / "alba.safetensors").write_bytes(b"x")
    (voices_dir / "alba.english_2026-09.safetensors").write_bytes(b"x")

    resolved = provider._resolve_voice_path("alba")
    assert resolved == str(voices_dir / "alba.german.safetensors")


def test_custom_voice_resolution_unchanged(tmp_path, monkeypatch):
    provider, voices_dir = make_provider(tmp_path, monkeypatch, model="german")
    (voices_dir / "Bob.wav").write_bytes(b"x")
    assert provider._resolve_voice_path("Bob") == str(voices_dir / "Bob.wav")
    import os, time
    current_clone(voices_dir / "Bob.german.safetensors")
    later = time.time() + 10
    os.utime(voices_dir / "Bob.german.safetensors", (later, later))
    assert provider._resolve_voice_path("Bob") == str(
        voices_dir / "Bob.german.safetensors"
    )


def test_ensure_builtin_voice_downloads_per_language(
    tmp_path, monkeypatch, recorded_downloads
):
    provider, voices_dir = make_provider(tmp_path, monkeypatch, model="german")

    dest = provider._ensure_builtin_voice("alba")

    assert dest == str(voices_dir / "alba.german.safetensors")
    assert (voices_dir / "alba.german.safetensors").exists()
    assert len(recorded_downloads) == 1
    url = recorded_downloads[0]
    # Derived from the library's own pinned URI: public repo, per-language path.
    assert url.startswith(
        "https://huggingface.co/kyutai/pocket-tts-without-voice-cloning/resolve/"
    )
    assert url.endswith("/languages/german/embeddings/alba.safetensors")


def test_ensure_builtin_voice_skips_download_when_cached(
    tmp_path, monkeypatch, recorded_downloads
):
    provider, voices_dir = make_provider(tmp_path, monkeypatch, model="german")
    from pocket_tts.utils.utils import get_predefined_voice
    from providers.pocket_tts import PocketTTS

    write_voice(
        voices_dir / "alba.german.safetensors",
        **{PocketTTS._DOWNLOADED_FROM: get_predefined_voice(language="german", name="alba")},
    )

    provider._ensure_builtin_voice("alba")

    assert recorded_downloads == []


def test_a_builtin_from_another_revision_is_downloaded_again(
    tmp_path, monkeypatch, recorded_downloads
):
    """What a pocket-tts bump that moves the embeddings looks like on disk."""
    from providers.pocket_tts import PocketTTS

    provider, voices_dir = make_provider(tmp_path, monkeypatch, model="german")
    old = "hf://kyutai/pocket-tts-without-voice-cloning/languages/german/embeddings/alba.safetensors@old"
    write_voice(voices_dir / "alba.german.safetensors", **{PocketTTS._DOWNLOADED_FROM: old})

    provider._ensure_builtin_voice("alba")

    assert len(recorded_downloads) == 1
    meta = PocketTTS._voice_file_metadata(str(voices_dir / "alba.german.safetensors"))
    assert meta[PocketTTS._DOWNLOADED_FROM] != old


def test_ensure_builtin_voice_rejects_custom_model_config(
    tmp_path, monkeypatch, recorded_downloads
):
    provider, _ = make_provider(tmp_path, monkeypatch, model="my_config.yaml")

    with pytest.raises(ValueError, match="custom model"):
        provider._ensure_builtin_voice("alba")
    assert recorded_downloads == []


def test_english_uses_the_canonical_tag(tmp_path, monkeypatch):
    provider, voices_dir = make_provider(tmp_path, monkeypatch, model="english")
    assert provider._builtin_voice_cache_path("alba") == str(
        voices_dir / "alba.english_drifting_26-09.safetensors"
    )


def test_get_available_voices_hides_builtin_stems(tmp_path, monkeypatch):
    provider, voices_dir = make_provider(tmp_path, monkeypatch, model="german")
    (voices_dir / "alba.german.safetensors").write_bytes(b"x")
    (voices_dir / "Bob.german.safetensors").write_bytes(b"x")
    (voices_dir / "Carol.wav").write_bytes(b"x")

    voices = asyncio.run(provider.get_available_voices())

    builtin_ids = [v.id for v in voices if v.provider == "pocket_tts"]
    custom_ids = [v.id for v in voices if v.provider == "custom_voices"]
    assert builtin_ids.count("alba") == 1
    assert sorted(custom_ids) == ["Bob", "Carol"]


def test_preload_includes_builtin_voices(tmp_path, monkeypatch):
    provider, _ = make_provider(tmp_path, monkeypatch, model="german")
    provider.model = object()  # pretend a model is loaded
    loaded = []
    monkeypatch.setattr(provider, "get_voice_state", loaded.append)

    results = provider.preload_voice_states(["alba", "alba", "Bob", ""])

    assert loaded == ["alba", "Bob"]
    assert results == {"alba": True, "Bob": True}


def test_get_voice_state_surfaces_download_failure(tmp_path, monkeypatch):
    provider, _ = make_provider(tmp_path, monkeypatch, model="german")
    provider.model = object()
    monkeypatch.setattr(
        "providers.pocket_tts.download_url_to_path",
        lambda url, dest, log=None: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    with pytest.raises(ValueError, match="could not be downloaded"):
        provider.get_voice_state("alba")


def test_get_voice_state_redownloads_stale_builtin_file(tmp_path, monkeypatch):
    """A built-in embedding that fails to import (e.g. stale after a pocket-tts
    bump) is deleted, re-downloaded once and loaded again — without ever
    falling back to cloning from a same-named audio file."""
    provider, voices_dir = make_provider(tmp_path, monkeypatch, model="german")
    stale = voices_dir / "alba.german.safetensors"
    # Stamped with the current source, so only the failing load reveals it.
    from pocket_tts.utils.utils import get_predefined_voice
    from providers.pocket_tts import PocketTTS

    write_voice(
        stale,
        **{PocketTTS._DOWNLOADED_FROM: get_predefined_voice(language="german", name="alba")},
    )
    # Decoy: must NOT be used as a re-clone source for a built-in name.
    (voices_dir / "alba.wav").write_bytes(b"x")

    downloads = []

    def fake_download(url, dest, log=None):
        downloads.append(url)
        write_voice(dest)

    monkeypatch.setattr("providers.pocket_tts.download_url_to_path", fake_download)

    class FakeModel:
        def __init__(self):
            self.attempts = 0

        def get_state_for_audio_prompt(self, path, truncate=False):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("incompatible safetensors")
            return {"state": "ok"}

    provider.model = FakeModel()

    state = provider.get_voice_state("alba")

    assert state == {"state": "ok"}
    assert len(downloads) == 1
    # Re-downloaded and stamped with where it came from.
    assert PocketTTS._voice_file_metadata(str(stale))[PocketTTS._DOWNLOADED_FROM]
    assert provider.model.attempts == 2


def test_a_replaced_wav_makes_its_cache_stale(tmp_path, monkeypatch):
    import os, time
    provider, voices_dir = make_provider(tmp_path, monkeypatch, model="german")
    cache = voices_dir / "Joe.german.safetensors"
    wav = voices_dir / "Joe.wav"
    wav.write_bytes(b"old")
    current_clone(cache)
    old = time.time() - 100
    os.utime(wav, (old, old))
    # Fresh cache: resolved to it, nothing to precompute. (ctime of the wav is
    # "now", so push the cache after it.)
    os.utime(cache, (time.time() + 10, time.time() + 10))
    assert provider._resolve_voice_path("Joe") == str(cache)
    assert provider.list_custom_voices_needing_precompute() == []

    # The user drops in a new recording: the cache is older than it now.
    os.utime(cache, (old, old))
    wav.write_bytes(b"new")
    assert provider._resolve_voice_path("Joe") == str(wav)
    assert provider.list_custom_voices_needing_precompute() == ["Joe"]


def test_a_clone_from_another_pocket_tts_is_stale(tmp_path, monkeypatch):
    import os, time
    from providers.pocket_tts import PocketTTS

    provider, voices_dir = make_provider(tmp_path, monkeypatch, model="german")
    wav = voices_dir / "Joe.wav"
    wav.write_bytes(b"audio")
    cache = voices_dir / "Joe.german.safetensors"
    later = time.time() + 10

    for stamp in ({}, {PocketTTS._CLONED_BY: "2.1.0"}):  # before 3.2.4 / older library
        write_voice(cache, **stamp)
        os.utime(cache, (later, later))
        assert provider._resolve_voice_path("Joe") == str(wav)
        assert provider.list_custom_voices_needing_precompute(only_stale=True) == ["Joe"]

    current_clone(cache)
    os.utime(cache, (later, later))
    assert provider._resolve_voice_path("Joe") == str(cache)
    assert provider.list_custom_voices_needing_precompute() == []


def test_only_stale_skips_voices_never_cloned_for_this_model(tmp_path, monkeypatch):
    provider, voices_dir = make_provider(tmp_path, monkeypatch, model="german")
    (voices_dir / "Joe.wav").write_bytes(b"audio")
    assert provider.list_custom_voices_needing_precompute() == ["Joe"]
    assert provider.list_custom_voices_needing_precompute(only_stale=True) == []


def test_a_clone_from_before_the_word_gap_prompts_is_made_again(tmp_path):
    from providers.pocket_tts import POCKET_TTS_VERSION, PocketTTS

    path = tmp_path / "Joe.german.safetensors"
    write_voice(path, **{PocketTTS._CLONED_BY: POCKET_TTS_VERSION})
    assert not PocketTTS._clone_is_current(str(path))


def test_during_a_model_switch_nothing_is_cloned_under_the_new_name(tmp_path, monkeypatch):
    import numpy as np
    import soundfile as sf

    provider, voices_dir = make_provider(tmp_path, monkeypatch, model="german")
    wav = voices_dir / "Joe.wav"
    sf.write(str(wav), np.zeros(24000, dtype=np.float32), 24000)

    class FakeModel:
        config = type("C", (), {"mimi": type("M", (), {"sample_rate": 24000})})()

        def get_state_for_audio_prompt(self, audio, truncate=False):
            return {"state": "ok"}

    provider.model = FakeModel()
    provider._loaded_model_id = "english_2026-09"  # still loaded, settings say german
    provider._switch_pending = True

    assert provider.get_status()["is_loading"]
    assert provider._clone_from_audio_and_cache(str(wav)) == {"state": "ok"}
    assert not (voices_dir / "Joe.german.safetensors").exists()


def test_clones_of_a_model_wingman_left_are_not_voices_of_their_own(tmp_path, monkeypatch):
    provider, voices_dir = make_provider(tmp_path, monkeypatch, model="english")
    (voices_dir / "Joe.wav").write_bytes(b"x")
    (voices_dir / "Joe.english_2026-09.safetensors").write_bytes(b"x")
    (voices_dir / "Joe.english_2026-04.safetensors").write_bytes(b"x")
    assert provider._list_voice_stems(str(voices_dir)) == ["Joe"]


def test_a_voice_with_a_recording_continues_the_piece_before(tmp_path, monkeypatch):
    import numpy as np
    import soundfile as sf
    import torch

    provider, voices_dir = make_provider(tmp_path, monkeypatch, model="german")
    sf.write(str(voices_dir / "Joe.wav"), np.full(24000 * 12, 0.3, dtype=np.float32), 24000)
    prompts = []

    class FakeModel:
        sample_rate = 24000

        def get_state_for_audio_prompt(self, audio, truncate=False):
            prompts.append(audio)
            return {"continued": True}

    provider.model = FakeModel()
    voice = {"voice": True}
    previous = torch.ones(24000 * 5)

    assert provider._continued_state(voice, "Joe", previous) == {"continued": True}
    # The recording first, then the end of the piece before, as one prompt.
    assert prompts[0].shape[0] == 1 and prompts[0][0, -1] == 1
    # Kyutai's built-in voices have no recording: they start from the voice.
    assert provider._continued_state(voice, "alba", previous) is voice


def test_a_voice_without_its_recording_shows_whether_it_still_fits(tmp_path, monkeypatch):
    from api.enums import VoiceCloneState
    from providers.pocket_tts import POCKET_TTS_VERSION

    provider, voices_dir = make_provider(tmp_path, monkeypatch, model="german")
    (voices_dir / "Rec.wav").write_bytes(b"x")  # recording: Wingman clones it again
    write_voice(voices_dir / "Rec.german.safetensors")
    current_clone(voices_dir / "Fresh.german.safetensors")
    write_voice(voices_dir / "Old.german.safetensors", **{PocketTTS._CLONED_BY: POCKET_TTS_VERSION})
    write_voice(voices_dir / "Gone.english_2026-09.safetensors")

    states = {v.id: v.clone_state for v in asyncio.run(provider.get_available_voices()) if v.provider == "custom_voices"}
    assert states == {
        "Rec": VoiceCloneState.CURRENT,
        "Fresh": VoiceCloneState.CURRENT,
        "Old": VoiceCloneState.OUTDATED,
        "Gone": VoiceCloneState.MISSING,
    }
