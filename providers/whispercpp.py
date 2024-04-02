import os
import subprocess
import time
import requests
from api.enums import WingmanInitializationErrorType
from api.interface import (
    WhispercppSttConfig,
    WhispercppTranscript,
    WingmanInitializationError,
)
from services.printr import Printr


class Whispercpp:
    def __init__(self, wingman_name: str):
        self.wingman_name = wingman_name
        self.times_checked_whispercpp: int = 0
        self.printr = Printr()

    def validate_config(self, config: WhispercppSttConfig):
        errors: list[WingmanInitializationError] = []

        if not config.base_url:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman_name,
                    message="Missing base_url for whispercpp.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )

        if config.autostart:
            if not config.autostart_settings:
                errors.append(
                    WingmanInitializationError(
                        wingman_name=self.wingman_name,
                        message="Autostart for Whispercpp requires autostart_settings to be set.",
                        error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                    )
                )
            else:
                if not os.path.exists(config.autostart_settings.whispercpp_exe_path):
                    errors.append(
                        WingmanInitializationError(
                            wingman_name=self.wingman_name,
                            message=f"whispercpp_exe_path '{config.autostart_settings.whispercpp_exe_path}' could not be found on your system.",
                            error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                        )
                    )
                if not os.path.exists(config.autostart_settings.whispercpp_model_path):
                    errors.append(
                        WingmanInitializationError(
                            wingman_name=self.wingman_name,
                            message=f"whispercpp_model_path '{config.autostart_settings.whispercpp_model_path}' could not be found on your system.",
                            error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                        )
                    )

        # check if whispercpp is running a few times, if cannot find it, send error
        while self.times_checked_whispercpp < 5:
            is_running_error = self.__check_if_whispercpp_is_running(config=config)
            if is_running_error == "ok":
                break
            self.times_checked_whispercpp += 1

        if is_running_error != "ok":
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman_name,
                    message=is_running_error,
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )

        return errors

    def transcribe(
        self, filename: str, config: WhispercppSttConfig, response_format: str = "json"
    ):
        url = config.base_url + "/inference"
        file_path = filename
        files = {"file": open(file_path, "rb")}
        data = {
            "temperature": config.temperature,
            "response_format": response_format,
        }
        try:
            response = requests.post(url, files=files, data=data, timeout=10)
            response.raise_for_status()
            # Need to use a pydantic base model to enable openaiwingman to use same transcript.text call as it uses for openai which also uses a pydantic object, otherwise response.json would be fine here, which would return {"text":"transcription"}.
            return WhispercppTranscript(
                text=response.json()["text"].strip(), language=config.language
            )
        except requests.HTTPError as e:
            self.printr.toast_error(
                text=f"Whispercpp transcription request failed: {e.strerror}"
            )
            return None

    def __check_if_whispercpp_is_running(self, config: WhispercppSttConfig):
        try:
            response = requests.get(config.base_url, timeout=5)
            response.raise_for_status()

        except requests.RequestException:
            if self.times_checked_whispercpp == 1 and config.autostart:
                time.sleep(1)
                # If not found, try to start whispercpp as a subprocess
                subprocess.Popen(
                    [
                        config.autostart_settings.whispercpp_exe_path,
                        "-m",
                        config.autostart_settings.whispercpp_model_path,
                        "-l",
                        config.language,
                    ]
                )
                time.sleep(5)
            return "Whispercpp is not running and autostart failed."

        return "ok"

    # Currently unused but whispercpp supports loading models by functions so including for possible future dev use.
    def load_whispercpp_model(
        self, config: WhispercppSttConfig, whispercpp_model_path: str
    ):
        data = {
            "model": whispercpp_model_path,
        }
        try:
            response = requests.post(config.base_url + "/load", data=data, timeout=10)
            response.raise_for_status()
            return "ok"
        except requests.HTTPError:
            return "There was an error with loading your whispercpp model. Double check your whispercpp install and model path."
