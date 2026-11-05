"""Plays a short Star Citizen flight into Wingman's telemetry, for testing without the game.

Runs a fake game on 127.0.0.1:2942 that streams telemetry the way Star Citizen does, 17 frames a second. In
Wingman, say you play Star Citizen and switch on telemetry (Settings > Star Citizen), then run from the repo root:

    python scripts/sc_telemetry_fake.py                  # one step every 10 s
    python scripts/sc_telemetry_fake.py --delay 12
    python scripts/sc_telemetry_fake.py --with-gamelog   # the game log too, for both sources at once
    python scripts/sc_telemetry_fake.py --replay tests/star_citizen/sc_telemetry_fixtures/combat_2026-10-28.jsonl.gz

--with-gamelog writes a new Game.log into ~/SC-Fake/LIVE (set Settings > Star Citizen > game folder to ~/SC-Fake)
with the lines the game writes at the same moments: the telemetry service registering, a reward, low fuel and going
down. Those are the moments both sources see; Star Citizen Events says each once, from the source picked in its
settings. Keep a step at 10 s or more: a quantum jump only counts as over 8 s after it ended, and a wallet change
5 s after the balance settled.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import threading
import time
from concurrent import futures
from dataclasses import dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FRAMES_PER_SECOND = 17
FLOAT_MAX = 3.4028234663852886e38
NO_PLANET = 3.4e38
"""The game sends 3.4028235e38 outside a planet's frame; this is the largest value a float field takes here."""


@dataclass(frozen=True)
class Pilot:
    """What the fake game shows: a pilot in a Drake Cutter."""

    seated: bool = True
    power: bool = False
    landed: bool = True
    gear: str = "DEPLOYED"
    shields: str = "NOMINAL"
    hit: str = "OFF"
    radar: str = "NOMINAL"
    thrusters: str = "NOMINAL"
    g: float = 1.0
    altitude: float = 1200.0
    speed: float = 0.0
    hydrogen: float = 0.8
    health: float = 100.0
    balance: int = 25_000

    def frame(self) -> dict:
        actor = {
            "state": {
                "locomotion": "ACTOR_LOCOMOTION_STATE_SEATED" if self.seated else "ACTOR_LOCOMOTION_STATE_ON_FOOT",
                "crew_role": "ACTOR_CREW_ROLE_PILOT" if self.seated else "ACTOR_CREW_ROLE_UNSPECIFIED",
                "seat_name": "DRAK_Cutter_SCItem_Seat_Pilot_907038284576" if self.seated else "",
                "uec_balance": str(self.balance),
            },
            "vitals": {
                "health": {"current": self.health, "max": 100.0},
                "oxygen": {"current": 100.0, "max": 100.0},
                "hunger": {"current": 80.0, "max": 100.0},
                "thirst": {"current": 75.0, "max": 100.0},
                "heart_rate": 72.0,
                "gravity": 1.0,
            },
            "environment": {"external_temperature": 21.0, "breathable_atmosphere": True},
        }
        if not self.seated:
            return {"actor": actor}
        planet = self.altitude < NO_PLANET
        light = "ANNUNCIATOR_STATE_"
        vehicle = {
            "state": {
                "name": "DRAK_Cutter_907038284543",
                "class_name": "DRAK_Cutter",
                "type": "VEHICLE_TYPE_SPACESHIP",
                "power": {
                    flag: self.power
                    for flag in ("powerplants", "engines", "weapons", "coolers", "life_support", "sensors",
                                 "shield_generators", "shield_emitters")
                },
                "annunciators": {
                    "pwr": light + ("NOMINAL" if self.power else "OFF"),
                    "shld": light + self.shields,
                    "hit": light + self.hit,
                    "radr": light + self.radar,
                    "thr": light + self.thrusters,
                },
                "flight": {
                    "state": {"is_landed": self.landed, "gear": f"VEHICLE_COMPONENT_DEPLOYMENT_STATE_{self.gear}"},
                    "instruments": {
                        "speed": self.speed,
                        "altitude": self.altitude,
                        "radar_altitude": self.altitude - 40.0 if planet else self.altitude,
                        "heading": 90.0,
                        "g_meter": {"current": self.g, "max": 5.0},
                        "hydrogen_fuel": self.hydrogen,
                        "boost": {"reserves": 1.0},
                    },
                },
            }
        }
        weapons = {
            "weapons": [
                {"name": "KLWE_LaserRepeater_S2_907038284578", "is_powered": self.power, "ready_to_fire": self.power},
            ],
            "countermeasures": [
                {"type": "COUNTERMEASURE_TYPE_DECOY", "amount": 24},
                {"type": "COUNTERMEASURE_TYPE_NOISE", "amount": 12},
            ],
        }
        return {"actor": actor, "vehicle": vehicle, "weapons": weapons}


STEPS: tuple[tuple[str, dict, str | None], ...] = (
    # (what happens, what changes, the game log's HUD notification at the same moment)
    ("Sitting in a Drake Cutter, power off. The first frames are the baseline: quiet", {}, None),
    ("Powerplant on", {"power": True}, None),
    ("Take off, gear up", {"landed": False, "gear": "RETRACTED", "speed": 120.0, "altitude": 1500.0}, None),
    ("Something locks on", {"radar": "MAJOR_ON"}, None),
    ("Taking hits, shields down", {"hit": "MAJOR_FLASHING", "shields": "MAJOR_ON"}, None),
    ("Shields back up", {"hit": "OFF", "shields": "NOMINAL", "radar": "NOMINAL"}, None),
    ("Quantum jump", {"thrusters": "MAJOR_ON", "g": 0.0, "altitude": NO_PLANET, "speed": 0.0}, None),
    ("Arrived", {"thrusters": "NOMINAL", "g": 1.0, "altitude": 2000.0, "speed": 80.0}, None),
    ("Reward of 12500 aUEC", {"balance": 37_500}, "Awarded 12500 aUEC:"),
    ("Hydrogen low", {"hydrogen": 0.1}, "Low Fuel"),
    ("Landing, gear down", {"landed": True, "gear": "DEPLOYED", "speed": 0.0}, None),
    ("Pilot down", {"health": 0.0}, "Incapacitated"),
    ("Respawned at a station", {"health": 100.0, "seated": False}, None),
)


def session(delay: float) -> list[tuple[float, Pilot, str, str | None]]:
    """(seconds from the start, what the game shows from then on, label, HUD notification) per step."""
    pilot = Pilot()
    steps = []
    for index, (label, changes, notification) in enumerate(STEPS):
        pilot = replace(pilot, **changes)
        steps.append((index * delay, pilot, label, notification))
    return steps


def frames(delay: float, start: float = 0.0) -> list[tuple[float, dict]]:
    """The whole session as (time, frame) at 17 frames a second, for the tests: what the server streams."""
    steps = session(delay)
    end = steps[-1][0] + delay
    result = []
    for tick in range(int(end * FRAMES_PER_SECOND)):
        t = tick / FRAMES_PER_SECOND
        pilot = [step[1] for step in steps if step[0] <= t][-1]
        result.append((start + t, pilot.frame()))
    return result


class FakeGame:
    """Streams the current frame 17 times a second to everyone who asks."""

    def __init__(self) -> None:
        self.frame: dict = Pilot().frame()
        self.stopped = threading.Event()

    def stream(self, request, context):
        from google.protobuf.json_format import ParseDict

        from services.sc_telemetry.schema import message_classes

        response_cls = message_classes()[1]
        print("  Wingman connected")
        while context.is_active() and not self.stopped.is_set():
            yield ParseDict(_clamped(self.frame), response_cls())
            time.sleep(1 / FRAMES_PER_SECOND)


def _clamped(value):
    if isinstance(value, dict):
        return {key: _clamped(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clamped(item) for item in value]
    if isinstance(value, float) and value > FLOAT_MAX:
        return FLOAT_MAX
    return value


def serve(game: FakeGame):
    import grpc

    from services.sc_telemetry.schema import SERVICE, message_classes

    request_cls, _ = message_classes()
    handler = grpc.method_handlers_generic_handler(SERVICE, {
        "TelemetryStream": grpc.unary_stream_rpc_method_handler(
            game.stream, request_deserializer=request_cls.FromString,
            response_serializer=lambda message: message.SerializeToString())})
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    server.add_generic_rpc_handlers((handler,))
    server.add_insecure_port("127.0.0.1:2942")
    server.start()
    return server


def _game_log(folder: str) -> Path:
    import sc_gamelog_fake  # next to this script

    log = Path(folder).expanduser() / "LIVE" / "Game.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    stamp = sc_gamelog_fake._stamp
    log.write_text(
        f"{stamp()}Log started on {time.strftime('%a %b %d %H:%M:%S %Y', time.gmtime())}\n"
        f"{stamp()}User Login Success Handle[MacPilot]\n"
        f"{stamp()}[Notice] <Register Service> Service 'sc.game.telemetry.v1.GameTelemetryService' registered "
        "[Team_OnlineTech][gRPC]\n",
        encoding="utf-8",
    )
    print(f"Game folder for Wingman: {log.parent.parent}")
    return log


def _write_notice(log: Path, text: str) -> None:
    import sc_gamelog_fake

    with log.open("a", encoding="utf-8") as stream:
        stream.write(sc_gamelog_fake._stamp() + sc_gamelog_fake._hud(text) + "\n")


def _replay(game: FakeGame, file: str) -> None:
    with gzip.open(file, "rt", encoding="utf-8") as handle:
        recorded = [(row["t"], row["frame"]) for row in map(json.loads, handle)]
    print(f"Replaying {len(recorded)} recorded frames, again and again. Ctrl+C stops.")
    while True:
        previous = recorded[0][0]
        for t, frame in recorded:
            time.sleep(max(0.0, min(t - previous, 1.0)))
            previous = t
            game.frame = frame
        print("  (from the start)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--delay", type=float, default=10.0, help="seconds between steps")
    parser.add_argument("--with-gamelog", action="store_true", help="also write the matching Game.log lines")
    parser.add_argument("--folder", default=str(Path.home() / "SC-Fake"), help="game folder for --with-gamelog")
    parser.add_argument("--replay", help="stream a recorded moment (.jsonl.gz) instead of the flight")
    args = parser.parse_args()

    game = FakeGame()
    server = serve(game)
    print("Fake Star Citizen telemetry on 127.0.0.1:2942. Waiting a few seconds for Wingman to connect.")
    try:
        if args.replay:
            _replay(game, args.replay)
            return
        log = _game_log(args.folder) if args.with_gamelog else None
        time.sleep(5)
        for _, pilot, label, notification in session(args.delay):
            game.frame = pilot.frame()
            print(f"  {label}" + (f"  (Game.log: {notification})" if log and notification else ""))
            if log and notification:
                _write_notice(log, notification)
            time.sleep(args.delay)
        print("Done. Run it again for another flight.")
    except KeyboardInterrupt:
        pass
    finally:
        game.stopped.set()
        server.stop(0)


if __name__ == "__main__":
    main()
