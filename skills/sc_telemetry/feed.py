"""The feed for other skills (NavPoint): a snapshot file and a read-only SQLite event feed.

Same contract style as the log reader's feed: a `contract_version`, a `source_id` that changes with every game session
(consumers drop their cursor when it changes), cursors that are sequence numbers, never timestamps.

- `telemetry_state.json`: the current smoothed state, written atomically (temp file + rename), ~10 times a second.
  A consumer treats it as stale when `written_at` is more than STALE_S old.
- `telemetry_events.sqlite`: every event the Handler detects, before its cooldowns and the notification switches,
  one row each.

Single writer: one skill instance per Wingman process. Writes and close() share a lock, so unload() cannot close
the database under a write from the reader thread.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

CONTRACT_VERSION = 1
STATE_FILE = "telemetry_state.json"
EVENTS_FILE = "telemetry_events.sqlite"
STALE_S = 2.0
KEEP_EVENTS = 5000
REPLACE_TRIES = 3
REPLACE_WAIT_S = 0.005


class Feed:
    def __init__(self, directory: Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self.source_id = uuid.uuid4().hex
        self._seq = 0
        self._lock = threading.Lock()
        self._closed = False
        self._db = sqlite3.connect(self._dir / EVENTS_FILE, check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)")
        self._db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                         "source_id TEXT, t REAL, type TEXT, grp TEXT, payload TEXT)")
        self._db.executemany("INSERT OR REPLACE INTO metadata VALUES (?, ?)",
                             [("contract_version", str(CONTRACT_VERSION)), ("source_id", self.source_id)])
        self._db.commit()

    def write_state(self, state: dict, status: str) -> None:
        """Raises OSError when the file is busy (Windows: a consumer has it open); the caller skips that frame."""
        with self._lock:
            if self._closed:
                return
            self._seq += 1
            payload = {"contract_version": CONTRACT_VERSION, "source_id": self.source_id, "seq": self._seq,
                       "written_at": time.time(), "status": status, "state": state}
            target = self._dir / STATE_FILE
            temp = target.with_suffix(".tmp")
            temp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            # Windows refuses the swap while a consumer has the target open for a moment (seen live: WinError 5
            # whenever a reader polled it). A few quick retries almost always get through.
            for attempt in range(REPLACE_TRIES):
                try:
                    os.replace(temp, target)
                    return
                except PermissionError:
                    if attempt == REPLACE_TRIES - 1:
                        raise
                    time.sleep(REPLACE_WAIT_S)

    def add_event(self, event_id: str, group: str, t: float, data: dict) -> None:
        with self._lock:
            if self._closed:
                return
            self._db.execute("INSERT INTO events (source_id, t, type, grp, payload) VALUES (?, ?, ?, ?, ?)",
                             (self.source_id, t, event_id, group, json.dumps(data)))
            self._db.execute("DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - ?", (KEEP_EVENTS,))
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._db.close()


def read_state(directory: Path) -> dict | None:
    """For consumers: the current state, or None when missing, unreadable or stale."""
    try:
        payload = json.loads((Path(directory) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if payload.get("contract_version") != CONTRACT_VERSION or time.time() - payload.get("written_at", 0) > STALE_S:
        return None
    return payload


def read_events(directory: Path, after: int = 0, limit: int = 200) -> dict:
    """For consumers: events after the cursor, read-only. Keep `source_id` with `next_cursor`."""
    db = sqlite3.connect(f"{(Path(directory) / EVENTS_FILE).resolve().as_uri()}?mode=ro", uri=True)
    try:
        meta = dict(db.execute("SELECT key, value FROM metadata"))
        rows = db.execute("SELECT id, t, type, grp, payload FROM events WHERE id > ? ORDER BY id LIMIT ?",
                          (after, limit)).fetchall()
    finally:
        db.close()
    events = [{"seq": r[0], "t": r[1], "type": r[2], "group": r[3], "data": json.loads(r[4])} for r in rows]
    return {"contract_version": int(meta.get("contract_version", 0)), "source_id": meta.get("source_id"),
            "next_cursor": events[-1]["seq"] if events else after, "events": events}
