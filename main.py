import asyncio
import threading
from pynput import keyboard
import yaml
from os import path
from services.audio_recorder import AudioRecorder
from services.tower import Tower
from exceptions import MissingApiKeyException


def read_config(file_name=None) -> dict[str, any]:
    if not file_name:
        bundle_dir = path.abspath(path.dirname(__file__))
        file_name = path.join(bundle_dir, "config.yaml")
    with open(file_name, "r", encoding="UTF-8") as stream:
        try:
            cfg = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print(exc)
    return cfg


def on_press(key):
    wingman = tower.get_wingman_from_key(key)
    if wingman:
        audio_recorder.start_recording()


def on_release(key):
    wingman = tower.get_wingman_from_key(key)
    if wingman:
        recorded_audio_wav = audio_recorder.stop_recording()

        def run_async_process():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(wingman.process(recorded_audio_wav))
            finally:
                loop.close()

        play_thread = threading.Thread(target=run_async_process)
        play_thread.start()


try:
    config = read_config()
    tower = Tower(config)
    audio_recorder = AudioRecorder()

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        print("Ready to listen!")
        listener.join()
except MissingApiKeyException:
    print("Please set your OpenAI API key in config.yaml.")
    
