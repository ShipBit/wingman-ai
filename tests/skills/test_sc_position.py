"""Star Citizen Position: the clipboard line, the body model, the key
sequence and the waypoint file."""

import asyncio
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from skills.sc_position import geo
from skills.sc_position.calibration import Calibration, CalibrationStore
from skills.sc_position.reader import ANSWER_PREFIX, COMMAND, PositionReader, ReadError
from skills.sc_position.waypoints import Waypoint, WaypointStore, parse_target
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


def _reader(game: FakeGame, chat_hidden: bool) -> PositionReader:
    return PositionReader(
        press=game.press, read_clipboard=game.read_clipboard, write_clipboard=game.write_clipboard,
        sleep=_no_sleep, now=lambda: 1234.5, chat_hidden=chat_hidden,
    )


def test_reads_the_position_when_the_chat_is_visible():
    game = FakeGame(chat_visible=True)

    reading = _run(_reader(game, chat_hidden=False).read())

    assert reading.text == PORT_TRESSLER_LINE
    assert reading.measured_at == 1234.5
    assert not reading.toggled_chat
    assert game.presses == ["enter", "ctrl+v", "enter"]
    assert game.chat_visible
    assert game.clipboard == "something the user copied"


def test_shows_a_hidden_chat_and_hides_it_again():
    game = FakeGame(chat_visible=False)

    reading = _run(_reader(game, chat_hidden=True).read())

    assert reading.text.startswith(ANSWER_PREFIX)
    assert reading.toggled_chat
    assert game.presses == ["f12", "enter", "ctrl+v", "enter", "f12"]
    assert not game.chat_visible
    assert game.clipboard == "something the user copied"


def test_a_wrong_setting_fails_once_and_names_the_setting():
    # The chat is visible but the setting says hidden: one sequence, no
    # second try with the other state (its keys would reach the game).
    game = FakeGame(chat_visible=True)

    with pytest.raises(ReadError, match="switch off 'Chat is hidden'"):
        _run(_reader(game, chat_hidden=True).read())

    assert game.presses == ["f12", "enter", "ctrl+v", "enter", "f12"]
    assert game.chat_visible
    assert game.clipboard == "something the user copied"

    game = FakeGame(chat_visible=False)

    with pytest.raises(ReadError, match="switch on 'Chat is hidden'"):
        _run(_reader(game, chat_hidden=False).read())

    assert game.presses == ["enter", "ctrl+v", "enter"]
    assert not game.chat_visible


def test_no_answer_is_an_error_and_leaves_things_as_they_were():
    game = FakeGame(chat_visible=False, answers=False)

    with pytest.raises(ReadError):
        _run(_reader(game, chat_hidden=True).read())

    assert not game.chat_visible
    assert game.clipboard == "something the user copied"


# --- calibration -----------------------------------------------------------------

def _measurement_at(bodies, body_name: str, place: str, t: float, true_offset_deg: float):
    """Global metres of a pilot standing at `place`, in a world whose body
    has turned `true_offset_deg` further than the model says."""
    body = next(b for b in bodies if b.name == body_name)
    poi = geo.find_poi(body, place)
    gx, gy, gz = geo.from_body_fixed(body, (poi.x, poi.y, poi.z), t, true_offset_deg)
    return body, poi, (gx * 1000, gy * 1000, gz * 1000)


def test_a_drifted_rotation_is_corrected_by_one_known_place(bodies):
    body, poi, (x, y, z) = _measurement_at(bodies, "microTech", "Port Tressler", PORT_TRESSLER_TIME, 4.1)

    before = geo.locate(bodies, x, y, z, PORT_TRESSLER_TIME)
    delta = geo.calibration_delta(before.local_km, poi)
    after = geo.locate(bodies, x, y, z, PORT_TRESSLER_TIME, {"microTech": delta})

    assert before.nearest.name == "Port Tressler" and before.nearest_km > 50
    assert math.isclose(delta, 4.1, abs_tol=1e-6)
    assert after.correction_deg == delta
    assert after.nearest.name == "Port Tressler" and after.nearest_km < 0.001


def test_the_correction_is_the_shortest_turn(bodies):
    body, poi, (x, y, z) = _measurement_at(bodies, "Daymar", "Shubin Mining Facility SCD-1", PORT_TRESSLER_TIME, -170.0)

    fix = geo.locate(bodies, x, y, z, PORT_TRESSLER_TIME)
    delta = geo.calibration_delta(fix.local_km, poi)

    assert math.isclose(delta, -170.0, abs_tol=1e-6)
    assert -180 < delta <= 180


def test_from_body_fixed_inverts_to_body_fixed(bodies):
    body = next(b for b in bodies if b.name == "Daymar")
    local = (100.0, -200.0, 50.0)

    gx, gy, gz = geo.from_body_fixed(body, local, PORT_TRESSLER_TIME, 2.5)
    back = geo.to_body_fixed(body, gx, gy, gz, PORT_TRESSLER_TIME, 2.5)

    assert all(math.isclose(a, b, abs_tol=1e-6) for a, b in zip(back, local))


def test_places_are_found_loosely(bodies):
    micro = next(b for b in bodies if b.name == "microTech")

    assert geo.find_poi(micro, "port tressler").name == "Port Tressler"
    assert geo.find_poi(micro, "PORT").name.startswith("Port")
    assert geo.find_poi(micro, "nowhere") is None
    assert geo.find_poi(micro, "") is None

    # The game log writes "HDMS-Anderson", the data "HDMS Anderson".
    aberdeen = next(b for b in bodies if b.name == "Aberdeen")
    assert geo.find_poi(aberdeen, "HDMS-Anderson").name == "HDMS Anderson"
    assert geo.find_poi(aberdeen, "hdms_anderson").name == "HDMS Anderson"


def test_calibrations_survive_a_restart(tmp_path):
    path = tmp_path / "calibration.json"
    store = CalibrationStore(path)
    store.set(Calibration(body="microTech", delta_deg=4.1, place="Port Tressler",
                          calibrated_at="2026-10-26T17:28:54+00:00", residual_m=900.0))

    again = CalibrationStore(path)

    assert again.get("microTech").place == "Port Tressler"
    assert again.deltas() == {"microTech": 4.1}
    assert again.get("Daymar") is None


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


def test_places_sharing_coordinates_rank_without_comparing_places(bodies):
    # Aberdeen lists Klescher Rehabilitation Facility and South Borehole at one spot;
    # ranking by distance alone fell through to comparing the places themselves.
    aberdeen = next(b for b in bodies if b.name == "Aberdeen")
    klescher = geo.find_poi(aberdeen, "Klescher Rehabilitation Facility")

    ranked = geo.nearest_pois(aberdeen, (klescher.x, klescher.y, klescher.z), 3)

    assert [poi.name for poi, _ in ranked[:2]] == ["Klescher Rehabilitation Facility", "South Borehole"]
    assert ranked[0][1] == 0 and ranked[1][1] == 0 and ranked[2][1] > 0


# --- the skill: what a failed measurement tells the model ---------------------------

from skills.sc_position.main import ScPosition  # noqa: E402


class _Log:
    def __init__(self):
        self.errors = []

    def error(self, message, server_only=False):
        self.errors.append((message, server_only))


def _skill_whose_measurement(raises) -> ScPosition:
    skill = object.__new__(ScPosition)
    skill.log = _Log()

    async def measure():
        raise raises

    skill._measure = measure
    return skill


def test_a_bug_in_the_skill_is_named_and_not_retried():
    skill = _skill_whose_measurement(TypeError("'<' not supported between instances of 'Poi' and 'Poi'"))

    fix, text = _run(skill._fix())

    assert fix is None
    assert "TypeError" in text and "Retrying will not help" in text
    assert skill.log.errors and skill.log.errors[0][1] is True  # traceback stays in the server log


def test_a_silent_game_is_reported_as_such():
    skill = _skill_whose_measurement(ReadError("Star Citizen did not answer /showlocation."))

    fix, text = _run(skill._fix())

    assert fix is None
    assert text.startswith("Could not read the position: Star Citizen did not answer")
    assert not skill.log.errors


# --- wording ---------------------------------------------------------------------

from skills.sc_position.wording import describe  # noqa: E402


def _fix_at(bodies, body_name: str, place: str, offset_km: tuple = (0.0, 0.0, 0.0), alt_km=None):
    """A fix on `body_name`, `offset_km` away from `place` in the body-fixed frame."""
    body = next(b for b in bodies if b.name == body_name)
    poi = geo.find_poi(body, place)
    local = (poi.x + offset_km[0], poi.y + offset_km[1], poi.z + offset_km[2])
    if alt_km is not None:
        lat, lon, _ = geo.lat_lon_alt(body, local)
        local = geo.body_fixed(body, lat, lon, alt_km)
    lat, lon, alt = geo.lat_lon_alt(body, local)
    nearest, nearest_km = geo.nearest_pois(body, local, 1)[0]
    return geo.Fix(body=body, lat=lat, lon=lon, alt_km=alt, local_km=local, global_m=(0, 0, 0),
                   measured_at=PORT_TRESSLER_TIME, nearest=nearest, nearest_km=nearest_km)


def test_within_the_place_radius_the_pilot_is_at_the_place(bodies):
    fix = _fix_at(bodies, "microTech", "Port Tressler", (1.0, 1.0, 0.0))

    text, hud = describe(fix, None, calibrated=True, place_km=5)

    assert "at Port Tressler (127 km above microTech)" in text
    assert "lat" not in text and "km from" not in text
    assert hud.startswith("Port Tressler · microTech 127 km up")


def test_up_to_five_radii_the_pilot_is_near_the_place(bodies):
    fix = _fix_at(bodies, "microTech", "Port Tressler", (12.0, 0.0, 0.0))

    text, hud = describe(fix, None, calibrated=True, place_km=5)

    assert "near Port Tressler, 12.0 km from it" in text
    assert hud.startswith("near Port Tressler 12.0 km")


def test_far_away_the_nearest_place_is_a_reference_with_coordinates(bodies):
    fix = _fix_at(bodies, "microTech", "Port Tressler", (60.0, 0.0, 0.0))

    text, hud = describe(fix, None, calibrated=True, place_km=5)

    assert "lat " in text and "nearest known place Port Tressler (60.0 km)" in text
    assert "at Port Tressler" not in text


def test_on_the_surface_the_pilot_is_on_the_body(bodies):
    fix = _fix_at(bodies, "Daymar", "Shubin Mining Facility SCD-1", alt_km=0.02)

    text, hud = describe(fix, None, calibrated=False, place_km=5)

    assert "at Shubin Mining Facility SCD-1 (on Daymar)" in text
    assert "not calibrated" in text
    assert "Daymar surface" in hud


def test_a_waypoint_reports_arrival_or_the_way(bodies):
    fix = _fix_at(bodies, "microTech", "Port Tressler", (1.0, 1.0, 0.0))
    here = Waypoint(name="Hangar", body="microTech", lat=fix.lat, lon=fix.lon, alt_m=fix.alt_km * 1000,
                    tolerance_m=500, measured_at="", global_m=[])
    elsewhere = Waypoint(name="Cave", body="Daymar", lat=0, lon=0, alt_m=0, tolerance_m=500,
                         measured_at="", global_m=[])

    text, hud = describe(fix, here, calibrated=True, place_km=5)
    assert "Waypoint 'Hangar': arrived" in text and hud.endswith("Hangar ✓")

    text, hud = describe(fix, elsewhere, calibrated=True, place_km=5)
    assert "Waypoint 'Cave' is on Daymar, not here" in text


def test_an_inline_target_is_a_waypoint_without_a_file():
    target = parse_target("Aberdeen 12.4 -88.1 120 800")
    assert (target.body, target.lat, target.lon, target.alt_m, target.tolerance_m) == ("Aberdeen", 12.4, -88.1, 120.0, 800.0)
    assert parse_target("Pyro IV 1.5, 2.5, 30").body == "Pyro IV"
    assert parse_target("Pyro IV 1.5 2.5 30").tolerance_m == 1000.0
    assert parse_target("Treasure cave") is None
    assert parse_target("") is None
    assert parse_target("12 13 14 15") is None
