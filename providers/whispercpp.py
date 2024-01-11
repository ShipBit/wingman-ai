import requests
import json
import os
import subprocess
import time
from api.enums import WingmanInitializationErrorType
from api.interface import WhispercppSttConfig, WhispercppTranscript, WingmanInitializationError
from os import path

class Whispercpp:
    def __init__(self, wingman_name: str, base_url: str, autostart: bool, whispercpp_exe_path: str, whispercpp_model_path: str, temperature: float, language: str, times_checked_whispercpp: int):
        self.wingman_name = wingman_name if wingman_name else ""
        self.base_url = base_url if base_url else "http://127.0.0.1:8080"
        self.autostart = autostart if autostart else False
        self.whispercpp_exe_path = whispercpp_exe_path if whispercpp_exe_path else None
        self.whispercpp_model_path = whispercpp_model_path if whispercpp_model_path else None
        self.temperature = temperature if temperature else 0.0
        self.language = language if language else "en"
        self.times_checked_whispercpp = 0
        
    def validate_config(self, config: WhispercppSttConfig, errors: list[WingmanInitializationError]):
        if not errors:
            errors = []

        if not config.base_url:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman_name,
                    message="Missing base url for whispercpp. Please provide a url where whispercpp can be reached.  By default this is http://127.0.0.1:8080.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )

        if config.autostart == True and (config.whispercpp_exe_path == None or config.whispercpp_model_path == None or not os.path.exists(config.whispercpp_exe_path) or not os.path.exists(config.whispercpp_model_path)):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman_name,
                    message="You chose to use whispercpp and chose autostart but did not provide proper paths to the whispercpp exe and model.  Please turn autostart off or set / confirm the paths to the exe and model.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )

        self.base_url = config.base_url if config.base_url else "http://127.0.0.1:8080"
        self.autostart = config.autostart if config.autostart else False
        self.whispercpp_exe_path = config.whispercpp_exe_path if config.whispercpp_exe_path else None
        self.whispercpp_model_path = config.whispercpp_model_path if config.whispercpp_model_path else None
        self.temperature = config.temperature if config.temperature else 0.0
        self.language = config.language if config.language else "en"
        self.times_checked_whispercpp = 0
        # check if whispercpp is running a few times, if cannot find it, send error
        while self.times_checked_whispercpp < 5:
            check = self.check_if_whispercpp_is_running()
            if check == "ok":
                break
            self.times_checked_whispercpp+=1

        if check != "ok":
            errors.append(WingmanInitializationError(
                    wingman_name=self.wingman_name,
                    message=check,
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                ))

        return errors

    def transcribe(self, filename: str, response_format: str = "json"):
        url = self.base_url + '/inference'
        file_path = filename
        files = {'file': open(file_path, 'rb')}
        data = {'temperature': self.temperature, 'response_format': response_format,}
        try:
            response = requests.post(url, files=files, data=data)
            response.raise_for_status()
            # Need to use a pydantic base model to enable openaiwingman to use same transcript.text call as it uses for openai which also uses a pydantic object, otherwise response.json would be fine here, which would return {"text":"transcription"}.
            return WhispercppTranscript(text=response.json()["text"].strip())
        except:
            return "There was an error with the whispercpp transcription.  The request to the server failed."

    def check_if_whispercpp_is_running(self):
        try:
            response = requests.get(self.base_url)
            response.raise_for_status()

        except requests.RequestException as e:
            time.sleep(1)
            if self.times_checked_whispercpp == 1 and self.autostart == True:
                #If not found, try to start whispercpp as a subprocess
                subprocess.Popen([self.whispercpp_exe_path, "-m", self.whispercpp_model_path, "-l", self.language])
                time.sleep(5)
            return "ERROR: You chose Whispercpp for speech to text but the program does not appear to be running, and if you enabled autostart, autostart failed.  Please check your whispercpp install and your paths if you enabled autostart."

        return "ok"

    # Currently unused but whispercpp supports loading models by functions so including for possible future dev use.
    def load_whispercpp_model(self, whispercpp_model_path:str):
        model_path = whispercpp_model_path
        data = {'model': model_path,}
        try:
            response = requests.post(self.base_url+"/load", data=data)
            response.raise_for_status()
            return "ok"
        except:
            return "There was an error with loading your whispercpp model. Double check your whispercpp install and model path."