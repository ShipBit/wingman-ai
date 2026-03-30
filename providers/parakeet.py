import platform
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


class Parakeet:
    def __init__(self, settings: ParakeetSettings):
        self.printr = Printr()
        self.settings = settings
        self.model = None
        self.is_windows = platform.system() == "Windows"

        if settings.enable and settings.run_locally:
            self.__load_model()

    def __load_model(self):
        self.__unload_model()

        try:
            import onnx_asr

            model_name = MODEL_VARIANT_MAP.get(
                self.settings.model_variant, "nemo-parakeet-tdt-0.6b-v2"
            )
            providers = EXECUTION_PROVIDER_MAP.get(
                self.settings.execution_provider, ["CPUExecutionProvider"]
            )

            self.model = onnx_asr.load_model(model_name, providers=providers)

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

    def __unload_model(self):
        if self.model is not None:
            self.printr.print(
                "Parakeet: Unloading current model...",
                server_only=True,
            )
            del self.model
            self.model = None

    def __transcribe_remote(self, filename: str) -> Optional[ParakeetTranscript]:
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
                f"Parakeet remote: Request timed out after 30s."
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

    def transcribe(
        self,
        config: ParakeetSttConfig,
        filename: str,
    ) -> Optional[ParakeetTranscript]:
        if not self.settings.run_locally:
            return self.__transcribe_remote(filename)

        if not self.model:
            self.printr.toast_error(
                "Parakeet model is not loaded. Enable Parakeet in settings first."
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

    def update_settings(self, settings: ParakeetSettings):
        old = self.settings
        self.settings = settings

        if not settings.enable:
            # Disabled — unload if needed
            if old.enable and old.run_locally:
                self.__unload_model()
            return

        if settings.run_locally:
            # Local mode — load model if switching to local or settings changed
            needs_reload = (
                not old.enable
                or not old.run_locally
                or old.model_variant != settings.model_variant
                or old.execution_provider != settings.execution_provider
            )
            if needs_reload:
                self.printr.print(
                    "Parakeet settings changed, reloading model...",
                    server_only=True,
                )
                self.__load_model()
        else:
            # Remote mode — unload local model if it was loaded
            if old.run_locally:
                self.__unload_model()
            self.printr.print(
                f"Parakeet remote mode: {settings.host}:{settings.port}",
                server_only=True,
            )

    def validate(self, errors: list[WingmanInitializationError]):
        pass
