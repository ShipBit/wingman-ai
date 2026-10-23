"""The event history in events.sqlite3.

The tables and the `erp_feed_*` metadata are the feed contract (version 1) of
the SC Log Reader skill this replaces: SC Accountant reads the file directly,
in its own read-only connection, by `events.id` as the cursor. Keep the column
names and the metadata keys as they are.

Every record gets a stable key from the log it came from and its byte range,
so reading the same Game.log again after a restart adds nothing twice.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

FEED_CONTRACT_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations(
    occurrence TEXT PRIMARY KEY, environment TEXT NOT NULL, generation TEXT NOT NULL,
    byte_start INTEGER, byte_end INTEGER, event_type TEXT, errors TEXT NOT NULL,
    fields TEXT NOT NULL, source_timestamp TEXT, instruction_version TEXT,
    observed_at REAL NOT NULL, rule_id TEXT);
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY, occurrence TEXT, environment TEXT, event_type TEXT,
    category TEXT, amount REAL, status TEXT, source_time REAL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS event_filter ON events(environment, event_type, category, id);
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT);
"""


class EventHistory:
    """Append-only history. Used from the reader thread only."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript(_SCHEMA)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(observations)")}
        if "rule_id" not in columns:
            self.db.execute("ALTER TABLE observations ADD COLUMN rule_id TEXT")
        known = dict(
            self.db.execute(
                "SELECT key, value FROM metadata WHERE key IN "
                "('erp_feed_source_id', 'erp_feed_contract_version')"
            )
        )
        if not known:
            self.db.executemany(
                "INSERT INTO metadata(key, value) VALUES(?, ?)",
                [
                    ("erp_feed_source_id", str(uuid.uuid4())),
                    ("erp_feed_contract_version", str(FEED_CONTRACT_VERSION)),
                ],
            )
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def record(self, occurrence, environment, generation, record, event, rows) -> bool:
        """Store one parsed record and the events it produced, in one
        transaction. False when this record was stored before."""
        with self.db:
            inserted = self.db.execute(
                "INSERT OR IGNORE INTO observations(occurrence, environment, generation, "
                "byte_start, byte_end, event_type, errors, fields, source_timestamp, "
                "instruction_version, observed_at, rule_id) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    occurrence,
                    environment,
                    generation,
                    record.start,
                    record.end,
                    event.event_type,
                    json.dumps(event.errors),
                    json.dumps(event.fields),
                    event.source_timestamp.isoformat() if event.source_timestamp else None,
                    event.instruction_version,
                    time.time(),
                    event.rule_id or None,
                ),
            ).rowcount
            if not inserted:
                return False
            source_time = event.source_timestamp.timestamp() if event.source_timestamp else None
            for row in rows:
                self.db.execute(
                    "INSERT INTO events(occurrence, environment, event_type, category, "
                    "amount, status, source_time, payload) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        occurrence,
                        environment,
                        row["event_type"],
                        row.get("category"),
                        row.get("amount_auec"),
                        row["status"],
                        source_time,
                        json.dumps(row),
                    ),
                )
        return True
