import asyncio
import os
import re
import threading
from typing import Optional
from fastapi import APIRouter, File, UploadFile
import sounddevice as sd
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
    AzureSttConfig,
    ConfigWithDirInfo,
    WingmanInitializationError,
)
from providers.open_ai import OpenAi
from providers.whispercpp import Whispercpp
from providers.wingman_pro import WingmanPro
from wingmen.open_ai_wingman import OpenAiWingman
from wingmen.wingman import Wingman
from services.file import get_writable_dir
from services.voice_service import VoiceService
from services.settings_service import SettingsService
from services.config_service import ConfigService
from services.audio_player import AudioPlayer
from services.audio_recorder import RECORDING_PATH, AudioRecorder
from services.config_manager import ConfigManager
from services.printr import Printr
from services.secret_keeper import SecretKeeper
from services.tower import Tower
from services.websocket_user import WebSocketUser


class WingmanCore(WebSocketUser):
    def __init__(self, config_manager: ConfigManager):
        self.printr = Printr()

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
            path="/send_audio-to-wingman",
            endpoint=self.send_audio_to_wingman,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/reset_conversation_history",
            endpoint=self.reset_conversation_history,
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
            "va_treshold_changed", self.on_va_treshold_changed
        )

        self.voice_service = VoiceService(
            config_manager=self.config_manager, audio_player=self.audio_player
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

    async def initialize_tower(self, config_dir_info: ConfigWithDirInfo):
        self.tower = Tower(
            config=config_dir_info.config, audio_player=self.audio_player
        )
        self.tower_errors = await self.tower.instantiate_wingmen(
            self.config_manager.settings_config
        )
        for error in self.tower_errors:
            self.printr.toast_error(error.message)

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
            self.settings_service.settings.voice_activation.mute_toggle_key_codes
            or self.settings_service.settings.voice_activation.mute_toggle_key
        )
        if (
            self.settings_service.settings.voice_activation.enabled
            and is_mute_hotkey_pressed
        ):
            self.toggle_voice_recognition()

        if self.tower and self.active_recording["key"] == "":
            wingman = None
            if key:
                for potential_wingman in self.tower.wingmen:
                    if potential_wingman.get_record_key() and self.is_hotkey_pressed(
                        potential_wingman.get_record_key()
                    ):
                        wingman = potential_wingman
            elif button:
                wingman = self.tower.get_wingman_from_mouse(button)
            if wingman:
                if key:
                    self.active_recording = dict(key=key.name, wingman=wingman)
                elif button:
                    self.active_recording = dict(key=button, wingman=wingman)

                self.was_listening_before_ptt = self.is_listening
                if (
                    self.settings_service.settings.voice_activation.enabled
                    and self.is_listening
                ):
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

            whisperccp = Whispercpp(wingman_name="system")
            transcription = whisperccp.transcribe(
                filename=recording_file,
                config=self.settings_service.settings.voice_activation.whispercpp,
            )
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
        # devices: [output_device, input_device]
        sd.default.device = devices
        self.audio_recorder.update_input_stream()

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

    def on_va_treshold_changed(self, _va_energy_threshold: float):
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
    async def ask_wingman_conversation_provider(self, text: str,  wingman_name: str):
        wingman = self.tower.get_wingman_by_name(wingman_name)

        if wingman and text:
            if isinstance(wingman, OpenAiWingman):
                messages = [
                    {
                        "role": "user",
                        "content": text 
                    }
                ]

                completion = await wingman.actual_llm_call(messages=messages)

                return completion.choices[0].message.content
 
        return None

    # POST /generate-image
    async def generate_image(self, text: str,  wingman_name: str):
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
    def reset_conversation_history(self, wingman_name: Optional[str]):
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
