"""Deriving the trade legs (commodity_route) from the imported prices, terminals and distances.

The skill no longer fetches trade routes from UEX: after each price import it builds every
profitable "buy here, sell there" leg itself, and replaces the table in one transaction."""

import pytest

from skills.uexcorp.uexcorp.api.uex import Uex
from tests.skills.uexcorp.support import DataApi

STANTON = 68
ORBIT_HURSTON, ORBIT_ARCCORP, ORBIT_CRUSADER = 1, 2, 3

TERMINALS = [
    # Station terminal without own loading dock: the station has one (facility counts via parent)
    {"id": 1, "name": "TDD Station", "code": "TDDS", "type": "commodity", "is_available": 1,
     "id_star_system": STANTON, "id_orbit": ORBIT_HURSTON, "id_space_station": 7,
     "star_system_name": "Stanton", "orbit_name": "Hurston", "planet_name": "Hurston", "has_loading_dock": 0},
    {"id": 2, "name": "Area18 TDD", "code": "A18", "type": "commodity", "is_available": 1,
     "id_star_system": STANTON, "id_orbit": ORBIT_ARCCORP, "id_city": 9,
     "star_system_name": "Stanton", "orbit_name": "ArcCorp", "planet_name": "ArcCorp", "has_loading_dock": 1},
    # Same orbit as terminal 1
    {"id": 3, "name": "Hurston Outpost", "code": "HOUT", "type": "commodity", "is_available": 1,
     "id_star_system": STANTON, "id_orbit": ORBIT_HURSTON, "star_system_name": "Stanton", "orbit_name": "Hurston"},
    # Orbit without any stored distance
    {"id": 4, "name": "Crusader Spot", "code": "CRU", "type": "commodity", "is_available": 1,
     "id_star_system": STANTON, "id_orbit": ORBIT_CRUSADER, "star_system_name": "Stanton", "orbit_name": "Crusader"},
]
SPACE_STATIONS = [{"id": 7, "name": "Everus", "is_monitored": 1, "has_refuel": 1, "has_loading_dock": 1}]
CITIES = [{"id": 9, "name": "Area18", "is_monitored": 0, "has_refuel": 0}]
STAR_SYSTEMS = [{"id": STANTON, "name": "Stanton", "is_available": 1}]
# Only stored one way round: the lookup has to try both directions
ORBIT_DISTANCES = [{"id": 1, "id_star_system_origin": STANTON, "id_star_system_destination": STANTON,
                    "id_orbit_origin": ORBIT_ARCCORP, "id_orbit_destination": ORBIT_HURSTON, "distance": 42.0}]
COMMODITIES = [{"id": 5, "name": "Laranite", "code": "LARA"}]
PRICES = [
    {"id": 1, "id_commodity": 5, "id_terminal": 1, "price_buy": 100, "price_sell": 0, "scu_buy": 300,
     "status_buy": 4, "container_sizes": "8,16,32"},
    {"id": 2, "id_commodity": 5, "id_terminal": 2, "price_buy": 0, "price_sell": 150, "scu_sell": 0,
     "status_sell": 2, "container_sizes": "1,2,4,8"},
    {"id": 3, "id_commodity": 5, "id_terminal": 3, "price_buy": 0, "price_sell": 120, "scu_sell": 40},
    {"id": 4, "id_commodity": 5, "id_terminal": 4, "price_buy": 0, "price_sell": 130},
    # Nothing to buy or sell: never a leg
    {"id": 5, "id_commodity": 5, "id_terminal": 2, "price_buy": 0, "price_sell": 0},
]


def api_with(prices=PRICES) -> DataApi:
    return DataApi({
        Uex.TERMINALS: TERMINALS, Uex.SPACE_STATIONS: SPACE_STATIONS, Uex.CITIES: CITIES,
        Uex.STAR_SYSTEMS: STAR_SYSTEMS, Uex.ORBITS_DISTANCES: ORBIT_DISTANCES,
        Uex.COMMODITIES: COMMODITIES, Uex.COMMODITIES_PRICES: prices,
    })


@pytest.fixture
def legs(import_env):
    """The derived legs by (origin, destination) terminal."""
    def read() -> dict[tuple[int, int], dict]:
        rows = import_env.db.execute_fetchall("SELECT * FROM commodity_route")
        return {(row["id_terminal_origin"], row["id_terminal_destination"]): dict(row) for row in rows}
    return read


def test_every_profitable_buy_sell_pair_becomes_a_leg_with_the_fields_the_tools_need(import_env, legs):
    import_env.run_import(api_with())

    assert set(legs()) == {(1, 2), (1, 3), (1, 4)}
    leg = legs()[(1, 2)]
    assert (leg["price_origin"], leg["price_destination"]) == (100, 150)
    assert leg["scu_origin"] == 300
    assert leg["scu_destination"] is None  # scu_sell 0 = demand not reported
    assert (leg["status_origin"], leg["status_destination"]) == (4, 2)
    assert (leg["container_size_min_origin"], leg["container_size_min_destination"]) == (8, 1)
    assert leg["code"] == "LARA-TDDS-A18"
    assert (leg["commodity_name"], leg["origin_terminal_name"]) == ("Laranite", "TDD Station")
    assert leg["profit"] == 50 * 300
    assert legs()[(1, 3)]["scu_destination"] == 40


def test_facilities_count_from_the_terminal_or_its_parent_location(import_env, legs):
    import_env.run_import(api_with())

    leg = legs()[(1, 2)]
    assert leg["has_loading_dock_origin"] == 1  # from the space station
    assert leg["has_loading_dock_destination"] == 1  # from the terminal itself
    assert (leg["is_monitored_origin"], leg["is_monitored_destination"]) == (1, 0)
    assert leg["is_space_station_origin"] == 1
    assert leg["is_on_ground_destination"] == 1


def test_distances_are_found_in_both_directions_in_one_orbit_and_unknown(import_env, legs):
    import_env.run_import(api_with())

    assert legs()[(1, 2)]["distance"] == 42.0  # stored as ArcCorp -> Hurston only
    assert legs()[(1, 3)]["distance"] == 0
    assert legs()[(1, 4)]["distance"] is None


def test_a_price_refresh_replaces_all_legs(import_env, legs):
    import_env.run_import(api_with())
    assert len(legs()) == 3
    cheaper_elsewhere = [dict(p) for p in PRICES]
    cheaper_elsewhere[2]["price_sell"] = 90  # Hurston Outpost now below the buy price
    import_env.expire(Uex.BUNDLE_SHORT)

    import_env.run_import(api_with(cheaper_elsewhere))

    assert set(legs()) == {(1, 2), (1, 4)}


def test_a_terminal_that_is_not_available_in_the_game_is_no_stop(import_env, legs):
    closed = {"id": 5, "name": "Closed Depot", "code": "CLOS", "type": "commodity", "is_available": 0,
              "id_star_system": STANTON, "id_orbit": ORBIT_HURSTON, "star_system_name": "Stanton"}
    api = api_with(PRICES + [{"id": 6, "id_commodity": 5, "id_terminal": 5, "price_buy": 0, "price_sell": 200}])
    api.data[Uex.TERMINALS] = TERMINALS + [closed]

    import_env.run_import(api)

    assert set(legs()) == {(1, 2), (1, 3), (1, 4)}  # nothing to Closed Depot, although it pays 200


def test_legs_wait_for_all_their_source_tables(import_env, legs):
    # Without orbit distances the legs would have no distances: not derived (and not marked)
    api = api_with()
    api.missing = {Uex.ORBITS_DISTANCES}

    import_env.run_import(api)

    assert legs() == {}
    assert "commodity_route" not in import_env.imports()
    retry = api_with()
    import_env.run_import(retry)
    assert legs()[(1, 2)]["distance"] == 42.0
    assert retry.fetched == [Uex.BUNDLE_LONG]  # only the incomplete bundle again, the prices were fine
