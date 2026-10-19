"""Focused tests for the "Use Estimated Availability" switch of uex_get_trade_routes.

No pytest. Run from the project root:

    python3 -m skills.uexcorp.tests.test_commodity_route_estimated_availability

Exits non-zero on the first failed assertion or crash; prints "ALL OK" on success.

Why this exists
---------------
With the switch on, the traded volume is capped by the estimated stock at the
origin (scu_origin) and the demand at the destination (scu_destination). With it
off, only cargo space and budget limit the volume. The SQL MIN() must never get a
single argument, as SQLite then treats it as the aggregate function.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from skills.uexcorp.uexcorp.helper import Helper
from skills.uexcorp.uexcorp.tool.commodity_route import CommodityRoute
from skills.uexcorp.tests.test_commodity_route_auto_load import _FakeHelper, _buy_volume, _parse_routes, _volume_note


class CommodityRouteEstimatedAvailabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        from skills.uexcorp.uexcorp.database.database import Database

        self._original_helper = Helper._instance
        self._tmp_dir = tempfile.mkdtemp(prefix="uexcorp_availability_test_")
        self._helper = _FakeHelper()
        Helper._instance = self._helper
        self._db = Database(self._tmp_dir, version="test-availability", helper=self._helper)
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
        # 10 SCU in stock at origin, 5 SCU demand at destination, 10 aUEC profit per SCU
        self._db.execute(
            """
            INSERT INTO commodity_route (
                id, id_terminal_origin, id_terminal_destination,
                commodity_name, origin_terminal_name, destination_terminal_name,
                origin_star_system_name, origin_planet_name,
                destination_star_system_name, destination_planet_name,
                price_origin, price_destination, scu_origin, scu_destination,
                profit, score, distance
            ) VALUES (1, 10, 11, 'Laranite', 'Origin TDD', 'Destination TDD',
                      'Stanton', 'Hurston', 'Stanton', 'Hurston',
                      10, 20, 10, 5, 50, 50, 1)
            """
        )
        self._db.execute(
            "INSERT INTO vehicle (id, name_full, is_loading_dock, scu) VALUES (1, 'Drake Cutlass Black', 0, 46)"
        )
        self._db.commit()

    def _route(self, use_estimated_availability: bool, **kwargs) -> dict:
        self._helper.get_handler_config().use_estimated_availability = use_estimated_availability
        payload, _instant = self._tool.execute(limit=15, **kwargs)
        routes = _parse_routes(payload)
        self.assertEqual(len(routes), 1)
        return routes[0]

    def test_on_caps_volume_by_stock_and_demand(self) -> None:
        route = self._route(True, used_ship="Drake Cutlass Black")
        self.assertEqual(_buy_volume(route), 5)
        self.assertEqual(route["estimated_profit"], 50)

    def test_off_uses_full_cargo_space(self) -> None:
        route = self._route(False, used_ship="Drake Cutlass Black")
        self.assertEqual(_buy_volume(route), 46)
        self.assertEqual(route["estimated_profit"], 460)

    def test_off_with_budget_only_uses_single_limit(self) -> None:
        # Only one limit left: must not become SQLite's aggregate MIN()
        route = self._route(False, available_money=300)
        self.assertEqual(_buy_volume(route), 30)
        self.assertEqual(route["estimated_profit"], 300)

    def _set_stock_and_demand(self, stock_origin: int, demand_destination: int) -> None:
        self._db.execute(
            "UPDATE commodity_route SET scu_origin = ?, scu_destination = ? WHERE id = 1",
            (stock_origin, demand_destination),
        )
        self._db.commit()

    def test_note_names_sell_location_when_demand_caps(self) -> None:
        route = self._route(True, used_ship="Drake Cutlass Black")
        self.assertEqual(
            _volume_note(route),
            "SCU count limited to 5 (instead of 46) by estimated availability at sell location.",
        )

    def test_note_names_buy_location_when_stock_caps(self) -> None:
        self._set_stock_and_demand(3, 20)
        route = self._route(True, used_ship="Drake Cutlass Black")
        self.assertEqual(_buy_volume(route), 3)
        self.assertIn("limited to 3 (instead of 46)", _volume_note(route))
        self.assertIn("at buy location.", _volume_note(route))

    def test_note_names_both_locations_when_equal(self) -> None:
        self._set_stock_and_demand(7, 7)
        route = self._route(True, available_money=1000)
        self.assertIn("limited to 7 (instead of 100)", _volume_note(route))
        self.assertIn("at sell and buy location.", _volume_note(route))

    def test_no_note_when_budget_or_space_is_the_limit(self) -> None:
        route = self._route(True, available_cargo_space_scu=4)
        self.assertEqual(_buy_volume(route), 4)
        self.assertIsNone(_volume_note(route))

    def test_no_note_when_switch_is_off(self) -> None:
        route = self._route(False, used_ship="Drake Cutlass Black")
        self.assertIsNone(_volume_note(route))

    def test_off_and_on_respect_budget_and_space_together(self) -> None:
        self.assertEqual(_buy_volume(self._route(False, used_ship="Drake Cutlass Black", available_money=200)), 20)
        self.assertEqual(_buy_volume(self._route(True, used_ship="Drake Cutlass Black", available_money=200)), 5)


def main() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CommodityRouteEstimatedAvailabilityTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
