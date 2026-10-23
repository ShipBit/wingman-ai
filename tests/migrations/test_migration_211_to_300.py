"""Parakeet replaced FasterWhisper in 3.0.0, and the 2.1.1 migration used to
pin its execution provider to 'cpu' for everyone. `hardware_scan_performed` is
already True for every 2.x user (2.0.0 set it for FasterWhisper), so the
boot-time scan that would have found the GPU never runs again - a user with an
RTX 3090 transcribed on the CPU forever.
"""

from unittest.mock import MagicMock

from services.migrations.migration_211_to_300 import Migration211To300


def _migration(cuda: bool, gpu_name: str | None) -> Migration211To300:
    service = MagicMock()
    service.system_manager.is_cuda_available.return_value = cuda
    service.system_manager.get_gpu_name.return_value = gpu_name
    return Migration211To300(service)


def _settings() -> dict:
    return {
        "voice_activation": {
            "stt_provider": "fasterwhisper",
            "fasterwhisper": {"device": "cuda", "model_size": "base.en"},
        }
    }


def test_gpu_machine_gets_cuda():
    out = _migration(True, "NVIDIA GeForce RTX 3090").migrate_settings(_settings())
    assert out["voice_activation"]["parakeet"]["execution_provider"] == "cuda"


def test_machine_without_gpu_gets_cpu():
    out = _migration(False, None).migrate_settings(_settings())
    assert out["voice_activation"]["parakeet"]["execution_provider"] == "cpu"


def test_existing_parakeet_block_is_corrected_too():
    """A 2.1.1 beta config can already carry a parakeet block with 'cpu' in it."""
    settings = _settings()
    settings["voice_activation"]["parakeet"] = {
        "run_locally": True,
        "model_variant": "v3",
        "execution_provider": "cpu",
        "host": "http://127.0.0.1",
        "port": 9876,
    }
    out = _migration(True, "NVIDIA GeForce RTX 3090").migrate_settings(settings)
    assert out["voice_activation"]["parakeet"]["execution_provider"] == "cuda"
    assert out["voice_activation"]["parakeet"]["port"] == 9876
