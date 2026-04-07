import gc
import platform
import threading
from typing import Optional

import requests

from api.enums import LogType
from api.interface import (
    ParakeetSettings,
    ParakeetSttConfig,
    ParakeetTranscript,
    WingmanInitializationError,
)
from services.printr import Printr


EXECUTION_PROVIDER_MAP = {
    "cpu": ["CPUExecutionProvider"],
    "directml": ["DmlExecutionProvider", "CPUExecutionProvider"],
    "coreml": ["CoreMLExecutionProvider", "CPUExecutionProvider"],
    "cuda": ["CUDAExecutionProvider", "CPUExecutionProvider"],
}

MODEL_VARIANT_MAP = {
    "v2": "nemo-parakeet-tdt-0.6b-v2",
    "v3": "nemo-parakeet-tdt-0.6b-v3",
}

# CoreML is excluded for TDT models — they use external data files that CoreML can't handle
COREML_EXCLUDED_PROVIDERS = ["CoreMLExecutionProvider"]


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

            model_name = MODEL_VARIANT_MAP.get(
                self.settings.model_variant, "nemo-parakeet-tdt-0.6b-v3"
            )
            providers = EXECUTION_PROVIDER_MAP.get(
                self.settings.execution_provider, ["CPUExecutionProvider"]
            )

            # Exclude CoreML for TDT models — crashes with external data files
            providers = [
                p for p in providers if p not in COREML_EXCLUDED_PROVIDERS
            ]
            if not providers:
                providers = ["CPUExecutionProvider"]

            load_kwargs = {"providers": providers}
            if model_path:
                load_kwargs["path"] = model_path

            self.model = onnx_asr.load_model(model_name, **load_kwargs)

            # Check if requested CUDA provider was actually available
            if self.settings.execution_provider == "cuda":
                try:
                    import onnxruntime as ort

                    available = ort.get_available_providers()
                    if "CUDAExecutionProvider" not in available:
                        self.printr.print(
                            "Parakeet: CUDA requested but not available in this ONNX Runtime build. "
                            "Using CPU fallback. For CUDA support, install onnxruntime-gpu.",
                            server_only=True,
                            color=LogType.WARNING,
                        )
                except Exception:
                    pass

            self.printr.print(
                f"Parakeet initialized with model '{model_name}' (providers: {providers}).",
                server_only=True,
                color=LogType.POSITIVE,
            )
        except ImportError:
            self.printr.toast_error(
                "Parakeet requires 'onnx-asr' and 'onnxruntime'. Install with: pip install onnx-asr onnxruntime"
            )
        except Exception as e:
            self.printr.toast_error(
                f"Failed to initialize Parakeet: {e}"
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
        host = (self.settings.host or "localhost").strip().rstrip("/")
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
