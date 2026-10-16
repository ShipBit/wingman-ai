"""Leaving a place, quantum arrivals of a ship boarded under its display name,
and contracts that hand out several objectives at once."""

from datetime import datetime, timedelta, timezone

from services.sc_gamelog.reader import Event
from services.sc_gamelog.state import State

START = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)
LOOKUPS = {"locations": {"RR_HUR_LEO": {"name": "Everus Harbor", "system": "Stanton"}}}
ME = {"player_name": "TestPilot"}


class Session:
    def __init__(self):
        self.state = State(LOOKUPS)
        self.n = 0
        self.send(0, "user_login", **ME)

    def send(self, second, kind, **fields):
        self.n += 1
        event = Event(kind, fields, START + timedelta(seconds=second))
        return [row["event_type"] for row in self.state.apply(event, f"o{self.n}", "g")]


def arrive_and_board(session, move_first=True):
    if move_first:
        session.send(10, "inventory_location_update", loc_from="0", loc_to="308639451", **ME)
        session.send(28, "location_change", location="RR_HUR_LEO", **ME)
    else:
        session.send(10, "location_change", location="RR_HUR_LEO", **ME)
        session.send(12, "inventory_location_update", loc_from="0", loc_to="308639451", **ME)
    session.send(60, "channel_change", action="joined", ship_name="RSI Constellation Mk V Centaurus", owner="TestPilot")


def test_taking_off_from_a_station_is_a_departure():
    session = Session()
    arrive_and_board(session)
    assert session.send(300, "inventory_location_update", loc_from="308639451", loc_to="467417103", **ME) == ["location_departed"]
    assert session.state.data["location_status"] == "departed"


def test_the_arrival_may_be_logged_before_its_inventory_move():
    session = Session()
    arrive_and_board(session, move_first=False)
    assert session.send(300, "inventory_location_update", loc_from="308639451", loc_to="467417103", **ME) == ["location_departed"]


def test_walking_into_another_inventory_on_foot_is_no_departure():
    session = Session()
    session.send(10, "inventory_location_update", loc_from="0", loc_to="308639451", **ME)
    session.send(28, "location_change", location="RR_HUR_LEO", **ME)
    assert session.send(300, "inventory_location_update", loc_from="308639451", loc_to="1409305106", **ME) == []
    assert session.state.data["location_status"] == "at"


def test_a_quantum_arrival_matches_the_display_name_of_the_boarded_ship():
    session = Session()
    arrive_and_board(session)
    assert session.send(400, "qt_arrived", entity_class="RSI_Constellation_Mk5_Centaurus") == ["qt_arrived"]
    assert session.send(500, "qt_arrived", entity_class="RSI_Hermes") == []  # Another ship nearby.


def test_a_contract_keeps_all_its_open_objectives():
    session = Session()
    mission = {"mission_id": "abc-123"}
    session.send(10, "contract_accepted", mission_name="Courier Run", **mission)
    for objective in ("Collect Food", "Collect Water", "Deliver Food"):
        session.send(11, "objective_new", objective=objective, **mission)
    session.send(20, "objective_complete", objective="Collect Food", **mission)
    active = session.state.data["active_missions"]["abc-123"]
    assert active["objectives"] == ["Collect Water", "Deliver Food"]
    assert active["objective"] == "Deliver Food"
