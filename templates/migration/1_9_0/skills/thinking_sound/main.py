import asyncio
from api.enums import LogType
from api.interface import WingmanInitializationError, AudioFileConfig
from skills.skill_base import Skill

class ThinkingSound(Skill):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.audio_config: AudioFileConfig = None
        self.original_volume = None
        self.stop_duration = 1
        self.active = False
        self.playing = False

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        self.audio_config = self.retrieve_custom_property_value("audio_config", errors)
        if self.audio_config:
            # force no wait for this skill to work
            self.audio_config.wait = False
        return errors

    async def unload(self) -> None:
        await self.stop_playback()
        self.active = False

    async def prepare(self) -> None:
        self.active = True

    async def on_playback_started(self, wingman_name):
        # placeholder for future implementation
        pass

    async def on_playback_finished(self, wingman_name):
        # placeholder for future implementation
        pass

    async def on_add_user_message(self, message: str) -> None:
        await self.wingman.audio_library.stop_playback(self.audio_config, 0)

        if self.wingman.settings.debug_mode:
            await self.printr.print_async(
                "Initiating filling sound.",
                color=LogType.INFO,
                server_only=False,
            )

        self.threaded_execution(self.start_playback)
        self.threaded_execution(self.auto_stop_playback)

    async def start_playback(self):
        if not self.audio_config:
            await self.printr.print_async(
                f"No filling soaund configured for {self.wingman.name}'s thinking_sound skill.",
                color=LogType.WARNING,
                server_only=False,
            )
            return

        if not self.playing:
            self.playing = True
            await self.wingman.audio_library.start_playback(
                self.audio_config, self.wingman.config.sound.volume
            )

    async def stop_playback(self):
        await self.wingman.audio_library.stop_playback(
            self.audio_config, self.stop_duration
        )

    async def auto_stop_playback(self):
        # Wait for main playback to start
        while not ( self.wingman.audio_player.stream or self.wingman.audio_player.raw_stream ) and self.active:
            await asyncio.sleep(0.1)

        if self.wingman.settings.debug_mode:
            await self.printr.print_async(
                "Stopping filling sound softly.",
                color=LogType.INFO,
                server_only=False,
            )

        await self.wingman.audio_library.stop_playback(self.audio_config, self.stop_duration)
        self.playing = False
