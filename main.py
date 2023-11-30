from os import path
import sys
import asyncio
import threading
import yaml
from pynput import keyboard
from services.audio_recorder import AudioRecorder
from services.check_version import check_version
from services.tower import Tower
from services.printr import Printr
from gui.root import WingmanUI


class WingmanAI():
    def __init__(self):
        self.active = False
        self.active_recording = dict(key="", wingman=None)
        self.tower = None
        self.audio_recorder = AudioRecorder()
        check_version("https://shipbit.de/wingman.json")

    def load_context(self, context=None):
        self.active = False
        try:
            config = self.read_config(context)

            # TODO: validate config & check which api keys are needed
            # append api keys
            apikeys = self.get_or_create_api_keys()
            for key, value in apikeys.items():
                config[key]["api_key"] = value.get("api_key")

            # TODO: move to "load config"?
            # config migration
            # if config.get("version") or config["openai"].get("api_key"):
            #     Printr.err_print(
            #         "You are using an outdated config.yaml file. Please copy&paste your changes/commands from the old one and save them or backup your old config. Then delete your config.yaml and copy the new one from our latest release into your Wingman directory. Then reapply your changes in the new config."
            #     )
            #     input("Press ENTER to continue...")
            #     sys.exit(0)

            self.tower = Tower(config)
            # Splashscreen.show(tower)

        # TODO: delete?
        # except MissingApiKeyException:
        #     Printr.err_print("Please set your OpenAI API key in your 'apikeys.yaml'")
        except FileNotFoundError:
            Printr.err_print(f"Could not find config.{context}.yaml")
        except Exception as e:
            # Everything else...
            Printr.err_print(str(e))

    def activate(self):
        if self.tower:
            self.active = True

    def deactivate(self):
        self.active = False

    def read_config(self, context=None) -> dict[str, any]:
        is_bundled = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")
        # move up one step, if bundled -> '../'
        # default name -> 'config.yaml'
        # context config -> 'config.{context}.yaml'
        config_name = f"{'../' if is_bundled else ''}config.{f'{context}.' if context else ''}yaml"

        bundle_dir = path.abspath(path.dirname(__file__))
        file_name = path.join(bundle_dir, config_name)

        with open(file_name, "r", encoding="UTF-8") as stream:
            try:
                cfg = yaml.safe_load(stream)
            except yaml.YAMLError as exc:
                # TODO: show in gui
                print(exc)
        return cfg


    def get_or_create_api_keys(self, filename="apikeys.yaml"):
        # Check if file exists
        if path.exists(filename):
            with open(filename, "r") as file:
                data = yaml.safe_load(file)
                return data

        # TODO: remake
        # print(
        #     f"{Printr.clr('⌬', Printr.CYAN)} How to get your OpenAI API key: https://www.patreon.com/posts/how-to-get-your-93307145"
        # )
        # openai_api_key = input("Please paste your OpenAI API key: ")
        # data = {"openai": {"api_key": openai_api_key}}

        # with open(filename, "w") as file:
        #     yaml.dump(data, file)

        return data


    def on_press(self, key):
        if self.active and self.active_recording["key"] == "":
            wingman = self.tower.get_wingman_from_key(key)
            if wingman:
                self.active_recording = dict(key= key, wingman=wingman)
                self.audio_recorder.start_recording()


    def on_release(self, key):
        if self.active and self.active_recording["key"] == key:

            wingman = self.active_recording["wingman"]
            recorded_audio_wav = self.audio_recorder.stop_recording()
            self.active_recording = dict(key="", wingman=None)

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


#─────────────────────────────────── ↓ START ↓ ─────────────────────────────────────────
if __name__ == "__main__":
    core = WingmanAI()

    # NOTE this is the only possibility to use `pynput` and `tkinter` in parallel
    listener = keyboard.Listener(on_press=core.on_press, on_release=core.on_release)
    listener.start()
    listener.wait()

    ui = WingmanUI(core)
    ui.mainloop()

    listener.stop()
