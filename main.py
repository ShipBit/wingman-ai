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


def read_main_config(file_name=None) -> dict[str, any]:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # running in a PyInstaller bundle
        if not file_name:
            bundle_dir = path.abspath(path.dirname(__file__))
            file_name = path.join(bundle_dir, "../config.yaml")
    else:
        # running in a normal Python process
        if not file_name:
            bundle_dir = path.abspath(path.dirname(__file__))
            file_name = path.join(bundle_dir, "config.yaml")

    with open(file_name, "r", encoding="UTF-8") as stream:
        try:
            cfg = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print(exc)
    return cfg


def get_or_create_api_keys(filename="apikeys.yaml"):
    # Check if file exists
    if path.exists(filename):
        with open(filename, "r", encoding="UTF-8") as file:
            data = yaml.safe_load(file)

            try:
                if data["openai"].get("api_key"):
                    return data
            except (KeyError, AttributeError):
                pass

    print(
        f"{Printr.clr('⌬', Printr.CYAN)} How to get your OpenAI API key: https://www.patreon.com/posts/how-to-get-your-93307145"
    )
    openai_api_key = input("Please paste your OpenAI API key: ")
    # TODO do not override whole file
    data = {"openai": {"api_key": openai_api_key}}

    with open(filename, "w", encoding="UTF-8") as file:
        yaml.dump(data, file)

    return data


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

        if recorded_audio_wav:
            play_thread = threading.Thread(target=run_async_process)
            play_thread.start()


try:
    config = read_main_config()

    # config migration
    # todo: remove for public release
    if config.get("version") or config["openai"].get("api_key"):
        Printr.err_print("You are using an outdated config.yaml file.")
        Printr.err_print(
            "Please copy&paste your changes/commands from the old one and save them or backup your old config.",
            False,
        )
        Printr.err_print(
            "Then delete your config.yaml and copy the new one from our latest release into your Wingman directory.",
            False,
        )
        Printr.err_print("Then reapply your changes in the new config.", False)
        input("Press your favorite key to exit...")
        sys.exit(0)

    apikeys = get_or_create_api_keys()
    for key, value in apikeys.items():
        if key not in config:
            config[key] = {}
        config[key]["api_key"] = value.get("api_key")

    tower = Tower(config)
    audio_recorder = AudioRecorder()

    if __name__ == "__main__":
        Splashscreen.show(tower)
        check_version("https://shipbit.de/wingman.json")
        tower.prepare_wingmen()

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
    Printr.err_print("Missing config.yaml")
    Printr.err_print(
        "Rename config.yaml.example to config.yaml if you're running from source.",
        False,
    )
    Printr.err_print(
        "Make sure that your VSCode terminal executed main.py from the root directory.",
        False,
    )
    Printr.err_print(
        "Sometimes you have to 'cd' into it first, then press F5 again.", False
    )

except MissingApiKeyException:
    Printr.err_print("Please set your OpenAI API key in 'apikeys.yaml'")

except KeyboardInterrupt:
    # Nothing bad. Just exit the application
    Printr.override_print("")
    print("Shutdown requested...")
    print("Goodbye, Commander! o7")

except Exception as e:
    # Everything else...
    Printr.err_print(str(e))

sys.exit(0)
