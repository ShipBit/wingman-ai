"""A fake Star Citizen for testing the Star Citizen skills without the game.

The skills take two things from the game: places from the Game.log and the
position from the /showlocation chat command. This fakes both.

    venv/bin/python scripts/sc_fake_game.py                # folder ~/SC-Fake
    venv\\Scripts\\python scripts\\sc_fake_game.py D:\\SC-Fake

Point Settings > Star Citizen > game folder at the folder it prints, then
type at its prompt:

    go Lorville                   arrive at a place, named as the game log names it
    leave                         board a ship and leave the place
    at HDMS-Anderson              /showlocation answers from this place
    at Aberdeen 48.6255 8.9795 1690
                                  ... from this latitude, longitude and height in metres
    where                         where /showlocation answers from
    quit

While it runs, a /showlocation on the clipboard (the Position skill puts it
there and presses the chat keys) is answered with a Coordinates line for the
chosen place, the way the game would. The chat keys land in whatever window
has the focus: keep this window in front when the skill reads the position,
here they do nothing. The coordinates follow the skill's own rotation model
and calibration, so the skill reads back the place you chose.

Every run starts a new Game.log, the same as a new game launch.
scripts/sc_gamelog_fake.py plays a scripted session of HUD events instead.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from skills.sc_position import geo  # noqa: E402

BODIES_FILE = REPO / "skills" / "sc_position" / "data" / "bodies.json"
RULES_FILE = REPO / "services" / "sc_gamelog" / "data" / "instructions.json"
PILOT = "FakePilot"
SHIP = "Drake Cutlass Black"
COMMAND = "/showlocation"
HELP = """\
  go <place>                    arrive there (as the game log names it)
  leave                         board a ship and leave
  at <place>                    /showlocation answers from this place
  at <body> <lat> <lon> <alt m> ... from these coordinates
  where                         where /showlocation answers from
  quit"""


# --- the Game.log --------------------------------------------------------------


def stamp(now: float | None = None) -> str:
    moment = datetime.fromtimestamp(time.time() if now is None else now, timezone.utc)
    return "<" + moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z> "


def header_lines(now: float | None = None) -> list[str]:
    """A new log: the launch line the reader recognizes a log by, and the login
    that tells it whose lines to believe."""
    started = datetime.fromtimestamp(now or time.time(), timezone.utc).strftime("%a %b %d %H:%M:%S %Y")
    return [
        f"{stamp(now)}Log started on {started}",
        f"{stamp(now)}User Login Success Handle[{PILOT}]",
    ]


def inventory_of(code: str) -> str:
    return "inv_" + re.sub(r"\W", "_", code.lower())


def arrival_lines(code: str, now: float | None = None) -> list[str]:
    """What the game logs on arrival: the request for the place's inventory,
    then the move of the personal inventory into it."""
    return [
        f"{stamp(now)}[Notice] <RequestLocationInventory> Player[{PILOT}] Location[{code}]",
        f"{stamp(now)}[Notice] <Update Inventory Location> Player[{PILOT}] "
        f"Location[0] -> [{inventory_of(code)}]",
    ]


def departure_lines(code: str, now: float | None = None) -> list[str]:
    """Leaving is done aboard a ship: the pilot joins the ship's channel, then
    the inventory moves out of the place."""
    return [
        f'{stamp(now)}[Notice] <SHUDEvent> Added notification '
        f"\"You joined channel '{SHIP} : {PILOT}'.\" [3] to queue.",
        f"{stamp(now)}[Notice] <Update Inventory Location> Player[{PILOT}] "
        f"Location[{inventory_of(code)}] -> [0]",
    ]


def load_places() -> dict[str, tuple[str, str]]:
    """Lower-case place name to (name, log code), from the bundled log rules."""
    data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    places: dict[str, tuple[str, str]] = {}
    for code, item in data["lookups"]["locations"].items():
        places.setdefault(item["name"].lower(), (item["name"], code))
    return places


def place_code(places: dict, name: str) -> tuple[str, str] | None:
    wanted = name.strip().lower()
    if not wanted:
        return None
    for match in (lambda n: n == wanted, lambda n: n.startswith(wanted), lambda n: wanted in n):
        for key, found in places.items():
            if match(key):
                return found
    return None


class GameLog:
    def __init__(self, folder: Path) -> None:
        self.path = folder / "LIVE" / "Game.log"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(header_lines()) + "\n", encoding="utf-8")

    def write(self, lines: list[str]) -> None:
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")


# --- the position -----------------------------------------------------------------


def _key(name: str) -> str:
    return re.sub(r"[\s\-_]+", " ", (name or "").strip().lower())


class Spot:
    """Where /showlocation answers from: a body and a body-fixed point."""

    def __init__(self, bodies) -> None:
        self.bodies = bodies
        self.body = None
        self.local = None

    def at_place(self, name: str) -> str | None:
        """The place called `name` on any body; its name, or None."""
        wanted = _key(name)
        for body in self.bodies:
            for poi in body.pois:
                if _key(poi.name) == wanted:
                    return self._set(body, poi)
        for body in self.bodies:
            poi = geo.find_poi(body, name)
            if poi is not None:
                return self._set(body, poi)
        return None

    def _set(self, body, poi) -> str:
        self.body, self.local = body, (poi.x, poi.y, poi.z)
        return poi.name

    def at_lat_lon(self, body_name: str, lat: float, lon: float, alt_m: float) -> str | None:
        body = next((b for b in self.bodies if b.name.lower() == body_name.strip().lower()), None)
        if body is None:
            return None
        self.body, self.local = body, geo.body_fixed(body, lat, lon, alt_m / 1000)
        return body.name

    def describe(self) -> str:
        if self.body is None:
            return "nowhere yet: say 'at <place>' first"
        lat, lon, alt = geo.lat_lon_alt(self.body, self.local)
        near = geo.nearest_pois(self.body, self.local, 1)
        nearest = f", {geo.format_distance(near[0][1])} from {near[0][0].name}" if near else ""
        return f"{self.body.name} {lat:.4f} {lon:.4f} at {alt * 1000:.0f} m{nearest}"

    def answer(self, now: float, corrections: dict) -> str | None:
        """The Coordinates line the game would put on the clipboard now."""
        if self.body is None:
            return None
        correction = float(corrections.get(self.body.name, 0.0))
        gx, gy, gz = geo.from_body_fixed(self.body, self.local, now, correction)
        return f"Coordinates: x:{gx * 1000:.6f} y:{gy * 1000:.6f} z:{gz * 1000:.6f}"


def calibration_deltas() -> dict:
    """The Position skill's calibration, so the coordinates read back right."""
    try:
        from services.file import get_generated_files_dir
        from skills.sc_position.calibration import CalibrationStore

        return CalibrationStore(Path(get_generated_files_dir("ScPosition")) / "calibration.json").deltas()
    except Exception:
        return {}


def answer_showlocation(spot: Spot) -> None:
    from services.clipboard import write_text

    line = spot.answer(time.time(), calibration_deltas())
    if line is None:
        print(f"\n  {COMMAND} asked, but no place chosen: say 'at <place>'\n> ", end="", flush=True)
        return
    write_text(line)
    print(f"\n  {COMMAND} answered from {spot.describe()}\n> ", end="", flush=True)


def watch_clipboard(spot: Spot, stop: threading.Event) -> None:
    """Answers the command the moment the skill puts it on the clipboard."""
    from services.clipboard import read_text

    while not stop.is_set():
        try:
            if read_text().strip() == COMMAND:
                answer_showlocation(spot)
        except Exception:
            pass  # the clipboard was busy; the next look gets it
        stop.wait(0.1)


# --- the prompt ----------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", nargs="?", default=str(Path.home() / "SC-Fake"))
    args = parser.parse_args()

    folder = Path(args.folder).expanduser()
    log = GameLog(folder)
    places = load_places()
    spot = Spot(geo.load_bodies(BODIES_FILE))
    here: tuple[str, str] | None = None
    stop = threading.Event()
    threading.Thread(target=watch_clipboard, args=(spot, stop), daemon=True).start()

    print(f"Game folder for Wingman: {folder}")
    print(HELP)
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        word, _, rest = line.partition(" ")
        word = word.lower()
        if word in ("quit", "exit"):
            break
        if word == "go":
            found = place_code(places, rest)
            if found is None:
                print(f"  no place called '{rest}' in the log rules")
                continue
            name, code = found
            log.write(arrival_lines(code))
            here = found
            print(f"  arrived at {name} ({code})")
            if spot.at_place(name):
                print(f"  {COMMAND} answers from {spot.describe()}")
        elif word == "leave":
            if here is None:
                print("  not at a place")
                continue
            log.write(departure_lines(here[1]))
            print(f"  left {here[0]}")
            here = None
        elif word == "at":
            parts = rest.split()
            if len(parts) == 4:
                try:
                    body = spot.at_lat_lon(parts[0], float(parts[1]), float(parts[2]), float(parts[3]))
                except ValueError:
                    body = None
                print(f"  {spot.describe()}" if body else f"  no body called '{parts[0]}'")
            elif spot.at_place(rest):
                print(f"  {spot.describe()}")
            else:
                print(f"  no place called '{rest}' in the position data")
        elif word == "where":
            print(f"  {spot.describe()}")
        elif line == COMMAND:
            answer_showlocation(spot)  # the skill's keys landed here
        else:
            print(HELP)
    stop.set()


if __name__ == "__main__":
    main()
