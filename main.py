from os import path
import sys
import asyncio
import threading
from pynput import keyboard
from services.audio_recorder import AudioRecorder
from services.check_version import check_version
from services.tower import Tower
from services.printr import Printr
from services.config_manager import ConfigManager
from gui.root import WingmanUI
from wingmen.wingman import Wingman


class WingmanAI():
    def __init__(self):
        self.active = False
        self.ready = False
        self.active_recording = {"key": "", "wingman": None}
        self.tower = None
        self.config_manager = None
        # self.printr = None
        self.audio_recorder = AudioRecorder()
        self.app_is_bundled = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")
        self.app_root_dir = path.abspath(path.dirname(__file__))
        check_version("https://shipbit.de/wingman.json")


    def setup(self):
        self.config_manager = ConfigManager(self.app_root_dir, self.app_is_bundled)
        # TODO: new Version of Printer, that handles core output
        # self.printr = NewPrintr()
        self.ready = True


    def load_context(self, context=None):
        self.active = False
        try:
            if self.config_manager:
                config = self.config_manager.get_context_config(context)
                self.tower = Tower(config)

        except FileNotFoundError:
            Printr.err_print(f"Could not find context.{context}.yaml")
        except Exception as e:
            # Everything else...
            Printr.err_print(str(e))


    def activate(self):
        if self.tower:
            self.active = True

    def deactivate(self):
        self.active = False


    def on_press(self, key):
        if self.active and self.tower and self.active_recording["key"] == "":
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
                    if isinstance(wingman, Wingman):
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
