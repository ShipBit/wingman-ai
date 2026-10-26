"""Star Citizen Position: the clipboard line, the body model, the key
sequence and the waypoint file."""

import asyncio
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from skills.sc_position import geo
from skills.sc_position.reader import ANSWER_PREFIX, COMMAND, PositionReader, ReadError
from skills.sc_position.waypoints import Waypoint, WaypointStore
from tests.support import REPO_ROOT

BODIES = Path(REPO_ROOT) / "skills" / "sc_position" / "data" / "bodies.json"
# Measured at Port Tressler, 2026-10-26, with a current game build.
PORT_TRESSLER_LINE = "Coordinates: x:22462439049.328499 y:37185045006.979584 z:808384.643767"
PORT_TRESSLER_TIME = datetime(2026, 10, 26, 17, 28, 54, tzinfo=timezone.utc).timestamp()


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def bodies():
    return geo.load_bodies(BODIES)


# --- the clipboard line -----------------------------------------------------------

def test_the_clipboard_line_parses_to_metres():
    assert geo.parse_clipboard(PORT_TRESSLER_LINE) == (22462439049.328499, 37185045006.979584, 808384.643767)
    assert geo.parse_clipboard("Coordinates: x:-12.5 y:0 z:3") == (-12.5, 0.0, 3.0)


def test_other_clipboard_text_is_refused():
    for text in ("", COMMAND, "Coordinates: nope", "x:1 y:2 z:3", None):
        with pytest.raises(ValueError):
            geo.parse_clipboard(text)


# --- bodies and rotation ------------------------------------------------------------

def test_the_body_data_loads(bodies):
    names = {body.name for body in bodies}
    assert {"Stanton", "microTech", "Daymar", "Hurston", "Crusader", "ArcCorp", "Yela"} <= names
    micro = next(body for body in bodies if body.name == "microTech")
    assert micro.radius_km == 1000.0
    assert micro.rotates
    assert any(poi.name == "Port Tressler" for poi in micro.pois)
    assert not any(poi.name.startswith("OM-") for poi in micro.pois)


def test_a_measurement_at_port_tressler_resolves(bodies):
    x, y, z = geo.parse_clipboard(PORT_TRESSLER_LINE)

    fix = geo.locate(bodies, x, y, z, PORT_TRESSLER_TIME)

    assert fix.body.name == "microTech"
    assert 120 < fix.alt_km < 130
    assert 45 < fix.lat < 47
    assert fix.nearest.name == "Port Tressler"
    assert fix.nearest_km < 3


def test_rotation_moves_a_surface_point(bodies):
    x, y, z = geo.parse_clipboard(PORT_TRESSLER_LINE)
    micro = next(body for body in bodies if body.name == "microTech")

    now = geo.locate(bodies, x, y, z, PORT_TRESSLER_TIME)
    later = geo.locate(bodies, x, y, z, PORT_TRESSLER_TIME + 3600)

    expected = 360 / micro.rotation_hours  # degrees per hour
    turned = (later.lon - now.lon) % 360
    assert math.isclose(min(turned, 360 - turned), expected, abs_tol=0.01)
    assert math.isclose(later.lat, now.lat, abs_tol=1e-9)
    assert math.isclose(later.alt_km, now.alt_km, abs_tol=1e-6)


def test_lat_lon_alt_round_trip(bodies):
    micro = next(body for body in bodies if body.name == "microTech")
    for lat, lon, alt in ((45.9, -44.8, 126.3), (-12.0, 170.0, 0.2), (0.0, 0.0, 0.0), (89.0, 10.0, 5.0)):
        local = geo.body_fixed(micro, lat, lon, alt)
        back = geo.lat_lon_alt(micro, local)
        assert math.isclose(back[0], lat, abs_tol=1e-6)
        assert math.isclose(((back[1] - lon) + 180) % 360 - 180, 0, abs_tol=1e-6)
        assert math.isclose(back[2], alt, abs_tol=1e-6)


def test_open_space_falls_back_to_the_system_frame(bodies):
    fix = geo.locate(bodies, 1.0e12, -2.0e12, 5.0e11, PORT_TRESSLER_TIME)

    assert fix.body.is_system
    assert fix.nearest is None
    assert fix.local_km == (1.0e9, -2.0e9, 5.0e8)


def test_bearing_and_compass():
    assert math.isclose(geo.bearing_deg(0, 0, 10, 0), 0, abs_tol=1e-9)
    assert math.isclose(geo.bearing_deg(0, 0, 0, 10), 90, abs_tol=1e-9)
    assert math.isclose(geo.bearing_deg(10, 0, 0, 0), 180, abs_tol=1e-9)
    assert geo.compass(0) == "N"
    assert geo.compass(44) == "NE"
    assert geo.compass(226) == "SW"
    assert geo.compass(359) == "N"


def test_distances_read_well():
    assert geo.format_distance(0.35) == "350 m"
    assert geo.format_distance(1.6) == "1.6 km"
    assert geo.format_distance(4344036.6) == "4,344,037 km"


# --- the key sequence -----------------------------------------------------------

class FakeGame:
    """Enough of Star Citizen's chat to answer /showlocation."""

    def __init__(self, chat_visible: bool, answers: bool = True) -> None:
        self.chat_visible = chat_visible
        self.answers = answers
        self.clipboard = "something the user copied"
        self.focused = False
        self.buffer = ""
        self.presses: list[str] = []

    async def press(self, key: str) -> None:
        self.presses.append(key)
        if key == "f12":
            self.chat_visible = not self.chat_visible
            self.focused = False
        elif key == "enter" and self.chat_visible:
            if self.focused:
                if self.buffer == COMMAND and self.answers:
                    self.clipboard = PORT_TRESSLER_LINE
                self.buffer, self.focused = "", False
            else:
                self.focused = True
        elif key == "ctrl+v" and self.focused:
            self.buffer += self.clipboard

    async def read_clipboard(self) -> str:
        return self.clipboard

    async def write_clipboard(self, text: str) -> None:
        self.clipboard = text


async def _no_sleep(_seconds: float) -> None:
    pass


def _reader(game: FakeGame) -> PositionReader:
    return PositionReader(
        press=game.press, read_clipboard=game.read_clipboard, write_clipboard=game.write_clipboard,
        sleep=_no_sleep, now=lambda: 1234.5,
    )


def test_reads_the_position_when_the_chat_is_visible():
    game = FakeGame(chat_visible=True)

    reading = _run(_reader(game).read())

    assert reading.text == PORT_TRESSLER_LINE
    assert reading.measured_at == 1234.5
    assert not reading.toggled_chat
    assert "f12" not in game.presses
    assert game.chat_visible
    assert game.clipboard == "something the user copied"


def test_shows_a_hidden_chat_and_hides_it_again():
    game = FakeGame(chat_visible=False)

    reading = _run(_reader(game).read())

    assert reading.text.startswith(ANSWER_PREFIX)
    assert reading.toggled_chat
    assert game.presses.count("f12") == 2
    assert not game.chat_visible
    assert game.clipboard == "something the user copied"


def test_no_answer_is_an_error_and_leaves_things_as_they_were():
    game = FakeGame(chat_visible=False, answers=False)

    with pytest.raises(ReadError):
        _run(_reader(game).read())

    assert not game.chat_visible
    assert game.clipboard == "something the user copied"


# --- waypoints ---------------------------------------------------------------------

def _waypoint(name: str, body: str = "Daymar") -> Waypoint:
    return Waypoint(name=name, body=body, lat=1.0, lon=2.0, alt_m=3.0, tolerance_m=500.0,
                    measured_at="2026-10-26T17:28:54+00:00", global_m=[1.0, 2.0, 3.0])


def test_waypoints_survive_a_restart(tmp_path):
    path = tmp_path / "waypoints.json"
    store = WaypointStore(path)
    store.add(_waypoint("Treasure cave"))
    store.add(_waypoint("Crash site"), activate=False)

    again = WaypointStore(path)

    assert [w.name for w in again.all()] == ["Treasure cave", "Crash site"]
    assert again.active().name == "Treasure cave"


def test_waypoints_are_found_loosely_and_replaced_by_name(tmp_path):
    store = WaypointStore(tmp_path / "waypoints.json")
    store.add(_waypoint("Treasure cave"))
    store.add(_waypoint("treasure CAVE", body="Yela"))

    assert [w.body for w in store.all()] == ["Yela"]
    assert store.find("TREASURE").name == "treasure CAVE"
    assert store.find("cave").name == "treasure CAVE"
    assert store.find("nothing") is None
    assert store.find("") is None


def test_a_broken_file_loads_as_empty(tmp_path):
    path = tmp_path / "waypoints.json"
    path.write_text("not json", encoding="utf-8")

    store = WaypointStore(path)

    assert store.all() == []
    assert store.active() is None
