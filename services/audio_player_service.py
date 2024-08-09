import asyncio
from os import path
from services.file import get_writable_dir
from services.audio_player import AudioPlayer

async def play_audio_file(relative_file_path: str, volume: float = 1.0):
    audio_player = AudioPlayer(
        asyncio.get_event_loop(),
        None,
        None
    )

    audio_player.play_audio_file(
        path.join(get_writable_dir("audio_files"), relative_file_path),
        volume
    )
