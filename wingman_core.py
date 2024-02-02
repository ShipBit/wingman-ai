import asyncio
import threading
from typing import Optional
from fastapi import APIRouter
import sounddevice as sd
import mouse.mouse as mouse
from api.enums import AzureRegion, LogType, OpenAiTtsVoice, ToastType
from api.interface import (
    AudioDevice,
    AudioSettings,
    AzureTtsConfig,
    ConfigDirInfo,
    ConfigWithDirInfo,
    ConfigsInfo,
    EdgeTtsConfig,
    ElevenlabsConfig,
    NewWingmanTemplate,
    SettingsConfig,
    SoundConfig,
    VoiceInfo,
    WingmanConfig,
    WingmanConfigFileInfo,
    WingmanInitializationError,
    XVASynthTtsConfig,
)
from providers.edge import Edge
from providers.elevenlabs import ElevenLabs
from providers.open_ai import OpenAi, OpenAiAzure
from providers.xvasynth import XVASynth
from wingmen.wingman import Wingman
from services.audio_recorder import AudioRecorder
from services.printr import Printr
from services.tower import Tower
from services.config_manager import ConfigManager

printr = Printr()


class WingmanCore:
    def __init__(self, config_manager: ConfigManager):
        self.router = APIRouter()
        self.router.add_api_route(
            methods=["GET"],
            path="/configs",
            endpoint=self.get_config_dirs,
            response_model=ConfigsInfo,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/configs/templates",
            endpoint=self.get_config_templates,
            response_model=list[ConfigDirInfo],
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/config",
            endpoint=self.get_config,
            response_model=ConfigWithDirInfo,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/config-dir-path",
            endpoint=self.get_config_dir_path,
            response_model=str,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/config",
            endpoint=self.load_config,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["DELETE"],
            path="/config",
            endpoint=self.delete_config,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/config/wingmen",
            endpoint=self.get_wingmen_config_files,
            response_model=list[WingmanConfigFileInfo],
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/config/new-wingman",
            endpoint=self.get_new_wingmen_template,
            response_model=NewWingmanTemplate,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/config/new-wingman",
            endpoint=self.add_new_wingman,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/config/wingman/default",
            endpoint=self.set_default_wingman,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["DELETE"],
            path="/config/wingman",
            endpoint=self.delete_wingman_config,
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
            path="/config/rename",
            endpoint=self.rename_config,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/config/default",
            endpoint=self.set_default_config,
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
            methods=["POST"],
            path="/voice-activation",
            endpoint=self.set_voice_activation,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/mute-key",
            endpoint=self.set_mute_key,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/settings",
            endpoint=self.get_settings,
            response_model=SettingsConfig,
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
        self.router.add_api_route(
            methods=["POST"],
            path="/play/xvasynth",
            endpoint=self.play_xvasynth_tts,
            tags=["core"],
        )

        self.config_manager = config_manager
        self.active_recording = {"key": "", "wingman": None}
        self.audio_recorder = AudioRecorder()
        self.tower: Tower = None

        self.current_config_dir: ConfigDirInfo = (
            self.config_manager.find_default_config()
        )

        self.startup_errors: list[WingmanInitializationError] = []
        self.is_started = False

        self.speech_recognizer = None
        self.is_listening = True

        # restore settings
        settings = self.get_settings()
        if settings.audio:
            input_device = settings.audio.input
            output_device = settings.audio.output
            sd.default.device = (input_device, output_device)
            self.audio_recorder.update_input_stream()

    def on_press(self, key=None, button=None):
        if self.tower and self.active_recording["key"] == "":
            if key:
                wingman = self.tower.get_wingman_from_key(key)
            elif button:
                wingman = self.tower.get_wingman_from_mouse(button)
            if wingman:
                if key:
                    self.active_recording = dict(key=key.name, wingman=wingman)
                elif button:
                    self.active_recording = dict(key=button, wingman=wingman)
                self.mute_voice_recognition(True)
                self.audio_recorder.start_recording(wingman_name=wingman.name)

    def on_release(self, key=None, button=None):
        if self.tower and (
            key is not None
            and self.active_recording["key"] == key.name
            or self.active_recording["key"] == button
        ):
            wingman = self.active_recording["wingman"]
            recorded_audio_wav = self.audio_recorder.stop_recording(
                wingman_name=wingman.name
            )
            self.active_recording = {"key": "", "wingman": None}
            self.mute_voice_recognition(False)

            def run_async_process():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    if isinstance(wingman, Wingman):
                        loop.run_until_complete(
                            wingman.process(audio_input_wav=str(recorded_audio_wav))
                        )
                finally:
                    loop.close()

            if recorded_audio_wav:
                play_thread = threading.Thread(target=run_async_process)
                play_thread.start()

    def on_key(self, key):
        if key.event_type == "down":
            self.on_press(key=key)
        elif key.event_type == "up":
            self.on_release(key=key)

    def on_mouse(self, event):
        # Check if event is of type ButtonEvent
        if not isinstance(event, mouse.ButtonEvent):
            return

        if event.event_type == "down":
            self.on_press(button=event.button)
        elif event.event_type == "up":
            self.on_release(button=event.button)

    def on_voice_recognition(self, voice_event):

        def run_async_process():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(wingman.process(transcript=text))
            finally:
                loop.close()

        text = voice_event.result.text
        wingman = self.tower.get_wingman_from_text(text)
        if text and wingman:
            play_thread = threading.Thread(target=run_async_process)
            play_thread.start()

    def mute_voice_recognition(self, is_muted: bool):
        if is_muted:
            self.speech_recognizer.stop_continuous_recognition()
        else:
            self.speech_recognizer.start_continuous_recognition()

    def on_mute_toggle(self):
        self.is_listening = not self.is_listening
        self.mute_voice_recognition(not self.is_listening)

    # GET /configs
    def get_config_dirs(self):
        return ConfigsInfo(
            config_dirs=self.config_manager.get_config_dirs(),
            current_config_dir=self.current_config_dir,
        )

    # GET /configs/templates
    def get_config_templates(self):
        return self.config_manager.get_template_dirs()

    # GET /config
    async def get_config(self, config_name: Optional[str] = "") -> ConfigWithDirInfo:
        if config_name and len(config_name) > 0:
            config_dir = self.config_manager.get_config_dir(config_name)

        errors, config_info = await self.load_config(config_dir)
        return config_info

    # GET /config-dir-path
    def get_config_dir_path(self, config_name: Optional[str] = ""):
        return self.config_manager.get_config_dir_path(config_name)

    # POST config
    async def load_config(
        self, config_dir: Optional[ConfigDirInfo] = None
    ) -> tuple[list[WingmanInitializationError], ConfigWithDirInfo]:
        try:
            loaded_config_dir, config = self.config_manager.load_config(config_dir)
        except Exception as e:
            printr.toast_error(str(e))
            raise e

        self.current_config_dir = loaded_config_dir
        self.tower = Tower(config=config)
        errors = await self.tower.instantiate_wingmen()
        return errors, ConfigWithDirInfo(config=config, config_dir=loaded_config_dir)

    # POST config/create
    async def create_config(
        self, config_name: str, template: Optional[ConfigDirInfo] = None
    ):
        new_dir = self.config_manager.create_config(
            config_name=config_name, template=template
        )
        await self.load_config(new_dir)

    # POST config/rename
    async def rename_config(self, config_dir: ConfigDirInfo, new_name: str):
        new_config_dir = self.config_manager.rename_config(
            config_dir=config_dir, new_name=new_name
        )
        if new_config_dir and config_dir.name == self.current_config_dir.name:
            await self.load_config(new_config_dir)

    # POST config/default
    def set_default_config(self, config_dir: ConfigDirInfo):
        self.config_manager.set_default_config(config_dir=config_dir)

    # DELETE config
    async def delete_config(self, config_dir: ConfigDirInfo):
        self.config_manager.delete_config(config_dir=config_dir)
        if config_dir.name == self.current_config_dir.name:
            await self.load_config()

    # GET config/wingmen
    async def get_wingmen_config_files(self, config_name: str):
        config_dir = self.config_manager.get_config_dir(config_name)
        return self.config_manager.get_wingmen_configs(config_dir)

    # DELETE config/wingman
    async def delete_wingman_config(
        self, config_dir: ConfigDirInfo, wingman_file: WingmanConfigFileInfo
    ):
        self.config_manager.delete_wingman_config(config_dir, wingman_file)
        await self.load_config(config_dir)  # refresh

    # GET config/new-wingman/
    async def get_new_wingmen_template(self):
        return self.config_manager.get_new_wingman_template()

    # POST config/new-wingman
    async def add_new_wingman(
        self, config_dir: ConfigDirInfo, wingman_config: WingmanConfig, avatar: str
    ):
        wingman_file = WingmanConfigFileInfo(
            name=wingman_config.name,
            file=f"{wingman_config.name}.yaml",
            is_deleted=False,
            avatar=avatar,
        )

        await self.save_wingman_config(
            config_dir=config_dir,
            wingman_file=wingman_file,
            wingman_config=wingman_config,
            auto_recover=False,
        )

    # POST config/save-wingman
    async def save_wingman_config(
        self,
        config_dir: ConfigDirInfo,
        wingman_file: WingmanConfigFileInfo,
        wingman_config: WingmanConfig,
        auto_recover: bool = False,
        silent: bool = False,
    ):
        self.config_manager.save_wingman_config(
            config_dir=config_dir,
            wingman_file=wingman_file,
            wingman_config=wingman_config,
        )
        try:
            if not silent:
                await self.load_config(config_dir)
                printr.toast("Wingman saved successfully.")
        except Exception:
            error_message = "Invalid Wingman configuration."
            if auto_recover:
                deleted = self.config_manager.delete_wingman_config(
                    config_dir, wingman_file
                )
                if deleted:
                    self.config_manager.create_configs_from_templates()

                await self.load_config(config_dir)

                restored_message = (
                    "Deleted broken config (and restored default if there is a template for it)."
                    if deleted
                    else ""
                )
                printr.toast_error(f"{error_message} {restored_message}")
            else:
                printr.toast_error(f"{error_message}")

    # POST config/wingman/default
    async def set_default_wingman(
        self,
        config_dir: ConfigDirInfo,
        wingman_name: str,
    ):
        _dir, config = self.config_manager.load_config(config_dir)
        wingman_config_files = await self.get_wingmen_config_files(config_dir.name)

        for wingman_config_file in wingman_config_files:
            wingman_config = config.wingmen[wingman_config_file.name]

            wingman_config.is_voice_activation_default = (
                wingman_config.name == wingman_name
            )

            await self.save_wingman_config(
                config_dir=config_dir,
                wingman_file=wingman_config_file,
                wingman_config=wingman_config,
                silent=True,
            )

        await self.load_config(config_dir)

    # GET /settings
    def get_settings(self):
        return self.config_manager.settings_config

    # GET /audio-devices
    def get_audio_devices(self):
        audio_devices = sd.query_devices()
        return audio_devices

    # POST /audio-devices
    def set_audio_devices(
        self, output_device: Optional[int] = None, input_device: Optional[int] = None
    ):
        # set the devices
        sd.default.device = input_device, output_device
        self.audio_recorder.update_input_stream()

        # save settings
        self.config_manager.settings_config.audio = AudioSettings(
            input=input_device,
            output=output_device,
        )

        if self.config_manager.save_settings_config():
            printr.print(
                "Audio devices updated.", toast=ToastType.NORMAL, color=LogType.POSITIVE
            )

    # POST /voice-activation
    def set_voice_activation(self, is_enabled: bool):
        self.config_manager.settings_config.voice_activation.enabled = is_enabled

        if self.config_manager.save_settings_config():
            printr.print(
                f"Voice activation {'enabled' if is_enabled else 'disabled'}.",
                toast=ToastType.NORMAL,
                color=LogType.POSITIVE,
            )

    # POST /mute-key
    def set_mute_key(self, key: str):
        self.config_manager.settings_config.voice_activation.mute_toggle_key = key

        if self.config_manager.save_settings_config():
            printr.print(
                f"Mute key saved.",
                toast=ToastType.NORMAL,
                color=LogType.POSITIVE,
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

    # POST /play/xvasynth
    async def play_xvasynth_tts(
        self, text: str, config: XVASynthTtsConfig, sound_config: SoundConfig
    ):
        xvasynth = XVASynth(wingman_name="")
        await xvasynth.play_audio(text=text, config=config, sound_config=sound_config)
