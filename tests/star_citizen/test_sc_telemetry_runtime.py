"""Reader (against an in-process gRPC server), feed, health and the event catalogue."""
import threading
import time

import pytest

from skills.sc_telemetry import events, feed, health
from skills.sc_telemetry.reader import TelemetryReader
from skills.sc_telemetry.schema import STREAM_METHOD
from tests.star_citizen.sc_telemetry_support import (
    load_frames,
    serve,
)


def test_reader_receives_recorded_frames():
    recorded = [frame for _, frame in load_frames("countermeasures_2026-10-28.jsonl")[:5]]
    server, port = serve(recorded)
    got, statuses = [], []
    done = threading.Event()

    def on_frame(frame, t):
        got.append(frame)
        if len(got) == len(recorded):
            done.set()

    reader = TelemetryReader(on_frame, statuses.append, address=f"127.0.0.1:{port}")
    reader.start()
    try:
        assert done.wait(10)
    finally:
        reader.stop()
        server.stop(0)
    assert got == recorded  # same dict shape as the probe recordings
    assert statuses[:2] == ["connected", "live"]
    assert STREAM_METHOD.endswith("/TelemetryStream")


def test_reader_waits_when_nothing_listens():
    statuses = []
    reader = TelemetryReader(lambda f, t: None, statuses.append, address="127.0.0.1:1")
    reader.start()
    deadline = time.time() + 10
    while "waiting" not in statuses and time.time() < deadline:
        time.sleep(0.1)
    reader.stop()
    assert "waiting" in statuses and statuses[-1] == "stopped"


def test_reader_refuses_non_loopback():
    with pytest.raises(ValueError):
        TelemetryReader(lambda f, t: None, lambda s: None, address="0.0.0.0:2942")


def test_feed_snapshot_and_events(tmp_path):
    writer = feed.Feed(tmp_path)
    writer.write_state({"derived": {"heading_valid": True}}, "live")
    writer.add_event("shields_down", "ship", 1.0, {})
    writer.add_event("under_fire", "combat", 2.0, {})
    snapshot = feed.read_state(tmp_path)
    assert snapshot["source_id"] == writer.source_id and snapshot["state"]["derived"]["heading_valid"]
    page = feed.read_events(tmp_path, after=0, limit=1)
    assert [e["type"] for e in page["events"]] == ["shields_down"]
    rest = feed.read_events(tmp_path, after=page["next_cursor"])
    assert [e["type"] for e in rest["events"]] == ["under_fire"]
    writer.close()


def test_stale_snapshot_reads_as_none(tmp_path, monkeypatch):
    writer = feed.Feed(tmp_path)
    writer.write_state({}, "live")
    later = time.time() + feed.STALE_S + 1
    monkeypatch.setattr(feed.time, "time", lambda: later)
    assert feed.read_state(tmp_path) is None
    writer.close()


@pytest.mark.parametrize("reader_status, variable, registered, expected", [
    ("no_grpc", True, True, "no_grpc"),
    ("live", False, None, "live"),
    ("waiting", False, None, "off"),
    ("waiting", True, False, "unsupported"),
    ("waiting", True, None, "waiting"),
    ("waiting", None, None, "other_os"),  # not Windows: the variable is set in the user's launcher
    ("live", None, None, "live"),
])
def test_health_status(reader_status, variable, registered, expected):
    assert health.overall(reader_status, variable, registered) == expected
    assert health.MESSAGES[expected]


def test_game_log_registration_line(tmp_path):
    log = tmp_path / "Game.log"
    log.write_text("...\n<Register Service> " + health.REGISTERED_LINE + " [Team_OnlineTech][gRPC]\n")
    assert health.game_log_registered(log) is True
    log.write_text("no telemetry here\n")
    assert health.game_log_registered(log) is False
    assert health.game_log_registered(tmp_path / "missing.log") is None


def test_every_event_has_a_known_group_and_renders():
    for spec in events.EVENTS:
        assert spec.group in events.GROUPS
        assert events.render(spec, {}).strip()
