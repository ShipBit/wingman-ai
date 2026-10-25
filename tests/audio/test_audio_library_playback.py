"""A sound the audio library cannot read is a warning to the user, not a crash."""

import asyncio

from api.interface import AudioFile
from services import audio_library as audio_library_module
from services.audio_library import AudioLibrary


class _UnreadablePlayer:
    async def play_audio_file(self, **_):
        raise RuntimeError("Error opening 'Illusions.mp3': File does not exist or is not a regular file")


def test_an_unreadable_file_warns_and_frees_the_playback(monkeypatch, tmp_path):
    warnings = []
    monkeypatch.setattr(audio_library_module.printr, "toast_warning", warnings.append)
    library = AudioLibrary()
    library.audio_library_path = str(tmp_path)
    library.current_playbacks["Illusions.mp3"] = ["player", [1.0], "file"]

    asyncio.run(
        library._play_file(
            AudioFile(path="", name="Illusions.mp3"), _UnreadablePlayer(), [1.0], "Illusions.mp3"
        )
    )

    assert len(warnings) == 1 and "Illusions.mp3" in warnings[0]
    assert "Illusions.mp3" not in library.current_playbacks
