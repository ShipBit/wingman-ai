"""
SC_Accountant - Atomic File Writes

Crash-safe replacement for truncating ``open(path, "w")`` writes of
source-of-truth data. A mid-write crash with a truncating open silently
leaves the file partial, and readers then skip the malformed lines. Writing
to a temp file on the same volume and then ``os.replace``-ing it over the
target keeps the original file intact until the new contents are fully on
disk.

Author: Mallachi
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write text to ``path`` atomically via a temp file in the same directory.

    Writes to a uniquely named temp file alongside the target (same volume,
    so ``os.replace`` is atomic on both Windows and POSIX), flushes and
    fsyncs it, then replaces the target with it. On any failure the temp file
    is removed and the original file at ``path`` is left untouched, so a crash
    or error can never leave a truncated or partially written file behind.

    Args:
        path: Destination file path.
        text: Full contents to write.
        encoding: Text encoding for the file. Defaults to UTF-8.

    Raises:
        OSError: If the temp file cannot be written or the replace fails. The
            caller keeps its existing log-and-continue handling; the original
            file is guaranteed intact when this raises.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f"{path.name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except OSError:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
