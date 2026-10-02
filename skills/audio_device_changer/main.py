from typing import TYPE_CHECKING

from api.interface import (
    SettingsConfig,
    SkillConfig,
    SoundConfig,
    WingmanInitializationError,
)
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext


class AudioDeviceChanger(Skill):
    """Skill that automatically routes TTS output to a configured audio device per Wingman."""

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "WingmanContext",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        # The device the user had before we switched, read at the moment of the
        # switch so a change in the settings meanwhile is respected.
        self.original_audio_device = None
        self.switched = False
        self._sub_finished = None

    async def validate(self) -> list[WingmanInitializationError]:
        return await super().validate()

    async def prepare(self) -> None:
        await super().prepare()
        self._sub_finished = self.wingman.audio.on_playback_finished(self.playback_finished)

    async def _change_audio_device(self, device_id) -> bool:
        """Change the audio output device in-process via the facade. Pass None to reset to
        the system default. Returns False if device control is unavailable."""
        try:
            ok = await self.wingman.audio.set_output_device(device_id)
            if ok:
                self.log.info(
                    f"Audio Device Changer: changed audio device to {device_id}",
                    server_only=True,
                )
            else:
                self.log.error(
                    "Audio Device Changer: audio device control unavailable."
                )
            return ok
        except Exception as e:
            self.log.error(
                f"Audio Device Changer: error changing audio device: {e}"
            )
            return False

    async def on_play_to_user(self, text: str, sound_config: SoundConfig):
        errors: list[WingmanInitializationError] = []
        audio_device = self.retrieve_custom_property_value(
            "audio_changer_device", errors
        )
        if len(errors) > 0:
            self.log.error(
                f"Audio Device Changer: Error retrieving audio device settings: {errors[0].message}"
            )
        elif audio_device is not None:
            if not self.switched:
                self.original_audio_device = self.wingman.audio.output_device
            if await self._change_audio_device(audio_device):
                self.switched = True
        return text

    async def playback_finished(self, _):
        await self.reset_audio_device()

    async def unload(self) -> None:
        await super().unload()
        await self.reset_audio_device()

        if self._sub_finished:
            self._sub_finished.unsubscribe()

        self.log.info("Audio Device Changer Skill unloaded.", server_only=True)

    async def reset_audio_device(self) -> None:
        """Resets the audio device to the original one"""

        if not self.switched:
            return
        self.switched = False
        await self._change_audio_device(self.original_audio_device)
        self.log.info(
            "Audio Device Changer: Reset audio device to original.", server_only=True
        )
