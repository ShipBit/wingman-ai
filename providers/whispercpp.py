import requests
from api.enums import LogType, WingmanInitializationErrorType
from api.interface import (
    WhispercppSettings,
    WhispercppSttConfig,
    WhispercppTranscript,
    WingmanInitializationError,
)
from services.printr import Printr


class Whispercpp:
    def __init__(
        self,
        settings: WhispercppSettings,
    ):
        self.settings = settings
        self.printr = Printr()

    def transcribe(
        self,
        filename: str,
        config: WhispercppSttConfig,
        response_format: str = "json",
        timeout: int = 10,
    ):
        if not self.settings.enable:
            self.printr.toast_error(
                text="Whispercpp must be enabled and configured in the Settings view."
            )
            return None
        try:
            with open(filename, "rb") as file:
                response = requests.post(
                    url=f"{self.settings.host}:{self.settings.port}/inference",
                    files={"file": file},
                    data={
                        "temperature": config.temperature,
                        "response_format": response_format,
                    },
                    timeout=timeout,
                )
                response.raise_for_status()
                # Wrap response.json = {"text":"transcription"} into a Pydantic model for typesafe further processing
                return WhispercppTranscript(
                    text=response.json()["text"].strip(),
                )
        except requests.HTTPError as e:
            self.printr.toast_error(
                text=f"whispercpp transcription request failed: {e.strerror}"
            )
            return None
        except requests.Timeout:
            self.printr.toast_error(
                text=f"whispercpp transcription request timed out after {timeout}s."
            )
            return None
        except FileNotFoundError:
            self.printr.toast_error(
                f"whispercpp file to transcript'{filename}' not found."
            )

    def update_settings(self, settings: WhispercppSettings):
        self.settings = settings
        self.printr.print("whispercpp settings updated.", server_only=True)

    def validate(self, wingman_name: str, errors: list[WingmanInitializationError]):
        if not self.__is_server_running():
            errors.append(
                WingmanInitializationError(
                    wingman_name=wingman_name,
                    message=f"Please start whispercpp server manually on {self.settings.host}:{self.settings.port}, then restart Wingman AI.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        else:
            self.printr.print(
                text=f"whispercpp connected on {self.settings.host}:{self.settings.port}.",
                color=LogType.HIGHLIGHT,
                server_only=True,
            )

    def __is_server_running(self, timeout=5):
        try:
            response = requests.get(
                url=f"{self.settings.host}:{self.settings.port}", timeout=timeout
            )
            return response.ok
        except Exception:
            return False
