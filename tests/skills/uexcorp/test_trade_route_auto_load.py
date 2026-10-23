"""filter_require_auto_load of uex_get_trade_routes.

Hangar auto load/unload is a terminal flag, not a route field. The tool must hard-filter origin
and destination through the terminals when asked, without using vehicle.is_hangar (that means
the ship contains a hangar) and without breaking the loading dock filter of used_ship."""

import pytest

from tests.skills.uexcorp.support import add_route, add_terminal, route_pairs, search

AUTO_CITY, AUTO_STATION, MANUAL_OUTPOST, MANUAL_PAD, AUTO_FUEL, AUTO_UNAVAILABLE = range(1, 7)

AUTO_CITY_TO_STATION = ("Auto City TDD", "Auto Station TDD")
AUTO_STATION_TO_CITY = ("Auto Station TDD", "Auto City TDD")


@pytest.fixture
def market(db):
    for terminal_id, name, auto_load, available, places in (
        (AUTO_CITY, "Auto City TDD", 1, 1, {"city_name": "Auto City"}),
        (AUTO_STATION, "Auto Station TDD", 1, 1, {}),
        (MANUAL_OUTPOST, "Manual Outpost TDD", 0, 1, {"outpost_name": "Manual Outpost"}),
        (MANUAL_PAD, "Manual Pad TDD", 0, 1, {}),
        (AUTO_UNAVAILABLE, "Auto Unavailable TDD", 1, 0, {}),
    ):
        add_terminal(db, terminal_id, name, is_auto_load=auto_load, is_available=available, **places)
    add_terminal(db, AUTO_FUEL, "Auto Fuel", type="fuel", is_auto_load=1)
    names = {terminal["id"]: terminal["name"] for terminal in db.execute_fetchall("SELECT id, name FROM terminal")}
    for route_id, origin, destination, dock in (
        (101, AUTO_CITY, AUTO_STATION, 0),
        (102, AUTO_CITY, MANUAL_OUTPOST, 1),
        (103, MANUAL_OUTPOST, AUTO_STATION, 0),
        (104, MANUAL_OUTPOST, MANUAL_PAD, 0),
        (105, AUTO_STATION, AUTO_CITY, 1),
        (106, AUTO_FUEL, AUTO_STATION, 0),
    ):
        add_route(
            db, route_id, id_terminal_origin=origin, id_terminal_destination=destination,
            origin_terminal_name=names[origin], destination_terminal_name=names[destination],
            price_origin=10, price_destination=20, scu_origin=8, scu_destination=8, profit=80, score=50, distance=1,
            has_loading_dock_origin=dock, has_loading_dock_destination=dock,
        )
    db.execute("INSERT INTO vehicle (id, name_full, is_loading_dock, is_hangar, scu) VALUES (1, 'MISC Hull C', 1, 0, 100), (2, 'ANVL Carrack', 0, 1, 50)")
    db.commit()


def test_the_filter_keeps_only_routes_with_auto_load_at_both_ends(helper, market):
    assert route_pairs(search(helper, filter_require_auto_load=True)) == {AUTO_CITY_TO_STATION, AUTO_STATION_TO_CITY}


def test_without_the_filter_or_with_it_off_every_route_stays(helper, market):
    everything = {
        AUTO_CITY_TO_STATION,
        ("Auto City TDD", "Manual Outpost TDD"),
        ("Manual Outpost TDD", "Auto Station TDD"),
        ("Manual Outpost TDD", "Manual Pad TDD"),
        AUTO_STATION_TO_CITY,
        ("Auto Fuel", "Auto Station TDD"),
    }

    assert route_pairs(search(helper)) == everything
    assert route_pairs(search(helper, filter_require_auto_load=False)) == everything


def test_the_loading_dock_of_the_used_ship_still_applies_next_to_the_filter(helper, market):
    assert route_pairs(search(helper, used_ship="MISC Hull C")) == {
        ("Auto City TDD", "Manual Outpost TDD"), AUTO_STATION_TO_CITY,
    }
    assert route_pairs(search(helper, used_ship="MISC Hull C", filter_require_auto_load=True)) == {AUTO_STATION_TO_CITY}


def test_a_ship_with_a_hangar_is_not_an_auto_load_filter(helper, market):
    assert route_pairs(search(helper, used_ship="ANVL Carrack")) == route_pairs(search(helper))
    assert route_pairs(search(helper, used_ship="ANVL Carrack", filter_require_auto_load=True)) == {
        AUTO_CITY_TO_STATION, AUTO_STATION_TO_CITY,
    }


def test_auto_load_and_the_start_location_must_both_hold(helper, market):
    assert search(helper, filter_start_location="Manual Outpost", filter_require_auto_load=True) == []
    assert any("No terminal at the start Manual Outpost has auto loading." in note for note in helper.notes), helper.notes

    assert route_pairs(search(helper, filter_start_location="Auto City", filter_require_auto_load=True)) == {AUTO_CITY_TO_STATION}


def test_an_unknown_ship_returns_a_note_instead_of_crashing(helper, market):
    assert search(helper, used_ship="Not A Real Ship") == []
    assert any("Not A Real Ship" in note and "not found" in note for note in helper.notes)
