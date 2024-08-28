import asyncio
import os
import random
import wave
from api.enums import LogType
from api.interface import WingmanInitializationError
from services.audio_player import AudioPlayer
from services.file import get_writable_dir
from skills.skill_base import Skill

class ThinkingSound(Skill):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.sound_path = get_writable_dir(
            os.path.join("skills", "thinking_sound", "sounds")
        )
        self.audio_player = AudioPlayer(
            event_queue=asyncio.Queue(),
            on_playback_started=self.on_playback_started,
            on_playback_finished=self.on_playback_finished,
        )
        self.audio_player.sample_dir = self.sound_path
        self.original_volume = None
        self.volume = None
        self.stop_duration = 1
        self.active = False
        self.playing = False

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        volume = self.retrieve_custom_property_value("volume", errors)
        if volume:
            self.original_volume = volume * self.wingman.config.sound.volume

        return errors

    async def unload(self) -> None:
        self.active = False

    async def prepare(self) -> None:
        # prepare wingman specific path
        get_writable_dir(os.path.join(self.sound_path, self.wingman.name))
        self.active = True

    async def on_playback_started(self, wingman_name):
        # placeholder for future implementation
        pass

    async def on_playback_finished(self, wingman_name):
        # placeholder for future implementation
        pass

    def get_file_name(self) -> str | bool:
        # check wingman specific sound path first
        path = get_writable_dir(os.path.join(self.sound_path, self.wingman.name))
        files = [file for file in os.listdir(path) if file.endswith((".wav"))]
        if files:
            return os.path.join(path, random.choice(files))

        # get files from general folder instead
        files = [
            file for file in os.listdir(self.sound_path) if file.endswith((".wav"))
        ]
        if files:
            return os.path.join(self.sound_path, random.choice(files))

        return False

    async def on_add_user_message(self, message: str) -> None:
        if self.original_volume:
            if self.wingman.settings.debug_mode:
                await self.printr.print_async(
                    "Initiating filling sound.",
                    color=LogType.INFO,
                    server_only=False,
                )
            self.threaded_execution(self.start_playback)
            self.threaded_execution(self.auto_stop_playback)

    async def start_playback(self):
        filename = self.get_file_name()
        if not filename:
            await self.printr.print_async(
                f"No filling sounds found in {self.sound_path} or subfolder {self.wingman.name}",
                color=LogType.WARNING,
                server_only=False,
            )
            return

        if self.wingman.settings.debug_mode:
            await self.printr.print_async(
                f"Using filling sound {filename}",
                color=LogType.INFO,
                server_only=False,
            )
        if not self.wingman.audio_player.is_playing and not self.playing:
            self.playing = True
            self.volume = [self.original_volume]
            print(self.volume)
            audio_data, bitrate = self.audio_player.get_audio_from_file(filename)
            with wave.open(filename, "rb") as audio_file:
                num_channels = audio_file.getnchannels()
            # loop playback until stopped by auto_stop_playback
            while (
                self.playing
                and self.active
                and not self.wingman.audio_player.is_playing
            ):
                await self.audio_player.stop_playback()
                self.audio_player.start_playback(
                    audio_data, bitrate, num_channels, None, self.volume
                )

    async def auto_stop_playback(self):
        # Wait for main playback to start
        while not self.wingman.audio_player.is_playing and self.active:
            await asyncio.sleep(0.1)
        if self.wingman.settings.debug_mode:
            await self.printr.print_async(
                "Stopping filling sound softly.",
                color=LogType.INFO,
                server_only=False,
            )

        # smoothly stop playback
        step_size = self.original_volume / 20
        step_duration = self.stop_duration / 20
        while self.playing and self.active and self.volume[0] > 0.0001:
            self.volume[0] -= step_size
            await asyncio.sleep(step_duration)
        await asyncio.sleep(0.1) # grace period
        self.playing = False
        await self.audio_player.stop_playback()
