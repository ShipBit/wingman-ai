from os import path
import platform
from typing import Optional
from faster_whisper import WhisperModel
from api.enums import LogType
from api.interface import (
    FasterWhisperSettings,
    FasterWhisperTranscript,
    FasterWhisperSttConfig,
    WingmanInitializationError,
)
from providers.provider_base import (
    BaseProvider,
    ProviderCapability,
    capabilities,
    SttProvider,
)
from services.printr import Printr

MODELS_DIR = "faster-whisper-models"


@capabilities(ProviderCapability.STT)
class FasterWhisper(BaseProvider, SttProvider):
    def __init__(
        self,
        config: FasterWhisperSettings,
        api_key: str = None,  # Not used but required by BaseProvider
        app_root_path: str = None,
        app_is_bundled: bool = False,
        wingman_name: str = None,  # For hotword assembly
    ):
        BaseProvider.__init__(self, config=config, api_key=api_key)
        self.printr = Printr()
        self.settings = config  # Alias for backward compatibility
        self.wingman_name = wingman_name

        self.is_windows = platform.system() == "Windows"
        if self.is_windows:
            # move one dir up, out of _internal (if bundled)
            app_dir = path.dirname(app_root_path) if app_is_bundled else app_root_path
            self.models_dir = path.join(app_dir, MODELS_DIR)

        self.__update_model()

    def __update_model(self):
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

    # Protocol implementation: SttProvider
    async def transcribe(self, filename: str, **kwargs) -> str:
        """Transcribe audio using FasterWhisper model.

        Args:
            filename: Path to audio file
            **kwargs: May include 'config' (FasterWhisperSttConfig) and 'hotwords' (list[str])

        Returns:
            Transcribed text or None on error
        """
        # Get config from kwargs or use default from self.config
        config = kwargs.get("config", self.config if hasattr(self, "config") else None)
        if not isinstance(config, FasterWhisperSttConfig):
            # If config is FasterWhisperSettings, use default values
            config = FasterWhisperSttConfig(
                beam_size=5,
                best_of=5,
                temperature=0.0,
                no_speech_threshold=0.6,
                language=None,
                multilingual=True,
                language_detection_threshold=0.5,
                hotwords=[],
                additional_hotwords=[],
            )

        # Assemble hotwords from multiple sources
        hotwords: list[str] = []

        # Add wingman name if available
        if self.wingman_name:
            hotwords.append(self.wingman_name)

        # Add default hotwords from config
        if hasattr(self.settings, "hotwords") and self.settings.hotwords:
            hotwords.extend(self.settings.hotwords)

        # Add additional hotwords from config
        if (
            hasattr(self.settings, "additional_hotwords")
            and self.settings.additional_hotwords
        ):
            hotwords.extend(self.settings.additional_hotwords)

        # Add any hotwords passed in kwargs (for backward compatibility)
        if "hotwords" in kwargs and kwargs["hotwords"]:
            hotwords.extend(kwargs["hotwords"])

        # Remove duplicates
        hotwords = list(set(hotwords))

        result = self._transcribe_sync(
            config=config,
            filename=filename,
            hotwords=hotwords,
        )
        return result.text if result else None

    def _transcribe_sync(
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
        self.settings = settings
        self.__update_model()

    def validate(self, errors: list[WingmanInitializationError]):
        pass
