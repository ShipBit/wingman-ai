import requests
from api.enums import LogType
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
        except requests.ConnectionError as e:
            self.printr.toast_error(
                text=f"whispercpp connection failed: Could not connect to {self.settings.host}:{self.settings.port}. Is the server running?"
            )
            return None
        except FileNotFoundError:
            self.printr.toast_error(
                f"whispercpp file to transcribe '{filename}' not found."
            )
            return None
        except Exception as e:
            self.printr.toast_error(text=f"whispercpp transcription failed: {str(e)}")
            return None

    def update_settings(self, settings: WhispercppSettings):
        self.settings = settings
        self.printr.print("whispercpp settings updated.", server_only=True)

    def validate(self, wingman_name: str, errors: list[WingmanInitializationError]):
        if not self.__is_server_running():
            # Log a warning but don't block - server might be started later
            self.printr.print(
                text=f"whispercpp server not reachable on {self.settings.host}:{self.settings.port}. Make sure to start it with '--host 0.0.0.0' as param before using voice commands.",
                color=LogType.WARNING,
                server_only=True,
            )
        else:
            self.printr.print(
                text=f"whispercpp connected on {self.settings.host}:{self.settings.port}.",
                color=LogType.STARTUP,
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
