"""Focused tests for routes without stock or demand in uex_get_trade_routes.

No pytest. Run from the project root:

    python3 -m skills.uexcorp.tests.test_commodity_route_no_availability

Exits non-zero on the first failed assertion or crash; prints "ALL OK" on success.

Why this exists
---------------
With "Use Estimated Availability" on, a route with zero stock at the origin or
zero demand at the destination is no real option and must not be returned as a
route. If it would otherwise rank among the shown routes, it is mentioned as a
note instead ("Normally X would be a good option, but ..."). Unknown stock or
demand (NULL) counts as available and must neither hide nor cap a route.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from skills.uexcorp.uexcorp.helper import Helper
from skills.uexcorp.uexcorp.tool.commodity_route import CommodityRoute
from skills.uexcorp.tests.test_commodity_route_auto_load import (
    _FakeHelper,
    _buy_volume,
    _first_buys,
    _parse_routes,
    _route_pairs,
)

# (route id, commodity, origin, destination, price origin, price destination, stock origin, demand destination)
ROUTES = [
    (1, "Gold", "Empty Origin", "Gold Buyer", 100, 200, 0, 500),  # best, but no stock
    (2, "Iron", "Iron Mine", "Iron Buyer", 10, 20, 500, 500),  # 10/SCU
    (3, "Tin", "Tin Mine", "Full Buyer", 10, 15, 500, 0),  # 5/SCU, but no demand
    (4, "Ice", "Ice Field", "Ice Buyer", 10, 11, None, None),  # 1/SCU, unknown availability
]


class CommodityRouteNoAvailabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        from skills.uexcorp.uexcorp.database.database import Database

        self._original_helper = Helper._instance
        self._tmp_dir = tempfile.mkdtemp(prefix="uexcorp_no_availability_test_")
        self._helper = _FakeHelper()
        Helper._instance = self._helper
        self._db = Database(self._tmp_dir, version="test-no-availability", helper=self._helper)
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
        for route_id, commodity, origin, destination, price_origin, price_destination, stock, demand in ROUTES:
            for terminal_id, name in ((route_id * 10, origin), (route_id * 10 + 1, destination)):
                self._db.execute(
                    "INSERT INTO terminal (id, name, type, is_available) VALUES (?, ?, 'commodity', 1)",
                    (terminal_id, name),
                )
            self._db.execute(
                """
                INSERT INTO commodity_route (
                    id, id_terminal_origin, id_terminal_destination,
                    commodity_name, origin_terminal_name, destination_terminal_name,
                    origin_star_system_name, origin_planet_name,
                    destination_star_system_name, destination_planet_name,
                    price_origin, price_destination, scu_origin, scu_destination,
                    price_margin, score, distance
                ) VALUES (?, ?, ?, ?, ?, ?, 'Stanton', 'Hurston', 'Stanton', 'Hurston', ?, ?, ?, ?, ?, 50, 1)
                """,
                (
                    route_id, route_id * 10, route_id * 10 + 1, commodity, origin, destination,
                    price_origin, price_destination, stock, demand,
                    (price_destination - price_origin) / price_destination * 100,
                ),
            )
        self._db.execute(
            "INSERT INTO vehicle (id, name_full, is_loading_dock, scu) VALUES (1, 'Drake Cutlass Black', 0, 46)"
        )
        self._db.commit()

    def _execute(self, use_estimated_availability: bool = True, **kwargs) -> tuple[list[dict], list[str]]:
        self._helper.get_handler_config().use_estimated_availability = use_estimated_availability
        self._helper.get_handler_tool().notes.clear()
        payload, _instant = self._tool.execute(used_ship="Drake Cutlass Black", **kwargs)
        notes = [note for note in self._helper.get_handler_tool().notes if note.startswith("Normally")]
        return _parse_routes(payload), notes

    def test_routes_without_stock_or_demand_are_no_options(self) -> None:
        routes, notes = self._execute(limit=4)
        self.assertEqual(
            _route_pairs(routes),
            {("Iron Mine", "Iron Buyer"), ("Ice Field", "Ice Buyer")},
        )
        # Fewer real routes than requested: every good no-availability route is mentioned
        self.assertEqual(len(notes), 2)
        self.assertIn(
            "Normally Gold from Empty Origin to Gold Buyer would be a good option "
            "(about 4600 aUEC profit for 46 SCU), but UEX data shows no stock left to buy at Empty Origin.",
            notes,
        )
        self.assertTrue(any("no demand left at Full Buyer" in note for note in notes))

    def test_notes_respect_start_and_destination(self) -> None:
        # Gold (no stock at Empty Origin) would be the best route, but the user starts at Iron Mine
        routes, notes = self._execute(limit=4, filter_start_location="Iron Mine")
        self.assertEqual(_route_pairs(routes), {("Iron Mine", "Iron Buyer")})
        self.assertEqual(notes, [])

        routes, notes = self._execute(limit=4, filter_destination_location="Gold Buyer")
        self.assertEqual(routes, [])
        self.assertEqual(len(notes), 1)
        self.assertIn("Gold", notes[0])

    def test_unknown_availability_neither_hides_nor_caps(self) -> None:
        routes, _notes = self._execute(limit=4)
        ice = next(route for route in routes if _first_buys(route)[0]["commodity"] == "Ice")
        self.assertEqual(_buy_volume(ice), 46)
        self.assertEqual(ice["estimated_profit"], 46)

    def test_only_routes_that_would_rank_are_mentioned(self) -> None:
        # Shown: Iron (460). Gold (4600) would have beaten it, Tin (230) would not.
        routes, notes = self._execute(limit=1)
        self.assertEqual(_route_pairs(routes), {("Iron Mine", "Iron Buyer")})
        self.assertEqual(len(notes), 1)
        self.assertIn("Gold", notes[0])

    def test_switch_off_keeps_routes_and_adds_no_notes(self) -> None:
        routes, notes = self._execute(use_estimated_availability=False, limit=1)
        self.assertEqual(_route_pairs(routes), {("Empty Origin", "Gold Buyer")})
        self.assertEqual(notes, [])

    def test_no_notes_on_later_pages(self) -> None:
        _routes, notes = self._execute(limit=1, offset=1)
        self.assertEqual(notes, [])

    def test_only_no_availability_routes_left(self) -> None:
        self._db.execute("UPDATE commodity_route SET scu_origin = 0 WHERE id IN (2, 4)")
        self._db.commit()
        routes, notes = self._execute(limit=2)
        self.assertEqual(routes, [])
        self.assertEqual(len(notes), 3)


def main() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CommodityRouteNoAvailabilityTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
