"""Plays a short Star Citizen session into a fake Game.log, for testing without the game.

Point Settings > Star Citizen > game folder at the folder this writes
(default ~/SC-Fake), then run:

    python scripts/sc_gamelog_fake.py            # one event every 20 s
    python scripts/sc_gamelog_fake.py --delay 5

Every run starts a new Game.log, the same as a new game launch.
"""

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path


def _hud(text: str, mission: str = "") -> str:
    tail = f" MissionId[{mission}]" if mission else ""
    return f'[Notice] <SHUDEvent> Added notification "{text}" [3] to queue.{tail}'


SESSION = [
    ("Leaving the armistice zone", _hud("Leaving Armistice Zone")),
    ("Contract accepted", _hud("Contract Accepted: Big Delivery: ", "fake-001")),
    ("Entered monitored space", _hud("Entered Monitored Space")),
    ("Low fuel", _hud("Low Fuel")),
    ("Contract complete", _hud("Contract Complete: Big Delivery: ", "fake-001")),
    ("Reward 12500 aUEC", _hud("Awarded 12500 aUEC:")),
    ("CrimeStat increased", _hud("CrimeStat Rating Increased")),
    ("Entering the armistice zone", _hud("Entering Armistice Zone")),
]


def _stamp() -> str:
    now = datetime.now(timezone.utc)
    return "<" + now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z> "


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", nargs="?", default=str(Path.home() / "SC-Fake"))
    parser.add_argument("--delay", type=float, default=20.0)
    args = parser.parse_args()

    log = Path(args.folder).expanduser() / "LIVE" / "Game.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S %Y")
    log.write_text(
        f"{_stamp()}Log started on {started}\n"
        f"{_stamp()}User Login Success Handle[MacPilot]\n",
        encoding="utf-8",
    )
    print(f"Game folder for Wingman: {log.parent.parent}")

    for label, line in SESSION:
        time.sleep(args.delay)
        with log.open("a", encoding="utf-8") as stream:
            stream.write(_stamp() + line + "\n")
        print(f"  {label}")
    print("Done. Run it again for a new session.")


if __name__ == "__main__":
    main()
