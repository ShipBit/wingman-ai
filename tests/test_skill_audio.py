"""Run: PYTHONPATH=. venv/bin/python -m tests.test_skill_audio"""
import asyncio
from wingmen.facade import SkillAudio, Subscription


class _Events:
    def __init__(self): self.subs = {"started": [], "finished": []}
    def subscribe(self, ev, cb): self.subs[ev].append(cb)
    def unsubscribe(self, ev, cb):
        if cb in self.subs[ev]: self.subs[ev].remove(cb)


class _Player:
    def __init__(self): self.is_playing = False; self.playback_events = _Events()


class _Lib:
    def __init__(self): self.played = None; self.stopped = None
    async def start_playback(self, cfg, vol): self.played = (cfg, vol)
    async def stop_playback(self, cfg, fade): self.stopped = (cfg, fade)


class _W:
    def __init__(self): self.audio_player = _Player(); self.audio_library = _Lib()
    settings = type("S", (), {"audio": None})()
    settings_service = None


def test_play_stop_param_names():
    w = _W(); a = SkillAudio(w)
    asyncio.get_event_loop().run_until_complete(a.play("cfg", volume=0.5))
    asyncio.get_event_loop().run_until_complete(a.stop("cfg", fade_out=1.0))
    assert w.audio_library.played == ("cfg", 0.5)
    assert w.audio_library.stopped == ("cfg", 1.0)
    print("PASS: play/stop volume + fade_out")


def test_subscription():
    w = _W(); a = SkillAudio(w)
    cb = lambda name: None
    sub = a.on_playback_started(cb)
    assert isinstance(sub, Subscription) and cb in w.audio_player.playback_events.subs["started"]
    sub.unsubscribe()
    assert cb not in w.audio_player.playback_events.subs["started"]
    assert not hasattr(a, "off_playback_started")
    print("PASS: on_* returns Subscription, off_* removed")


if __name__ == "__main__":
    test_play_stop_param_names()
    test_subscription()
    print("ALL OK")
