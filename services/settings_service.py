from typing import Optional
from fastapi import APIRouter
import sounddevice as sd
from api.enums import LogType, ToastType, VoiceActivationSttProvider, WingmanProRegion
from api.interface import (
    AudioSettings,
    AudioDeviceSettings,
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
        self.converted_audio_settings = False
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
            path="/settings/default-provider",
            endpoint=self.set_default_provider,
            tags=tags,
        )

    # GET /settings
    def get_settings(self):
        config = self.config_manager.settings_config
        config.audio = self.get_audio_settings_indexed(
            not self.converted_audio_settings
        )
        self.converted_audio_settings = True
        return config

    def get_audio_settings_indexed(self, write: bool = True) -> AudioSettings:
        input_device = None
        output_device = None
        if self.config_manager.settings_config.audio:
            input_settings_orig = input_settings = (
                self.config_manager.settings_config.audio.input
            )
            output_settings_orig = output_settings = (
                self.config_manager.settings_config.audio.output
            )

            # check input
            if input_settings is not None:
                input_name = None
                input_hostapi = None

                if isinstance(input_settings, int):
                    # if integer - check if audio device exists
                    if input_settings < len(sd.query_devices()):
                        input_device = input_settings
                        device = sd.query_devices(input_settings)
                        if not device["max_input_channels"]:
                            if write:
                                self.printr.print(
                                    "Configured input device is not an input device. Using default.",
                                    toast=ToastType.NORMAL,
                                    color=LogType.WARNING,
                                )
                            input_device = None
                        else:
                            input_name = sd.query_devices()[input_settings]["name"]
                            input_hostapi = sd.query_devices()[input_settings][
                                "hostapi"
                            ]
                            input_settings = AudioDeviceSettings(
                                name=input_name, hostapi=input_hostapi
                            )
                            if write:
                                self.printr.print(
                                    f"Using input device '{input_name}'.",
                                    color=LogType.INFO,
                                    server_only=True,
                                )
                    else:
                        if write:
                            self.printr.print(
                                "Configured input device not found. Using default.",
                                toast=ToastType.NORMAL,
                                color=LogType.WARNING,
                            )
                        input_device = None
                elif isinstance(input_settings, AudioDeviceSettings):
                    # get id with name and hostapi
                    for device in sd.query_devices():
                        if (
                            device["max_input_channels"] > 0
                            and device["name"] == input_settings.name
                            and device["hostapi"] == input_settings.hostapi
                        ):
                            if write:
                                device_name = device["name"]
                                self.printr.print(
                                    f"Using input device '{device_name}'.",
                                    color=LogType.INFO,
                                    server_only=True,
                                )
                            input_device = device["index"]
                            break
                    if input_device is None:
                        if write:
                            self.printr.print(
                                f"Configured input device '{input_settings.name}' not found. Using default.",
                                toast=ToastType.NORMAL,
                                color=LogType.WARNING,
                            )
            elif write:
                self.printr.print(
                    "No input device set. Using default.",
                    color=LogType.INFO,
                    server_only=True,
                )

            # check output
            if output_settings is not None:
                output_name = None
                output_hostapi = None

                if isinstance(output_settings, int):
                    # if integer - check if audio device exists
                    if output_settings < len(sd.query_devices()):
                        output_device = output_settings
                        device = sd.query_devices(output_settings)
                        if not device["max_output_channels"]:
                            if write:
                                self.printr.print(
                                    "Configured output device is not an output device. Using default.",
                                    toast=ToastType.NORMAL,
                                    color=LogType.WARNING,
                                )
                            output_device = None
                        else:
                            output_name = sd.query_devices()[output_settings]["name"]
                            output_hostapi = sd.query_devices()[output_settings][
                                "hostapi"
                            ]
                            output_settings = AudioDeviceSettings(
                                name=output_name, hostapi=output_hostapi
                            )
                            if write:
                                self.printr.print(
                                    f"Using output device '{output_name}'.",
                                    color=LogType.INFO,
                                    server_only=True,
                                )
                    else:
                        if write:
                            self.printr.print(
                                "Configured output device not found. Using default.",
                                toast=ToastType.NORMAL,
                                color=LogType.WARNING,
                            )
                        output_device = None
                # check if instance of AudioDeviceSettings
                elif isinstance(output_settings, AudioDeviceSettings):
                    # get id with name and hostapi
                    for device in sd.query_devices():
                        if (
                            device["max_output_channels"] > 0
                            and device["name"] == output_settings.name
                            and device["hostapi"] == output_settings.hostapi
                        ):
                            if write:
                                device_name = device["name"]
                                self.printr.print(
                                    f"Using output device '{device_name}'.",
                                    color=LogType.INFO,
                                    server_only=True,
                                )
                            output_device = device["index"]
                            break
                    if output_device is None:
                        if write:
                            self.printr.print(
                                f"Configured audio output device '{output_settings.name}' not found. Using default.",
                                toast=ToastType.NORMAL,
                                color=LogType.WARNING,
                            )
            elif write:
                self.printr.print(
                    "No output device set. Using default.",
                    color=LogType.INFO,
                    server_only=True,
                )

            # overwrite settings with new structure, if needed
            if write and (
                input_settings_orig != input_settings
                or output_settings_orig != output_settings
            ):
                self.config_manager.settings_config.audio = AudioSettings(
                    input=input_settings, output=output_settings
                )
                self.config_manager.save_settings_config()
                print("Audio settings updated.")
        return AudioSettings(input=input_device, output=output_device)

    # POST /settings/audio-devices
    async def set_audio_devices(
        self, output_device: Optional[int] = None, input_device: Optional[int] = None
    ):
        input_settings = None
        output_settings = None

        if input_device is not None:
            # get name and hostapi with id
            device = sd.query_devices(input_device)
            input_settings = AudioDeviceSettings(
                name=device["name"],
                hostapi=device["hostapi"],
            )

        if output_device is not None:
            # get name and hostapi with id
            device = sd.query_devices(output_device)
            output_settings = AudioDeviceSettings(
                name=device["name"],
                hostapi=device["hostapi"],
            )

        self.config_manager.settings_config.audio = AudioSettings(
            input=input_settings,
            output=output_settings,
        )

        if self.config_manager.save_settings_config():
            self.printr.print(
                "Audio devices updated.", toast=ToastType.NORMAL, color=LogType.POSITIVE
            )
            await self.settings_events.publish(
                "audio_devices_changed", (input_device, output_device)
            )
        return input_device, output_device

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

    # POST /settings/default-provider
    async def set_default_provider(self, provider: str, patch_existing_wingmen: bool):
        if provider != "wingman_pro" and provider != "openai":
            self.printr.toast_error(
                "Only 'wingman_pro' and 'openai' are valid default providers for summarization, conversation, TTS and STT.",
            )
            return

        self.config_manager.default_config.features.conversation_provider = provider
        self.config_manager.default_config.features.summarize_provider = provider
        self.config_manager.default_config.features.tts_provider = provider
        self.config_manager.default_config.features.stt_provider = provider

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
                        wingman_config.features.conversation_provider = provider
                        wingman_config.features.summarize_provider = provider
                        wingman_config.features.tts_provider = provider
                        wingman_config.features.stt_provider = provider

                        self.config_manager.save_wingman_config(
                            config_dir=config_dir,
                            wingman_file=wingman_config_file,
                            wingman_config=wingman_config,
                        )
        await self.config_service.load_config(self.config_service.current_config_dir)

        await self.printr.print_async(
            "Default providers updated.",
            toast=ToastType.NORMAL,
            color=LogType.POSITIVE,
        )
