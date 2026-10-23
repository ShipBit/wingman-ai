"""PortAudio reports the end of a playback on its audio thread. Closing the
stream there fails on macOS ("cannot do in current context"), and with
previews clicked in quick succession it closed the next voice's stream."""

import threading

import numpy as np

from services import audio_player as audio_player_module
from services.audio_player import AudioPlayer


class FakeOutputStream:
    def __init__(self, finished_callback, **kwargs):
        self.finished_callback = finished_callback
        self.closed_on = None

    def start(self):
        # The end of the audio, reported on a thread of PortAudio's own.
        threading.Thread(target=self.finished_callback).start()

    def close(self):
        self.closed_on = threading.current_thread()


def test_stream_closes_on_the_playback_thread(monkeypatch):
    streams = []

    def output_stream(**kwargs):
        streams.append(FakeOutputStream(**kwargs))
        return streams[-1]

    monkeypatch.setattr(audio_player_module.sd, "OutputStream", output_stream)
    player = AudioPlayer(None, None, None)
    finished = []

    player.start_playback(np.zeros(480), 48000, 1, lambda: finished.append(True), 1.0)

    assert streams[0].closed_on is threading.current_thread()
    assert player.stream is None
    assert finished == [True]


def test_old_stream_leaves_the_next_playback_alone(monkeypatch):
    newer = object()

    def output_stream(**kwargs):
        stream = FakeOutputStream(**kwargs)
        # The next preview took over the player while this one played.
        stream.start = lambda: (
            setattr(player, "stream", newer),
            threading.Thread(target=stream.finished_callback).start(),
        )
        return stream

    monkeypatch.setattr(audio_player_module.sd, "OutputStream", output_stream)
    player = AudioPlayer(None, None, None)
    finished = []

    player.start_playback(np.zeros(480), 48000, 1, lambda: finished.append(True), 1.0)

    assert player.stream is newer
    assert finished == []
