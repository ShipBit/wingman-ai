"""Tests for deriving trade legs (commodity_route) from imported prices, terminals and distances.

No pytest. Run from the project root:

    python3 -m skills.uexcorp.tests.test_route_derivation

Exits non-zero on the first failed assertion or crash; prints "ALL OK" on success.

Why this exists
---------------
The skill no longer fetches trade routes from UEX: after each price import it builds
every profitable "buy here, sell there" leg itself. The rebuild must reproduce the
fields UEX used to deliver and replace the table in one transaction, so a route tool
call never sees an empty or half-filled table.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from skills.uexcorp.uexcorp.api.uex import Uex
from skills.uexcorp.uexcorp.helper import Helper
from skills.uexcorp.tests.test_uex_api_failures import _DataApi, _Helper

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
    # Selling below the buy price: never a leg
    {"id": 5, "id_commodity": 5, "id_terminal": 2, "price_buy": 0, "price_sell": 0},
]


def _api(prices=PRICES) -> _DataApi:
    return _DataApi({
        Uex.TERMINALS: TERMINALS, Uex.SPACE_STATIONS: SPACE_STATIONS, Uex.CITIES: CITIES,
        Uex.STAR_SYSTEMS: STAR_SYSTEMS, Uex.ORBITS_DISTANCES: ORBIT_DISTANCES,
        Uex.COMMODITIES: COMMODITIES, Uex.COMMODITIES_PRICES: prices,
    })


class RouteDerivationTest(unittest.TestCase):
    def setUp(self) -> None:
        from skills.uexcorp.uexcorp.database.database import Database
        from skills.uexcorp.uexcorp.handler.import_handler import ImportHandler

        self._original_helper = Helper._instance
        self._tmp_dir = tempfile.mkdtemp(prefix="uexcorp_route_derivation_test_")
        self._helper = _Helper()
        Helper._instance = self._helper
        self._helper.db = Database(self._tmp_dir, version="test-route-derivation", helper=self._helper)
        self._importer = ImportHandler(self._helper)
        self._helper.importer = self._importer

    def tearDown(self) -> None:
        try:
            self._helper.db.destroy()
        except Exception:
            pass
        Helper._instance = self._original_helper
        try:
            for name in os.listdir(self._tmp_dir):
                os.remove(os.path.join(self._tmp_dir, name))
            os.rmdir(self._tmp_dir)
        except OSError:
            pass

    def _import(self, api: _DataApi) -> None:
        self._importer._ImportHandler__api = api
        self._importer.import_data(force=True)

    def _legs(self) -> dict[tuple[int, int], dict]:
        rows = self._helper.db.execute_fetchall("SELECT * FROM commodity_route")
        return {(row["id_terminal_origin"], row["id_terminal_destination"]): dict(row) for row in rows}

    def test_legs_are_derived_without_a_routes_request(self) -> None:
        api = _api()
        self._import(api)
        self.assertEqual(api.fetched, [Uex.VERSION, Uex.BUNDLE_LONG, Uex.BUNDLE_SHORT])
        self.assertEqual(set(self._legs()), {(1, 2), (1, 3), (1, 4)})

    def test_leg_fields(self) -> None:
        self._import(_api())
        leg = self._legs()[(1, 2)]
        self.assertEqual((leg["price_origin"], leg["price_destination"]), (100, 150))
        self.assertEqual(leg["scu_origin"], 300)
        self.assertIsNone(leg["scu_destination"])  # scu_sell 0 = demand not reported
        self.assertEqual((leg["status_origin"], leg["status_destination"]), (4, 2))
        self.assertEqual((leg["container_size_min_origin"], leg["container_size_min_destination"]), (8, 1))
        self.assertEqual(leg["code"], "LARA-TDDS-A18")
        self.assertEqual(leg["commodity_name"], "Laranite")
        self.assertEqual(leg["origin_terminal_name"], "TDD Station")
        self.assertAlmostEqual(leg["price_roi"], 50.0)
        self.assertEqual(leg["profit"], 50 * 300)
        self.assertEqual(self._legs()[(1, 3)]["scu_destination"], 40)

    def test_facilities_count_from_terminal_or_parent_location(self) -> None:
        self._import(_api())
        leg = self._legs()[(1, 2)]
        self.assertEqual(leg["has_loading_dock_origin"], 1)  # from the space station
        self.assertEqual(leg["has_loading_dock_destination"], 1)  # from the terminal itself
        self.assertEqual((leg["is_monitored_origin"], leg["is_monitored_destination"]), (1, 0))
        self.assertEqual(leg["is_space_station_origin"], 1)
        self.assertEqual(leg["is_on_ground_destination"], 1)

    def test_distance_both_directions_same_orbit_and_unknown(self) -> None:
        self._import(_api())
        legs = self._legs()
        self.assertEqual(legs[(1, 2)]["distance"], 42.0)  # stored as ArcCorp -> Hurston only
        self.assertEqual(legs[(1, 3)]["distance"], 0)
        self.assertIsNone(legs[(1, 4)]["distance"])

    def test_price_refresh_replaces_all_legs(self) -> None:
        self._import(_api())
        self.assertEqual(len(self._legs()), 3)
        cheaper_elsewhere = [dict(p) for p in PRICES]
        cheaper_elsewhere[2]["price_sell"] = 90  # Hurston Outpost now below the buy price
        # The relay has new prices: the short bundle is due again
        self._helper.db.execute("UPDATE imports SET date_expires = 0 WHERE `table` = 'relay_short'")
        self._helper.db.commit()
        self._import(_api(cheaper_elsewhere))
        self.assertEqual(set(self._legs()), {(1, 2), (1, 4)})

    def test_unavailable_terminals_are_no_stops(self) -> None:
        # A terminal not available in the game (is_available 0) paying 200: never a route stop
        closed = {"id": 5, "name": "Closed Depot", "code": "CLOS", "type": "commodity", "is_available": 0,
                  "id_star_system": STANTON, "id_orbit": ORBIT_HURSTON, "star_system_name": "Stanton"}
        api = _api(PRICES + [{"id": 6, "id_commodity": 5, "id_terminal": 5, "price_buy": 0, "price_sell": 200}])
        api.data[Uex.TERMINALS] = TERMINALS + [closed]
        self._import(api)
        self.assertNotIn((1, 5), self._legs())
        self.assertEqual(set(self._legs()), {(1, 2), (1, 3), (1, 4)})

    def test_routes_wait_for_all_source_tables(self) -> None:
        # Without orbit distances the legs would have no distances: not derived (and not marked)
        api = _api()
        api.missing = {Uex.ORBITS_DISTANCES}
        self._import(api)
        self.assertEqual(self._legs(), {})
        imported = {r["table"] for r in self._helper.db.execute_fetchall("SELECT `table` FROM imports")}
        self.assertNotIn("orbit_distance", imported)
        self.assertNotIn("commodity_route", imported)

        retry = _api()
        self._import(retry)
        self.assertEqual(self._legs()[(1, 2)]["distance"], 42.0)
        # Only the incomplete bundle is fetched again, the prices were fine
        self.assertEqual(retry.fetched, [Uex.BUNDLE_LONG])

    def test_replace_table_rolls_back_on_error(self) -> None:
        self._import(_api())
        before = self._legs()
        with self.assertRaises(Exception):
            self._helper.db.replace_table("commodity_route", ["id", "no_such_column"], [(1, 2)])
        self.assertEqual(self._legs(), before)


def main() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RouteDerivationTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
