from os import path
import sys
import asyncio
import threading
import yaml
from pynput import keyboard
from exceptions import MissingApiKeyException
from services.audio_recorder import AudioRecorder
from services.check_version import check_version
from services.tower import Tower
from services.splashscreen import Splashscreen
from services.printr import Printr


def read_config(file_name=None) -> dict[str, any]:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # running in a PyInstaller bundle'
        if not file_name:
            bundle_dir = path.abspath(path.dirname(__file__))
            file_name = path.join(bundle_dir, "../config.yaml")
    else:
        # running in a normal Python process'
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

    if __name__ == "__main__":
        Splashscreen.show(tower)

        check_version(config.get("version"), "https://shipbit.de/wingman.json")

        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            print(
                f"{Printr.clr('⌬', Printr.CYAN)} Press an assigned key to talk to the respective wingman"
            )
            print("")
            print(
                f"{Printr.clr('⌬', Printr.CYAN)} Exit this program by pressing [{Printr.clr('Ctrl', Printr.BLUE)}] + [{Printr.clr('C', Printr.BLUE)}]"
            )
            print("")
            listener.join()

except FileNotFoundError:
    print("Missing config.yaml")
    print("Rename config.yaml.example to config.yaml if you're running from source.")
    print(
        "Make sure that your VSCode terminal executed main.py from the root directory. Sometimes you have to 'cd' into it first, then press F5 again."
    )
except MissingApiKeyException:
    print("Please set your OpenAI API key in config.yaml")
except KeyboardInterrupt:
    print("")
    print("Shutdown requested...")
    print("Goodbye, Commander! o7")
sys.exit(0)
