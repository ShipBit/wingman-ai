from copy import deepcopy
from typing import Optional
from fastapi import APIRouter
import sounddevice as sd
from api.enums import LogType, ToastType
from api.interface import (
    AudioSettings,
    AudioDeviceSettings,
    SettingsConfig,
)
from providers.whispercpp import Whispercpp
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
        self.whispercpp: Whispercpp = None

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
            path="/settings/default-provider",
            endpoint=self.set_default_provider,
            tags=tags,
        )

    def initialize(self, whispercpp: Whispercpp):
        self.whispercpp = whispercpp

    # GET /settings
    def get_settings(self):
        config = self.config_manager.settings_config
        config.audio = self._get_audio_settings_indexed(
            not self.converted_audio_settings
        )
        self.converted_audio_settings = True
        return config

    # POST /settings
    async def save_settings(self, settings: SettingsConfig):
        old = deepcopy(self.config_manager.settings_config)

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
            await self._set_audio_devices(settings.audio.input, settings.audio.output)

        # whispercpp
        if not self.whispercpp:
            self.printr.toast_error(
                "Whispercpp is not initialized. Please run SettingsService.initialize()",
            )
            return
        self.whispercpp.update_settings(settings=settings.voice_activation.whispercpp)

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

        # save the config file
        self.config_manager.save_settings_config()

        # update running wingmen
        for wingman in self.config_service.tower.wingmen:
            await wingman.update_settings(settings=self.config_manager.settings_config)

    async def _set_audio_devices(
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

        await self.settings_events.publish(
            "audio_devices_changed", (input_device, output_device)
        )
        self.printr.print("Audio devices changed.", server_only=True)

    # POST /settings/default-provider
    async def set_default_provider(self, provider: str, patch_existing_wingmen: bool):
        if provider != "wingman_pro" and provider != "openai":
            self.printr.toast_error(
                "Only 'wingman_pro' and 'openai' are valid default providers for summarization, conversation, TTS and STT.",
            )
            return

        config = deepcopy(self.config_manager.default_config)
        config.features.conversation_provider = provider
        config.features.summarize_provider = provider
        config.features.tts_provider = provider
        config.features.stt_provider = provider

        await self.config_service.save_defaults_config(config=config, validate=True)

    def _get_audio_settings_indexed(self, write: bool = True) -> AudioSettings:
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
                                    server_only=True,
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
                                server_only=True,
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
                                server_only=True,
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
                                    server_only=True,
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
                                server_only=True,
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
                                server_only=True,
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
                self.printr.print("Audio settings updated.", server_only=True)
        return AudioSettings(input=input_device, output=output_device)
