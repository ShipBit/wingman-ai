import gc
import platform
import threading
import time
from typing import Optional

import numpy as np

import requests

from api.enums import LogType
from api.interface import (
    ParakeetSettings,
    ParakeetSttConfig,
    ParakeetTranscript,
    WingmanInitializationError,
)
from services.printr import Printr


# No CoreML: on a Mac Parakeet runs on the CPU. Measured 2026-09-23 on an M2
# Pro with onnxruntime 1.22, CoreML took 219 ms per sentence against 128 ms on
# the CPU and 3 s longer to load (older versions crashed on the model's
# external data files). Configs that still say "coreml" get the CPU.
EXECUTION_PROVIDER_MAP = {
    "cpu": ["CPUExecutionProvider"],
    "directml": ["DmlExecutionProvider", "CPUExecutionProvider"],
    "cuda": ["CUDAExecutionProvider", "CPUExecutionProvider"],
}

# v3 only. v2 transcribes English alone and was only marginally better at it;
# with one spoken language per user it was a setting that could only break.
PARAKEET_MODEL = "nemo-parakeet-tdt-0.6b-v3"


class Parakeet:
    def __init__(self, settings: ParakeetSettings):
        self.printr = Printr()
        self.settings = settings
        self.model = None
        self.is_windows = platform.system() == "Windows"
        self._loading = False
        self._load_lock = threading.Lock()

    def load(self, model_path: Optional[str] = None):
        """Load the Parakeet model. Called by SttProviderManager.

        Args:
            model_path: Local directory containing model files (from ModelDownloader).
                        If None, onnx_asr downloads internally.
        """
        with self._load_lock:
            self._loading = True
            try:
                self._load_model_inner(model_path)
            finally:
                self._loading = False

    def _load_model_inner(self, model_path: Optional[str] = None):
        self.unload()

        try:
            import onnx_asr

            model_name = PARAKEET_MODEL
            providers = EXECUTION_PROVIDER_MAP.get(
                self.settings.execution_provider, ["CPUExecutionProvider"]
            )

            # Filter requested providers against what ONNX Runtime actually has
            # available, so we know up front whether CUDA will really be used.
            try:
                import onnxruntime as ort

                available = set(ort.get_available_providers())
            except Exception:
                available = None

            effective_providers = providers
            if available is not None:
                effective_providers = [p for p in providers if p in available]
                if not effective_providers:
                    effective_providers = ["CPUExecutionProvider"]

                if (
                    self.settings.execution_provider == "cuda"
                    and "CUDAExecutionProvider" not in available
                ):
                    self.printr.print(
                        "Parakeet: CUDA requested but not available in this ONNX Runtime build. "
                        "Using CPU fallback. For CUDA support, install onnxruntime-gpu.",
                        server_only=True,
                        color=LogType.WARNING,
                    )

            if "CUDAExecutionProvider" in effective_providers:
                self._preload_cuda_libraries()

            load_kwargs = {"providers": effective_providers}
            if model_path:
                load_kwargs["path"] = model_path

            self.model = onnx_asr.load_model(model_name, **load_kwargs)

            # What the sessions actually got. ONNX Runtime drops the CUDA
            # provider without raising when its libraries fail to load, so the
            # requested list alone does not say whether the GPU is used.
            running_on = self._session_providers() or effective_providers
            self.printr.print(
                f"Parakeet initialized with model '{model_name}' (providers: {running_on}).",
                server_only=True,
                color=LogType.POSITIVE,
            )
            if (
                "CUDAExecutionProvider" in effective_providers
                and "CUDAExecutionProvider" not in running_on
            ):
                self.printr.print(
                    "Parakeet: the CUDA libraries could not be loaded, running on the CPU. "
                    "The ONNX Runtime lines above name the file that failed.",
                    server_only=True,
                    color=LogType.WARNING,
                )
            self._warm_up()
        except ImportError:
            self.printr.toast_error(
                "Parakeet requires 'onnx-asr' and 'onnxruntime'. Install with: pip install onnx-asr onnxruntime"
            )
        except Exception as e:
            self.printr.toast_error(
                f"Failed to initialize Parakeet: {e}"
            )

    def _preload_cuda_libraries(self):
        """Load the bundled CUDA and cuDNN libraries before the sessions start.

        They sit in _internal/nvidia/cu13/bin/x86_64 (Windows) or
        _internal/nvidia/cu13/lib (Linux), cuDNN in nvidia/cudnn, where the
        loader does not look on its own. onnxruntime's preload_dlls() knows that
        layout; the PATH entries in main.py only help on Windows, and on Linux
        nothing found libcublas at all.
        """
        try:
            import onnxruntime as ort

            if hasattr(ort, "preload_dlls"):
                ort.preload_dlls()
        except Exception as e:
            self.printr.print(
                f"Parakeet: preloading the CUDA libraries failed: {e}",
                server_only=True,
                color=LogType.WARNING,
            )

    def _session_providers(self) -> list[str]:
        """The providers of the first ONNX Runtime session inside the model.

        onnx_asr keeps its sessions in private attributes (the encoder of the
        NeMo models is `_encoder`), so search three levels of attributes instead
        of naming one. Empty when nothing is found.
        """
        try:
            import onnxruntime as ort
        except ImportError:
            return []

        pending = [self.model]
        for _ in range(3):
            found = []
            for obj in pending:
                for value in getattr(obj, "__dict__", {}).values():
                    if isinstance(value, ort.InferenceSession):
                        return value.get_providers()
                    found.append(value)
            pending = found
        return []

    def _warm_up(self):
        """Run one recognition on a second of faint noise and throw it away.

        ONNX Runtime sets up its kernels on the first run: measured 2026-09-23
        on an M2 Pro, the first real sentence took 696 ms and every later one
        140 ms. Paid here, during loading, the user's first sentence is as fast
        as the rest. The noise stands in for speech; the encoder is where the
        time goes, and it does the same work either way.
        """
        try:
            noise = (np.random.default_rng(0).standard_normal(16000) * 0.003).astype(
                np.float32
            )
            started = time.monotonic()
            self.model.recognize(noise, sample_rate=16000)
            self.printr.print(
                f"Parakeet warmed up in {(time.monotonic() - started) * 1000:.0f} ms.",
                server_only=True,
            )
        except Exception as e:
            self.printr.print(
                f"Parakeet warm-up failed, the first sentence will be slower: {e}",
                color=LogType.WARNING,
                server_only=True,
            )

    def unload(self):
        """Unload the model and free all resources. Called by SttProviderManager."""
        if self.model is not None:
            self.printr.print(
                "Parakeet: Unloading current model...",
                server_only=True,
            )
            del self.model
            self.model = None
            gc.collect()

    def transcribe(
        self,
        config: ParakeetSttConfig,
        filename: str,
    ) -> Optional[ParakeetTranscript]:
        if not self.settings.run_locally:
            return self._transcribe_remote(filename)

        if self._loading:
            self.printr.toast_error(
                "Parakeet model is still loading. Please wait and try again."
            )
            return None

        if not self.model:
            self.printr.toast_error(
                "Parakeet model is not loaded. Check STT settings."
            )
            return None

        try:
            # No language hint: Parakeet TDT detects the language itself and
            # ignores the argument.
            text = self.model.recognize(filename)

            if isinstance(text, list):
                text = " ".join(text)

            return ParakeetTranscript(text=text.strip())

        except FileNotFoundError:
            self.printr.toast_error(
                f"Parakeet: file to transcribe '{filename}' not found."
            )
        except Exception as e:
            self.printr.toast_error(f"Parakeet failed to transcribe. Error: {e}")

        return None

    def _transcribe_remote(self, filename: str) -> Optional[ParakeetTranscript]:
        """POST audio file to remote Parakeet server for transcription."""
        host = (self.settings.host or "").strip().rstrip("/")
        if not host:
            self.printr.toast_error(
                "Parakeet runs on a server of yours, but no host is set. Enter it in Settings > Speech-to-text."
            )
            return None
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        url = f"{host}:{self.settings.port}/v1/audio/transcriptions"
        try:
            with open(filename, "rb") as f:
                response = requests.post(
                    url=url,
                    files={"file": f},
                    data={
                        "model": "parakeet",
                        "response_format": "json",
                    },
                    timeout=30,
                )
                response.raise_for_status()
                text = response.json().get("text", "").strip()
                return ParakeetTranscript(text=text)
        except requests.ConnectionError:
            self.printr.toast_error(
                f"Parakeet remote: Could not connect to {self.settings.host}:{self.settings.port}. Is the server running?"
            )
        except requests.Timeout:
            self.printr.toast_error(
                "Parakeet remote: Request timed out after 30s."
            )
        except requests.HTTPError as e:
            self.printr.toast_error(
                f"Parakeet remote: Server returned error: {e}"
            )
        except FileNotFoundError:
            self.printr.toast_error(
                f"Parakeet: File to transcribe '{filename}' not found."
            )
        except Exception as e:
            self.printr.toast_error(
                f"Parakeet remote transcription failed: {e}"
            )
        return None

    def validate(self, errors: list[WingmanInitializationError]):
        pass
