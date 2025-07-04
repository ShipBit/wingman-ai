import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
import re
import threading
from typing import Optional
import pygame
from google.genai import types
from fastapi import APIRouter, File, UploadFile
import requests
import sounddevice as sd
from showinfm import show_in_file_manager
import azure.cognitiveservices.speech as speechsdk
import keyboard.keyboard as keyboard
import mouse.mouse as mouse
from api.commands import VoiceActivationMutedCommand
from api.enums import (
    AzureRegion,
    CommandTag,
    LogType,
    VoiceActivationSttProvider,
)
from api.interface import (
    AudioDevice,
    AudioFile,
    AzureSttConfig,
    CommandJoystickConfig,
    Config,
    ConfigWithDirInfo,
    ElevenlabsModel,
    OpenRouterEndpointResult,
    VoiceActivationSettings,
    WingmanInitializationError,
)
from providers.elevenlabs import ElevenLabs
from providers.faster_whisper import FasterWhisper
from providers.google import GoogleGenAI
from providers.open_ai import OpenAi
from providers.whispercpp import Whispercpp
from providers.wingman_pro import WingmanPro
from providers.xvasynth import XVASynth
from wingmen.open_ai_wingman import OpenAiWingman
from wingmen.wingman import Wingman
from services.file import get_writable_dir
from services.voice_service import VoiceService
from services.settings_service import SettingsService
from services.config_service import ConfigService
from services.audio_player import AudioPlayer
from services.audio_library import AudioLibrary
from services.audio_recorder import RECORDING_PATH, AudioRecorder
from services.config_manager import ConfigManager
from services.printr import Printr
from services.secret_keeper import SecretKeeper
from services.tower import Tower
from services.websocket_user import WebSocketUser


class WingmanCore(WebSocketUser):
    def __init__(
        self, config_manager: ConfigManager, app_root_path: str, app_is_bundled: bool
    ):
        self.printr = Printr()
        self.app_root_path = app_root_path
        self.is_client_logged_in: bool = False
        self.is_client_pro: bool = False
        self.client_account_name: str = ""

        self.router = APIRouter()
        tags = ["core"]
        self.router.add_api_route(
            methods=["GET"],
            path="/audio-devices",
            endpoint=self.get_audio_devices,
            response_model=list[AudioDevice],
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/voice-activation/mute",
            endpoint=self.start_voice_recognition,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/startup-errors",
            endpoint=self.get_startup_errors,
            response_model=list[WingmanInitializationError],
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/stop-playback",
            endpoint=self.stop_playback,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/send-text-to-wingman",
            endpoint=self.send_text_to_wingman,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/ask-wingman-conversation-provider",
            endpoint=self.ask_wingman_conversation_provider,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/generate-image",
            endpoint=self.generate_image,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/send-audio-to-wingman",
            endpoint=self.send_audio_to_wingman,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/reset-conversation-history",
            endpoint=self.reset_conversation_history,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/fasterwhisper/modelsizes",
            response_model=list[str],
            endpoint=self.get_fasterwhisper_modelsizes,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/fasterwhisper/computetypes",
            response_model=list[str],
            endpoint=self.get_fasterwhisper_computetypes,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/fasterwhisper/devices",
            response_model=list[str],
            endpoint=self.get_fasterwhisper_devices,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/xvasynth/start",
            endpoint=self.start_xvasynth,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/xvasynth/stop",
            endpoint=self.stop_xvasynth,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/xvsynth/model_dirs",
            response_model=list[str],
            endpoint=self.get_xvasynth_model_dirs,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/xvsynth/voices",
            response_model=list[str],
            endpoint=self.get_xvasynth_voices,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/open-filemanager",
            endpoint=self.open_file_manager,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/open-filemanager/config",
            endpoint=self.open_config_directory,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/open-filemanager/logs",
            endpoint=self.open_logs_directory,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/open-filemanager/audio-library",
            endpoint=self.open_audio_library_directory,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/openrouter",
            response_model=list,
            endpoint=self.get_openrouter_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/openrouter/endpoints",
            response_model=Optional[OpenRouterEndpointResult],
            endpoint=self.get_openrouter_model_endpoints,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/groq",
            response_model=list,
            endpoint=self.get_groq_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/cerebras",
            response_model=list,
            endpoint=self.get_cerebras_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/openai",
            response_model=list,
            endpoint=self.get_openai_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/elevenlabs",
            response_model=list[ElevenlabsModel],
            endpoint=self.get_elevenlabs_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/google",
            response_model=list[types.Model],
            endpoint=self.get_google_models,
            tags=tags,
        )
        # TODO: Refactor - move these to a new AudioLibrary service:
        self.router.add_api_route(
            methods=["GET"],
            path="/audio-library",
            response_model=list[AudioFile],
            endpoint=self.get_audio_library,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/audio-library/play",
            endpoint=self.play_from_audio_library,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/elevenlabs/generate-sfx",
            endpoint=self.generate_sfx_elevenlabs,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/elevenlabs/subscription-data",
            endpoint=self.get_elevenlabs_subscription_data,
            response_model=dict,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/shutdown",
            endpoint=self.shutdown,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/wingman-pro",
            response_model=list,
            endpoint=self.get_wingman_pro_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/regions/wingman-pro",
            response_model=list,
            endpoint=self.get_wingman_pro_regions,
            tags=tags,
        )

        self.config_manager = config_manager
        self.config_service = ConfigService(config_manager=config_manager)
        self.config_service.config_events.subscribe(
            "config_loaded", self.initialize_tower
        )

        self.secret_keeper: SecretKeeper = SecretKeeper()

        self.event_queue = asyncio.Queue()
        self.audio_player = AudioPlayer(
            event_queue=self.event_queue,
            on_playback_started=self.on_playback_started,
            on_playback_finished=self.on_playback_finished,
        )
        self.audio_library = AudioLibrary()

        self.tower: Tower = None

        self.active_recording = {"key": "", "wingman": None}

        self.is_started = False
        self.startup_errors: list[WingmanInitializationError] = []
        self.tower_errors: list[WingmanInitializationError] = []

        self.azure_speech_recognizer: speechsdk.SpeechRecognizer = None
        self.is_listening = False
        self.was_listening_before_ptt = False
        self.was_listening_before_playback = False

        self.key_events = {}

        self.settings_service = SettingsService(
            config_manager=config_manager, config_service=self.config_service
        )
        self.settings_service.settings_events.subscribe(
            "audio_devices_changed", self.on_audio_devices_changed
        )
        self.settings_service.settings_events.subscribe(
            "voice_activation_changed", self.set_voice_activation
        )
        self.settings_service.settings_events.subscribe(
            "va_settings_changed", self.on_va_settings_changed
        )

        self.whispercpp = Whispercpp(
            settings=self.settings_service.settings.voice_activation.whispercpp,
        )
        self.fasterwhisper = FasterWhisper(
            settings=self.settings_service.settings.voice_activation.fasterwhisper,
            app_root_path=app_root_path,
            app_is_bundled=app_is_bundled,
        )
        self.xvasynth = XVASynth(settings=self.settings_service.settings.xvasynth)
        self.settings_service.initialize(
            whispercpp=self.whispercpp,
            fasterwhisper=self.fasterwhisper,
            xvasynth=self.xvasynth,
        )

        self.voice_service = VoiceService(
            config_manager=self.config_manager,
            audio_player=self.audio_player,
            xvasynth=self.xvasynth,
        )

        # restore settings
        self.audio_recorder = AudioRecorder(
            on_speech_recorded=self.on_audio_recorder_speech_recorded
        )

        if self.settings_service.settings.audio:
            sd.default.device = [
                self.settings_service.settings.audio.input,
                self.settings_service.settings.audio.output,
            ]
            self.audio_recorder.update_input_stream()

    async def startup(self):
        if self.settings_service.settings.voice_activation.enabled:
            await self.set_voice_activation(is_enabled=True)

    def is_mouse_configured(self, config: Config) -> bool:
        return any(
            config.wingmen[wingman].record_mouse_button for wingman in config.wingmen
        )

    def is_joystick_configured(self, config: Config) -> bool:
        return any(
            config.wingmen[wingman].record_joystick_button for wingman in config.wingmen
        )

    async def start_joysticks(self, config: Config):
        pygame.init()

        # Get all joystick configs
        joystick_configs = [
            config.wingmen[wingman].record_joystick_button
            for wingman in config.wingmen
            if config.wingmen[wingman].record_joystick_button
        ]

        joysticks = [
            pygame.joystick.Joystick(x) for x in range(pygame.joystick.get_count())
        ]
        for joystick in joysticks:
            if any(
                [
                    joystick.get_guid() == joystick_config.guid
                    for joystick_config in joystick_configs
                ]
            ):
                joystick.init()

        running = True
        while running and pygame.joystick.get_init():
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.JOYBUTTONDOWN:
                    joystick_origin = pygame.joystick.Joystick(event.joy)
                    for joystick_config in joystick_configs:
                        if joystick_origin.get_guid() == joystick_config.guid:
                            self.on_press(
                                joystick_config=CommandJoystickConfig(
                                    guid=joystick_config.guid, button=event.button
                                )
                            )
                elif event.type == pygame.JOYBUTTONUP:
                    joystick_origin = pygame.joystick.Joystick(event.joy)
                    for joystick_config in joystick_configs:
                        if joystick_origin.get_guid() == joystick_config.guid:
                            self.on_release(
                                joystick_config=CommandJoystickConfig(
                                    guid=joystick_config.guid, button=event.button
                                )
                            )

            # Add a small sleep to prevent the loop from consuming too much CPU
            await asyncio.sleep(0.01)

    def init_joystick(self, config: Config):

        def run_async_process():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # Create a task for start_joysticks instead of running it directly
                loop.create_task(self.start_joysticks(config))
                # Run the event loop forever instead of running until complete
                loop.run_forever()
            finally:
                loop.close()

        play_thread = threading.Thread(target=run_async_process)
        play_thread.start()

    async def initialize_tower(self, config_dir_info: ConfigWithDirInfo):
        if not self.is_client_logged_in:
            self.printr.print(
                "Client not logged in yet - skipping Tower initialization.",
                color=LogType.WARNING,
                server_only=True,
            )
            return

        await self.unload_tower()

        config = config_dir_info.config

        # Register hooks
        if self.is_mouse_configured(config):
            mouse.hook(self.on_mouse)
        if self.is_joystick_configured(config):
            self.init_joystick(config)

        self.tower = Tower(
            config=config,
            config_dir=config_dir_info.config_dir,
            config_manager=self.config_manager,
            audio_player=self.audio_player,
            audio_library=self.audio_library,
            whispercpp=self.whispercpp,
            fasterwhisper=self.fasterwhisper,
            xvasynth=self.xvasynth,
        )
        self.tower_errors = await self.tower.instantiate_wingmen(
            self.config_manager.settings_config
        )
        for error in self.tower_errors:
            self.printr.toast_error(error.message)

        self.config_service.set_tower(self.tower)
        self.printr.print(
            "Tower initializated.",
            color=LogType.POSITIVE,
            server_only=True,
        )

    async def unload_tower(self):
        if self.tower:
            for wingman in self.tower.wingmen:
                await wingman.unload()
            self.tower = None
            self.config_service.set_tower(None)
            self.printr.print(
                "Tower unloaded.",
                server_only=True,
            )

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

    def on_press(
        self, key=None, mouse_button=None, joystick_config: CommandJoystickConfig = None
    ):
        is_mute_hotkey_pressed = self.is_hotkey_pressed(
            self.settings_service.settings.voice_activation.mute_toggle_key_codes
            or self.settings_service.settings.voice_activation.mute_toggle_key
        )
        if (
            self.settings_service.settings.voice_activation.enabled
            and is_mute_hotkey_pressed
        ):
            self.toggle_voice_recognition()

        is_cancel_tts_hotkey_pressed = self.is_hotkey_pressed(
            self.settings_service.settings.cancel_tts_key_codes
            or self.settings_service.settings.cancel_tts_key
        )
        if is_cancel_tts_hotkey_pressed:
            self.ensure_async(self.stop_playback())

        if self.tower and self.active_recording["key"] == "":
            wingman = None
            for potential_wingman in self.tower.wingmen:
                if key:
                    if potential_wingman.get_record_key() and self.is_hotkey_pressed(
                        potential_wingman.get_record_key()
                    ):
                        wingman = potential_wingman
                        break
                if mouse_button:
                    if potential_wingman.get_record_mouse_button() == mouse_button:
                        wingman = potential_wingman
                        break
                if joystick_config:
                    if (
                        potential_wingman.get_record_joystick_button()
                        == f"{joystick_config.guid}{joystick_config.button}"
                    ):
                        wingman = potential_wingman
                        break

            if wingman:
                if key:
                    self.active_recording = dict(key=key.name, wingman=wingman)
                elif mouse_button:
                    self.active_recording = dict(key=mouse_button, wingman=wingman)
                elif joystick_config:
                    self.active_recording = dict(
                        key=f"{joystick_config.guid}{joystick_config.button}",
                        wingman=wingman,
                    )

                self.was_listening_before_ptt = self.is_listening
                if (
                    self.settings_service.settings.voice_activation.enabled
                    and self.is_listening
                ):
                    self.start_voice_recognition(mute=True)

                self.audio_recorder.start_recording(wingman_name=wingman.name)

    def on_release(
        self, key=None, mouse_button=None, joystick_config: CommandJoystickConfig = None
    ):
        if self.tower and (
            key is not None
            and self.active_recording["key"] == key.name
            or self.active_recording["key"] == mouse_button
            or (
                joystick_config
                and self.active_recording["key"]
                == f"{joystick_config.guid}{joystick_config.button}"
            )
        ):
            wingman = self.active_recording["wingman"]
            recorded_audio_wav = self.audio_recorder.stop_recording(
                wingman_name=wingman.name
            )
            self.active_recording = {"key": "", "wingman": None}

            if (
                self.settings_service.settings.voice_activation.enabled
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
            self.on_press(mouse_button=event.button)
        elif event.event_type == "up":
            self.on_release(mouse_button=event.button)

    # called when AudioRecorder regonized voice
    def on_audio_recorder_speech_recorded(self, recording_file: str):
        def run_async_process():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(wingman.process(transcript=text))
            finally:
                loop.close()

        provider = self.settings_service.settings.voice_activation.stt_provider
        text = None

        if provider == VoiceActivationSttProvider.WINGMAN_PRO:
            wingman_pro = WingmanPro(
                wingman_name="system",
                settings=self.settings_service.settings.wingman_pro,
            )
            transcription = wingman_pro.transcribe_azure_speech(
                filename=recording_file,
                config=AzureSttConfig(
                    languages=self.settings_service.settings.voice_activation.azure.languages,
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

            transcription = self.whispercpp.transcribe(
                filename=recording_file,
                config=self.settings_service.settings.voice_activation.whispercpp_config,
            )
            if transcription:
                cleaned, text = filter_and_clean_text(transcription.text)
                if cleaned:
                    self.printr.print(
                        f"Cleaned original transcription: {transcription.text}",
                        server_only=True,
                        color=LogType.SUBTLE,
                    )
        elif provider == VoiceActivationSttProvider.OPENAI:
            # TODO: can't await secret_keeper.retrieve here, so just assume the secret is there...
            openai = OpenAi(api_key=self.secret_keeper.secrets["openai"])
            transcription = openai.transcribe(filename=recording_file)
            text = transcription.text
        elif provider == VoiceActivationSttProvider.FASTER_WHISPER:
            combined_hotwords: list[str] = []

            # add the default hotwords from settings
            default_hotwords = (
                self.settings_service.settings.voice_activation.fasterwhisper_config.hotwords
            )
            if default_hotwords and len(default_hotwords) > 0:
                combined_hotwords.extend(default_hotwords)

            for wingman in self.tower.wingmen:
                # add the wingman names explicitly
                combined_hotwords.append(wingman.name)
                # and their additional hotwords
                wingman_hotwords = wingman.config.fasterwhisper.additional_hotwords
                if wingman_hotwords and len(wingman_hotwords) > 0:
                    combined_hotwords.extend(wingman_hotwords)

            transcription = self.fasterwhisper.transcribe(
                config=self.settings_service.settings.voice_activation.fasterwhisper_config,
                filename=recording_file,
                hotwords=list(set(combined_hotwords)),
            )
            text = transcription.text

        if text:
            wingman = self.tower.get_wingman_from_text(text)
            if wingman:
                play_thread = threading.Thread(target=run_async_process)
                play_thread.start()
        else:
            self.printr.print(
                "ignored empty transcription - probably just noise.", server_only=True
            )

    async def on_audio_devices_changed(self, devices: tuple[int | None, int | None]):
        # devices: [input_device, output_device]

        # get current audio devices
        current_mic = sd.default.device[0]

        # set new devices
        sd.default.device = devices

        # update input stream if the input device has changed
        if current_mic != devices[0]:
            self.audio_recorder.valid_mic = True  # this allows a new error message
            self.audio_recorder.update_input_stream()
            if self.is_listening:
                self.start_voice_recognition(mute=True)
                self.start_voice_recognition(mute=False, adjust_for_ambient_noise=True)

    async def set_voice_activation(self, is_enabled: bool):
        if is_enabled:
            if (
                self.settings_service.settings.voice_activation.stt_provider
                == VoiceActivationSttProvider.AZURE
                and not self.azure_speech_recognizer
            ):
                await self.__init_azure_voice_activation()
        else:
            self.start_voice_recognition(mute=True)
            self.azure_speech_recognizer = None

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
        if self.azure_speech_recognizer or not self.config_service.current_config:
            return

        key = await self.secret_keeper.retrieve(
            requester="Voice Activation",
            key="azure_tts",
            prompt_if_missing=True,
        )

        speech_config = speechsdk.SpeechConfig(
            region=self.settings_service.settings.voice_activation.azure.region.value,
            subscription=key,
        )

        auto_detect_source_language_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=self.settings_service.settings.voice_activation.azure.languages
        )

        self.azure_speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            auto_detect_source_language_config=auto_detect_source_language_config,
        )
        self.azure_speech_recognizer.recognized.connect(self.on_azure_voice_recognition)

    async def on_playback_started(self, wingman_name: str):
        await self.printr.print_async(
            text=f"Playback started ({wingman_name})",
            source_name=wingman_name,
            command_tag=CommandTag.PLAYBACK_STARTED,
        )

        self.was_listening_before_playback = self.is_listening
        if (
            self.settings_service.settings.voice_activation.enabled
            and self.is_listening
        ):
            self.start_voice_recognition(mute=True)

    async def on_playback_finished(self, wingman_name: str):
        await self.printr.print_async(
            text=f"Playback finished ({wingman_name})",
            source_name=wingman_name,
            command_tag=CommandTag.PLAYBACK_STOPPED,
        )

        if (
            self.settings_service.settings.voice_activation.enabled
            and not self.is_listening
            and self.was_listening_before_playback
        ):
            self.start_voice_recognition()

    async def process_events(self):
        while True:
            callback, wingman_name = await self.event_queue.get()
            await callback(wingman_name)

    def on_va_settings_changed(self, _va_settings: VoiceActivationSettings):
        # restart VA with new settings
        if self.is_listening:
            self.start_voice_recognition(mute=True)
            self.start_voice_recognition(mute=False, adjust_for_ambient_noise=True)

    def start_voice_recognition(
        self,
        mute: Optional[bool] = False,
        adjust_for_ambient_noise: Optional[bool] = False,
    ):
        self.is_listening = not mute
        if self.is_listening:
            if (
                self.settings_service.settings.voice_activation.stt_provider
                == VoiceActivationSttProvider.AZURE
            ):
                self.azure_speech_recognizer.start_continuous_recognition()
            else:
                if adjust_for_ambient_noise:
                    self.audio_recorder.adjust_for_ambient_noise()
                self.audio_recorder.start_continuous_listening(
                    va_settings=self.settings_service.settings.voice_activation
                )
        else:
            if (
                self.settings_service.settings.voice_activation.stt_provider
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

    # GET /audio-devices
    def get_audio_devices(self):
        audio_devices = sd.query_devices()
        return audio_devices

    # GET /startup-errors
    def get_startup_errors(self):
        return self.startup_errors

    # POST /stop-playback
    async def stop_playback(self):
        await self.audio_player.stop_playback()

    # POST /ask-wingman-conversation-provider
    async def ask_wingman_conversation_provider(self, text: str, wingman_name: str):
        wingman = self.tower.get_wingman_by_name(wingman_name)

        if wingman and text:
            if isinstance(wingman, OpenAiWingman):
                messages = [{"role": "user", "content": text}]

                completion = await wingman.actual_llm_call(messages=messages)

                return completion.choices[0].message.content

        return None

    # POST /generate-image
    async def generate_image(self, text: str, wingman_name: str):
        wingman = self.tower.get_wingman_by_name(wingman_name)

        if wingman and text:
            if isinstance(wingman, OpenAiWingman):
                return await wingman.generate_image(text=text)

        return None

    # POST /send-text-to-wingman
    async def send_text_to_wingman(self, text: str, wingman_name: str):
        wingman = self.tower.get_wingman_by_name(wingman_name)

        def run_async_process():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(wingman.process(transcript=text))
            finally:
                loop.close()

        if wingman and text:
            play_thread = threading.Thread(target=run_async_process)
            play_thread.start()

    # POST /send-audio-to-wingman
    async def send_audio_to_wingman(
        self, wingman_name: str, file: UploadFile = File(...)
    ):
        wingman = self.tower.get_wingman_by_name(wingman_name)
        if not wingman:
            return

        contents = await file.read()

        filename = os.path.join(
            get_writable_dir(RECORDING_PATH), "client_recording.wav"
        )
        with open(filename, "wb") as f:
            f.write(contents)

        def run_async_process():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                if isinstance(wingman, Wingman):
                    loop.run_until_complete(
                        wingman.process(audio_input_wav=str(filename))
                    )
            finally:
                loop.close()

        if filename:
            play_thread = threading.Thread(target=run_async_process)
            play_thread.start()

    # POST /reset-conversation-history
    def reset_conversation_history(self, wingman_name: Optional[str] = None):
        if wingman_name:
            wingman = self.tower.get_wingman_by_name(wingman_name)
            if wingman:
                wingman.reset_conversation_history()
                self.printr.toast(
                    f"Conversation history cleared for {wingman_name}.",
                )
        else:
            for wingman in self.tower.wingmen:
                wingman.reset_conversation_history()
            self.printr.toast(
                "Conversation history cleared.",
            )
        return True

    # GET /fasterwhisper/modelsizes
    def get_fasterwhisper_modelsizes(self):
        model_sizes = [
            "tiny",
            "tiny.en",
            "base",
            "base.en",
            "small",
            "small.en",
            "distil-small.en",
            "medium",
            "medium.en",
            "distil-medium.en",
            "large-v1",
            "large-v2",
            "large-v3",
            "large",
            "distil-large-v2",
            "distil-large-v3",
            "large-v3-turbo",
            "turbo",
        ]
        return model_sizes

    # GET /fasterwhisper/computetypes
    def get_fasterwhisper_computetypes(self):
        compute_types = [
            "default",
            "auto",
            "int8",
            "int16",
            "int8_float16",
            "int8_float32",
            "float16",
            "float32",
        ]
        return compute_types

    # GET /fasterwhisper/devices
    def get_fasterwhisper_devices(self):
        devices = [
            "auto",
            "cpu",
            "cuda",
        ]
        return devices

    # POST /xvasynth/start
    def start_xvasynth(self):
        self.xvasynth.start_server()

    # POST /xvasynth/stop
    def stop_xvasynth(self):
        try:
            self.xvasynth.stop_server()
        except Exception:
            pass

    def get_xvasynth_model_dirs(self):
        subfolders = []
        try:
            subfolders = [
                dir.name for dir in os.scandir(self.xvasynth.models_dir) if dir.is_dir()
            ]
        except Exception:
            pass

        return subfolders

    def get_xvasynth_voices(self, model_directory: str):
        voices = []
        directory = os.path.join(self.xvasynth.models_dir, model_directory)
        try:
            # listing all files in the directory
            files = [
                f
                for f in os.listdir(directory)
                if os.path.isfile(os.path.join(directory, f))
            ]

            # extracting unique base filenames
            unique_base_filenames = set(os.path.splitext(f)[0] for f in files)
            voices = list(unique_base_filenames)
        except Exception:
            # this can fail:
            # - on MacOS (always)
            # - in Dev mode if the dev hasn't copied the whispercpp-models dir to the repository
            # in these cases, we return an empty list and the client will lock the controls and show a warning.
            pass
        return voices

    # POST /open-filemanager
    def open_file_manager(self, path: str):
        show_in_file_manager(path)

    # POST /open-filemanager/config
    def open_config_directory(self, config_name: str):
        show_in_file_manager(self.config_manager.get_config_dir_path(config_name))

    # POST /open-filemanager/logs
    def open_logs_directory(self):
        show_in_file_manager(get_writable_dir("logs"))

    # POST /open-filemanager/audio-library
    def open_audio_library_directory(self):
        show_in_file_manager(get_writable_dir("audio_library"))

    # GET /models/openrouter
    async def get_openrouter_models(self):
        response = requests.get(url="https://openrouter.ai/api/v1/models", timeout=10)
        response.raise_for_status()
        content = response.json()
        return content.get("data", [])

    # GET /models/openrouter/endpoints
    async def get_openrouter_model_endpoints(self, model_id: str):
        if not model_id:
            return None
        response = requests.get(
            url=f"https://openrouter.ai/api/v1/models/{model_id}/endpoints",
            timeout=10,
        )
        response.raise_for_status()
        content = response.json()
        result = OpenRouterEndpointResult(**content.get("data", {}))
        return result

    # GET /models/groq
    async def get_groq_models(self):
        groq_api_key = await self.secret_keeper.retrieve(key="groq", requester="Groq")
        response = requests.get(
            url="https://api.groq.com/openai/v1/models",
            timeout=10,
            headers={
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        content = response.json()
        return content.get("data", [])

    async def get_cerebras_models(self):
        cerebras_api_key = await self.secret_keeper.retrieve(
            key="cerebras", requester="Cerebras"
        )
        response = requests.get(
            url="https://api.cerebras.ai/v1/models",
            timeout=10,
            headers={
                "Authorization": f"Bearer {cerebras_api_key}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        content = response.json()
        return content.get("data", [])

    async def get_openai_models(self):
        openai_api_key = await self.secret_keeper.retrieve(
            key="openai", requester="OpenAI"
        )
        response = requests.get(
            url="https://api.openai.com/v1/models",
            timeout=10,
            headers={
                "Authorization": f"Bearer {openai_api_key}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        content = response.json()
        return content.get("data", [])

    async def get_wingman_pro_models(self):
        wingman_pro_token = await self.secret_keeper.retrieve(
            key="wingman_pro", requester="WingmanPro"
        )
        response = requests.get(
            url=f"{self.settings_service.settings.wingman_pro.base_url}/wingman-pro-models",
            params={"region": self.settings_service.settings.wingman_pro.region},
            timeout=10,
            headers={
                "Authorization": f"Bearer {wingman_pro_token}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        model_list = response.json()
        return model_list

    async def get_wingman_pro_regions(self):
        wingman_pro_token = await self.secret_keeper.retrieve(
            key="wingman_pro", requester="WingmanPro"
        )
        response = requests.get(
            url=f"{self.settings_service.settings.wingman_pro.base_url}/wingman-pro-regions",
            params={"region": self.settings_service.settings.wingman_pro.region},
            timeout=10,
            headers={
                "Authorization": f"Bearer {wingman_pro_token}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        model_list = response.json()
        return model_list

    # GET /models/elevenlabs
    async def get_elevenlabs_models(self) -> list[ElevenlabsModel]:
        elevenlabs_api_key = await self.secret_keeper.retrieve(
            key="elevenlabs", requester="Elevenlabs"
        )
        elevenlabs = ElevenLabs(api_key=elevenlabs_api_key, wingman_name="")
        try:
            models = elevenlabs.get_available_models()

            convert = lambda model: ElevenlabsModel(
                name=model.name,
                model_id=model.modelID,
                description=model.description,
                max_characters=model.maxCharacters,
                cost_factor=model.costFactor,
                supported_languages=model.supportedLanguages,
                metadata=model.metadata,
            )
            result = [convert(model) for model in models]
            return result
        except ValueError as e:
            self.printr.toast_error(f"Elevenlabs: \n{str(e)}")
            return []

    # GET /models/google
    async def get_google_models(self) -> list[types.Model]:
        google_api_key = await self.secret_keeper.retrieve(
            key="google", requester="Google"
        )
        google = GoogleGenAI(api_key=google_api_key)
        try:
            models = google.get_available_models()
            return models
        except ValueError as e:
            self.printr.toast_error(f"Google: \n{str(e)}")
            return []

    # GET /audio-library
    async def get_audio_library(self):
        return self.audio_library.get_audio_files()

    # POST /audio-library/play
    async def play_from_audio_library(
        self, name: str, path: str, volume: Optional[float] = 1.0
    ):
        await self.audio_library.audio_library_toggle_play(
            audio_file=AudioFile(name=name, path=path), volume_modifier=volume
        )

    # POST /elevenlabs/generate-sfx
    async def generate_sfx_elevenlabs(
        self,
        prompt: str,
        path: str,
        name: str,
        duration_seconds: Optional[float] = None,
        prompt_influence: Optional[float] = None,
    ):
        elevenlabs_api_key = await self.secret_keeper.retrieve(
            key="elevenlabs", requester="Elevenlabs"
        )
        elevenlabs = ElevenLabs(api_key=elevenlabs_api_key, wingman_name="")
        try:
            audio_bytes = await elevenlabs.generate_sound_effect(
                prompt=prompt,
                duration_seconds=duration_seconds,
                prompt_influence=prompt_influence,
            )

            if not name.endswith(".mp3"):
                name += ".mp3"

            directory = get_writable_dir(os.path.join("audio_library", path))

            if os.path.exists(os.path.join(directory, name)):

                def get_unique_filename(directory: str, filename: str) -> str:
                    base, extension = os.path.splitext(filename)
                    counter = 1
                    while os.path.exists(os.path.join(directory, filename)):
                        filename = f"{base}-{counter}{extension}"
                        counter += 1
                    return filename

                name = get_unique_filename(directory, name)

            with open(os.path.join(directory, name), "wb") as f:
                f.write(audio_bytes)

            await self.audio_library.start_playback(
                audio_file=AudioFile(name=name, path=path)
            )
        except ValueError as e:
            self.printr.toast_error(f"Elevenlabs: \n{str(e)}")
            return False

        return True

    # GET /elevenlabs/subscription-data
    async def get_elevenlabs_subscription_data(self):
        elevenlabs_api_key = await self.secret_keeper.retrieve(
            key="elevenlabs", requester="Elevenlabs"
        )
        elevenlabs = ElevenLabs(api_key=elevenlabs_api_key, wingman_name="")
        try:
            # Run the synchronous method in a separate thread
            loop = asyncio.get_running_loop()
            with ThreadPoolExecutor() as pool:
                data = await loop.run_in_executor(
                    pool, elevenlabs.get_subscription_data
                )
            return data
        except ValueError as e:
            self.printr.toast_error(f"Elevenlabs: \n{str(e)}")

    async def shutdown(self):
        if self.settings_service.settings.xvasynth.enable:
            await self.stop_xvasynth()
        await self.unload_tower()

        self.printr.print(
            "Core shutdown.",
            server_only=True,
            color=LogType.SUBTLE,
        )
