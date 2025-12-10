from typing import TYPE_CHECKING

from api.enums import LogType
from api.interface import (
    AudioFileConfig,
    SettingsConfig,
    SkillConfig,
    WingmanInitializationError,
)
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class ThinkingSound(Skill):
    """Skill that plays a looping sound while the AI is thinking/processing."""

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        self.stop_duration = 1
        self.is_playing = False

        # Subscribe to playback events
        self.wingman.audio_player.playback_events.subscribe(
            "started", self.on_playback_started
        )
        self.wingman.audio_player.playback_events.subscribe(
            "finished", self.on_playback_finished
        )

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        # Validate that audio_config exists (don't cache it)
        self.retrieve_custom_property_value("audio_config", errors)
        return errors

    async def unload(self) -> None:
        await super().unload()
        await self.stop_playback()

        # Unsubscribe from playback events
        self.wingman.audio_player.playback_events.unsubscribe(
            "started", self.on_playback_started
        )
        self.wingman.audio_player.playback_events.unsubscribe(
            "finished", self.on_playback_finished
        )

        self.printr.print(
            "Thinking Sound Skill unloaded.",
            color=LogType.INFO,
            server_only=True,
        )

    async def on_playback_started(self, _):
        """Called when main TTS playback starts - stop the thinking sound."""
        if self.is_playing:
            self.printr.print(
                "Thinking Sound: Stopping (TTS playback started).",
                color=LogType.INFO,
                server_only=True,
            )
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
        await self.wingman.audio_library.stop_playback(audio_config, 0)

        self.printr.print(
            "Thinking Sound: Starting playback.",
            color=LogType.INFO,
            server_only=True,
        )

        self.threaded_execution(self.start_playback)

    async def start_playback(self):
        """Start playing the thinking sound."""
        audio_config = self._get_audio_config()
        if not audio_config or self.is_playing:
            return

        self.is_playing = True
        await self.wingman.audio_library.start_playback(
            audio_config, self.wingman.config.sound.volume
        )

    async def stop_playback(self):
        """Stop the thinking sound with fade out."""
        audio_config = self._get_audio_config()
        if not audio_config or not self.is_playing:
            return

        await self.wingman.audio_library.stop_playback(audio_config, self.stop_duration)
        self.is_playing = False
