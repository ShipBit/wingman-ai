from faster_whisper import WhisperModel
from api.interface import (
    FasterWhisperSettings,
    FasterWhisperTranscript,
    FasterWhisperSttConfig,
    WingmanInitializationError,
)
from services.printr import Printr


class FasterWhisper:
    def __init__(
        self,
        settings: FasterWhisperSettings,
    ):
        self.settings = settings
        self.current_model = None
        self.printr = Printr()
        self.model = WhisperModel(
            settings.model_size,
            device=settings.device,
            compute_type=settings.compute_type,
        )

    def transcribe(
        self,
        config: FasterWhisperSttConfig,
        wingman_name: str,
        filename: str,
    ):
        try:
            segments, info = self.model.transcribe(
                filename,
                without_timestamps=True,
                beam_size=config.beam_size,
                best_of=config.best_of,
                temperature=config.temperature,
                hotwords=(
                    wingman_name
                    if not config.hotwords
                    else ",".join([wingman_name, config.hotwords])
                ),
                no_speech_threshold=config.no_speech_threshold,
                language=config.language,
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
                f"FasterWhisper file to transcript'{filename}' not found."
            )

    def update_settings(self, settings: FasterWhisperSettings):
        self.settings = settings
        self.model = WhisperModel(
            settings.model_size,
            device=settings.device,
            compute_type=settings.compute_type,
        )
        self.printr.print("FasterWhisper settings updated.", server_only=True)

    def validate(self, errors: list[WingmanInitializationError]):
        pass
