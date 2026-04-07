from os import path
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


class FasterWhisper:
    def __init__(self, settings: FasterWhisperSettings):
        self.printr = Printr()
        self.settings = settings
        self.model: Optional[WhisperModel] = None

    def load(self, model_dir: str):
        """Load the FasterWhisper model. Called by SttProviderManager.

        Args:
            model_dir: Directory containing model files (from ModelDownloader).
        """
        self.unload()

        model_file = path.join(model_dir, self.settings.model_size)
        model = model_file if path.exists(model_file) else self.settings.model_size

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

    def unload(self):
        """Unload the current model to free VRAM. Called by SttProviderManager."""
        if self.model is not None:
            self.printr.print(
                "FasterWhisper: Unloading current model to free VRAM...",
                server_only=True,
            )
            del self.model
            self.model = None

            gc.collect()

            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
            except ImportError:
                pass
            except Exception as e:
                self.printr.print(
                    f"FasterWhisper: CUDA cleanup failed during model unload: {e}",
                    server_only=True,
                    color=LogType.WARNING,
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

    def validate(self, errors: list[WingmanInitializationError]):
        pass
