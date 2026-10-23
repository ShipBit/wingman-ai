"""Append-only debug log of local-AI memory operations (extraction + greeting).

Captures the raw input and raw model output of every memory extraction and
greeting generation, so the behaviour of the support model against our
prompts can be analysed against *real* usage later instead of guessed at.

Enabled by default; set ``WINGMAN_MEMORY_DEBUG_LOG=0`` to disable. Writes JSON
lines to ``<persistent_memory_dir>/memory_debug.jsonl`` and rotates to
``memory_debug.jsonl.1`` once the file passes ~5 MB.

This is best-effort diagnostics: every failure is swallowed so logging can never
break a memory operation.
"""

import json
import os
import time
from os import path

from services.file import get_persistent_memory_dir

LOG_FILENAME = "memory_debug.jsonl"
MAX_BYTES = 5 * 1024 * 1024


def _enabled() -> bool:
    return os.getenv("WINGMAN_MEMORY_DEBUG_LOG", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _log_path() -> str:
    return path.join(get_persistent_memory_dir(), LOG_FILENAME)


def _rotate_if_needed(p: str) -> None:
    try:
        if path.exists(p) and os.path.getsize(p) > MAX_BYTES:
            backup = p + ".1"
            if path.exists(backup):
                os.remove(backup)
            os.replace(p, backup)
    except OSError:
        pass


def log_memory_event(event_type: str, wingman_name: str, **fields) -> None:
    """Append one diagnostic record as a JSON line. Never raises.

    Args:
        event_type: e.g. ``"extraction"`` or ``"greeting"``.
        wingman_name: the Wingman the event belongs to.
        **fields: arbitrary JSON-serialisable diagnostic data (input text, raw
            model output, sampling preset, reasoning flag, truncation, etc.).
    """
    if not _enabled():
        return
    try:
        record = {
            "ts": time.time(),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "type": event_type,
            "wingman": wingman_name,
            **fields,
        }
        p = _log_path()
        _rotate_if_needed(p)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        # Diagnostics must never interfere with a memory operation.
        pass
