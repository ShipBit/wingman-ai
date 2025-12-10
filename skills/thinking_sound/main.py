import asyncio
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

        self.audio_config: AudioFileConfig = None
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
        self.audio_config = self.retrieve_custom_property_value("audio_config", errors)
        if self.audio_config:
            # Force no wait for this skill to work
            self.audio_config.wait = False
        else:
            self.printr.print(
                f"Thinking Sound: No audio configured for {self.wingman.name}.",
                color=LogType.WARNING,
                server_only=True,
            )
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

    async def on_add_user_message(self, message: str) -> None:
        """Start playing thinking sound when user message is added."""
        if not self.audio_config:
            return

        # Stop any existing playback first
        await self.wingman.audio_library.stop_playback(self.audio_config, 0)

        self.printr.print(
            "Thinking Sound: Starting playback.",
            color=LogType.INFO,
            server_only=True,
        )

        self.threaded_execution(self.start_playback)

    async def start_playback(self):
        """Start playing the thinking sound."""
        if not self.audio_config or self.is_playing:
            return

        self.is_playing = True
        await self.wingman.audio_library.start_playback(
            self.audio_config, self.wingman.config.sound.volume
        )

    async def stop_playback(self):
        """Stop the thinking sound with fade out."""
        if not self.audio_config or not self.is_playing:
            return

        await self.wingman.audio_library.stop_playback(
            self.audio_config, self.stop_duration
        )
        self.is_playing = False
