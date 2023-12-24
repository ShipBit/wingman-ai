import requests
import json
import os
import subprocess
import time
from api.enums import XVASynthModel
from api.interface import XVASynthTtsConfig, SoundConfig
from services.audio_player import AudioPlayer
from os import path

class XVASynth:
    def __init__(self, wingman_name: str, xvasynth_path: str, process_device: str, times_checked_xvasynth: int):
        self.wingman_name = wingman_name if wingman_name else ""
        self.xvasynth_path = ""
        self.process_device = ""
        self.times_checked_xvasynth = 0
        
    def validate_config(self, config: XVASynthTtsConfig, errors: list[str]):
        if not errors:
            errors = []

        if not config.xvasynth_path:
            errors.append(
                "Missing path to xvasynth on user's hard drive. Please provide a valid path to use xvasynth."
            )
        if not config.game_folder_name:
            errors.append(
                "Missing game folder name where xvasynth voice is located, e.g., masseffect, skyrim, etc. Please provide the game folder name to use xvasynth voice."
            )
        if not config.voice:
            errors.append(
                "Missing voice name.  Please provide voice name to use xvasynth."
            )
            
        self.xvasynth_path = config.xvasynth_path
        self.process_device = config.process_device
        self.times_checked_xvasynth = 0
        # check if xvasynth is running a few times, if cannot find it, send error
        while self.times_checked_xvasynth < 5:
            check = self.check_if_xvasynth_is_running()
            if check == "ok":
                break
            self.times_checked_xvasynth+=1
        
        if check != "ok":
            errors.append(check)
        # if xvasynth is found, load initial XVASynth voice
        else:
            loadmodel_url = XVASynthModel.LOADMODEL_URL
            # example: voice_path = "D:\\DExtraSteamGames\\steamapps\\common\\xVASynth\\resources\\app\\models\\masseffect\\me_edi"
            voice_path = config.xvasynth_path + "\\resources\\app\\models\\" + config.game_folder_name + "\\" + config.voice
            base_lang = config.language
            model_change = {
            'outputs': None,
            'version': '3.0',
            'model': voice_path, 
            'modelType': 'XVAPitch',
            'base_lang': base_lang, 
            'pluginsContext': '{}',
            }
            requests.post(loadmodel_url, json=model_change)
        return errors

    def play_audio(
        self, text: str, config: XVASynthTtsConfig, sound_config: SoundConfig
    ):
        #voice = config.voice
        voiceline = text
        file_dir = path.abspath(path.dirname(__file__))
        wingman_dir = path.abspath(path.dirname(file_dir))
        final_voiceline_file =  wingman_dir + "\\audio_output\\xvasynth.wav"

        if path.exists(final_voiceline_file):
            os.remove(final_voiceline_file)

        # Synthesize voiceline
        synthesize_url= XVASynthModel.SYNTHESIZE_URL
        data = {
            'pluginsContext': '{}',
            'modelType': 'xVAPitch',
            'sequence': voiceline,
            'pace': config.pace,
            'outfile': final_voiceline_file,
            'vocoder': 'n/a',
            'base_lang': config.language,
            'base_emb': '[]',
            'useSR': config.useSR,
            'useCleanup': config.useCleanup,
        }
        response = requests.post(synthesize_url, json=data)
        audio_player = AudioPlayer()
        audio, sample_rate = audio_player.get_audio_from_file(final_voiceline_file)
        audio_player.stream_with_effects(input_data=(audio, sample_rate), config=sound_config)

    def check_if_xvasynth_is_running(self):
        try:
            response = requests.get('http://127.0.0.1:8008/')
            response.raise_for_status()

        except requests.RequestException as e:
            time.sleep(1)
            if self.times_checked_xvasynth == 1:
                #If not found, try to start xvasynth as a subprocess
                subprocess.Popen([f'{self.xvasynth_path}/resources/app/cpython_{self.process_device}/server.exe'], cwd=self.xvasynth_path)
                time.sleep(6)
            return "ERROR: You chose XVASynth for Text to Speech but the program does not appear to be running.  Please start XVASynth and try again or choose another Text to Speech type."

        return "ok"