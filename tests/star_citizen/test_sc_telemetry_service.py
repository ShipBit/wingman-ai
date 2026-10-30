"""Core's telemetry service against a fake game: one stream for everyone, events to every subscriber on their own
queue, a status that says what is wrong, and a stop that never hangs."""

import asyncio
import importlib.util
import sys
import time
from pathlib import Path

from api.enums import ScTelemetryState
from services.sc_telemetry import service as service_module
from tests.star_citizen.gamelog import until
from tests.star_citizen.telemetry import FakeGame, ids, replay
from tests.support import REPO_ROOT

CUTTER = "DRAK_Cutter_907038284543"


def _ship(shields: str = "NOMINAL", balance: int = 1000) -> dict:
    return {
        "actor": {"state": {"locomotion": "ACTOR_LOCOMOTION_STATE_SEATED", "uec_balance": str(balance)},
                  "vitals": {"health": {"current": 100.0, "max": 100.0}}},
        "vehicle": {"state": {"name": CUTTER, "class_name": "DRAK_Cutter",
                              "power": {"powerplants": True, "engines": True},
                              "annunciators": {"shld": f"ANNUNCIATOR_STATE_{shields}"},
                              "flight": {"instruments": {"altitude": 900.0, "g_meter": {"current": 1.0}}}}},
    }


async def _stream(game, frame, seconds):
    """The same frame at the game's rate for a while."""
    for _ in range(int(seconds * 17)):
        game.send(frame)
        await asyncio.sleep(1 / 17)


def test_frames_become_state_events_and_status(telemetry, game):
    statuses, events = [], []

    async def status_changed(status):
        statuses.append(status.state)

    async def run():
        telemetry.status_callback = status_changed
        await telemetry.apply_settings(True, "")
        telemetry.subscribe("*", events.append)
        await until(lambda: game.calls)
        await _stream(game, _ship(), 0.5)  # the first frames are the baseline: quiet
        await until(lambda: telemetry.state() is not None)
        assert telemetry.status().state == ScTelemetryState.LIVE
        assert telemetry.status().vehicle == "DRAK Cutter"
        await _stream(game, _ship("MAJOR_ON"), 2.0)
        await until(lambda: "shields_down" in ids(events))
        state = telemetry.state()
        state["vehicle"]["lights"]["shld"] = "changed by a skill"
        assert telemetry.state()["vehicle"]["lights"]["shld"] == "major_on"  # a copy
        await telemetry.stop()

    asyncio.run(run())
    assert ScTelemetryState.LIVE in statuses and statuses[-1] == ScTelemetryState.OFF
    assert ids(events) == ["shields_down"]
    assert [e.type for e in telemetry.recent(5)] == ["shields_down"]


def test_live_turns_to_connected_when_the_frames_stop(telemetry, game, monkeypatch):
    monkeypatch.setattr(service_module, "FRAME_STALE_S", 0.3)

    async def run():
        await telemetry.apply_settings(True, "")
        await until(lambda: game.calls)
        await _stream(game, _ship(), 0.3)
        await until(lambda: telemetry.status().state == ScTelemetryState.LIVE)
        # The game goes to its menu: the stream stays open, no frames come.
        await until(lambda: telemetry.status().state == ScTelemetryState.CONNECTED)
        assert telemetry.state() is None
        await telemetry.stop()

    asyncio.run(run())


def test_stop_does_not_wait_for_a_silent_stream(telemetry, game):
    """In the menus the game sends nothing; stopping must not hang until it does."""

    async def run():
        await telemetry.apply_settings(True, "")
        await until(lambda: telemetry.status().state == ScTelemetryState.CONNECTED)
        started = time.monotonic()
        await telemetry.apply_settings(False, "")
        stopped_in = time.monotonic() - started
        game.send(_ship(), _ship("MAJOR_ON"))
        await asyncio.sleep(0.3)
        return stopped_in

    assert asyncio.run(run()) < 2.0
    assert telemetry.state() is None and telemetry.status().state == ScTelemetryState.OFF


def test_a_renamed_service_reads_as_incompatible(telemetry, monkeypatch):
    patched = FakeGame(telemetry=False)
    from services.sc_telemetry import reader

    monkeypatch.setattr(reader, "ADDRESS", patched.address)

    seen = []

    async def changed(status):
        seen.append(status.state)

    async def run():
        telemetry.status_callback = changed
        await telemetry.apply_settings(True, "")
        await until(lambda: telemetry.status().state == ScTelemetryState.INCOMPATIBLE)
        await asyncio.sleep(0.5)  # several retries
        status = telemetry.status()
        await telemetry.stop()
        return status

    try:
        status = asyncio.run(run())
    finally:
        patched.stop()
    assert "UNIMPLEMENTED" in status.detail
    first = seen.index(ScTelemetryState.INCOMPATIBLE)
    assert ScTelemetryState.CONNECTED not in seen[first:]  # it does not flicker with every retry


def test_nothing_listening_is_waiting_and_a_running_game_without_telemetry_says_so(telemetry, tmp_path, monkeypatch):
    from services.sc_telemetry import reader

    monkeypatch.setattr(reader, "ADDRESS", "127.0.0.1:1")
    monkeypatch.setattr(service_module, "GAME_LOG_CHECK_S", 0.05)
    log = tmp_path / "game" / "LIVE" / "Game.log"

    async def run():
        await telemetry.apply_settings(True, str(tmp_path / "game"))
        await until(lambda: telemetry.status().state == ScTelemetryState.WAITING)
        # The game starts, from a launcher that was running before the switch was set.
        log.parent.mkdir(parents=True)
        log.write_text("<2026-10-30T10:00:00.000Z> Log started on Fri Oct 30 10:00:00 2026\n")
        await until(lambda: telemetry.status().state == ScTelemetryState.GAME_WITHOUT_TELEMETRY)
        # The next session has telemetry: back to waiting until the port opens.
        log.write_text("<2026-10-30T11:00:00.000Z> Log started on Fri Oct 30 11:00:00 2026\n"
                       "Service 'sc.game.telemetry.v1.GameTelemetryService' registered\n")
        await until(lambda: telemetry.status().state == ScTelemetryState.WAITING)
        await telemetry.stop()

    asyncio.run(run())


def test_a_failing_and_a_slow_subscriber_do_not_hold_up_another(telemetry, game):
    fast = []

    def failing(event):
        raise RuntimeError("a skill's bug")

    async def slow(event):
        await asyncio.sleep(10)

    async def run():
        await telemetry.apply_settings(True, "")
        telemetry.subscribe("*", failing)
        telemetry.subscribe("*", slow)
        telemetry.subscribe("shields_down", fast.append)
        await until(lambda: game.calls)
        await _stream(game, _ship(), 0.3)
        await _stream(game, _ship("MAJOR_ON"), 2.0)
        await until(lambda: fast)
        await telemetry.stop()

    asyncio.run(run())
    assert ids(fast) == ["shields_down"]


def test_state_subscribers_get_the_latest_state_and_none_once_it_stops(telemetry, game, monkeypatch):
    monkeypatch.setattr(service_module, "FRAME_STALE_S", 0.3)
    states = []

    async def run():
        await telemetry.apply_settings(True, "")
        telemetry.subscribe_state(states.append, interval=0.2)
        await until(lambda: game.calls)
        await _stream(game, _ship(balance=4242), 0.5)
        await until(lambda: states and states[-1] is not None)
        await until(lambda: states[-1] is None)
        await asyncio.sleep(0.5)
        await telemetry.stop()

    asyncio.run(run())
    assert states[0]["player"]["uec_balance"] == 4242
    assert states.count(None) == 1  # once, not every interval while nothing comes


def test_without_grpc_or_protobuf_the_status_says_so(telemetry, monkeypatch):
    from services.sc_telemetry import schema

    def broken():
        raise ImportError("No module named 'grpc'")

    monkeypatch.setattr(schema, "message_classes", broken)

    async def run():
        await telemetry.apply_settings(True, "")
        return telemetry.status()

    status = asyncio.run(run())
    assert status.state == ScTelemetryState.UNAVAILABLE and "grpc" in status.detail
    assert not telemetry.running


def test_the_fake_game_script_flies_a_session_with_every_moment(monkeypatch):
    """scripts/sc_telemetry_fake.py is how to test on a Mac: its flight must keep producing these events."""
    spec = importlib.util.spec_from_file_location(
        "sc_telemetry_fake", Path(REPO_ROOT) / "scripts" / "sc_telemetry_fake.py"
    )
    script = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, script)  # its dataclass looks itself up there
    spec.loader.exec_module(script)
    _, events, _ = replay(script.frames(delay=10.0, start=1_000_000.0))
    found = ids(events)
    for expected in ("powerplant_online", "took_off", "gear_retracted", "locked_on", "under_fire", "shields_down",
                     "shields_restored", "jump_started", "jump_finished", "uec_changed", "hydrogen_low", "landed",
                     "gear_deployed", "player_down", "respawned"):
        assert expected in found, expected
    assert found.index("jump_started") < found.index("jump_finished")
    assert not [event for event in events if event.time < 1_000_010.0]  # the baseline is quiet
