import threading
from pynput import keyboard
import yaml
from services.audio_recorder import AudioRecorder
from services.tower import Tower


def read_config(file_name="config.yaml") -> dict[str, any]:
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
        play_thread = threading.Thread(
            target=wingman.process,
            args=(recorded_audio_wav,),
        )
        play_thread.start()


config = read_config()
tower = Tower(config)
audio_recorder = AudioRecorder()

with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
    listener.join()
