from typing import Optional
from fastapi import APIRouter
from api.enums import LogType, ToastType, VoiceActivationSttProvider, WingmanProRegion
from api.interface import (
    AudioSettings,
    AzureSttConfig,
    SettingsConfig,
    WhispercppSttConfig,
)
from services.config_manager import ConfigManager
from services.config_service import ConfigService
from services.printr import Printr
from services.pub_sub import PubSub


class SettingsService:
    def __init__(self, config_manager: ConfigManager, config_service: ConfigService):
        self.printr = Printr()
        self.config_manager = config_manager
        self.config_service = config_service
        self.settings = self.get_settings()
        self.settings_events = PubSub()

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
            path="/settings/audio-devices",
            endpoint=self.set_audio_devices,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/voice-activation",
            endpoint=self.set_voice_activation,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/mute-key",
            endpoint=self.set_mute_key,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/wingman-pro",
            endpoint=self.set_wingman_pro_settings,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/wingman-pro/make-default",
            endpoint=self.set_wingman_pro_as_default,
            tags=tags,
        )

    # GET /settings
    def get_settings(self):
        return self.config_manager.settings_config

    # POST /settings/audio-devices
    async def set_audio_devices(
        self, output_device: Optional[int] = None, input_device: Optional[int] = None
    ):
        self.config_manager.settings_config.audio = AudioSettings(
            input=input_device,
            output=output_device,
        )

        if self.config_manager.save_settings_config():
            self.printr.print(
                "Audio devices updated.", toast=ToastType.NORMAL, color=LogType.POSITIVE
            )
            await self.settings_events.publish(
                "audio_devices_changed", (output_device, input_device)
            )
        return output_device, input_device

    # POST /settings/voice-activation
    async def set_voice_activation(self, is_enabled: bool):
        self.config_manager.settings_config.voice_activation.enabled = is_enabled

        if self.config_manager.save_settings_config():
            self.printr.print(
                f"Voice activation {'enabled' if is_enabled else 'disabled'}.",
                toast=ToastType.NORMAL,
                color=LogType.POSITIVE,
            )
            await self.settings_events.publish("voice_activation_changed", is_enabled)

    # POST /settings/mute-key
    def set_mute_key(self, key: str, keycodes: Optional[list[int]] = None):
        self.config_manager.settings_config.voice_activation.mute_toggle_key = key
        self.config_manager.settings_config.voice_activation.mute_toggle_key_codes = (
            keycodes
        )

        if self.config_manager.save_settings_config():
            self.printr.print(
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
            await self.config_service.load_config()
            self.printr.print(
                "Wingman Pro settings updated.",
                toast=ToastType.NORMAL,
                color=LogType.POSITIVE,
            )
            if old_va_threshold != va_energy_threshold:
                await self.settings_events.publish(
                    "va_treshold_changed", va_energy_threshold
                )

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
            config_dirs = self.config_service.get_config_dirs()
            for config_dir in config_dirs.config_dirs:
                wingman_config_files = (
                    await self.config_service.get_wingmen_config_files(config_dir.name)
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
        await self.config_service.load_config(self.config_service.current_config_dir)

        self.printr.print(
            "Have fun using Wingman Pro!",
            toast=ToastType.NORMAL,
            color=LogType.POSITIVE,
        )
