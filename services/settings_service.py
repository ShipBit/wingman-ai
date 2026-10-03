from copy import deepcopy
from typing import Optional
from fastapi import APIRouter
from services import audio_backend as sd
from api.enums import LogType, ToastType
from api.interface import (
    AudioSettings,
    AudioDeviceSettings,
    SettingsConfig,
)
from providers.faster_whisper import FasterWhisper
from providers.whispercpp import Whispercpp
from providers.xvasynth import XVASynth
from providers.pocket_tts import PocketTTS
from services.config_manager import ConfigManager
from services.config_service import ConfigService
from services.printr import Printr
from services.pub_sub import PubSub


class SettingsService:
    def __init__(self, config_manager: ConfigManager, config_service: ConfigService):
        self.printr = Printr()
        self.config_manager = config_manager
        self.config_service = config_service
        self.converted_audio_settings = False
        try:
            sd.supervisor.reconcile()
        except Exception as exc:
            sd.supervisor.report("devices", f"recovering ({exc})")
        sd.supervisor.configure(config_manager.settings_config.audio)
        self.settings = config_manager.settings_config
        self.settings_events = PubSub()
        self.whispercpp: Whispercpp = None
        self.fasterwhisper: FasterWhisper = None
        self.xvasynth: XVASynth = None
        self.pocket_tts: PocketTTS = None

        self.router = APIRouter()
        tags = ["settings"]

        self.router.add_api_route(
            methods=["GET"],
            path="/settings",
            endpoint=self.get_settings,
            response_model=SettingsConfig,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings",
            endpoint=self.save_settings,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/audio-devices",
            endpoint=self.set_audio_devices,
            tags=tags,
        )

    def initialize(
        self,
        whispercpp: Whispercpp,
        fasterwhisper: FasterWhisper,
        xvasynth: XVASynth,
        pocket_tts: PocketTTS,
    ):
        self.whispercpp = whispercpp
        self.fasterwhisper = fasterwhisper
        self.xvasynth = xvasynth
        self.pocket_tts = pocket_tts

    # GET /settings
    def get_settings(self):
        config = deepcopy(self.config_manager.settings_config)
        config.audio = self._get_audio_settings_indexed(
            not self.converted_audio_settings
        )
        self.converted_audio_settings = True
        return config

    # POST /settings
    async def save_settings(self, settings: SettingsConfig):
        old = self.get_settings()

        # audio devices
        if (
            (settings.audio is not None and old.audio is None)
            or (settings.audio is None and old.audio is not None)
            or (
                settings.audio is not None
                and old.audio is not None
                and (
                    settings.audio.input != old.audio.input
                    or settings.audio.output != old.audio.output
                )
            )
        ):
            saved_audio = self.config_manager.settings_config.audio
            preferences = {}
            for direction in ("input", "output"):
                value = getattr(settings.audio, direction, None)
                # An unchanged None in the UI can represent a missing preferred device.
                preferences[direction] = (getattr(saved_audio, direction, None)
                    if value == getattr(old.audio, direction, None)
                    else self._device_preference(value, direction))
            await self._save_audio_preferences(AudioSettings(**preferences))

        # whispercpp
        if not self.whispercpp:
            self.printr.toast_error(
                "Whispercpp is not initialized. Please run SettingsService.initialize()",
            )
            return
        self.whispercpp.update_settings(settings=settings.voice_activation.whispercpp)

        # FasterWhisper
        if not self.fasterwhisper:
            self.printr.toast_error(
                "FasterWhisper is not initialized. Please run SettingsService.initialize()",
            )
            return
        self.fasterwhisper.update_settings(
            settings=settings.voice_activation.fasterwhisper
        )

        # XVASynth
        if not self.xvasynth:
            self.printr.toast_error(
                "XVASynth is not initialized. Please run SettingsService.initialize()",
            )
            return
        self.xvasynth.update_settings(settings=settings.xvasynth)
        self.config_manager.settings_config.xvasynth = settings.xvasynth

        # PocketTTS
        if not self.pocket_tts:
            self.printr.toast_error(
                "PocketTTS is not initialized. Please run SettingsService.initialize()",
            )
            return
        self.pocket_tts.update_settings(settings=settings.pocket_tts)
        self.config_manager.settings_config.pocket_tts = settings.pocket_tts

        # voice activation
        self.config_manager.settings_config.voice_activation = settings.voice_activation

        if settings.voice_activation.enabled != old.voice_activation.enabled:
            await self.settings_events.publish(
                "voice_activation_changed", settings.voice_activation.enabled
            )
            self.printr.print(
                f"Voice activation {'enabled' if settings.voice_activation.enabled else 'disabled'}.",
                server_only=True,
            )

        if (
            settings.voice_activation.energy_threshold
            != old.voice_activation.energy_threshold
            or settings.voice_activation.stt_provider
            != old.voice_activation.stt_provider
        ):
            await self.settings_events.publish(
                "va_settings_changed", settings.voice_activation
            )
            self.printr.print("Voice Activation settings changed.", server_only=True)

        # rest
        self.config_manager.settings_config.wingman_pro = settings.wingman_pro
        self.config_manager.settings_config.debug_mode = settings.debug_mode
        self.config_manager.settings_config.streamer_mode = settings.streamer_mode

        # cancel TTS ("shut up") bindings
        self.config_manager.settings_config.cancel_tts_key = settings.cancel_tts_key
        self.config_manager.settings_config.cancel_tts_key_codes = (
            settings.cancel_tts_key_codes
        )
        self.config_manager.settings_config.cancel_tts_joystick_button = (
            settings.cancel_tts_joystick_button
        )

        # HUD server
        self.config_manager.settings_config.hud_server = settings.hud_server
        if settings.hud_server != old.hud_server:
            await self.settings_events.publish(
                "hud_server_settings_changed", settings.hud_server
            )

        # save the config file
        self.config_manager.save_settings_config()

        # update running wingmen
        for wingman in self.config_service.tower.wingmen:
            await wingman.update_settings(settings=self.config_manager.settings_config)

    async def set_audio_devices(
        self, input_device: Optional[int] = None, output_device: Optional[int] = None
    ):
        await self._save_audio_preferences(AudioSettings(
            input=self._device_preference(input_device, "input"),
            output=self._device_preference(output_device, "output")))

    def _device_preference(self, value, direction):
        if value is None or isinstance(value, AudioDeviceSettings):
            return value
        device = sd.query_devices(value)
        key = "max_input_channels" if direction == "input" else "max_output_channels"
        if not device[key]:
            raise ValueError(f"Selected device has no {direction} channels")
        return AudioDeviceSettings(name=device["name"], hostapi=device["hostapi"])

    async def _save_audio_preferences(self, preferences):
        self.config_manager.settings_config.audio = preferences
        sd.supervisor.configure(preferences)
        self.config_manager.save_settings_config()
        indexed = self._get_audio_settings_indexed(write=False)
        await self.settings_events.publish(
            "audio_devices_changed", (indexed.input, indexed.output)
        )
        self.printr.print("Audio devices changed.", server_only=True)

    def _get_audio_settings_indexed(self, write: bool = True) -> AudioSettings:
        # Return a UI projection, never replace the persisted preferred identity
        # with a fallback index or None when a device disappears.
        audio = self.config_manager.settings_config.audio
        devices = sd.query_devices()
        result = {}
        for direction in ("input", "output"):
            value = getattr(audio, direction, None)
            key = "max_input_channels" if direction == "input" else "max_output_channels"
            if isinstance(value, int):
                device = next((d for d in devices if d["index"] == value and d[key]), None)
                if device and write:
                    setattr(audio, direction, AudioDeviceSettings(name=device["name"], hostapi=device["hostapi"]))
                    self.config_manager.save_settings_config()
            elif isinstance(value, AudioDeviceSettings):
                device = next((d for d in devices if d["name"] == value.name and d["hostapi"] == value.hostapi and d[key]), None)
            else:
                device = None
            result[direction] = device["index"] if device else None
        return AudioSettings(**result)
