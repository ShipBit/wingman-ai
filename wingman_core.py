import asyncio
import threading
from fastapi import APIRouter
import sounddevice as sd
from api.enums import LogType, ToastType
from api.interface import AudioDevice, AudioSettings, Config, ContextInfo
from wingmen.wingman import Wingman
from services.audio_recorder import AudioRecorder
from services.printr import Printr
from services.tower import Tower
from services.config_manager import ConfigManager

printr = Printr()


class WingmanCore:
    def __init__(self, app_is_bundled: bool, app_root_dir: str):
        self.router = APIRouter()
        self.router.add_api_route(
            methods=["GET"],
            path="/contexts",
            endpoint=self.get_contexts,
            response_model=ContextInfo,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/config/",
            endpoint=self.get_config,
            response_model=Config,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/audio-devices",
            endpoint=self.get_audio_devices,
            response_model=list[AudioDevice],
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/audio-devices",
            endpoint=self.set_audio_devices,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/configured-audio-devices",
            endpoint=self.get_configured_audio_devices,
            response_model=AudioSettings,
            tags=["core"],
        )

        self.app_root_dir = app_root_dir
        self.active_recording = {"key": "", "wingman": None}
        self.config_manager = ConfigManager(app_root_dir, app_is_bundled)
        self.audio_recorder = AudioRecorder(app_root_dir=app_root_dir)
        self.tower = None
        self.current_config = None

        # restore settings
        configured_devices = self.get_configured_audio_devices()
        sd.default.device = (configured_devices.input, configured_devices.output)

    async def load_config(self, config_name=""):
        try:
            config = self.config_manager.load_config(config_name)
        except FileNotFoundError:
            printr.toast_error(f"Could not find config.{config_name}.yaml")
            raise
        except Exception as e:
            # Everything else...
            printr.toast_error(str(e))
            raise e

        self.current_config = config
        self.tower = Tower(config=config, app_root_dir=self.app_root_dir)
        errors = await self.tower.instantiate_wingmen()

    def on_press(self, key):
        if self.tower and self.active_recording["key"] == "":
            wingman = self.tower.get_wingman_from_key(key)
            if wingman:
                self.active_recording = dict(key=key, wingman=wingman)
                self.audio_recorder.start_recording(wingman_name=wingman.name)

    def on_release(self, key):
        if self.tower and self.active_recording["key"] == key:
            wingman = self.active_recording["wingman"]
            recorded_audio_wav = self.audio_recorder.stop_recording(
                wingman_name=wingman.name
            )
            self.active_recording = {"key": "", "wingman": None}

            def run_async_process():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    if isinstance(wingman, Wingman):
                        loop.run_until_complete(
                            wingman.process(str(recorded_audio_wav))
                        )
                finally:
                    loop.close()

            if recorded_audio_wav:
                play_thread = threading.Thread(target=run_async_process)
                play_thread.start()

    # GET /contexts
    def get_contexts(self):
        return ContextInfo(
            contexts=self.config_manager.contexts,
            currentContext=self.current_config,
        )

    # GET /config
    def get_config(self, context: str = None) -> Config:
        return self.config_manager.load_config(context or "")

    # GET /configured-audio-devices
    def get_configured_audio_devices(self):
        audio_devices = self.config_manager.settings_config.audio
        input_device = audio_devices.input if audio_devices else None
        output_device = audio_devices.output if audio_devices else None
        return AudioSettings(input=input_device, output=output_device)

    # GET /audio-devices
    def get_audio_devices(self):
        audio_devices = sd.query_devices()
        return audio_devices

    # POST /audio-devices
    def set_audio_devices(self, output_device: int, input_device: int):
        # set the devices
        sd.default.device = input_device, output_device
        # save settings
        self.config_manager.settings_config.audio = AudioSettings(
            input=input_device,
            output=output_device,
        )
        if self.config_manager.save_settings_config():
            printr.print(
                "Audio devices updated.", toast=ToastType.NORMAL, color=LogType.POSITIVE
            )
