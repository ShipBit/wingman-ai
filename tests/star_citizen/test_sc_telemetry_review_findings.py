"""Regression tests for the code review of 2026-10-28 (findings numbered as in the review)."""
import asyncio
import json
import threading
import types

from skills.sc_telemetry.handler import Handler, Thresholds
from skills.sc_telemetry.reader import TelemetryReader
from tests.star_citizen.sc_telemetry_support import (
    load_frames,
    make_skill,
    serve,
)

SHIP = "DRAK_Cutter_907038284543"


def _ship_frame(**lights) -> dict:
    annunciators = {key: f"ANNUNCIATOR_STATE_{value.upper()}" for key, value in lights.items()}
    return {"vehicle": {"state": {"name": SHIP, "class_name": "DRAK_Cutter", "annunciators": annunciators,
                                  "power": {"powerplants": True, "engines": True},
                                  "flight": {"instruments": {"altitude": 900.0, "g_meter": {"current": 1.0}}}}}}


def _player_frame(health: float, **vitals) -> dict:
    return {"actor": {"state": {"locomotion": "ACTOR_LOCOMOTION_STATE_ON_FOOT"},
                      "vitals": {"health": {"current": health, "max": 100.0}, **vitals}}}


def _run(handler: Handler, frames: list[tuple[float, dict]]) -> list[str]:
    fired = []
    for t, frame in frames:
        fired += [e.id for e in handler.update(frame, t, Thresholds())]
    return fired


def test_1_feed_errors_do_not_lose_events():
    skill = make_skill({})
    offered = []
    skill._loop = types.SimpleNamespace(call_soon_threadsafe=lambda fn, events: offered.extend(events))

    class BrokenFeed:
        def write_state(self, *a):
            raise PermissionError("consumer has the file open")

        def add_event(self, *a):
            raise OSError("disk full")

    skill._feed = BrokenFeed()
    for t, frame in load_frames("combat_2026-10-28.jsonl"):
        skill._on_frame_thread(frame, t)  # must not raise
    assert "shields_down" in {e.id for e in offered}
    assert 1 <= len(skill.logged) <= 2  # rate-limited: one line per kind of problem, not one per frame


def test_4_stale_frames_are_not_described_as_live():
    skill = make_skill({})
    skill._loop = types.SimpleNamespace(call_soon_threadsafe=lambda fn, events: None)
    for t, frame in load_frames("combat_2026-10-28.jsonl")[:20]:
        skill._on_frame_thread(frame, t)
    skill._reader_status = "live"
    assert asyncio.run(skill.get_ship_status()).startswith("Ship:")
    skill._last_frame_at -= 10  # no frame for 10 s: menu or loading
    assert "spawned" in asyncio.run(skill.get_ship_status())


def test_2_one_bad_frame_does_not_drop_the_stream():
    recorded = [frame for _, frame in load_frames("countermeasures_2026-10-28.jsonl")[:4]]
    server, port = serve(recorded)
    got, statuses, done = [], [], threading.Event()

    def on_frame(frame, t):
        got.append(frame)
        if len(got) == 1:
            raise KeyError("unexpected frame")
        if len(got) == len(recorded):
            done.set()

    reader = TelemetryReader(on_frame, statuses.append, address=f"127.0.0.1:{port}")
    reader.start()
    try:
        assert done.wait(10)
    finally:
        reader.stop()
        server.stop(0)
    assert got == recorded  # the same stream continued: no reconnect replayed frame 1
    assert statuses.count("connected") == 1


def test_3_enable_setting_survives_a_broken_record(tmp_path):
    skill = make_skill({"enable_telemetry": False})
    skill.get_generated_files_dir = lambda: str(tmp_path)
    (tmp_path / "enable_applied.json").write_text(json.dumps(["not", "a", "dict"]))
    skill._apply_enable_setting()  # must not raise, must not touch the registry


def test_5_reentering_the_same_ship_is_silent():
    handler = Handler()
    frames = [(0.0, _ship_frame(prox="nominal"))]
    frames += [(1.0 + i * 0.1, _player_frame(100.0)) for i in range(20)]  # on foot, no vehicle frame
    frames += [(5.0 + i * 0.2, _ship_frame(prox="major_on", hit="major_flashing")) for i in range(30)]
    assert _run(handler, frames) == []


def test_6_entering_a_ship_with_lights_already_on_is_silent():
    handler = Handler()
    frames = [(i * 0.2, _ship_frame(prox="major_on", hit="major_flashing", wpn="minor_on")) for i in range(30)]
    assert _run(handler, frames) == []


def test_7_respawn_through_an_intermediate_health_value():
    handler = Handler()
    frames = [(0.0, _player_frame(100.0))] + [(1.0 + i * 0.5, _player_frame(0.0)) for i in range(6)]
    frames += [(5.0, _player_frame(40.0)), (5.5, _player_frame(100.0))]
    fired = _run(handler, frames)
    assert fired.count("player_down") == 1 and fired.count("respawned") == 1


def test_8_two_spikes_a_minute_apart_are_not_exhaustion():
    handler = Handler()
    frames = [(0.0, _player_frame(100.0, heart_rate=60.0)), (1.0, _player_frame(100.0, heart_rate=171.0))]
    frames += [(1.5 + i, _player_frame(100.0, heart_rate=160.0)) for i in range(60)]
    frames += [(62.0, _player_frame(100.0, heart_rate=171.0))]
    assert "exhausted" not in _run(handler, frames)


def test_8_repeated_spikes_are_exhaustion_once():
    handler = Handler()
    rates = [60, 165, 171, 166, 171, 168, 171, 167, 171]
    frames = [(i * 0.6, _player_frame(100.0, heart_rate=float(rate))) for i, rate in enumerate(rates)]
    assert _run(handler, frames).count("exhausted") == 1


def test_11_feed_gets_events_the_cooldown_holds_back():
    handler = Handler()
    frames, t = [], 0.0
    for _ in range(3):  # three hits within the 90 s cooldown
        frames += [(t + i * 0.2, _ship_frame(hit=("major_flashing" if i < 5 else "nominal"))) for i in range(10)]
        t += 5.0
    fired = []
    raw = []
    for when, frame in [(0.0, _ship_frame())] + frames:
        fired += [e.id for e in handler.update(frame, when, Thresholds())]
        raw += [e.id for e in handler.last_unfiltered]
    assert fired.count("under_fire") == 1 and raw.count("under_fire") == 3
