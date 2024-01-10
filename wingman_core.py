import asyncio
import threading
from fastapi import APIRouter
import sounddevice as sd
from api.enums import AzureRegion, LogType, OpenAiTtsVoice, ToastType
from api.interface import (
    AudioDevice,
    AudioSettings,
    AzureTtsConfig,
    Config,
    ConfigInfo,
    EdgeTtsConfig,
    ElevenlabsConfig,
    SoundConfig,
    VoiceInfo,
    WingmanInitializationError,
)
from providers.edge import Edge
from providers.elevenlabs import ElevenLabs
from providers.open_ai import OpenAi, OpenAiAzure
from wingmen.wingman import Wingman
from services.audio_recorder import AudioRecorder
from services.printr import Printr
from services.tower import Tower
from services.config_manager import DEFAULT_CONFIG_DIR, ConfigManager

printr = Printr()


class WingmanCore:
    def __init__(self, config_manager: ConfigManager):
        self.router = APIRouter()
        self.router.add_api_route(
            methods=["GET"],
            path="/configs",
            endpoint=self.get_configs,
            response_model=ConfigInfo,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/default-config/",
            endpoint=self.get_default_config,
            response_model=Config,
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
            methods=["DELETE"],
            path="/config/",
            endpoint=self.delete_config,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/config/create",
            endpoint=self.create_config,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/config/save-wingman",
            endpoint=self.save_wingman_config,
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
            path="/audio-devices/configured",
            endpoint=self.get_configured_audio_devices,
            response_model=AudioSettings,
            tags=["core"],
        )

        self.router.add_api_route(
            methods=["GET"],
            path="/startup-errors",
            endpoint=self.get_startup_errors,
            response_model=list[WingmanInitializationError],
            tags=["core"],
        )

        self.router.add_api_route(
            methods=["GET"],
            path="/voices/elevenlabs",
            endpoint=self.get_elevenlabs_voices,
            response_model=list[VoiceInfo],
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/voices/azure",
            endpoint=self.get_azure_voices,
            response_model=list[VoiceInfo],
            tags=["core"],
        )

        self.router.add_api_route(
            methods=["POST"],
            path="/play/openai",
            endpoint=self.play_openai_tts,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/play/azure",
            endpoint=self.play_azure_tts,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/play/elevenlabs",
            endpoint=self.play_elevenlabs_tts,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/play/edgetts",
            endpoint=self.play_edge_tts,
            tags=["core"],
        )

        self.config_manager = config_manager
        self.active_recording = {"key": "", "wingman": None}
        self.audio_recorder = AudioRecorder()
        self.tower: Tower = None
        self.current_config: str = None
        self.startup_errors: list[WingmanInitializationError] = []
        self.is_started = False

        # restore settings
        configured_devices = self.get_configured_audio_devices()
        sd.default.device = (configured_devices.input, configured_devices.output)

    async def load_config(self, config_name: str = DEFAULT_CONFIG_DIR):
        try:
            config = self.config_manager.load_config(config_name)
        except FileNotFoundError:
            printr.toast_error(f"Could not find config.{config_name}.yaml")
            raise
        except Exception as e:
            # Everything else...
            printr.toast_error(str(e))
            raise e

        self.current_config = config_name
        self.tower = Tower(config=config)
        errors = await self.tower.instantiate_wingmen()
        return errors

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

    # GET /configs
    def get_configs(self):
        return ConfigInfo(
            configs=self.config_manager.config_dirs,
            currentConfig=self.current_config,
        )

    # GET /config
    def get_config(self, config_name: str) -> Config:
        return self.config_manager.load_config(config_name)

    # GET /default-config
    def get_default_config(self) -> Config:
        return self.config_manager.load_default_config()

    # POST config/create
    def create_config(self, config_name: str, template: str = None):
        self.config_manager.create_config(config_name=config_name, template=template)

    # DELETE config
    def delete_config(self, config_name: str):
        self.config_manager.delete_config(config_name=config_name)

    # POST config/save-wingman
    def save_wingman_config(self, config_name: str, wingman_name: str, config: Config):
        self.config_manager.save_wingman_config(
            config_name=config_name, wingman_name=wingman_name, config=config
        )

    # GET /audio-devices/configured
    def get_configured_audio_devices(self):
        audio_devices = (
            self.config_manager.settings_config.audio
            if self.config_manager.settings_config
            else None
        )
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

    # GET /startup-errors
    def get_startup_errors(self):
        return self.startup_errors

    # GET /voices/elevenlabs
    def get_elevenlabs_voices(self, api_key: str):
        elevenlabs = ElevenLabs(api_key=api_key, wingman_name="")
        voices = elevenlabs.get_available_voices()
        convert = lambda voice: VoiceInfo(id=voice.voiceID, name=voice.name)
        result = [convert(voice) for voice in voices]

        return result

    # GET /voices/azure
    def get_azure_voices(self, api_key: str, region: AzureRegion, locale: str = ""):
        azure = OpenAiAzure()
        voices = azure.get_available_voices(
            api_key=api_key, region=region.value, locale=locale
        )
        convert = lambda voice: VoiceInfo(
            id=voice.short_name,
            name=voice.local_name,
            gender=voice.gender.name,
            locale=voice.locale,
        )
        result = [convert(voice) for voice in voices]

        return result

    # POST /play/openai
    def play_openai_tts(
        self, text: str, api_key: str, voice: OpenAiTtsVoice, sound_config: SoundConfig
    ):
        openai = OpenAi(api_key=api_key)
        openai.play_audio(text=text, voice=voice, sound_config=sound_config)

    # POST /play/azure
    def play_azure_tts(
        self, text: str, api_key: str, config: AzureTtsConfig, sound_config: SoundConfig
    ):
        azure = OpenAiAzure()
        azure.play_audio(
            text=text,
            api_key=api_key,
            config=config,
            sound_config=sound_config,
        )

    # POST /play/elevenlabs
    def play_elevenlabs_tts(
        self,
        text: str,
        api_key: str,
        config: ElevenlabsConfig,
        sound_config: SoundConfig,
    ):
        elevenlabs = ElevenLabs(api_key=api_key, wingman_name="")
        elevenlabs.play_audio(
            text=text,
            config=config,
            sound_config=sound_config,
        )

    # POST /play/edgetts
    async def play_edge_tts(
        self, text: str, config: EdgeTtsConfig, sound_config: SoundConfig
    ):
        edge = Edge()
        await edge.play_audio(text=text, config=config, sound_config=sound_config)
