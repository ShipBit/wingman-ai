from time import sleep
from os import path
import platform
import subprocess
import requests
from api.enums import LogType, WingmanInitializationErrorType
from api.interface import (
    WhispercppSttConfig,
    WhispercppTranscript,
    WingmanInitializationError,
)
from services.printr import Printr

STANDARD_DIR = "whispercpp"
CUDA_DIR = "whispercpp-cuda"
MODELS_DIR = "whispercpp-models"
SERVER_EXE = "server.exe"


class Whispercpp:
    def __init__(self, wingman_name: str, app_root_path: str):
        self.printr = Printr()
        self.wingman_name = wingman_name
        self.current_model = None
        self.runnig_process = None

        self.is_windows = platform.system() == "Windows"
        if self.is_windows:
            # move one dir up, out of _internal (if bundled)
            app_dir = path.dirname(app_root_path)
            self.models_dir = path.join(app_dir, MODELS_DIR)
            self.standard_dir = path.join(app_dir, STANDARD_DIR)
            self.cuda_dir = path.join(app_dir, CUDA_DIR)

    def validate_config(self, config: WhispercppSttConfig):
        errors: list[WingmanInitializationError] = []

        if not self.is_windows:
            if not self.__is_server_running(config):
                errors.append(
                    WingmanInitializationError(
                        wingman_name=self.wingman_name,
                        message=f"Please start whispercpp server manually on {config.host}:{config.port}, then restart Wingman AI.",
                        error_type=WingmanInitializationErrorType.UNKNOWN,
                    )
                )
            return errors

        # On Windows:
        model_path = path.join(self.models_dir, config.model)
        if not path.exists(model_path):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman_name,
                    message=f"whispercpp is missing model file '{model_path}'.",
                    error_type=WingmanInitializationErrorType.UNKNOWN,
                )
            )
        if not path.exists(self.cuda_dir):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman_name,
                    message=f"whispercpp is missing dir '{self.cuda_dir}'.",
                    error_type=WingmanInitializationErrorType.UNKNOWN,
                )
            )
        if not path.exists(self.standard_dir):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman_name,
                    message=f"whispercpp is missing dir '{self.standard_dir}'.",
                    error_type=WingmanInitializationErrorType.UNKNOWN,
                )
            )
        # attempt to start whispercpp server
        self.start_server(config)
        return errors

    def transcribe(
        self,
        filename: str,
        config: WhispercppSttConfig,
        response_format: str = "json",
        timeout: int = 10,
    ):
        try:
            self.load_model(config)
        except requests.HTTPError as e:
            self.printr.toast_error(
                text=f"Whispercpp model loading failed: {e.strerror}"
            )
            return None

        try:
            with open(filename, "rb") as file:
                response = requests.post(
                    url=f"{config.host}:{config.port}/inference",
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
                    text=response.json()["text"].strip(), language=config.language
                )
        except requests.HTTPError as e:
            self.printr.toast_error(
                text=f"whispercpp transcription request failed: {e.strerror}"
            )
            return None
        except FileNotFoundError:
            self.printr.toast_error(
                f"whispercpp file to transcript'{filename}' not found."
            )

    def load_model(self, config: WhispercppSttConfig, timeout=10):
        if self.current_model != config.model:
            response = requests.post(
                f"{config.host}:{config.port}/load",
                data={"model": path.join(self.models_dir, config.model)},
                timeout=timeout,
            )
            response.raise_for_status()
            self.current_model = config.model

    def start_server(self, config: WhispercppSttConfig):
        if self.__is_server_running(config):
            return True

        args = [
            path.join(
                self.cuda_dir if config.use_cuda else self.standard_dir,
                SERVER_EXE,
            ),
            "-m",
            path.join(self.models_dir, config.model),
            "-l",
            config.language,
        ]
        if config.translate_to_english:
            args.append("-tr")

        try:
            self.stop_server()
            self.runnig_process = subprocess.Popen(args)
            self.current_model = config.model
            sleep(2)
            is_running = self.__is_server_running(config)
            if is_running:
                self.printr.print(
                    f"whispercpp server started on {config.host}:{config.port}.",
                    server_only=True,
                    color=LogType.HIGHLIGHT,
                )
            else:
                self.printr.toast_error(
                    text="Failed to start whispercpp server. Please start it manually."
                )
            return is_running
        except Exception:
            self.printr.toast_error(
                text="Failed to start whispercpp server. Please start it manually."
            )
            return False

    def stop_server(self) -> str:
        if self.runnig_process:
            self.runnig_process.kill()
            sleep(2)
            self.runnig_process = None
            self.printr.print(
                "whispercpp server stopped.", server_only=True, color=LogType.HIGHLIGHT
            )

    def __is_server_running(self, config: WhispercppSttConfig, timeout=5):
        response = requests.get(url=f"{config.host}:{config.port}", timeout=timeout)
        return response.ok
