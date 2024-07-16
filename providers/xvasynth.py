import os
from os import path
import platform
import subprocess
import time
import requests
from api.enums import LogType
from api.interface import XVASynthSettings, XVASynthTtsConfig, SoundConfig
from services.audio_player import AudioPlayer
from services.file import get_writable_dir
from services.printr import Printr

RECORDING_PATH = "audio_output"
OUTPUT_FILE = "xvasynth.wav"
SYNTHESIZE_URL = "synthesize"
LOAD_MODEL_URL = "loadModel"


class XVASynth:
    def __init__(self, settings: XVASynthSettings):
        self.settings = settings
        self.running_process = None
        self.retries: int = 0
        self.current_model: str = ""
        self.printr = Printr()
        self.models_dir: str = ""
        self.server_executable_path: str = ""

        if settings.enable and self.__validate():
            self.start_server()

    async def play_audio(
        self,
        text: str,
        config: XVASynthTtsConfig,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
    ):
        if not self.settings.enable:
            self.printr.toast_error(
                text="XVASynth must be enabled and configured in the Settings view."
            )
            return
        if not self.change_voice(config):
            self.printr.toast_error(
                text=f"Unable to load XVASynth model {config.voice.model_directory}/{config.voice.voice_name}."
            )
            return

        voiceline = text

        file_path = path.join(get_writable_dir(RECORDING_PATH), OUTPUT_FILE)
        if path.exists(file_path):
            os.remove(file_path)

        # Synthesize voiceline
        data = {
            "pluginsContext": "{}",
            "modelType": "xVAPitch",
            "sequence": voiceline,
            "pace": config.pace,
            "outfile": file_path,
            "vocoder": "n/a",
            "base_lang": config.voice.language,
            "base_emb": "[]",
            "useSR": config.use_super_resolution,
            "useCleanup": config.use_cleanup,
        }
        try:
            response = requests.post(
                f"{self.settings.host}:{self.settings.port}/{SYNTHESIZE_URL}",
                json=data,
                timeout=30,
            )
            response.raise_for_status()
            audio, sample_rate = audio_player.get_audio_from_file(file_path)

            await audio_player.play_with_effects(
                input_data=(audio, sample_rate),
                config=sound_config,
                wingman_name=wingman_name,
            )
        except requests.HTTPError as e:
            self.printr.toast_error(
                text=f"Error synthesizing XVASynth voice line: \n{str(e)}"
            )

    def start_server(self):
        if not platform.system() == "Windows":
            self.printr.toast_error(text="XVASynth is only supported on Windows.")
            return False

        try:
            self.stop_server()
            self.running_process = subprocess.Popen(
                args=[self.server_executable_path], cwd=self.settings.install_dir
            )
            time.sleep(6)
            is_running = self.__is_server_running()
            if is_running:
                self.printr.print(
                    f"XVASynth server started on {self.settings.host}:{self.settings.port}.",
                    server_only=True,
                    color=LogType.HIGHLIGHT,
                )
            else:
                self.printr.toast_error(
                    text="Failed to start XVASynth server. Please start it manually."
                )
            return is_running
        except Exception:
            self.printr.toast_error(
                text="Failed to start XVASynth server. Please start it manually."
            )
            return False

    def stop_server(self):
        if self.running_process:
            self.running_process.kill()
            self.running_process.wait()
            self.running_process = None
            self.printr.print(
                "XVASynth server stopped.", server_only=True, color=LogType.HIGHLIGHT
            )

    def update_settings(self, settings: XVASynthSettings):
        requires_restart = (
            self.settings.enable != settings.enable
            or self.settings.host != settings.host
            or self.settings.port != settings.port
            or self.settings.process_device != settings.process_device
            or self.settings.install_dir != settings.install_dir
        )

        self.settings = settings

        if self.settings.enable and self.__validate():
            if requires_restart:
                self.stop_server()
                self.start_server()
        elif not self.settings.enable:
            self.stop_server()

        self.printr.print("XVASynth settings updated.", server_only=True)

    def change_voice(self, config: XVASynthTtsConfig, timeout=10):
        if (
            self.current_model
            == f"{config.voice.model_directory}/{config.voice.voice_name}"
        ):
            return True
        # example: "D:\SteamGames\steamapps\common\xVASynth\resources\app\models\masseffect\me_edi"
        voice_path = path.join(
            self.models_dir,
            config.voice.model_directory,
            config.voice.voice_name,
        )
        model_change = {
            "outputs": None,
            "version": "3.0",
            "model": voice_path,
            "modelType": "XVAPitch",
            "base_lang": config.voice.language,
            "pluginsContext": "{}",
        }
        response = requests.post(
            f"{self.settings.host}:{self.settings.port}/{LOAD_MODEL_URL}",
            json=model_change,
            timeout=timeout,
        )
        response.raise_for_status()
        self.current_model = f"{config.voice.model_directory}/{config.voice.voice_name}"
        return response.ok

    def __validate(self):
        if not path.exists(self.settings.install_dir):
            self.printr.toast_error(
                text=f"XVASynth install directory '{self.settings.install_dir}' not found."
            )
            return False

        models_dir = path.join(self.settings.install_dir, "resources", "app", "models")
        if not path.exists(models_dir):
            self.printr.toast_error(
                text=f"XVASynth model directory not found in '{models_dir}'."
            )
            return False
        else:
            self.models_dir = models_dir

        server_executable_path = path.join(
            self.settings.install_dir,
            "resources",
            "app",
            f"cpython_{self.settings.process_device}",
            "server.exe",
        )
        if not path.exists(server_executable_path):
            self.printr.toast_error(
                text=f"XVASynth server executable not found in '{server_executable_path}'."
            )
            return False
        else:
            self.server_executable_path = server_executable_path

        return True

    def __is_server_running(self, timeout=10):
        try:
            response = requests.get(
                url=f"{self.settings.host}:{self.settings.port}", timeout=timeout
            )
            return response.ok
        except Exception:
            return False
