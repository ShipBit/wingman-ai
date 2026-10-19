"""Focused tests for the used_ship container size filter of uex_get_trade_routes.

No pytest. Run from the project root:

    python3 -m skills.uexcorp.tests.test_commodity_route_container_size

Exits non-zero on the first failed assertion or crash; prints "ALL OK" on success.

Why this exists
---------------
UEX lists per route which container sizes each terminal handles (csv, e.g.
"8,16,24,32"). A ship whose largest container is 4 SCU can't trade at a terminal
whose smallest container is 8 SCU, so those routes must be dropped when a
used_ship is given. CommodityRoute.set_data derives container_size_min_origin /
_destination at import; unknown sizes (NULL) must never hide a route.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from skills.uexcorp.uexcorp.helper import Helper
from skills.uexcorp.uexcorp.model.commodity_route import CommodityRoute as CommodityRouteModel
from skills.uexcorp.uexcorp.model.vehicle import Vehicle
from skills.uexcorp.uexcorp.tool.commodity_route import CommodityRoute
from skills.uexcorp.tests.test_commodity_route_auto_load import (
    _FakeHelper,
    _first_buys,
    _parse_routes,
    _route_pairs,
)

# (route id, origin name, destination name, smallest container origin, smallest container destination)
ROUTES = [
    (201, "Small Origin", "Small Destination", 1, 1),
    (202, "Large Origin", "Small Destination", 8, 1),
    (203, "Small Origin", "Large Destination", 1, 8),
    (204, "Unknown Origin", "Unknown Destination", None, None),
    (205, "Medium Origin", "Medium Destination", 4, 4),
]


class CommodityRouteContainerSizeFilterTest(unittest.TestCase):
    def setUp(self) -> None:
        from skills.uexcorp.uexcorp.database.database import Database

        self._original_helper = Helper._instance
        self._tmp_dir = tempfile.mkdtemp(prefix="uexcorp_container_size_test_")
        self._helper = _FakeHelper()
        Helper._instance = self._helper
        self._db = Database(self._tmp_dir, version="test-container-size", helper=self._helper)
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
        for route_id, origin, destination, min_origin, min_destination in ROUTES:
            self._db.execute(
                """
                INSERT INTO commodity_route (
                    id, id_terminal_origin, id_terminal_destination,
                    commodity_name, origin_terminal_name, destination_terminal_name,
                    origin_star_system_name, origin_planet_name,
                    destination_star_system_name, destination_planet_name,
                    price_origin, price_destination, scu_origin, scu_destination,
                    profit, score, distance,
                    container_size_min_origin, container_size_min_destination
                ) VALUES (?, ?, ?, 'Laranite', ?, ?, 'Stanton', 'Hurston', 'Stanton', 'Hurston',
                          10, 20, 8, 8, 80, 50, 1, ?, ?)
                """,
                (route_id, route_id * 10, route_id * 10 + 1, origin, destination, min_origin, min_destination),
            )
        self._db.execute(
            """
            INSERT INTO vehicle (id, name_full, is_loading_dock, scu, container_sizes)
            VALUES
                (1, 'Aegis Avenger Titan', 0, 8, '1,2,4'),
                (2, 'Crusader C2 Hercules Starlifter', 0, 696, '1,2,4,8,16,24,32'),
                (3, 'MISC Hull D', 0, 6912, ''),
                (4, 'Origin 600i Executive Edition', 0, 40, NULL),
                (5, 'Anvil Hornet', 0, NULL, NULL)
            """
        )
        self._db.commit()

    def _execute(self, **kwargs) -> list[dict]:
        payload, _instant = self._tool.execute(limit=15, **kwargs)
        return _parse_routes(payload)

    def test_set_data_derives_smallest_container_sizes(self) -> None:
        route = CommodityRouteModel(1)
        route.set_data({"container_sizes_origin": "16,8,32", "container_sizes_destination": "1,2,4,8,16"})
        self.assertEqual(route.get_container_size_min_origin(), 8)
        self.assertEqual(route.get_container_size_min_destination(), 1)

        route = CommodityRouteModel(2)
        route.set_data({"container_sizes_origin": "", "container_sizes_destination": None})
        self.assertIsNone(route.get_container_size_min_origin())
        self.assertIsNone(route.get_container_size_min_destination())

    def test_vehicle_max_container_size(self) -> None:
        self.assertEqual(Vehicle(1, load=True).get_max_container_size(), 4)
        self.assertEqual(Vehicle(2, load=True).get_max_container_size(), 32)
        self.assertIsNone(Vehicle(3, load=True).get_max_container_size())
        self.assertIsNone(Vehicle(4, load=True).get_max_container_size())

    def test_small_ship_drops_routes_with_larger_minimum_containers(self) -> None:
        pairs = _route_pairs(self._execute(used_ship="Aegis Avenger Titan"))
        self.assertEqual(
            pairs,
            {
                ("Small Origin", "Small Destination"),
                ("Unknown Origin", "Unknown Destination"),
                ("Medium Origin", "Medium Destination"),
            },
        )
        # Every route found fits the ship: nothing for the user to check
        self.assertFalse(any("container" in note for note in self._helper.get_handler_tool().notes))

    def test_container_limit_is_only_mentioned_when_no_route_fits(self) -> None:
        self._db.execute(
            "DELETE FROM commodity_route WHERE COALESCE(container_size_min_origin, 0) <= 4 "
            "AND COALESCE(container_size_min_destination, 0) <= 4"
        )
        self._db.commit()
        self.assertEqual(self._execute(used_ship="Aegis Avenger Titan"), [])
        self.assertTrue(any(
            "No route found" in note and "up to 4 SCU" in note for note in self._helper.get_handler_tool().notes
        ))

    def test_buy_says_the_largest_container_the_sell_terminal_takes(self) -> None:
        # The ship and the buy terminal go up to 32 SCU, the sell terminal only to 24: 32 SCU boxes would be stuck
        self._db.execute(
            "UPDATE commodity_route SET container_sizes_origin = '1,2,4,8,16,24,32', "
            "container_sizes_destination = '1,2,4,8,16,24' WHERE id = 201"
        )
        self._db.execute(
            "UPDATE commodity_route SET container_sizes_origin = '1,2,4,8,16,24,32', "
            "container_sizes_destination = '8,16,24,32' WHERE id = 205"
        )
        # The buy terminal itself only has 16 SCU boxes: no choice to make
        self._db.execute(
            "UPDATE commodity_route SET container_sizes_origin = '1,2,4,8,16', "
            "container_sizes_destination = '1,2,4,8,16,24,32' WHERE id = 203"
        )
        self._db.commit()
        buys = {
            route["path"]: _first_buys(route)[0]
            for route in self._execute(used_ship="Crusader C2 Hercules Starlifter")
        }
        self.assertEqual(
            buys["Small Origin -> Small Destination"].get("container_note"),
            "Buy it in containers of at most 24 SCU: Small Destination, where you sell it, takes no bigger ones.",
        )
        # The buy terminal is the limit itself, or 32 SCU fits everywhere: nothing to choose, nothing to say
        self.assertNotIn("container_note", buys["Small Origin -> Large Destination"])
        self.assertNotIn("container_note", buys["Medium Origin -> Medium Destination"])

        # A small ship is the limit: it names the ship, not a terminal
        buys = {route["path"]: _first_buys(route)[0] for route in self._execute(used_ship="Aegis Avenger Titan")}
        self.assertEqual(
            buys["Small Origin -> Small Destination"].get("container_note"),
            "Buy it in containers of at most 4 SCU: bigger ones don't fit the Aegis Avenger Titan.",
        )

    def test_large_ship_keeps_all_routes(self) -> None:
        pairs = _route_pairs(self._execute(used_ship="Crusader C2 Hercules Starlifter"))
        self.assertEqual(pairs, _route_pairs(self._execute()))
        self.assertEqual(len(pairs), len(ROUTES))

    def test_ship_without_cargo_data_uses_given_cargo_space_or_asks(self) -> None:
        # No SCU in UEX used to force cargo 0, even over cargo space the user gave
        self.assertTrue(self._execute(used_ship="Anvil Hornet", available_cargo_space_scu=4))
        self.assertEqual(self._execute(used_ship="Anvil Hornet"), [])
        self.assertTrue(
            any("no cargo capacity" in note and "Anvil Hornet" in note for note in self._helper.get_handler_tool().notes)
        )

    def test_ship_without_container_data_is_not_filtered(self) -> None:
        all_pairs = _route_pairs(self._execute())
        self.assertEqual(_route_pairs(self._execute(used_ship="MISC Hull D")), all_pairs)
        self.assertEqual(_route_pairs(self._execute(used_ship="Origin 600i Executive Edition")), all_pairs)
        self.assertFalse(
            any("container" in note for note in self._helper.get_handler_tool().notes)
        )


def main() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CommodityRouteContainerSizeFilterTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
