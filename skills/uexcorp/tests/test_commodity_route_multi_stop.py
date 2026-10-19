"""Focused tests for multi-stop and circular routes of uex_get_trade_routes.

No pytest. Run from the project root:

    python3 -m skills.uexcorp.tests.test_commodity_route_multi_stop

Exits non-zero on the first failed assertion or crash; prints "ALL OK" on success.

Why this exists
---------------
The tool plans routes itself from the derived trade legs (commodity_route rows):
max_stops allows several stops with buying and selling at each, return_to_start
asks for circular routes, and the start location limits where a route begins -
not every hop of it. Planner details are covered in test_route_planner.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from skills.uexcorp.uexcorp.helper import Helper
from skills.uexcorp.uexcorp.tool.commodity_route import CommodityRoute
from skills.uexcorp.tests.test_commodity_route_auto_load import _FakeHelper, _parse_routes

TERMINALS = {1: "Term A", 2: "Term B", 3: "Term C", 4: "Term D"}

# (commodity id, name, origin, destination, buy, sell, stock at origin)
# Cargo is 10 SCU. Best by total profit: A -> B -> C -> D = 350
# (Gold 5 carried A -> C = 150, Xenon 5 A -> B = 50, Yttrium 5 B -> C = 50, Iron 10 C -> D = 100).
# Best per stop: A -> C with Gold only = 150 for 1 stop.
LEGS = [
    (11, "Xenon", 1, 2, 10, 20, 1000),  # A -> B 10/SCU
    (12, "Yttrium", 2, 3, 10, 20, 1000),  # B -> C 10/SCU
    (13, "Zinc", 3, 1, 10, 20, 1000),  # C -> A 10/SCU (for circular routes)
    (14, "Gold", 1, 3, 10, 40, 5),  # A -> C 30/SCU, only 5 SCU, worth carrying past B
    (15, "Iron", 3, 4, 10, 20, 1000),  # C -> D 10/SCU
]


class CommodityRouteMultiStopTest(unittest.TestCase):
    def setUp(self) -> None:
        from skills.uexcorp.uexcorp.database.database import Database

        self._original_helper = Helper._instance
        self._tmp_dir = tempfile.mkdtemp(prefix="uexcorp_multi_stop_test_")
        self._helper = _FakeHelper()
        Helper._instance = self._helper
        self._db = Database(self._tmp_dir, version="test-multi-stop", helper=self._helper)
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
        for terminal_id, name in TERMINALS.items():
            self._db.execute(
                "INSERT INTO terminal (id, name, type, is_available, star_system_name) VALUES (?, ?, 'commodity', 1, 'Stanton')",
                (terminal_id, name),
            )
        for index, (commodity_id, commodity, origin, destination, buy, sell, stock) in enumerate(LEGS):
            self._db.execute(
                """
                INSERT INTO commodity_route (
                    id, id_commodity, commodity_name, id_terminal_origin, id_terminal_destination,
                    origin_terminal_name, destination_terminal_name,
                    origin_star_system_name, destination_star_system_name, origin_planet_name, destination_planet_name,
                    price_origin, price_destination, scu_origin, price_margin, distance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Stanton', 'Stanton', 'Hurston', 'Hurston', ?, ?, ?, ?, 10)
                """,
                (
                    index + 1, commodity_id, commodity, origin, destination, TERMINALS[origin], TERMINALS[destination],
                    buy, sell, stock, (sell - buy) / sell * 100,
                ),
            )
        self._db.commit()

    def _execute(self, ranking: str = "total_profit", **kwargs) -> tuple[list[dict], list[str]]:
        self._helper.get_handler_config().ranking = ranking
        self._helper.get_handler_tool().notes.clear()
        payload, _instant = self._tool.execute(limit=15, available_cargo_space_scu=10, **kwargs)
        return _parse_routes(payload), list(self._helper.get_handler_tool().notes)

    @staticmethod
    def _stops(route: dict) -> list[str]:
        return [stop["terminal"] for stop in route["stops"]]

    def test_single_hop_is_the_default(self) -> None:
        routes, _notes = self._execute()
        self.assertTrue(routes)
        self.assertTrue(all(len(route["stops"]) == 2 for route in routes))

    def test_multi_stop_route_buys_and_sells_along_the_way(self) -> None:
        routes, _notes = self._execute(max_stops=3)
        route = next(route for route in routes if route.get("stop_count") == 3)
        self.assertEqual(len(route["stops"]), 4)
        self.assertIn("buy", route["stops"][0])
        self.assertIn("sell", route["stops"][-1])
        self.assertEqual(route["estimated_profit"], sum(
            sale["scu"] * sale["price_per_scu"] for stop in route["stops"] for sale in stop.get("sell", [])
        ) - sum(buy["scu"] * buy["price_per_scu"] for stop in route["stops"] for buy in stop.get("buy", [])))

    def test_total_profit_ranking_orders_by_profit(self) -> None:
        routes, _notes = self._execute(max_stops=3)
        profits = [route["estimated_profit"] for route in routes]
        self.assertEqual(profits, sorted(profits, reverse=True))
        self.assertEqual(self._stops(routes[0]), ["Term A", "Term B", "Term C", "Term D"])
        self.assertEqual(routes[0]["estimated_profit"], 350)

    def test_cargo_carried_past_a_stop_says_where_it_is_sold(self) -> None:
        routes, _notes = self._execute(max_stops=2, filter_start_location="Term A", filter_destination_location="Term C")
        route = next(route for route in routes if self._stops(route) == ["Term A", "Term B", "Term C"])
        gold = next(buy for buy in route["stops"][0]["buy"] if buy["commodity"] == "Gold")
        self.assertEqual(gold["sell_at"], "Term C")
        self.assertEqual(route["stops"][2]["sell"][0]["commodity"], "Gold")

    def test_circular_routes_return_to_start(self) -> None:
        routes, _notes = self._execute(max_stops=3, return_to_start=True)
        self.assertTrue(routes)
        for route in routes:
            stops = self._stops(route)
            self.assertEqual(stops[0], stops[-1])
            self.assertTrue(route["circular"])

    def test_start_location_limits_the_first_stop_only(self) -> None:
        routes, _notes = self._execute(max_stops=3, filter_start_location="Term B")
        self.assertTrue(routes)
        self.assertTrue(all(self._stops(route)[0] == "Term B" for route in routes))
        self.assertTrue(any(len(route["stops"]) > 2 for route in routes))

    def test_note_when_fewer_stops_rank_better(self) -> None:
        # Per stop, A -> C with Gold (150 for 1 stop) beats every longer route
        routes, notes = self._execute(ranking="profit_per_stop", max_stops=3)
        self.assertEqual(self._stops(routes[0]), ["Term A", "Term C"])
        self.assertTrue(any("fewer than 3 stops" in note for note in notes), notes)

        # By total profit the 3-stop route wins, nothing to explain
        routes, notes = self._execute(ranking="total_profit", max_stops=3)
        self.assertEqual(routes[0]["stop_count"], 3)
        self.assertFalse(any("fewer than" in note for note in notes), notes)

    def test_unknown_start_location_returns_note(self) -> None:
        routes, notes = self._execute(filter_start_location="Nowhere")
        self.assertEqual(routes, [])
        self.assertTrue(any("Nowhere" in note for note in notes), notes)


def main() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CommodityRouteMultiStopTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
