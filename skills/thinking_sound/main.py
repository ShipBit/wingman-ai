from typing import TYPE_CHECKING

from api.interface import (
    AudioFileConfig,
    SettingsConfig,
    SkillConfig,
    WingmanInitializationError,
)
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext


class ThinkingSound(Skill):
    """Skill that plays a looping sound while the AI is thinking/processing."""

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "WingmanContext",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        self.stop_duration = 1
        self.is_playing = False

        # Subscribe to playback events (keep the Subscription handles to detach on unload)
        self._sub_started = self.wingman.audio.on_playback_started(self.on_playback_started)
        self._sub_finished = self.wingman.audio.on_playback_finished(self.on_playback_finished)

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        # Validate that audio_config exists (don't cache it)
        self.retrieve_custom_property_value("audio_config", errors)
        return errors

    async def unload(self) -> None:
        await super().unload()
        await self.stop_playback()

        # Unsubscribe from playback events
        self._sub_started.unsubscribe()
        self._sub_finished.unsubscribe()

        self.log.info("Thinking Sound Skill unloaded.", server_only=True)

    async def on_playback_started(self, _):
        """Called when main TTS playback starts - stop the thinking sound."""
        if self.is_playing:
            self.log.info("Thinking Sound: Stopping (TTS playback started).", server_only=True)
            await self.stop_playback()

    async def on_playback_finished(self, _):
        """Called when main TTS playback finishes."""
        pass

    def _get_audio_config(self) -> AudioFileConfig | None:
        """Retrieve fresh audio_config at runtime."""
        errors: list[WingmanInitializationError] = []
        audio_config = self.retrieve_custom_property_value("audio_config", errors)
        if audio_config:
            # Force no wait for this skill to work
            audio_config.wait = False
        return audio_config

    async def on_add_user_message(self, message: str) -> None:
        """Start playing thinking sound when user message is added."""
        audio_config = self._get_audio_config()
        if not audio_config:
            return

        # Stop any existing playback first
        await self.wingman.audio.stop(audio_config, fade_out=0)

        self.log.info("Thinking Sound: Starting playback.", server_only=True)

        self.wingman.run_in_thread(self.start_playback)

    async def start_playback(self):
        """Start playing the thinking sound."""
        audio_config = self._get_audio_config()
        if not audio_config or self.is_playing:
            return

        self.is_playing = True
        await self.wingman.audio.play(audio_config, volume=self.wingman.config.sound.volume)

    async def stop_playback(self):
        """Stop the thinking sound with fade out."""
        audio_config = self._get_audio_config()
        if not audio_config or not self.is_playing:
            return

        await self.wingman.audio.stop(audio_config, fade_out=self.stop_duration)
        self.is_playing = False
