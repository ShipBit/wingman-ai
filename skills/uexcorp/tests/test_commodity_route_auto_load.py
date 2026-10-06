"""Focused tests for uex_get_trade_routes filter_require_auto_load.

No pytest. Run from the project root:

    python3 -m skills.uexcorp.tests.test_commodity_route_auto_load

Exits non-zero on the first failed assertion or crash; prints "ALL OK" on success.

Why this exists
---------------
Commodity-route rows expose has_loading_dock / has_freight_elevator / has_docking_port
but not is_auto_load. Hangar auto load/unload is a terminal flag (UEX is_auto_load,
shown as "Auto Load" on terminal pages). The trade-routes tool must hard-filter
both origin and destination through TerminalDataAccess when asked, without using
vehicle.is_hangar (that means the ship contains a hangar) and without breaking
used_ship's existing has_loading_dock filter.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from skills.uexcorp.uexcorp.compression import LEGEND_KEY
from skills.uexcorp.uexcorp.helper import Helper
from skills.uexcorp.uexcorp.tool.commodity_route import CommodityRoute
from skills.uexcorp.uexcorp.tool.validator import Validator


class _NullHandler:
    def write(self, *args, **kwargs):
        return None


class _FakeConfig:
    def get_behavior_commodity_route_default_count(self) -> int:
        return 15

    def get_behavior_commodity_route_advanced_info(self) -> bool:
        return False


class _FakeToolHandler:
    def __init__(self):
        self.notes: list[str] = []

    def add_note(self, note: str) -> None:
        self.notes.append(note)


class _FakeHelper:
    """Minimal Helper stand-in so CommodityRoute.execute can hit a real sqlite DB."""

    def __init__(self):
        self._database = None
        self._config = _FakeConfig()
        self._tool = _FakeToolHandler()
        self._debug = _NullHandler()
        self._error = _NullHandler()

    def set_database(self, database) -> None:
        self._database = database

    def get_database(self):
        return self._database

    def get_handler_config(self):
        return self._config

    def get_handler_tool(self):
        return self._tool

    def get_handler_debug(self):
        return self._debug

    def get_handler_error(self):
        return self._error


# Terminal ids
AUTO_CITY = 1
AUTO_STATION = 2
MANUAL_OUTPOST = 3
MANUAL_PAD = 4
AUTO_FUEL = 5
AUTO_UNAVAILABLE = 6

# Route ids
ROUTE_AUTO_AUTO = 101
ROUTE_AUTO_MANUAL = 102
ROUTE_MANUAL_AUTO = 103
ROUTE_MANUAL_MANUAL = 104
ROUTE_AUTO_AUTO_DOCK = 105
ROUTE_FUEL_TO_AUTO = 106


def _parse_routes(payload: str) -> list[dict]:
    data = json.loads(payload)
    if isinstance(data, dict) and LEGEND_KEY in data:
        data = data.get("data") or []
    return data


def _route_pairs(routes: list[dict]) -> set[tuple[str, str]]:
    return {(route["buy_at"], route["sell_at"]) for route in routes}


class CommodityRouteAutoLoadFilterTest(unittest.TestCase):
    def setUp(self) -> None:
        from skills.uexcorp.uexcorp.database.database import Database

        self._original_helper = Helper._instance
        self._tmp_dir = tempfile.mkdtemp(prefix="uexcorp_auto_load_test_")
        self._helper = _FakeHelper()
        Helper._instance = self._helper
        self._db = Database(self._tmp_dir, version="test-auto-load", helper=self._helper)
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
        self._db.execute(
            """
            INSERT INTO terminal (id, name, type, is_available, is_auto_load, city_name, outpost_name)
            VALUES
                (?, 'Auto City TDD', 'commodity', 1, 1, 'Auto City', NULL),
                (?, 'Auto Station TDD', 'commodity', 1, 1, NULL, NULL),
                (?, 'Manual Outpost TDD', 'commodity', 1, 0, NULL, 'Manual Outpost'),
                (?, 'Manual Pad TDD', 'commodity', 1, 0, NULL, NULL),
                (?, 'Auto Fuel', 'fuel', 1, 1, NULL, NULL),
                (?, 'Auto Unavailable TDD', 'commodity', 0, 1, NULL, NULL)
            """,
            (AUTO_CITY, AUTO_STATION, MANUAL_OUTPOST, MANUAL_PAD, AUTO_FUEL, AUTO_UNAVAILABLE),
        )
        self._insert_route(
            ROUTE_AUTO_AUTO,
            AUTO_CITY,
            AUTO_STATION,
            "Auto City TDD",
            "Auto Station TDD",
            has_loading_dock=0,
        )
        self._insert_route(
            ROUTE_AUTO_MANUAL,
            AUTO_CITY,
            MANUAL_OUTPOST,
            "Auto City TDD",
            "Manual Outpost TDD",
            has_loading_dock=1,
        )
        self._insert_route(
            ROUTE_MANUAL_AUTO,
            MANUAL_OUTPOST,
            AUTO_STATION,
            "Manual Outpost TDD",
            "Auto Station TDD",
            has_loading_dock=0,
        )
        self._insert_route(
            ROUTE_MANUAL_MANUAL,
            MANUAL_OUTPOST,
            MANUAL_PAD,
            "Manual Outpost TDD",
            "Manual Pad TDD",
            has_loading_dock=0,
        )
        self._insert_route(
            ROUTE_AUTO_AUTO_DOCK,
            AUTO_STATION,
            AUTO_CITY,
            "Auto Station TDD",
            "Auto City TDD",
            has_loading_dock=1,
        )
        self._insert_route(
            ROUTE_FUEL_TO_AUTO,
            AUTO_FUEL,
            AUTO_STATION,
            "Auto Fuel",
            "Auto Station TDD",
            has_loading_dock=0,
        )
        self._db.execute(
            """
            INSERT INTO vehicle (id, name_full, is_loading_dock, is_hangar, scu)
            VALUES
                (1, 'MISC Hull C', 1, 0, 100),
                (2, 'ANVL Carrack', 0, 1, 50)
            """
        )
        self._db.commit()

    def _insert_route(
        self,
        route_id: int,
        origin_id: int,
        dest_id: int,
        origin_name: str,
        dest_name: str,
        has_loading_dock: int,
    ) -> None:
        self._db.execute(
            """
            INSERT INTO commodity_route (
                id, id_terminal_origin, id_terminal_destination,
                commodity_name, origin_terminal_name, destination_terminal_name,
                origin_star_system_name, origin_planet_name,
                destination_star_system_name, destination_planet_name,
                price_origin, price_destination, scu_origin, scu_destination,
                profit, score, distance,
                has_loading_dock_origin, has_loading_dock_destination
            ) VALUES (?, ?, ?, 'Laranite', ?, ?, 'Stanton', 'Hurston', 'Stanton', 'Hurston',
                      10, 20, 8, 8, 80, 50, 1, ?, ?)
            """,
            (route_id, origin_id, dest_id, origin_name, dest_name, has_loading_dock, has_loading_dock),
        )

    def _execute(self, **kwargs) -> list[dict]:
        payload, _instant = self._tool.execute(limit=15, **kwargs)
        return _parse_routes(payload)

    def test_optional_field_is_bool_and_describes_hangar_auto_load(self) -> None:
        fields = self._tool.get_optional_fields()
        self.assertIn("filter_require_auto_load", fields)
        validator = fields["filter_require_auto_load"]
        definition = validator.get_llm_definition()
        self.assertEqual(definition["type"], "boolean")
        prompt = definition["description"].lower()
        self.assertIn("hangar", prompt)
        self.assertIn("auto load", prompt)

    def test_filter_on_keeps_only_routes_with_auto_load_at_both_ends(self) -> None:
        pairs = _route_pairs(self._execute(filter_require_auto_load=True))
        self.assertEqual(
            pairs,
            {
                ("Auto City TDD", "Auto Station TDD"),
                ("Auto Station TDD", "Auto City TDD"),
            },
        )

    def test_filter_off_and_absent_leave_all_seeded_routes(self) -> None:
        expected = {
            ("Auto City TDD", "Auto Station TDD"),
            ("Auto City TDD", "Manual Outpost TDD"),
            ("Manual Outpost TDD", "Auto Station TDD"),
            ("Manual Outpost TDD", "Manual Pad TDD"),
            ("Auto Station TDD", "Auto City TDD"),
            ("Auto Fuel", "Auto Station TDD"),
        }
        self.assertEqual(_route_pairs(self._execute()), expected)
        self.assertEqual(_route_pairs(self._execute(filter_require_auto_load=False)), expected)

    def test_used_ship_loading_dock_still_applies_with_auto_load_filter(self) -> None:
        dock_only = _route_pairs(self._execute(used_ship="MISC Hull C"))
        self.assertEqual(
            dock_only,
            {
                ("Auto City TDD", "Manual Outpost TDD"),
                ("Auto Station TDD", "Auto City TDD"),
            },
        )
        dock_and_auto = _route_pairs(
            self._execute(used_ship="MISC Hull C", filter_require_auto_load=True)
        )
        self.assertEqual(dock_and_auto, {("Auto Station TDD", "Auto City TDD")})

    def test_used_ship_is_hangar_does_not_act_as_auto_load_filter(self) -> None:
        hangar_ship = _route_pairs(self._execute(used_ship="ANVL Carrack"))
        self.assertEqual(hangar_ship, _route_pairs(self._execute()))
        hangar_plus_auto = _route_pairs(
            self._execute(used_ship="ANVL Carrack", filter_require_auto_load=True)
        )
        self.assertEqual(
            hangar_plus_auto,
            {
                ("Auto City TDD", "Auto Station TDD"),
                ("Auto Station TDD", "Auto City TDD"),
            },
        )

    def test_auto_load_and_start_location_are_anded(self) -> None:
        pairs = _route_pairs(
            self._execute(
                filter_start_location="Manual Outpost",
                filter_require_auto_load=True,
            )
        )
        self.assertEqual(pairs, set())

        auto_start = _route_pairs(
            self._execute(
                filter_start_location="Auto City",
                filter_require_auto_load=True,
            )
        )
        self.assertEqual(auto_start, {("Auto City TDD", "Auto Station TDD")})

    def test_no_auto_load_commodity_terminals_returns_empty(self) -> None:
        self._db.execute(
            "UPDATE terminal SET is_auto_load = 0 WHERE type = 'commodity'"
        )
        self._db.commit()
        payload, _instant = self._tool.execute(limit=15, filter_require_auto_load=True)
        self.assertEqual(_parse_routes(payload), [])
        self.assertTrue(
            any("auto load" in note.lower() for note in self._helper.get_handler_tool().notes)
        )


def main() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CommodityRouteAutoLoadFilterTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
