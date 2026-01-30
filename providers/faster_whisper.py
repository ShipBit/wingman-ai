from os import path
import platform
import gc
from typing import Optional
from faster_whisper import WhisperModel
from api.enums import LogType
from api.interface import (
    FasterWhisperSettings,
    FasterWhisperTranscript,
    FasterWhisperSttConfig,
    WingmanInitializationError,
)
from services.printr import Printr

MODELS_DIR = "faster-whisper-models"


class FasterWhisper:
    def __init__(
        self,
        settings: FasterWhisperSettings,
        app_root_path: str,
        app_is_bundled: bool,
    ):
        self.printr = Printr()
        self.settings = settings
        self.model: Optional[WhisperModel] = None

        self.is_windows = platform.system() == "Windows"
        if self.is_windows:
            # move one dir up, out of _internal (if bundled)
            app_dir = path.dirname(app_root_path) if app_is_bundled else app_root_path
            self.models_dir = path.join(app_dir, MODELS_DIR)

        self.__update_model()

    def __unload_model(self):
        """Unload the current model to free VRAM."""
        if self.model is not None:
            self.printr.print(
                "FasterWhisper: Unloading current model to free VRAM...",
                server_only=True,
            )
            del self.model
            self.model = None

            # Force garbage collection to release memory
            gc.collect()

            # Clear CUDA cache if using GPU
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
            except ImportError:
                pass  # torch not available, skip CUDA cleanup
            except Exception as e:
                # any other CUDA-related cleanup error should not crash model reload
                self.printr.print(
                    f"FasterWhisper: CUDA cleanup failed during model unload: {e}",
                    server_only=True,
                    color=LogType.WARNING,
                )

    def __update_model(self):
        # Unload the existing model first to free VRAM
        self.__unload_model()

        if self.is_windows:
            model_file = path.join(self.models_dir, (self.settings.model_size))
            model = model_file if path.exists(model_file) else self.settings.model_size
        else:
            model_file = self.settings.model_size
            model = self.settings.model_size

        try:
            self.model = WhisperModel(
                model,
                device=self.settings.device,
                compute_type=self.settings.compute_type,
            )
            self.printr.print(
                f"FasterWhisper initialized with model '{model}' (device: '{self.settings.device}').",
                server_only=True,
                color=LogType.POSITIVE,
            )
        except Exception as e:
            self.printr.toast_error(
                f"Failed to initialize FasterWhisper with model {model_file}. Error: {e}"
            )

    def transcribe(
        self,
        config: FasterWhisperSttConfig,
        filename: str,
        hotwords: Optional[list[str]],
    ):
        try:
            segments, info = self.model.transcribe(
                filename,
                without_timestamps=True,
                beam_size=config.beam_size,
                best_of=config.best_of,
                temperature=config.temperature,
                hotwords=(
                    ", ".join(hotwords) if hotwords and len(hotwords) > 0 else None
                ),
                no_speech_threshold=config.no_speech_threshold,
                language=config.language if config.language else None,
                multilingual=False if config.language else config.multilingual,
                language_detection_threshold=(
                    None if config.language else config.language_detection_threshold
                ),
            )
            segments = list(segments)
            text = ""
            for segment in segments:
                text += segment.text.strip()

            return FasterWhisperTranscript(
                text=text,
                language=info.language,
                language_probability=info.language_probability,
            )

        except FileNotFoundError:
            self.printr.toast_error(
                f"FasterWhisper file to transcribe '{filename}' not found."
            )
        except Exception as e:
            self.printr.toast_error(f"FasterWhisper failed to transcribe. Error: {e}")

        return None

    def update_settings(self, settings: FasterWhisperSettings):
        if self.settings == settings:
            self.printr.print("FasterWhisper settings updated.", server_only=True)
            return
        self.printr.print(f"FasterWhisper settings updated, reloading model..", server_only=True)
        self.settings = settings
        self.__update_model()

    def validate(self, errors: list[WingmanInitializationError]):
        pass
