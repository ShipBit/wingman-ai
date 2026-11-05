#!/usr/bin/env python3
"""Write the update channel into services/build_channel.py before a build.

    python scripts/set_build_channel.py production

Run by the Core build workflows right before PyInstaller, so the same commit
can be built for unstable and for production. Only the working copy of the
runner changes; nothing is committed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANNELS = ("unstable", "production")
TARGET = Path(__file__).resolve().parent.parent / "services" / "build_channel.py"


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in CHANNELS:
        raise SystemExit(f"usage: set_build_channel.py {'|'.join(CHANNELS)}")
    channel = sys.argv[1]
    text = TARGET.read_text(encoding="utf-8")
    text, count = re.subn(r'^CHANNEL = ".*"$', f'CHANNEL = "{channel}"', text, flags=re.M)
    if count != 1:
        raise SystemExit(f"{TARGET} has no single CHANNEL line to set.")
    TARGET.write_text(text, encoding="utf-8")
    print(f"Build channel: {channel}")


if __name__ == "__main__":
    main()
