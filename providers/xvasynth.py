import os
from os import path
import subprocess
import time
from urllib.parse import urlparse, urlunparse
import requests
from api.enums import WingmanInitializationErrorType
from api.interface import XVASynthTtsConfig, SoundConfig, WingmanInitializationError
from services.audio_player import AudioPlayer
from services.file import get_writable_dir
from services.printr import Printr

RECORDING_PATH = "audio_output"
OUTPUT_FILE: str = "xvasynth.wav"


class XVASynth:
    def __init__(self, wingman_name: str):
        self.wingman_name = wingman_name
        self.xvasynth_path = ""
        self.process_device = ""
        self.times_checked_xvasynth = 0
        self.current_voice = ""
        self.printr = Printr()

    def validate_config(
        self, config: XVASynthTtsConfig, errors: list[WingmanInitializationError]
    ):
        if not errors:
            errors = []

        self.xvasynth_path = config.xvasynth_path
        self.process_device = config.process_device
        self.times_checked_xvasynth = 0

        # check if xvasynth is running a few times, if cannot find it, send error
        while self.times_checked_xvasynth < 5:
            is_running_error = self.__check_if_running(config.synthesize_url)
            if is_running_error == "ok":
                break
            self.times_checked_xvasynth += 1

        if is_running_error != "ok":
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman_name,
                    message=is_running_error,
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        # if xvasynth is found, load initial XVASynth voice
        else:
            model_loaded_error = self.__load_model(
                path_to_xvasynth=config.xvasynth_path,
                game_folder=config.game_folder_name,
                voice=config.voice,
                language=config.language,
                load_model_url=config.load_model_url,
            )
            if model_loaded_error != "ok":
                errors.append(
                    WingmanInitializationError(
                        wingman_name=self.wingman_name,
                        message=model_loaded_error,
                        error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                    )
                )
            self.current_voice = config.voice

        return errors

    def play_audio(
        self,
        text: str,
        config: XVASynthTtsConfig,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
    ):
        model_loaded_error = self.__load_model(
            path_to_xvasynth=config.xvasynth_path,
            game_folder=config.game_folder_name,
            voice=config.voice,
            language=config.language,
            load_model_url=config.load_model_url,
        )
        if model_loaded_error != "ok":
            self.printr.toast_error(
                text="There was a problem loading your XVASynth voice. Check your voice name and game folder for your voice in XVAsynth."
            )
        voiceline = text

        file_path = path.join(get_writable_dir(RECORDING_PATH), OUTPUT_FILE)
        if path.exists(file_path):
            os.remove(file_path)

        # Synthesize voiceline
        synthesize_url = config.synthesize_url
        data = {
            "pluginsContext": "{}",
            "modelType": "xVAPitch",
            "sequence": voiceline,
            "pace": config.pace,
            "outfile": file_path,
            "vocoder": "n/a",
            "base_lang": config.language,
            "base_emb": "[]",
            "useSR": config.use_sr,
            "useCleanup": config.use_cleanup,
        }
        response = requests.post(synthesize_url, json=data, timeout=10)
        audio, sample_rate = audio_player.get_audio_from_file(file_path)

        audio_player.stream_with_effects(
            input_data=(audio, sample_rate), config=sound_config
        )

    def __check_if_running(self, url: str):
        # get base url from synthesize url in config
        parsed_url = urlparse(url)
        base_url = urlunparse((parsed_url.scheme, parsed_url.netloc, "/", "", "", ""))
        try:
            response = requests.get(base_url, timeout=10)
            response.raise_for_status()

        except requests.RequestException:
            time.sleep(1)
            if self.times_checked_xvasynth == 1:
                # If not found, try to start xvasynth as a subprocess
                subprocess.Popen(
                    [
                        f"{self.xvasynth_path}/resources/app/cpython_{self.process_device}/server.exe"
                    ],
                    cwd=self.xvasynth_path,
                )
                time.sleep(6)
            return "XVASynth does not appear to be running. Please start XVASynth and try again, or choose another TTS provider."

        return "ok"

    def __load_model(
        self,
        path_to_xvasynth: str,
        game_folder: str,
        voice: str,
        language: str,
        load_model_url: str,
    ):
        # example: voice_path = "D:\SteamGames\steamapps\common\xVASynth\resources\app\models\masseffect\me_edi"
        voice_path = (
            f"{path_to_xvasynth}\\resources\\app\\models\\{game_folder}\\{voice}"
        )

        base_lang = language
        model_change = {
            "outputs": None,
            "version": "3.0",
            "model": voice_path,
            "modelType": "XVAPitch",
            "base_lang": base_lang,
            "pluginsContext": "{}",
        }
        try:
            response = requests.post(load_model_url, json=model_change, timeout=10)
            response.raise_for_status()
            self.current_voice = voice
            return "ok"
        except:
            return "There was an error with loading your XVASynth voice. Double check your game folder and voice path."
