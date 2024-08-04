from time import sleep
from os import path
import platform
import subprocess
import requests
from api.enums import LogType
from api.interface import WhispercppSettings, WhispercppSttConfig, WhispercppTranscript
from services.printr import Printr

STANDARD_DIR = "whispercpp"
CUDA_DIR = "whispercpp-cuda"
MODELS_DIR = "whispercpp-models"
SERVER_EXE = "server.exe"


class Whispercpp:
    def __init__(
        self,
        settings: WhispercppSettings,
        app_root_path: str,
        app_is_bundled: bool,
    ):
        self.settings = settings
        self.current_model = None
        self.running_process = None
        self.printr = Printr()

        self.is_windows = platform.system() == "Windows"
        if self.is_windows:
            # move one dir up, out of _internal (if bundled)
            app_dir = path.dirname(app_root_path) if app_is_bundled else app_root_path
            self.models_dir = path.join(app_dir, MODELS_DIR)
            self.standard_dir = path.join(app_dir, STANDARD_DIR)
            self.cuda_dir = path.join(app_dir, CUDA_DIR)

            if self.__validate():
                self.start_server()
        else:
            self.__validate()

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
                    language=self.settings.language,
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

    def start_server(self):
        if self.__is_server_running() or not self.is_windows:
            return True

        args = [
            path.join(
                self.cuda_dir if self.settings.use_cuda else self.standard_dir,
                SERVER_EXE,
            ),
            "-m",
            path.join(self.models_dir, self.settings.model),
            "-l",
            self.settings.language,
        ]
        if self.settings.translate_to_english:
            args.append("-tr")

        try:
            self.stop_server()
            self.running_process = subprocess.Popen(args)
            self.current_model = self.settings.model
            sleep(2)
            is_running = self.__is_server_running()
            if is_running:
                self.printr.print(
                    f"whispercpp server started on {self.settings.host}:{self.settings.port}.",
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

    def stop_server(self):
        if self.running_process:
            self.running_process.kill()
            self.running_process.wait()
            self.running_process = None
            self.printr.print(
                "whispercpp server stopped.", server_only=True, color=LogType.HIGHLIGHT
            )

    def update_settings(self, settings: WhispercppSettings):
        requires_restart = (
            self.settings.host != settings.host
            or self.settings.port != settings.port
            or self.settings.use_cuda != settings.use_cuda
            or self.settings.language != settings.language
            or self.settings.translate_to_english != settings.translate_to_english
        )
        if self.__validate():
            self.settings = settings

            if requires_restart:
                self.stop_server()
                self.start_server()
            else:
                self.change_model()

            self.printr.print("whispercpp settings updated.", server_only=True)

    def change_model(self, timeout=10):
        if not self.is_windows:
            return

        if self.current_model != self.settings.model:
            response = requests.post(
                f"{self.settings.host}:{self.settings.port}/load",
                data={"model": path.join(self.models_dir, self.settings.model)},
                timeout=timeout,
            )
            response.raise_for_status()
            self.current_model = self.settings.model

    def __validate(self):
        if not self.is_windows:
            if not self.__is_server_running():
                self.printr.print(
                    text=f"Please start whispercpp server manually on {self.settings.host}:{self.settings.port}.",
                    color=LogType.ERROR,
                    server_only=True,
                )
                return False
            return True

        # On Windows:
        model_path = path.join(self.models_dir, self.settings.model)
        if not path.exists(model_path):
            self.printr.print(
                text=f"whispercpp is missing model file '{model_path}'.",
                color=LogType.ERROR,
                server_only=True,
            )
            return False
        if not path.exists(self.cuda_dir):
            self.printr.print(
                text=f"whispercpp is missing directory '{self.cuda_dir}'.",
                color=LogType.ERROR,
                server_only=True,
            )
            return False
        if not path.exists(self.standard_dir):
            self.printr.print(
                text=f"whispercpp is missing directory '{self.standard_dir}'.",
                color=LogType.ERROR,
                server_only=True,
            )
            return False

        return True

    def __is_server_running(self, timeout=5):
        try:
            response = requests.get(
                url=f"{self.settings.host}:{self.settings.port}", timeout=timeout
            )
            return response.ok
        except Exception:
            return False
