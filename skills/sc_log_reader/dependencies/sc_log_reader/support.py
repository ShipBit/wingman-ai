"""Bounded local diagnostics. Domain evidence and money never enter these tables."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import tempfile
import time
from contextlib import closing
from pathlib import Path

ENVIRONMENTS = ("LIVE", "PTU", "EPTU", "HOTFIX", "TECH-PREVIEW")
REASONS = (
    "unrecognized",
    "incomplete_record",
    "record_too_large",
    "ambiguous_rules",
    "regex_budget_exceeded",
    "invalid_record_fields",
    "state_field_validation_failed",
    "missing",
    "invalid",
    "conflicting_aliases",
    "other_diagnostic",
)
TIMEOUT_CAUSES = ("regex_timeout", "operation_deadline", "entry_deadline")
PARSE_STAGES = (
    "record",
    "notification",
    "ignore",
    "match",
    "read",
    "legacy",
    "validate",
    "timestamp",
    "return",
    "capture",
    "bracket_fields",
    "constant",
    "normalize",
    "choose",
    "collect_true_fields",
    "exclude_values",
    "quantity_with_unit",
    "notification_payload",
)
SLOT_LIMIT = 256
RECENT_LIMIT = 512
SAMPLE_LIMIT = 50
UNKNOWN_LIMIT = 100
TEXT_BYTES = 2048
PAYLOAD_BYTES = 4096
MAX_COUNT = (1 << 63) - 1
HISTORY_WARNING_BYTES = 1 << 30
COUNT_SCOPE = (
    "Committed ordered source prefixes are checkpoint-fenced. Direct diagnostic "
    "ingest deduplicates only the latest 512 occurrences; older replay may recount. "
    "Financial and state occurrence identities remain durable."
)


def environment_bucket(value):
    return value if value in ENVIRONMENTS else "OTHER"


def timeout_detail(fields):
    """Only engine-owned enums may cross the persisted/exported detail boundary."""
    cause = fields.get("timeout_cause", fields.get("reason"))
    stage = fields.get("stage")
    return {
        "timeout_cause": cause if cause in TIMEOUT_CAUSES else "unknown",
        "stage": stage if stage in PARSE_STAGES else "unknown",
    }


def clipped(value, limit=128):
    return str(value or "").encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def identity(value):
    text = str(value or "")
    if len(text.encode("utf-8")) <= 128 and all(ord(c) >= 32 for c in text):
        return text
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def encoded(payload):
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode()) > PAYLOAD_BYTES:
        raise ValueError("Support payload exceeds bound")
    return raw


def increment(payload, key, amount=1):
    prior = payload.get(key, 0)
    payload[key] = min(MAX_COUNT, prior + amount)
    if prior + amount > MAX_COUNT:
        payload["counter_saturated"] = True


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS support_totals(key TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS support_buckets(key TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS support_recent(occurrence TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS support_samples(environment TEXT,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS support_unknown(fingerprint TEXT PRIMARY KEY,environment TEXT,payload TEXT NOT NULL);
    """)


def _read(db, table, key):
    row = db.execute(f"SELECT payload FROM {table} WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def _write(db, table, key, payload):
    db.execute(f"INSERT OR REPLACE INTO {table} VALUES(?,?)", (key, encoded(payload)))


def record_support(
    db,
    record,
    environment,
    generation,
    occurrence,
    event,
    version,
    instruction_digest,
    *,
    unknown=False,
):
    """Call only inside the source/checkpoint transaction; no process caches."""
    if db.execute(
        "SELECT 1 FROM support_recent WHERE occurrence=?", (occurrence,)
    ).fetchone():
        return False
    db.execute("INSERT INTO support_recent VALUES(?)", (occurrence,))
    db.execute(
        "DELETE FROM support_recent WHERE rowid NOT IN (SELECT rowid FROM support_recent ORDER BY rowid DESC LIMIT ?)",
        (RECENT_LIMIT,),
    )
    env = environment_bucket(environment)
    error = event.errors[0] if event and event.errors else "other_diagnostic"
    reason = "unrecognized" if unknown else error.split(":", 1)[0]
    reason = reason if reason in REASONS else "other_diagnostic"
    timeout = (
        timeout_detail(event.fields)
        if event and reason == "regex_budget_exceeded"
        else {}
    )
    now = time.time()
    ref = {
        "generation": identity(generation),
        "byte_start": max(-MAX_COUNT, min(MAX_COUNT, record.start)),
        "byte_end": max(-MAX_COUNT, min(MAX_COUNT, record.end)),
        "occurrence": occurrence,
        "source_timestamp": event.source_timestamp.isoformat()
        if event and event.source_timestamp
        else None,
    }
    base = {
        "environment": env,
        "reason": reason,
        "count": 0,
        "first": ref,
        "last": ref,
        "first_ingested_at": now,
        "last_ingested_at": now,
        "counter_saturated": False,
    }
    total_key = env + ":" + reason
    total = _read(db, "support_totals", total_key) or dict(base)
    increment(total, "count")
    total.update(last=ref, last_ingested_at=now)
    label = identity(event.rule_id) if event else ""
    ver = identity(event.instruction_version or version) if event else identity(version)
    # One ingestion-hour window, with an absolute global cap even under clock changes.
    bucket_identity = [env, reason, label, ver, instruction_digest, int(now // 3600)]
    if timeout:
        bucket_identity.append(timeout)
    bucket_key = hashlib.sha256(encoded(bucket_identity).encode()).hexdigest()
    bucket = _read(db, "support_buckets", bucket_key)
    if bucket is None:
        if (
            db.execute("SELECT COUNT(*) FROM support_buckets").fetchone()[0]
            >= SLOT_LIMIT
        ):
            db.execute(
                "DELETE FROM support_buckets WHERE rowid=(SELECT MIN(rowid) FROM support_buckets)"
            )
            increment(total, "evicted_bucket_count")
        bucket = dict(
            base,
            **timeout,
            rule_id=label,
            instruction_version=ver,
            instruction_digest=instruction_digest,
            identity_overflow=bool(
                event
                and (
                    label != event.rule_id
                    or ver != (event.instruction_version or version)
                )
            ),
        )
    increment(bucket, "count")
    bucket.update(last=ref, last_ingested_at=now)
    # Only the first sample of a retained slot is kept; repeated text cannot grow keys.
    sampled = bucket["count"] == 1
    increment(bucket, "sample_count" if sampled else "sample_suppressed_count")
    increment(total, "sample_count" if sampled else "sample_suppressed_count")
    if sampled:
        sample = {
            **timeout,
            "environment": env,
            "generation": identity(generation),
            "byte_start": ref["byte_start"],
            "byte_end": ref["byte_end"],
            "instruction_version": ver,
            "rule_id": label or None,
            "event_type": identity(event.event_type) if event else None,
            "errors": [clipped(e, 128) for e in event.errors[:4]] if event else [],
            "sample": clipped(record.text, TEXT_BYTES),
            "truncated": len(record.text.encode()) > TEXT_BYTES,
        }
        # JSON escaping can expand control characters sixfold. Trim the whole encoded payload.
        while (
            len(json.dumps(sample, ensure_ascii=False, separators=(",", ":")).encode())
            > PAYLOAD_BYTES
        ):
            if sample["sample"]:
                sample["sample"] = sample["sample"][: len(sample["sample"]) // 2]
            else:
                sample["errors"] = sample["errors"][: len(sample["errors"]) // 2]
            sample["truncated"] = True
        if sample["truncated"] or (
            event
            and (
                len(event.errors) > 4
                or any(len(str(e).encode()) > 128 for e in event.errors)
            )
        ):
            sample["truncated"] = True
            increment(total, "sample_truncated_count")
        if unknown:
            db.execute(
                "INSERT OR REPLACE INTO support_unknown VALUES(?,?,?)",
                (occurrence, env, encoded(sample)),
            )
            db.execute(
                "DELETE FROM support_unknown WHERE environment=? AND rowid NOT IN (SELECT rowid FROM support_unknown WHERE environment=? ORDER BY rowid DESC LIMIT ?)",
                (env, env, UNKNOWN_LIMIT),
            )
        else:
            db.execute(
                "INSERT INTO support_samples VALUES(?,?)", (env, encoded(sample))
            )
            db.execute(
                "DELETE FROM support_samples WHERE rowid NOT IN (SELECT rowid FROM support_samples ORDER BY rowid DESC LIMIT ?)",
                (SAMPLE_LIMIT,),
            )
    _write(db, "support_totals", total_key, total)
    _write(db, "support_buckets", bucket_key, bucket)
    return True


def summary(db):
    totals = [
        json.loads(row[0]) for row in db.execute("SELECT payload FROM support_totals")
    ]
    return {
        "total_count": min(MAX_COUNT, sum(p["count"] for p in totals)),
        "retained_slots": db.execute("SELECT COUNT(*) FROM support_buckets").fetchone()[
            0
        ],
        "recent_occurrences": db.execute(
            "SELECT COUNT(*) FROM support_recent"
        ).fetchone()[0],
        "diagnostic_samples": db.execute(
            "SELECT COUNT(*) FROM support_samples"
        ).fetchone()[0],
        "unknown_samples": db.execute(
            "SELECT COUNT(*) FROM support_unknown"
        ).fetchone()[0],
        "evicted_bucket_count": min(
            MAX_COUNT, sum(p.get("evicted_bucket_count", 0) for p in totals)
        ),
        "sample_suppressed_count": min(
            MAX_COUNT, sum(p.get("sample_suppressed_count", 0) for p in totals)
        ),
        "sample_truncated_count": min(
            MAX_COUNT, sum(p.get("sample_truncated_count", 0) for p in totals)
        ),
        "retained_details": [
            json.loads(row[0])
            for row in db.execute(
                "SELECT payload FROM support_buckets ORDER BY rowid DESC"
            )
        ],
        "counter_saturated": any(p["counter_saturated"] for p in totals)
        or sum(p["count"] for p in totals) > MAX_COUNT,
        "count_scope": COUNT_SCOPE,
        "detail_scope": "Exact rule/version identities only for retained slots; oversized identities are SHA-256 labelled. Evicted detail is unavailable.",
        "totals": totals,
        "limits": {
            "aggregate_slots": SLOT_LIMIT,
            "recent_occurrences": RECENT_LIMIT,
            "diagnostic_samples": SAMPLE_LIMIT,
            "unknown_samples_per_environment": UNKNOWN_LIMIT,
            "payload_bytes": PAYLOAD_BYTES,
            "text_bytes": TEXT_BYTES,
            "counter_max": MAX_COUNT,
        },
    }


def resources(root, db):
    """Bounded one-directory scan; callers cache the result between health calls."""
    result = {
        "measured_at": time.time(),
        "measurement_errors": [],
        "history_pruning_enabled": False,
        "object_cleanup_enabled": False,
    }
    for label, suffix in (
        ("database_bytes", ""),
        ("wal_bytes", "-wal"),
        ("shm_bytes", "-shm"),
    ):
        try:
            result[label] = (root / ("events.sqlite3" + suffix)).stat().st_size
        except FileNotFoundError:
            result[label] = None if not suffix else 0
            if not suffix:
                result["measurement_errors"].append(label)
        except OSError:
            result[label] = None
            result["measurement_errors"].append(label)
    result["history_warning"] = (
        "history_at_least_1_gib"
        if sum(result[k] or 0 for k in ("database_bytes", "wal_bytes"))
        >= HISTORY_WARNING_BYTES
        else None
    )
    result.update(object_bytes=0, object_count=0, object_scan_truncated=False)
    try:
        with os.scandir(root / "instructions" / "objects") as entries:
            for index, entry in enumerate(entries):
                if index == 4096:
                    result["object_scan_truncated"] = True
                    break
                if entry.is_file(follow_symlinks=False):
                    result["object_bytes"] += entry.stat(follow_symlinks=False).st_size
                    result["object_count"] += 1
    except OSError:
        result.update(object_bytes=None, object_count=None)
        result["measurement_errors"].append("objects")
    result["support_payload_bytes_approximate"] = sum(
        db.execute(
            f"SELECT COALESCE(SUM(length(CAST(payload AS BLOB))),0) FROM {table}"
        ).fetchone()[0]
        for table in (
            "support_totals",
            "support_buckets",
            "support_samples",
            "support_unknown",
        )
    )
    result["support_size_scope"] = (
        "UTF-8 JSON payload bytes; excludes SQLite pages/index overhead and recent occurrence digests."
    )
    return result


def _no_links(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("Support paths must not contain links")
        try:
            metadata = os.lstat(part)
        except FileNotFoundError:
            continue  # The requested new output file need not exist yet.
        if (
            getattr(metadata, "st_file_attributes", 0)
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError("Support paths must not contain reparse points")


def export_support(runtime, destination):
    """Read-only coherent SQLite snapshot; strict allowlist, no runtime construction."""
    root = Path(runtime).absolute()
    dest = Path(destination).absolute()
    _no_links(root)
    _no_links(dest)
    root = root.resolve()
    dest = dest.resolve()
    db_path = root / "events.sqlite3"
    _no_links(db_path)
    for suffix in ("-wal", "-shm"):
        _no_links(root / ("events.sqlite3" + suffix))
    if not root.is_dir() or not db_path.is_file():
        raise ValueError("Existing runtime database required")
    if (
        dest.exists()
        or not dest.parent.is_dir()
        or dest.suffix.lower() != ".json"
        or dest.is_relative_to(root)
    ):
        raise ValueError(
            "Choose a new JSON file outside the runtime in an existing directory"
        )
    try:
        with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("BEGIN")
            support = summary(db)
            measured = resources(root, db)
            # Never serialize source fields, labels, references, errors or arbitrary metadata.
            safe = {
                key: support[key]
                for key in (
                    "total_count",
                    "retained_slots",
                    "recent_occurrences",
                    "diagnostic_samples",
                    "unknown_samples",
                    "evicted_bucket_count",
                    "sample_suppressed_count",
                    "counter_saturated",
                    "limits",
                )
            }
            safe["totals"] = [
                {
                    "environment": p["environment"]
                    if p["environment"] in (*ENVIRONMENTS, "OTHER")
                    else "OTHER",
                    "reason": p["reason"]
                    if p["reason"] in REASONS
                    else "other_diagnostic",
                    "count": max(0, min(MAX_COUNT, int(p["count"]))),
                }
                for p in support["totals"]
            ]
            safe["timeout_details"] = [
                {
                    **timeout_detail(p),
                    "count": max(0, min(MAX_COUNT, int(p["count"]))),
                }
                for p in support["retained_details"]
                if p.get("reason") == "regex_budget_exceeded"
            ]
            safe["timeout_detail_scope"] = (
                "Counts for retained aggregate slots only; evicted detail is unavailable. "
                "Older slots without cause/stage are reported as unknown."
            )
            result = {
                "schema_version": 1,
                "redacted": True,
                "support": safe,
                "resources": measured,
            }
            payload = json.dumps(result, indent=2).encode()
    except (sqlite3.Error, KeyError, TypeError, ValueError) as exc:
        raise ValueError("Cannot read support data from runtime") from exc
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=dest.parent, prefix=".support-", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        _no_links(dest)
        if dest.exists():
            raise ValueError("Support destination already exists")
        # Windows rename refuses overwrite; a racing file cannot be replaced.
        if os.name == "nt":
            os.rename(temporary, dest)
        else:
            os.link(temporary, dest)
            temporary.unlink()
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"exported": True, "redacted": True}
