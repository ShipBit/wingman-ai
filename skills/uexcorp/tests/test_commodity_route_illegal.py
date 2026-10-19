"""Tests for illegal and blacklisted commodities in uex_get_trade_routes.

No pytest. Run from the project root:

    python3 -m skills.uexcorp.tests.test_commodity_route_illegal

Exits non-zero on the first failed assertion or crash; prints "ALL OK" on success.

Why this exists
---------------
Routes are derived from all prices, so they include illegal commodities. By default
they stay in the results, but every route carrying one must say so clearly, so the
AI never suggests contraband without a warning. filter_allow_illegal_commodities
false removes them; commodities blacklisted in the skill config are never traded.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from skills.uexcorp.uexcorp.helper import Helper
from skills.uexcorp.uexcorp.tool.commodity_route import CommodityRoute
from skills.uexcorp.uexcorp.tool.validator import Validator
from skills.uexcorp.tests.test_commodity_route_auto_load import _FakeHelper, _parse_routes

TERMINALS = {1: "Term A", 2: "Term B", 3: "Term C"}

# (commodity id, name, is_illegal, is_blacklisted)
COMMODITIES = [
    (11, "Xenon", 0, 0),
    (12, "WiDoW", 1, 0),
    (13, "Gold", 0, 1),
]

# (route id, commodity id, origin, destination, buy, sell, stock, demand)
LEGS = [
    (1, 11, 1, 2, 10, 20, 1000, None),  # legal: 10/SCU
    (2, 12, 1, 3, 10, 50, 1000, None),  # illegal: 40/SCU, best legal-or-not option
    (3, 13, 1, 2, 10, 90, 1000, None),  # blacklisted: 80/SCU, must never show up
    (4, 12, 2, 3, 10, 60, 0, None),  # illegal, no stock left: only a note
]


class CommodityRouteIllegalTest(unittest.TestCase):
    def setUp(self) -> None:
        from skills.uexcorp.uexcorp.database.database import Database

        self._original_helper = Helper._instance
        self._tmp_dir = tempfile.mkdtemp(prefix="uexcorp_illegal_test_")
        self._helper = _FakeHelper()
        Helper._instance = self._helper
        self._db = Database(self._tmp_dir, version="test-illegal", helper=self._helper)
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
        names = {}
        for commodity_id, name, is_illegal, is_blacklisted in COMMODITIES:
            names[commodity_id] = name
            self._db.execute(
                "INSERT INTO commodity (id, name, is_illegal, is_blacklisted) VALUES (?, ?, ?, ?)",
                (commodity_id, name, is_illegal, is_blacklisted),
            )
        for route_id, commodity_id, origin, destination, buy, sell, stock, demand in LEGS:
            self._db.execute(
                """
                INSERT INTO commodity_route (
                    id, id_commodity, commodity_name, id_terminal_origin, id_terminal_destination,
                    origin_terminal_name, destination_terminal_name,
                    origin_star_system_name, destination_star_system_name, origin_planet_name, destination_planet_name,
                    price_origin, price_destination, scu_origin, scu_destination, price_margin, distance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Stanton', 'Stanton', 'Hurston', 'Hurston', ?, ?, ?, ?, ?, 10)
                """,
                (
                    route_id, commodity_id, names[commodity_id], origin, destination,
                    TERMINALS[origin], TERMINALS[destination], buy, sell, stock, demand, (sell - buy) / sell * 100,
                ),
            )
        self._db.commit()

    def _execute(self, **kwargs) -> tuple[list[dict], list[str]]:
        self._helper.get_handler_tool().notes.clear()
        payload, _instant = self._tool.execute(limit=15, available_cargo_space_scu=10, **kwargs)
        return _parse_routes(payload), list(self._helper.get_handler_tool().notes)

    @staticmethod
    def _bought(route: dict) -> set[str]:
        return {buy["commodity"] for stop in route["stops"] for buy in stop.get("buy", [])}

    def test_illegal_commodities_are_included_by_default_with_warnings(self) -> None:
        routes, notes = self._execute()
        illegal_route = next(route for route in routes if "WiDoW" in self._bought(route))
        # Route level: first key, names the commodity
        self.assertEqual(next(iter(illegal_route)), "warning")
        self.assertIn("illegal", illegal_route["warning"])
        self.assertIn("WiDoW", illegal_route["warning"])
        self.assertEqual(illegal_route["illegal_commodities"], ["WiDoW"])
        # Buy level: the warning comes first
        buy = next(buy for stop in illegal_route["stops"] for buy in stop.get("buy", []) if buy["commodity"] == "WiDoW")
        self.assertEqual(buy["warnings"][0], CommodityRoute.ILLEGAL_WARNING)
        # Relay note for the user, with how to get legal routes only
        note = next(note for note in notes if note.startswith("Routes include illegal commodities"))
        self.assertIn("WiDoW", note)
        self.assertIn("filter_allow_illegal_commodities", note)

    def test_legal_routes_carry_no_illegal_warning(self) -> None:
        routes, _notes = self._execute()
        legal_route = next(route for route in routes if self._bought(route) == {"Xenon"})
        self.assertNotIn("warning", legal_route)
        self.assertNotIn("illegal_commodities", legal_route)
        buy = legal_route["stops"][0]["buy"][0]
        self.assertNotIn(CommodityRoute.ILLEGAL_WARNING, buy.get("warnings", []))  # empty lists are left out

    def test_filter_false_excludes_illegal_commodities(self) -> None:
        routes, notes = self._execute(filter_allow_illegal_commodities=False)
        self.assertTrue(routes)
        self.assertTrue(all("WiDoW" not in self._bought(route) for route in routes))
        self.assertFalse(any("illegal" in note.lower() for note in notes))

    def test_filter_true_is_the_default(self) -> None:
        default, _ = self._execute()
        explicit, _ = self._execute(filter_allow_illegal_commodities=True)
        self.assertEqual(default, explicit)

    def test_blacklisted_commodities_are_never_traded(self) -> None:
        for kwargs in ({}, {"filter_allow_illegal_commodities": False}, {"max_stops": 3}):
            routes, _notes = self._execute(**kwargs)
            self.assertTrue(all("Gold" not in self._bought(route) for route in routes), kwargs)

    def test_multi_stop_route_with_illegal_leg_is_marked(self) -> None:
        routes, _notes = self._execute(max_stops=2)
        marked = [route for route in routes if "WiDoW" in self._bought(route)]
        self.assertTrue(marked)
        self.assertTrue(all(route["illegal_commodities"] == ["WiDoW"] for route in marked))

    def test_no_availability_note_warns_about_illegal_commodity(self) -> None:
        _routes, notes = self._execute()
        note = next(note for note in notes if note.startswith("Normally WiDoW"))
        self.assertIn(CommodityRoute.ILLEGAL_WARNING, note)

    def test_field_is_offered_to_the_llm(self) -> None:
        field = self._tool.get_optional_fields()["filter_allow_illegal_commodities"]
        definition = field.get_llm_definition()
        self.assertEqual(definition["type"], "boolean")
        self.assertIn("illegal", definition["description"])


def main() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CommodityRouteIllegalTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
