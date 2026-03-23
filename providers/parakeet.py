import platform
from typing import Optional
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

        if settings.enable:
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

    def transcribe(
        self,
        config: ParakeetSttConfig,
        filename: str,
    ) -> Optional[ParakeetTranscript]:
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
        old_enable = self.settings.enable
        old_variant = self.settings.model_variant
        old_provider = self.settings.execution_provider
        self.settings = settings

        if settings.enable and (
            not old_enable
            or old_variant != settings.model_variant
            or old_provider != settings.execution_provider
        ):
            self.printr.print(
                "Parakeet settings changed, reloading model...",
                server_only=True,
            )
            self.__load_model()
        elif not settings.enable and old_enable:
            self.__unload_model()
        else:
            self.printr.print("Parakeet settings updated.", server_only=True)

    def validate(self, errors: list[WingmanInitializationError]):
        pass
