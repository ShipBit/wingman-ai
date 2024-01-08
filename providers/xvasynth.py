import requests
import json
import os
import subprocess
import time
from api.enums import WingmanInitializationErrorType
from api.interface import XVASynthTtsConfig, SoundConfig, WingmanInitializationError
from services.audio_player import AudioPlayer
from os import path
from urllib.parse import urlparse, urlunparse
from concurrent.futures import ThreadPoolExecutor

class XVASynth:
    def __init__(self, wingman_name: str, xvasynth_path: str, process_device: str, times_checked_xvasynth: int):
        self.wingman_name = wingman_name if wingman_name else ""
        self.xvasynth_path = ""
        self.process_device = ""
        self.times_checked_xvasynth = 0
        self.current_voice = ""
        
    def validate_config(self, config: XVASynthTtsConfig, errors: list[WingmanInitializationError]):
        if not errors:
            errors = []

        if not config.xvasynth_path:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman_name,
                    message="Missing path to xvasynth on user's hard drive. Please provide a valid path to use xvasynth.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        if not config.game_folder_name:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman_name,
                    message="Missing game folder name where xvasynth voice is located, e.g., masseffect, skyrim, etc. Please provide the game folder name to use xvasynth voice.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        if not config.voice:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman_name,
                    message="Missing voice name.  Please provide voice name to use xvasynth.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
            
        self.xvasynth_path = config.xvasynth_path
        self.process_device = config.process_device
        self.times_checked_xvasynth = 0
        # check if xvasynth is running a few times, if cannot find it, send error
        while self.times_checked_xvasynth < 5:
            check = self.check_if_xvasynth_is_running(config.synthesize_url)
            if check == "ok":
                break
            self.times_checked_xvasynth+=1
        
        if check != "ok":
            errors.append(WingmanInitializationError(
                    wingman_name=self.wingman_name,
                    message=check,
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                ))
        # if xvasynth is found, load initial XVASynth voice
        else:
            load_ok = self.load_xvasynth_model(path_to_xvasynth=config.xvasynth_path, game_folder=config.game_folder_name, voice=config.voice, language=config.language, load_model_url=config.load_model_url)
            if load_ok != "ok":
                errors.append(WingmanInitializationError(
                    wingman_name=self.wingman_name,
                    message=load_ok,
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                ))
            self.current_voice = config.voice

        return errors

    def play_audio(self, text: str, config: XVASynthTtsConfig, sound_config: SoundConfig):
        load_ok = self.load_xvasynth_model(path_to_xvasynth=config.xvasynth_path, game_folder=config.game_folder_name, voice=config.voice, language=config.language, load_model_url=config.load_model_url)
        if load_ok != "ok":
            print("There was a problem loading your XVASynth voice, check your voice name and game folder for your voice in XVAsynth")

        file_dir = path.abspath(path.dirname(__file__))
        wingman_dir = path.abspath(path.dirname(file_dir))

        # Create a list to store generated audio futures
        audio_futures = []

        # Define a function to generate audio and return the file path only after the response is completed
        def generate_audio(sentence, index):
            final_voiceline_file = wingman_dir + f"\\audio_output\\xvasynth{index}.wav"
            if path.exists(final_voiceline_file):
                os.remove(final_voiceline_file)

            synthesize_url = config.synthesize_url
            data = {
                'pluginsContext': '{}',
                'modelType': 'xVAPitch',
                'sequence': sentence,
                'pace': config.pace,
                'outfile': final_voiceline_file,
                'vocoder': 'n/a',
                'base_lang': config.language,
                'base_emb': '[]',
                'useSR': config.use_sr,
                'useCleanup': config.use_cleanup,
            }
            response = requests.post(synthesize_url, json=data)
            return final_voiceline_file

        # Use ThreadPoolExecutor to parallelize audio generation
        with ThreadPoolExecutor() as executor:
            sentences = text.split(". ")
            # Submit tasks for each sentence and store the futures
            audio_futures = [executor.submit(generate_audio, sentence, i) for i, sentence in enumerate(sentences)]

        # Play the generated audio files sequentially
        audio_player = AudioPlayer()
        for future in audio_futures:
            audio_file = future.result()
            audio, sample_rate = audio_player.get_audio_from_file(audio_file)
            audio_player.stream_with_effects(input_data=(audio, sample_rate), config=sound_config, wait=True)

    def check_if_xvasynth_is_running(self, url:str):
        # get base url from synthesize url in config
        parsed_url = urlparse(url)
        base_url = urlunparse((parsed_url.scheme, parsed_url.netloc, '/', '', '', ''))
        try:
            response = requests.get(base_url)
            response.raise_for_status()

        except requests.RequestException as e:
            time.sleep(1)
            if self.times_checked_xvasynth == 1:
                #If not found, try to start xvasynth as a subprocess
                subprocess.Popen([f'{self.xvasynth_path}/resources/app/cpython_{self.process_device}/server.exe'], cwd=self.xvasynth_path)
                time.sleep(6)
            return "ERROR: You chose XVASynth for Text to Speech but the program does not appear to be running.  Please start XVASynth and try again or choose another Text to Speech type."

        return "ok"

    def load_xvasynth_model(self, path_to_xvasynth:str, game_folder:str, voice:str, language:str, load_model_url:str):
        # example: voice_path = "D:\\DExtraSteamGames\\steamapps\\common\\xVASynth\\resources\\app\\models\\masseffect\\me_edi"
        voice_path = path_to_xvasynth + "\\resources\\app\\models\\" + game_folder + "\\" + voice
        base_lang = language
        model_change = {
            'outputs': None,
            'version': '3.0',
            'model': voice_path, 
            'modelType': 'XVAPitch',
            'base_lang': base_lang, 
            'pluginsContext': '{}',
            }
        try:
            response = requests.post(load_model_url, json=model_change)
            response.raise_for_status()
            self.current_voice = voice
            return "ok"
        except:
            return "There was an error with loading your XVASynth voice. Double check your game folder and voice path."