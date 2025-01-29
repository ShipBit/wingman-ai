from faster_whisper import WhisperModel
from api.interface import (
    FasterWhisperSettings,
    FasterWhisperTranscript,
    FasterWhisperSttConfig,
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
        filename: str,
    ):
        try:
            segments, info = self.model.transcribe(
                filename,
                without_timestamps=True,
                beam_size=config.beam_size,
                best_of=config.best_of,
                temperature=config.temperature,
                hotwords=config.hotwords,
                language=config.language,
                no_speech_threshold=config.no_speech_threshold,
                multilingual=config.multilingual,
                language_detection_threshold=config.language_detection_threshold,
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
        if self.__validate():
            self.settings = settings
            self.model = WhisperModel(
                settings.model_size,
                device=settings.device,
                compute_type=settings.compute_type,
            )
            self.printr.print("FasterWhisper settings updated.", server_only=True)

    def __validate(self):
        return True
