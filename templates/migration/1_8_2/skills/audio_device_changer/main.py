from typing import TYPE_CHECKING
import aiohttp
from api.interface import (
    AudioDeviceSettings,
    SettingsConfig,
    SkillConfig,
    SoundConfig,
    WingmanInitializationError,
)
from api.enums import LogType
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class AudioDeviceChanger(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        self.original_audio_device = settings.audio.output
        self.current_audio_device = settings.audio.output
        self.backend_port = 49111
        self.wingman.audio_player.playback_events.subscribe(
            "finished", self.playback_finished
        )

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        backend_port = self.retrieve_custom_property_value("backend_port", errors)
        if backend_port is not None:
            self.backend_port = backend_port

        return errors

    async def _change_audio_device(self, device_id: int | AudioDeviceSettings) -> bool:
        """Change the audio output device via HTTP request."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"http://127.0.0.1:{self.backend_port}/settings/audio-devices?output_device={device_id}"
                    if device_id
                    else f"http://127.0.0.1:{self.backend_port}/settings/audio-devices"
                ) as response:
                    if response.status == 200:
                        self.printr.print(
                            f"Audio Device Changer: changed audio device to {device_id}",
                            LogType.INFO,
                            server_only=True,
                        )
                        return True
                    else:
                        await self.printr.print_async(
                            f"Audio Device Changer: Failed to change audio device. Status: {response.status}",
                            LogType.ERROR,
                        )
                        return False
        except Exception as e:
            await self.printr.print_async(
                f"Audio Device Changer: Error changing audio device. Error: {str(e)}",
                LogType.ERROR,
            )
            return False

    async def on_play_to_user(self, text: str, sound_config: SoundConfig):
        errors: list[WingmanInitializationError] = []
        audio_device = self.retrieve_custom_property_value(
            "audio_changer_device", errors
        )
        if len(errors) > 0:
            await self.printr.print_async(
                f"Audio Device Changer: Error retrieving audio device settings: {errors[0].message}",
                LogType.ERROR,
            )
        elif audio_device is not None and audio_device != self.original_audio_device:
            self.current_audio_device = audio_device
            await self._change_audio_device(audio_device)
        return text

    async def playback_finished(self, _):
        await self.reset_audio_device()

    async def unload(self) -> None:
        await self.reset_audio_device()

        self.wingman.audio_player.playback_events.unsubscribe(
            "finished", self.playback_finished
        )

        self.printr.print(
            text="Audio Device Changer Skill unloaded.",
            color=LogType.INFO,
            server_only=True,
        )

    async def reset_audio_device(self) -> None:
        """Resets the audio device to the original one"""

        if self.current_audio_device == self.original_audio_device:
            return
        await self._change_audio_device(self.original_audio_device)
        self.printr.print(
            text="Audio Device Changer: Reset audio device to original.",
            color=LogType.INFO,
            server_only=True,
        )
