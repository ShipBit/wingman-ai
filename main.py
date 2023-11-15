import yaml
import threading
from api.audio_recorder import AudioRecorder
from pynput import keyboard

from api.tower import Tower


def read_config(file_name="config.yaml"):
    with open(file_name, "r") as stream:
        try:
            config = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print(exc)

    return config


def on_press(key):
    wingman = tower.get_wingman_from_key(key)
    if wingman:
        audio_recorder.start_recording()


def on_release(key):
    wingman = tower.get_wingman_from_key(key)
    if wingman:
        recorded_audio_wav = audio_recorder.stop_recording()
        play_thread = threading.Thread(
            target=wingman.process,
            args=(recorded_audio_wav,),
        )
        play_thread.start()


is_recording = False

config = read_config()
tower = Tower(config)
audio_recorder = AudioRecorder()

with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
    listener.join()
