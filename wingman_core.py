import asyncio
import re
import threading
from typing import Optional
from fastapi import APIRouter
import sounddevice as sd
import azure.cognitiveservices.speech as speechsdk
import keyboard.keyboard as keyboard
import mouse.mouse as mouse
from api.commands import VoiceActivationMutedCommand
from api.enums import (
    AzureRegion,
    CommandTag,
    LogType,
    OpenAiTtsVoice,
    ToastType,
    VoiceActivationSttProvider,
    WingmanProRegion,
)
from api.interface import (
    AudioDevice,
    AudioSettings,
    AzureSttConfig,
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
    WhispercppSttConfig,
    WingmanConfig,
    WingmanConfigFileInfo,
    WingmanInitializationError,
    XVASynthTtsConfig,
)
from providers.edge import Edge
from providers.elevenlabs import ElevenLabs
from providers.open_ai import OpenAi, OpenAiAzure
from providers.whispercpp import Whispercpp
from providers.wingman_pro import WingmanPro
from providers.xvasynth import XVASynth
from wingmen.wingman import Wingman
from services.audio_player import AudioPlayer
from services.audio_recorder import AudioRecorder
from services.config_manager import ConfigManager
from services.printr import Printr
from services.secret_keeper import SecretKeeper
from services.tower import Tower
from services.websocket_user import WebSocketUser

printr = Printr()


class WingmanCore(WebSocketUser):
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
            path="/settings",
            endpoint=self.get_settings,
            response_model=SettingsConfig,
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
            path="/settings/audio-devices",
            endpoint=self.set_audio_devices,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/voice-activation",
            endpoint=self.set_voice_activation,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/mute-key",
            endpoint=self.set_mute_key,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/wingman-pro",
            endpoint=self.set_wingman_pro_settings,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/wingman-pro/make-default",
            endpoint=self.set_wingman_pro_as_default,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/voice-activation/mute",
            endpoint=self.start_voice_recognition,
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
            methods=["GET"],
            path="/voices/azure/wingman-pro",
            endpoint=self.get_wingman_pro_azure_voices,
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
        self.router.add_api_route(
            methods=["POST"],
            path="/play/wingman-pro/azure",
            endpoint=self.play_wingman_pro_azure,
            tags=["core"],
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/play/wingman-pro/openai",
            endpoint=self.play_wingman_pro_openai,
            tags=["core"],
        )

        self.router.add_api_route(
            methods=["POST"],
            path="/stop-playback",
            endpoint=self.stop_playback,
            tags=["core"],
        )

        self.config_manager = config_manager
        self.secret_keeper: SecretKeeper = SecretKeeper()

        self.event_queue = asyncio.Queue()
        self.audio_player = AudioPlayer(
            event_queue=self.event_queue,
            on_playback_started=self.on_playback_started,
            on_playback_finished=self.on_playback_finished,
        )

        self.tower: Tower = None

        self.current_config_dir: ConfigDirInfo = (
            self.config_manager.find_default_config()
        )
        self.current_config = None
        self.active_recording = {"key": "", "wingman": None}

        self.is_started = False
        self.startup_errors: list[WingmanInitializationError] = []

        self.azure_speech_recognizer: speechsdk.SpeechRecognizer = None
        self.is_listening = False
        self.was_listening_before_ptt = False
        self.was_listening_before_playback = False

        self.key_events = {}

        # restore settings
        self.settings = self.get_settings()
        self.audio_recorder = AudioRecorder(
            on_speech_recorded=self.on_audio_recorder_speech_recorded
        )

        if self.settings.audio:
            input_device = self.settings.audio.input
            output_device = self.settings.audio.output
            sd.default.device = (input_device, output_device)
            self.audio_recorder.update_input_stream()

    async def startup(self):
        if self.settings.voice_activation.enabled:
            await self.set_voice_activation(is_enabled=True)

    def is_hotkey_pressed(self, hotkey: list[int] | str) -> bool:
        codes = []

        if isinstance(hotkey, str):
            hotkey_codes = keyboard.parse_hotkey(hotkey)
            codes = [item[0] for tup in hotkey_codes for item in tup]

        if isinstance(hotkey, list):
            codes = hotkey

        # check if all hotkey codes are in the key events code list
        is_pressed = all(code in self.key_events for code in codes)

        return is_pressed

    def on_press(self, key=None, button=None):
        is_mute_hotkey_pressed = self.is_hotkey_pressed(
            self.settings.voice_activation.mute_toggle_key_codes
            or self.settings.voice_activation.mute_toggle_key
        )
        if is_mute_hotkey_pressed:
            self.toggle_voice_recognition()

        if self.tower and self.active_recording["key"] == "":
            wingman = None
            if key:
                for potential_wingman in self.tower.wingmen:
                    if self.is_hotkey_pressed(potential_wingman.get_record_key()):
                        wingman = potential_wingman
            elif button:
                wingman = self.tower.get_wingman_from_mouse(button)
            if wingman:
                if key:
                    self.active_recording = dict(key=key.name, wingman=wingman)
                elif button:
                    self.active_recording = dict(key=button, wingman=wingman)

                self.was_listening_before_ptt = self.is_listening
                if self.settings.voice_activation.enabled and self.is_listening:
                    self.start_voice_recognition(mute=True)

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

            if (
                self.settings.voice_activation.enabled
                and not self.is_listening
                and self.was_listening_before_ptt
            ):
                self.start_voice_recognition()

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
            if key.scan_code not in self.key_events:
                self.key_events[key.scan_code] = key
            self.on_press(key=key)
        elif key.event_type == "up":
            if key.scan_code in self.key_events:
                del self.key_events[key.scan_code]
            self.on_release(key=key)

    def on_mouse(self, event):
        # Check if event is of type ButtonEvent
        if not isinstance(event, mouse.ButtonEvent):
            return

        if event.event_type == "down":
            self.on_press(button=event.button)
        elif event.event_type == "up":
            self.on_release(button=event.button)

    # called when AudioRecorder regonized voice
    def on_audio_recorder_speech_recorded(self, recording_file: str):
        def run_async_process():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(wingman.process(transcript=text))
            finally:
                loop.close()

        provider = self.settings.voice_activation.stt_provider
        text = None

        if provider == VoiceActivationSttProvider.WINGMAN_PRO:
            wingman_pro = WingmanPro(
                wingman_name="system", settings=self.settings.wingman_pro
            )
            transcription = wingman_pro.transcribe_azure_speech(
                filename=recording_file,
                config=AzureSttConfig(
                    languages=self.settings.voice_activation.azure.languages,
                    # unused as Wingman Pro sets this at API level - just for Pydantic:
                    region=AzureRegion.WESTEUROPE,
                ),
            )
            if transcription:
                text = transcription.get("_text")
        elif provider == VoiceActivationSttProvider.WHISPERCPP:

            def filter_and_clean_text(text):
                # First, save the original text for comparison
                original_text = text
                # Remove the ambient noise descriptions
                noise_pattern = r"(\(.*?\))|(\[.*?\])|(\*.*?\*)"
                text = re.sub(noise_pattern, "", text)
                # Remove extra spaces, newlines, and commas
                cleanup_pattern = r"[\s,]+"
                text = re.sub(cleanup_pattern, " ", text)
                # Strip leading and trailing whitespaces
                text = text.strip()

                return original_text != text, text

            whisperccp = Whispercpp(wingman_name="system")
            transcription = whisperccp.transcribe(
                filename=recording_file,
                config=self.settings.voice_activation.whispercpp,
            )
            cleaned, text = filter_and_clean_text(transcription.text)
            if cleaned:
                printr.print(
                    f"Cleaned original transcription: {transcription.text}",
                    server_only=True,
                    color=LogType.SUBTLE,
                )
        elif provider == VoiceActivationSttProvider.OPENAI:
            # TODO: can't await secret_keeper.retrieve here, so just assume the secret is there...
            openai = OpenAi(api_key=self.secret_keeper.secrets["openai"])
            transcription = openai.transcribe(filename=recording_file)
            text = transcription.text

        if text:
            wingman = self.tower.get_wingman_from_text(text)
            if wingman:
                play_thread = threading.Thread(target=run_async_process)
                play_thread.start()
        else:
            printr.print(
                "ignored empty transcription - probably just noise.", server_only=True
            )

    # called when Azure Speech Recognizer recognized voice
    def on_azure_voice_recognition(self, voice_event):
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

    async def __init_azure_voice_activation(self):
        if self.azure_speech_recognizer or not self.current_config:
            return

        key = await self.secret_keeper.retrieve(
            requester="Voice Activation",
            key="azure_tts",
            prompt_if_missing=True,
        )

        speech_config = speechsdk.SpeechConfig(
            region=self.settings.voice_activation.azure.region.value, subscription=key
        )

        auto_detect_source_language_config = (
            speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
                languages=self.settings.voice_activation.azure.languages
            )
        )

        self.azure_speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            auto_detect_source_language_config=auto_detect_source_language_config,
        )
        self.azure_speech_recognizer.recognized.connect(self.on_azure_voice_recognition)

    async def on_playback_started(self, wingman_name: str):
        await printr.print_async(
            text=f"Playback started ({wingman_name})",
            source_name=wingman_name,
            command_tag=CommandTag.PLAYBACK_STARTED,
        )

        self.was_listening_before_playback = self.is_listening
        if self.settings.voice_activation.enabled and self.is_listening:
            self.start_voice_recognition(mute=True)

    async def on_playback_finished(self, wingman_name: str):
        await printr.print_async(
            text=f"Playback finished ({wingman_name})",
            source_name=wingman_name,
            command_tag=CommandTag.PLAYBACK_STOPPED,
        )

        if (
            self.settings.voice_activation.enabled
            and not self.is_listening
            and self.was_listening_before_playback
        ):
            self.start_voice_recognition()

    async def process_events(self):
        while True:
            callback, wingman_name = await self.event_queue.get()
            await callback(wingman_name)

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

        for error in errors:
            printr.toast_error(error.message)

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
        self.current_config = config
        self.tower = Tower(config=config, audio_player=self.audio_player)

        errors = await self.tower.instantiate_wingmen(
            self.config_manager.settings_config
        )

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

        # Check if the wingman_name is already the default
        already_default = any(
            (
                config.wingmen[file.name].name == wingman_name
                and config.wingmen[file.name].is_voice_activation_default
            )
            for file in wingman_config_files
        )

        for wingman_config_file in wingman_config_files:
            wingman_config = config.wingmen[wingman_config_file.name]

            if already_default:
                # If wingman_name is already default, undefault it
                wingman_config.is_voice_activation_default = False
            else:
                # Set the new default
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

    # GET /audio-devices
    def get_audio_devices(self):
        audio_devices = sd.query_devices()
        return audio_devices

    # GET /settings
    def get_settings(self):
        return self.config_manager.settings_config

    # POST /settings/audio-devices
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

    # POST /settings/voice-activation
    async def set_voice_activation(self, is_enabled: bool):
        if is_enabled:
            if (
                self.settings.voice_activation.stt_provider
                == VoiceActivationSttProvider.AZURE
                and not self.azure_speech_recognizer
            ):
                await self.__init_azure_voice_activation()
        else:
            self.azure_speech_recognizer = None

        self.start_voice_recognition(
            mute=not is_enabled, adjust_for_ambient_noise=is_enabled
        )

        self.config_manager.settings_config.voice_activation.enabled = is_enabled

        if self.config_manager.save_settings_config():
            printr.print(
                f"Voice activation {'enabled' if is_enabled else 'disabled'}.",
                toast=ToastType.NORMAL,
                color=LogType.POSITIVE,
            )

    # POST /settings/mute-key
    def set_mute_key(self, key: str, keycodes: Optional[list[int]] = None):
        self.config_manager.settings_config.voice_activation.mute_toggle_key = key
        self.config_manager.settings_config.voice_activation.mute_toggle_key_codes = (
            keycodes
        )

        if self.config_manager.save_settings_config():
            printr.print(
                "Mute key saved.",
                toast=ToastType.NORMAL,
                color=LogType.POSITIVE,
            )

    # POST /settings/wingman-pro
    async def set_wingman_pro_settings(
        self,
        base_url: str,
        region: WingmanProRegion,
        stt_provider: VoiceActivationSttProvider,
        azure: AzureSttConfig,
        whispercpp: WhispercppSttConfig,
        va_energy_threshold: float,
    ):
        self.config_manager.settings_config.wingman_pro.base_url = base_url
        self.config_manager.settings_config.wingman_pro.region = region

        self.config_manager.settings_config.voice_activation.stt_provider = stt_provider
        self.config_manager.settings_config.voice_activation.azure = azure
        self.config_manager.settings_config.voice_activation.whispercpp = whispercpp

        old_va_threshold = (
            self.config_manager.settings_config.voice_activation.energy_threshold
        )
        self.config_manager.settings_config.voice_activation.energy_threshold = (
            va_energy_threshold
        )

        if self.config_manager.save_settings_config():
            await self.load_config()
            printr.print(
                "Wingman Pro settings updated.",
                toast=ToastType.NORMAL,
                color=LogType.POSITIVE,
            )

        # restart VA with new settings
        if self.is_listening and old_va_threshold != va_energy_threshold:
            self.start_voice_recognition(mute=True)
            self.start_voice_recognition(mute=False, adjust_for_ambient_noise=True)

    # POST /settings/wingman-pro/make-default
    async def set_wingman_pro_as_default(self, patch_existing_wingmen: bool):
        self.config_manager.default_config.features.conversation_provider = (
            "wingman_pro"
        )
        self.config_manager.default_config.features.summarize_provider = "wingman_pro"
        self.config_manager.default_config.features.tts_provider = "wingman_pro"
        self.config_manager.default_config.features.stt_provider = "wingman_pro"

        self.config_manager.save_defaults_config()

        if patch_existing_wingmen:
            config_dirs = self.get_config_dirs()
            for config_dir in config_dirs.config_dirs:
                wingman_config_files = await self.get_wingmen_config_files(
                    config_dir.name
                )
                for wingman_config_file in wingman_config_files:
                    wingman_config = self.config_manager.load_wingman_config(
                        config_dir=config_dir, wingman_file=wingman_config_file
                    )
                    if wingman_config:
                        wingman_config.features.conversation_provider = "wingman_pro"
                        wingman_config.features.summarize_provider = "wingman_pro"
                        wingman_config.features.tts_provider = "wingman_pro"
                        wingman_config.features.stt_provider = "wingman_pro"

                        self.config_manager.save_wingman_config(
                            config_dir=config_dir,
                            wingman_file=wingman_config_file,
                            wingman_config=wingman_config,
                        )
        await self.load_config(self.current_config_dir)

        printr.print(
            "Have fun using Wingman Pro!",
            toast=ToastType.NORMAL,
            color=LogType.POSITIVE,
        )

    # POST /voice-activation/mute
    def start_voice_recognition(
        self,
        mute: Optional[bool] = False,
        adjust_for_ambient_noise: Optional[bool] = False,
    ):
        self.is_listening = not mute
        if self.is_listening:
            if (
                self.settings.voice_activation.stt_provider
                == VoiceActivationSttProvider.AZURE
            ):
                self.azure_speech_recognizer.start_continuous_recognition()
            else:
                if adjust_for_ambient_noise:
                    self.audio_recorder.adjust_for_ambient_noise()
                self.audio_recorder.start_continuous_listening(
                    va_settings=self.settings.voice_activation
                )
        else:
            if (
                self.settings.voice_activation.stt_provider
                == VoiceActivationSttProvider.AZURE
            ):
                self.azure_speech_recognizer.stop_continuous_recognition()
            else:
                self.audio_recorder.stop_continuous_listening()

        command = VoiceActivationMutedCommand(muted=mute)
        self.ensure_async(self._connection_manager.broadcast(command))

    def toggle_voice_recognition(self):
        mute = self.is_listening
        self.start_voice_recognition(mute)

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
        result = [self.__convert_azure_voice(voice) for voice in voices]
        return result

    # GET /voices/azure/wingman-pro
    def get_wingman_pro_azure_voices(self, locale: str = ""):
        wingman_pro = WingmanPro(
            wingman_name="", settings=self.config_manager.settings_config.wingman_pro
        )
        voices = wingman_pro.get_available_voices(locale=locale)
        if not voices:
            return []
        result = [self.__convert_azure_voice(voice) for voice in voices]
        return result

    # POST /play/openai
    async def play_openai_tts(
        self, text: str, api_key: str, voice: OpenAiTtsVoice, sound_config: SoundConfig
    ):
        openai = OpenAi(api_key=api_key)
        await openai.play_audio(
            text=text,
            voice=voice,
            sound_config=sound_config,
            audio_player=self.audio_player,
            wingman_name="system",
        )

    # POST /play/azure
    async def play_azure_tts(
        self, text: str, api_key: str, config: AzureTtsConfig, sound_config: SoundConfig
    ):
        azure = OpenAiAzure()
        await azure.play_audio(
            text=text,
            api_key=api_key,
            config=config,
            sound_config=sound_config,
            audio_player=self.audio_player,
            wingman_name="system",
        )

    # POST /play/elevenlabs
    async def play_elevenlabs_tts(
        self,
        text: str,
        api_key: str,
        config: ElevenlabsConfig,
        sound_config: SoundConfig,
    ):
        elevenlabs = ElevenLabs(api_key=api_key, wingman_name="")
        await elevenlabs.play_audio(
            text=text,
            config=config,
            sound_config=sound_config,
            audio_player=self.audio_player,
            wingman_name="system",
            stream=False,
        )

    # POST /play/edgetts
    async def play_edge_tts(
        self, text: str, config: EdgeTtsConfig, sound_config: SoundConfig
    ):
        edge = Edge()
        await edge.play_audio(
            text=text,
            config=config,
            sound_config=sound_config,
            audio_player=self.audio_player,
            wingman_name="system",
        )

    # POST /play/xvasynth
    async def play_xvasynth_tts(
        self, text: str, config: XVASynthTtsConfig, sound_config: SoundConfig
    ):
        xvasynth = XVASynth(wingman_name="")
        await xvasynth.play_audio(
            text=text,
            config=config,
            sound_config=sound_config,
            audio_player=self.audio_player,
            wingman_name="system",
        )

    # POST /play/wingman-pro/azure
    async def play_wingman_pro_azure(
        self, text: str, config: AzureTtsConfig, sound_config: SoundConfig
    ):
        wingman_pro = WingmanPro(
            wingman_name="system",
            settings=self.config_manager.settings_config.wingman_pro,
        )
        await wingman_pro.generate_azure_speech(
            text=text,
            config=config,
            sound_config=sound_config,
            audio_player=self.audio_player,
            wingman_name="system",
        )

    # POST /play/wingman-pro/azure
    async def play_wingman_pro_openai(
        self, text: str, voice: OpenAiTtsVoice, sound_config: SoundConfig
    ):
        wingman_pro = WingmanPro(
            wingman_name="system",
            settings=self.config_manager.settings_config.wingman_pro,
        )
        await wingman_pro.generate_openai_speech(
            text=text,
            voice=voice,
            sound_config=sound_config,
            audio_player=self.audio_player,
            wingman_name="system",
        )

    # POST /stop-playback
    async def stop_playback(self):
        await self.audio_player.stop_playback()

    def __convert_azure_voice(self, voice):
        # retrieved from Wingman Pro as serialized dict
        if isinstance(voice, dict):
            return VoiceInfo(
                id=voice.get("short_name"),
                name=voice.get("local_name"),
                gender=voice.get("gender"),
                locale=voice.get("locale"),
            )
        # coming directly from Azure API as a voice object
        else:
            return VoiceInfo(
                id=voice.short_name,
                name=voice.local_name,
                gender=voice.gender.name,
                locale=voice.locale,
            )
