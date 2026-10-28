"""scripts/sc_fake_game.py stands in for the game: its log lines must read as
arrivals and departures with the real rules, and its coordinates must read
back as the place chosen."""

import asyncio
import importlib.util
import time
from pathlib import Path

from skills.sc_position import geo
from tests.star_citizen.gamelog import until
from tests.support import REPO_ROOT


def _fake_game():
    spec = importlib.util.spec_from_file_location("sc_fake_game", Path(REPO_ROOT) / "scripts" / "sc_fake_game.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_fake_log_arrives_and_departs_under_the_real_rules(reader, tmp_path):
    fake = _fake_game()
    log = tmp_path / "game" / "LIVE" / "Game.log"
    log.parent.mkdir(parents=True)
    log.write_text("\n".join(fake.header_lines()) + "\n", encoding="utf-8")
    name, code = fake.place_code(fake.load_places(), "lorville")
    assert name == "Lorville"

    async def run():
        heard = []
        reader.subscribe("*", heard.append)
        await reader.start(str(tmp_path / "game"))
        await until(lambda: reader.state() is not None)
        with log.open("a", encoding="utf-8") as stream:
            stream.write("\n".join(fake.arrival_lines(code)) + "\n")
        await until(lambda: any(event.type == "location_arrived" for event in heard))
        with log.open("a", encoding="utf-8") as stream:
            stream.write("\n".join(fake.departure_lines(code)) + "\n")
        await until(lambda: any(event.type == "location_departed" for event in heard))
        await reader.stop()
        return heard

    heard = asyncio.run(run())
    arrived = next(event for event in heard if event.type == "location_arrived")
    assert arrived.data["location_name"] == "Lorville" and arrived.catching_up is False
    departed = next(event for event in heard if event.type == "location_departed")
    assert departed.data["location_name"] == "Lorville"


def test_the_fake_position_reads_back_as_the_place_chosen():
    fake = _fake_game()
    spot = fake.Spot(geo.load_bodies(fake.BODIES_FILE))
    now = time.time()
    assert spot.answer(now, {}) is None, "no place chosen yet"

    assert spot.at_lat_lon("Aberdeen", 48.6255, 8.9795, 1690) == "Aberdeen"
    calibrated = {"Aberdeen": 12.5}
    x, y, z = geo.parse_clipboard(spot.answer(now, calibrated))
    fix = geo.locate(spot.bodies, x, y, z, now, calibrated)
    assert fix.body.name == "Aberdeen"
    assert abs(fix.lat - 48.6255) < 1e-4 and abs(fix.lon - 8.9795) < 1e-4
    assert abs(fix.alt_km * 1000 - 1690) < 1

    # The log's hyphen, the data's space: the same place.
    assert spot.at_place("HDMS-Anderson") == "HDMS Anderson"
    x, y, z = geo.parse_clipboard(spot.answer(now, {}))
    fix = geo.locate(spot.bodies, x, y, z, now, {})
    assert fix.nearest.name == "HDMS Anderson" and fix.nearest_km < 0.001
    assert "HDMS Anderson" in spot.describe()
