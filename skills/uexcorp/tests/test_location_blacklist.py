"""Tests for filter_location_blacklist (uex_get_trade_routes, uex_get_commodity_information).

No pytest. Run from the project root:

    python3 -m skills.uexcorp.tests.test_location_blacklist

Exits non-zero on the first failed assertion or crash; prints "ALL OK" on success.

Why this exists
---------------
More than one blacklisted location crashed with "row value misused" (column != (a, b)).
With one location, terminals with any empty location column (NULL != x is NULL in SQL)
fell out of the "not blacklisted" set, and trade routes excluded that set instead of the
blacklisted terminals, so blacklisted terminals still showed up in routes.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from skills.uexcorp.uexcorp.data_access.terminal_data_access import TerminalDataAccess
from skills.uexcorp.uexcorp.helper import Helper
from skills.uexcorp.uexcorp.tool.commodity_route import CommodityRoute
from skills.uexcorp.tests.test_commodity_route_auto_load import _FakeHelper, _parse_routes

# (terminal id, name, star system, planet, space station, city)
TERMINALS = [
    (1, "Term Lorville", "Stanton", "Hurston", None, "Lorville"),
    (2, "Term Ruin", "Pyro", "Pyro V", "Ruin Station", None),
    (3, "Term Everus", "Stanton", "Hurston", "Everus Harbor", None),
    (4, "Term Levski", "Nyx", "Delamar", None, "Levski"),
]
NAMES = {terminal[0]: terminal[1] for terminal in TERMINALS}
SYSTEMS = {terminal[0]: terminal[2] for terminal in TERMINALS}

# (route id, origin, destination, buy, sell)
LEGS = [
    (1, 1, 2, 10, 90),  # best margin, but into Pyro
    (2, 2, 4, 10, 80),  # out of Pyro
    (3, 1, 3, 10, 30),
    (4, 3, 4, 10, 40),
]


class LocationBlacklistTest(unittest.TestCase):
    def setUp(self) -> None:
        from skills.uexcorp.uexcorp.database.database import Database

        self._original_helper = Helper._instance
        self._tmp_dir = tempfile.mkdtemp(prefix="uexcorp_location_blacklist_test_")
        self._helper = _FakeHelper()
        Helper._instance = self._helper
        self._db = Database(self._tmp_dir, version="test-location-blacklist", helper=self._helper)
        self._helper.set_database(self._db)
        self._seed()
        self._tool = CommodityRoute()

    def tearDown(self) -> None:
        try:
            self._db.destroy()
        except Exception:
            pass
        Helper._instance = self._original_helper
        try:
            for name in os.listdir(self._tmp_dir):
                os.remove(os.path.join(self._tmp_dir, name))
            os.rmdir(self._tmp_dir)
        except OSError:
            pass

    def _seed(self) -> None:
        for terminal_id, name, star_system, planet, space_station, city in TERMINALS:
            self._db.execute(
                """
                INSERT INTO terminal (id, name, type, is_available, star_system_name, planet_name, space_station_name, city_name)
                VALUES (?, ?, 'commodity', 1, ?, ?, ?, ?)
                """,
                (terminal_id, name, star_system, planet, space_station, city),
            )
        self._db.execute("INSERT INTO commodity (id, name, is_illegal, is_blacklisted) VALUES (11, 'Tin', 0, 0)")
        for route_id, origin, destination, buy, sell in LEGS:
            self._db.execute(
                """
                INSERT INTO commodity_route (
                    id, id_commodity, commodity_name, id_terminal_origin, id_terminal_destination,
                    origin_terminal_name, destination_terminal_name,
                    origin_star_system_name, destination_star_system_name,
                    price_origin, price_destination, scu_origin, scu_destination, price_margin, distance
                ) VALUES (?, 11, 'Tin', ?, ?, ?, ?, ?, ?, ?, ?, 1000, NULL, ?, 10)
                """,
                (
                    route_id, origin, destination, NAMES[origin], NAMES[destination],
                    SYSTEMS[origin], SYSTEMS[destination], buy, sell, (sell - buy) / sell * 100,
                ),
            )
        self._db.commit()

    def _routes(self, **kwargs) -> list[dict]:
        payload, _instant = self._tool.execute(limit=15, available_cargo_space_scu=10, **kwargs)
        return _parse_routes(payload)

    @staticmethod
    def _terminals(route: dict) -> set[str]:
        return {stop["terminal"] for stop in route["stops"]}

    def _not_blacklisted(self, location_names: list[str]) -> set[int]:
        data_access = TerminalDataAccess()
        data_access.add_filter_by_location_name_blacklist(location_names)
        return {terminal.get_id() for terminal in data_access.load()}

    def test_terminal_filter_keeps_terminals_with_empty_location_columns(self) -> None:
        self.assertEqual(self._not_blacklisted(["Pyro"]), {1, 3, 4})

    def test_terminal_filter_accepts_several_locations(self) -> None:
        self.assertEqual(self._not_blacklisted(["Pyro", "Terminus", "Ruin Station"]), {1, 3, 4})
        self.assertEqual(self._not_blacklisted(["Lorville", "Everus Harbor"]), {2, 4})

    def test_terminal_filter_accepts_a_single_string(self) -> None:
        data_access = TerminalDataAccess()
        data_access.add_filter_by_location_name_blacklist("Nyx")
        self.assertEqual({terminal.get_id() for terminal in data_access.load()}, {1, 2, 3})

    def test_routes_without_blacklist_use_the_blacklisted_terminal(self) -> None:
        routes = self._routes(max_stops=3)
        self.assertTrue(any("Term Ruin" in self._terminals(route) for route in routes))

    def test_routes_skip_blacklisted_terminals(self) -> None:
        for blacklist in (["Pyro"], ["Pyro", "Terminus", "Ruin Station"], ["Ruin Station"]):
            for max_stops in (1, 3):
                routes = self._routes(max_stops=max_stops, filter_location_blacklist=blacklist)
                self.assertTrue(routes, (blacklist, max_stops))
                for route in routes:
                    self.assertNotIn("Term Ruin", self._terminals(route), (blacklist, max_stops))

    def test_routes_keep_terminals_that_are_not_blacklisted(self) -> None:
        routes = self._routes(max_stops=1, filter_location_blacklist=["Pyro"])
        used = set().union(*(self._terminals(route) for route in routes))
        self.assertEqual(used, {"Term Lorville", "Term Everus", "Term Levski"})

    def test_star_system_whitelist_keeps_every_stop_in_those_systems(self) -> None:
        for systems, allowed in (
            (["Stanton"], {"Term Lorville", "Term Everus"}),
            (["Stanton", "Nyx"], {"Term Lorville", "Term Everus", "Term Levski"}),
        ):
            routes = self._routes(max_stops=3, filter_star_system_whitelist=systems)
            self.assertTrue(routes, systems)
            used = set().union(*(self._terminals(route) | set(route.get("last_sale_also_at", [])) for route in routes))
            self.assertEqual(used, allowed, systems)


def main() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LocationBlacklistTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
