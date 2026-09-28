"""Explicit human launch hook for a source-Python host; never a model tool."""

import json
import sys
from pathlib import Path

from .updates import atomic_write


def write_launcher(runtime):
    if getattr(sys, "frozen", False) or Path(sys.executable).stem.lower() not in {
        "python",
        "pythonw",
        "python3",
        "python3.11",
        "python3.13",
    }:
        raise RuntimeError(
            "Review launcher unavailable for a frozen executable; a qualified Python review runtime is required"
        )
    runtime = Path(runtime).resolve()
    script = runtime / "review-updates.py"
    package_root = str(Path(__file__).resolve().parent.parent)
    code = (
        "# Human-only launcher, generated for this exact runtime.\n"
        "import os, sys\n"
        f"if os.path.normcase(sys.executable) != os.path.normcase({sys.executable!r}):\n"
        "    raise RuntimeError('Use the exact Python interpreter in review-launcher.json')\n"
        f"sys.path.insert(0, {package_root!r})\n"
        "from sc_log_reader.review_ui import show_review\n"
        f"print('Review runtime:', {str(runtime)!r})\n"
        f"show_review({str(runtime)!r}, host_mode=True)\n"
    )
    atomic_write(script, code.encode())
    command = [sys.executable, str(script)]
    atomic_write(
        runtime / "review-launcher.json",
        json.dumps({"runtime": str(runtime), "argv": command}).encode(),
    )
    return command


def invalidate_launcher(runtime):
    runtime = Path(runtime).resolve()
    if (runtime / "review-updates.py").exists():
        atomic_write(
            runtime / "review-updates.py",
            b"raise RuntimeError('Wingman runtime configuration changed; use the current review launcher')\n",
        )
        atomic_write(
            runtime / "review-launcher.json", b'{"status":"configuration changed"}'
        )
