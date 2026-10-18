"""Tests for the filter parameters of the information tools, the validator and the SQL Filter.

No pytest. Run from the project root:

    python3 -m skills.uexcorp.tests.test_tool_filters

Exits non-zero on the first failed assertion or crash; prints "ALL OK" on success.

Why this exists
---------------
A review of every filter found filters that crashed, matched everything or nothing, or
combined their conditions the wrong way (OR instead of AND, per commodity instead of per
price). Each test below pins one of those fixes.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest

from skills.uexcorp.uexcorp.database.filter import Filter
from skills.uexcorp.uexcorp.helper import Helper
from skills.uexcorp.tests.test_commodity_route_auto_load import _FakeHelper, _parse_routes

# (terminal id, name, type, star system, planet, space station, city, poi id)
TERMINALS = [
    (1, "Term Lorville", "commodity", "Stanton", "Hurston", None, "Lorville", None),
    (2, "Term MIC-L1", "commodity", "Stanton", None, "MIC-L1", None, None),
    (3, "Term Ruin", "commodity", "Pyro", None, "Ruin Station", None, None),
    (4, "Term Spaceport", "item", "Stanton", "microTech", None, None, 90),
]

# (commodity id, name)
COMMODITIES = [(11, "Waste"), (12, "Tin"), (13, "Gold")]

# (commodity id, terminal id, buy, sell)
COMMODITY_PRICES = [
    (11, 2, 115, None),  # Waste: cheap only at MIC-L1
    (11, 1, 199, None),
    (11, 3, None, 200),
    (12, 1, 100, None),  # Tin: margin 50 %
    (12, 3, None, 200),
    (13, 3, 50, None),  # Gold: margin 20 %, only buyable in Pyro
    (13, 2, None, 62.5),
]

# (item id, name)
ITEMS = [(21, "Omnisky VI Cannon"), (22, "Omnisky IX Cannon"), (23, "Arrowhead Sniper Rifle"), (24, "P4-AR Rifle")]

# (item id, attribute, value)
ITEM_ATTRIBUTES = [
    (21, "Size", "1"), (21, "Grade", "A"), (21, "Rate of Fire", "120"), (21, "Quantum Fuel Burn", "6.54"),
    (22, "Size", "1"), (22, "Grade", "B"), (22, "Rate of Fire", ""),
    (23, "Size", "2"), (23, "Grade", "A"), (23, "Rate of Fire", "N/A (Beam)"),
    (24, "Size", "1"), (24, "Grade", "A"), (24, "Rate of Fire", "600"), (24, "Quantum Fuel Burn", "6"),
]


def _names(payload) -> list[str]:
    if not payload:
        return []
    data = _parse_routes(payload) if isinstance(payload, str) else payload
    return [entry["name"] if isinstance(entry, dict) else entry.split(" (")[0] for entry in data]


class _FilterTestBase(unittest.TestCase):
    def setUp(self) -> None:
        from skills.uexcorp.uexcorp.database.database import Database

        self._original_helper = Helper._instance
        self._tmp_dir = tempfile.mkdtemp(prefix="uexcorp_tool_filters_test_")
        self._helper = _FakeHelper()
        Helper._instance = self._helper
        self._db = Database(self._tmp_dir, version="test-tool-filters", helper=self._helper)
        self._helper.set_database(self._db)
        self._seed()
        self._db.commit()

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
        pass


class SqlFilterTest(_FilterTestBase):
    def _seed(self) -> None:
        for terminal_id, value in ((1, 0), (2, 5), (3, None), (4, -5)):
            self._db.execute("INSERT INTO terminal (id, name, mcs) VALUES (?, ?, ?)", (terminal_id, f"T{terminal_id}", value))

    def _ids(self, *wheres, groups=()) -> list[int]:
        from skills.uexcorp.uexcorp.data_access.terminal_data_access import TerminalDataAccess

        data_access = TerminalDataAccess()
        for where in wheres:
            data_access.filter.where(*where)
        for group, is_or in groups:
            data_access.apply_filter(group, is_or)
        return sorted(terminal.get_id() for terminal in data_access.load())

    def test_null_counts_as_zero_only_where_zero_matches(self) -> None:
        self.assertEqual(self._ids(("mcs", 0, ">")), [2])
        self.assertEqual(self._ids(("mcs", 0, "<")), [4])
        self.assertEqual(self._ids(("mcs", 0, "!=")), [2, 4])
        self.assertEqual(self._ids(("mcs", 0)), [1, 3])
        self.assertEqual(self._ids(("mcs", 0, "<=")), [1, 3, 4])

    def test_lists_with_equality_operators(self) -> None:
        self.assertEqual(self._ids(("name", ["T1", "T2"], "!=")), [3, 4])
        self.assertEqual(self._ids(("name", ["T1", "T2"], "=")), [1, 2])
        self.assertEqual(self._ids(("name", "T1", "NOT IN")), [2, 3, 4])

    def test_none_value(self) -> None:
        self.assertEqual(self._ids(("mcs", None)), [3])
        self.assertEqual(self._ids(("mcs", None, "!=")), [1, 2, 4])

    def test_groups_keep_their_precedence(self) -> None:
        group_a = Filter()
        group_a.where("name", "T1")
        group_b = Filter()
        group_b.where("name", "T2")
        # (mcs = 5 OR name = T1) AND name = T2, not mcs = 5 OR (name = T1 AND name = T2)
        self.assertEqual(self._ids(("mcs", 5), groups=((group_a, True), (group_b, False))), [2])
        group_c = Filter()
        group_c.where("name", "T3")
        self.assertEqual(self._ids(("id", 1), ("mcs", 0), groups=((group_c, True),)), [1, 3])


class ValidatorTest(_FilterTestBase):
    @staticmethod
    def _validate(logic: str, value, multiple: bool = False, config: dict | None = None):
        from skills.uexcorp.uexcorp.tool.validator import Validator

        return asyncio.run(Validator(logic, multiple=multiple, config=config).validate(value))

    def test_null_values_are_rejected_without_crashing(self) -> None:
        from skills.uexcorp.uexcorp.tool.validator import Validator

        self.assertIsNone(self._validate(Validator.VALIDATE_NUMBER, None, config={"min": 1}))
        self.assertIsNone(self._validate(Validator.VALIDATE_BOOL, None))
        self.assertIsNone(self._validate(Validator.VALIDATE_BOOL, 1))

    def test_number_limits(self) -> None:
        from skills.uexcorp.uexcorp.tool.validator import Validator

        self.assertIsNone(self._validate(Validator.VALIDATE_NUMBER, -3, config={"min": 0}))
        self.assertEqual(self._validate(Validator.VALIDATE_NUMBER, 0, config={"min": 0}), 0)
        self.assertEqual(self._validate(Validator.VALIDATE_NUMBER, "12", config={"min": 1}), 12)
        self.assertIsNone(self._validate(Validator.VALIDATE_NUMBER, 16, config={"min": 1, "max": 15}))

    def test_operation_int(self) -> None:
        from skills.uexcorp.uexcorp.tool.validator import Validator

        validate = lambda value: self._validate(Validator.VALIDATE_OPERATION_INT, value, multiple=True)
        self.assertEqual(validate([{"operation": ">=", "value": 100}]), [(100, ">=")])
        self.assertEqual(validate([{"operation": ">=", "value": "-5"}]), [(-5, ">=")])
        self.assertEqual(validate([{"operation": "<", "value": "99.5"}]), [(99, "<")])
        self.assertIsNone(validate([{"operation": ">=", "value": "abc"}]))
        self.assertIsNone(validate([{"operation": ">="}]))
        self.assertIsNone(validate(["not a dict"]))
        self.assertIsNone(validate([{"operation": "~", "value": 1}]))


class CommodityInformationFilterTest(_FilterTestBase):
    def _seed(self) -> None:
        _seed_terminals(self._db)
        for commodity_id, name in COMMODITIES:
            self._db.execute("INSERT INTO commodity (id, name, is_illegal, is_blacklisted) VALUES (?, ?, 0, 0)", (commodity_id, name))
        for price_id, (commodity_id, terminal_id, buy, sell) in enumerate(COMMODITY_PRICES, start=1):
            self._db.execute(
                "INSERT INTO commodity_price (id, id_commodity, id_terminal, price_buy, price_sell) VALUES (?, ?, ?, ?, ?)",
                (price_id, commodity_id, terminal_id, buy, sell),
            )

    def _names(self, **kwargs) -> list[str]:
        from skills.uexcorp.uexcorp.tool.commodity_information import CommodityInformation

        payload, _instant = CommodityInformation().execute(**kwargs)
        return sorted(_names(payload))

    def test_location_blacklist_is_offered_to_the_llm(self) -> None:
        from skills.uexcorp.uexcorp.tool.commodity_information import CommodityInformation

        self.assertIn("filter_location_blacklist", CommodityInformation().get_optional_fields())

    def test_location_blacklist(self) -> None:
        self.assertEqual(self._names(filter_location_blacklist=["Pyro"]), ["Gold", "Tin", "Waste"])
        self.assertEqual(self._names(filter_location_blacklist=["Pyro", "MIC-L1"]), ["Tin", "Waste"])

    def test_price_is_checked_at_the_location(self) -> None:
        self.assertEqual(self._names(filter_buy_price=[(150, "<=")]), ["Gold", "Tin", "Waste"])
        self.assertEqual(self._names(filter_location_whitelist=["Lorville"], filter_buy_price=[(150, "<=")]), ["Tin"])
        self.assertEqual(self._names(filter_location_blacklist=["Pyro"], filter_buy_price=[(150, "<=")]), ["Tin", "Waste"])

    def test_buy_and_sell_may_match_at_different_terminals(self) -> None:
        self.assertEqual(self._names(filter_buy_price=[(100, "<=")], filter_sell_price=[(150, ">=")]), ["Tin"])

    def test_several_profit_conditions_must_all_match(self) -> None:
        self.assertEqual(self._names(filter_profit_margin_percent=[(10, ">="), (30, "<=")]), ["Gold"])
        self.assertEqual(self._names(filter_profit_margin_percent=[(30, ">=")]), ["Tin", "Waste"])

    def test_profit_equals(self) -> None:
        self.assertEqual(self._names(filter_profit_absolute_per_scu=[(100, "=")]), ["Tin"])

    def test_empty_lists_are_no_filter(self) -> None:
        self.assertEqual(self._names(filter_commodities=[], filter_location_whitelist=[]), ["Gold", "Tin", "Waste"])


class ItemInformationFilterTest(_FilterTestBase):
    def _seed(self) -> None:
        _seed_terminals(self._db)
        self._db.execute("INSERT INTO poi (id, name) VALUES (90, 'New Babbage Interstellar Spaceport')")
        for item_id, name in ITEMS:
            self._db.execute("INSERT INTO item (id, name) VALUES (?, ?)", (item_id, name))
        for attribute_id, (item_id, attribute, value) in enumerate(ITEM_ATTRIBUTES, start=1):
            self._db.execute(
                "INSERT INTO item_attribute (id, id_item, attribute_name, value) VALUES (?, ?, ?, ?)",
                (attribute_id, item_id, attribute, value),
            )
        self._db.execute("INSERT INTO item_price (id, id_item, id_terminal, terminal_name, price_buy) VALUES (1, 23, 4, 'Term Spaceport', 5000)")
        self._db.execute("INSERT INTO item_price (id, id_item, id_terminal, terminal_name, price_buy) VALUES (2, 24, 4, 'Term Spaceport', NULL)")

    def _names(self, **kwargs) -> list[str]:
        from skills.uexcorp.uexcorp.tool.item_information import ItemInformation

        payload, _instant = ItemInformation().execute(**kwargs)
        return sorted(_names(payload))

    @staticmethod
    def _attribute(attribute: str, operator: str, value: str) -> dict:
        return {"attribute": attribute, "operator": operator, "value": value}

    def test_name_search_needs_all_words_of_a_term(self) -> None:
        self.assertEqual(self._names(filter_name_search=["Omnisky "]), ["Omnisky IX Cannon", "Omnisky VI Cannon"])
        self.assertEqual(self._names(filter_name_search=["Arrowhead  Sniper"]), ["Arrowhead Sniper Rifle"])
        self.assertEqual(self._names(filter_name_search=["P4-AR"]), ["P4-AR Rifle"])
        self.assertEqual(self._names(filter_name_search=["Omnisky VI", "P4-AR"]), ["Omnisky VI Cannon", "P4-AR Rifle"])

    def test_numeric_attribute_ignores_values_that_are_no_numbers(self) -> None:
        self.assertEqual(self._names(filter_attribute=[self._attribute("Rate of Fire", "<", "200")]), ["Omnisky VI Cannon"])

    def test_numeric_attribute_keeps_decimals(self) -> None:
        self.assertEqual(self._names(filter_attribute=[self._attribute("Quantum Fuel Burn", ">", "6")]), ["Omnisky VI Cannon"])
        self.assertEqual(self._names(filter_attribute=[self._attribute("Quantum Fuel Burn", "<", "6.5")]), ["P4-AR Rifle"])

    def test_several_attributes_must_all_match(self) -> None:
        both = [self._attribute("Size", "=", "1"), self._attribute("Grade", "=", "A")]
        self.assertEqual(self._names(filter_attribute=both), ["Omnisky VI Cannon", "P4-AR Rifle"])

    def test_buy_location_matches_poi_and_needs_a_price(self) -> None:
        self.assertEqual(self._names(filter_buy_location=["New Babbage Interstellar Spaceport"]), ["Arrowhead Sniper Rifle"])


class LocationInformationFilterTest(_FilterTestBase):
    def _seed(self) -> None:
        for station_id, name in ((1, "Everus Harbor"), (2, "Baijini Point"), (3, "Pyro Gateway (Stanton)")):
            self._db.execute(
                "INSERT INTO space_station (id, name, star_system_name, is_available) VALUES (?, ?, 'Stanton', 1)",
                (station_id, name),
            )
        self._db.execute("INSERT INTO orbit (id, name) VALUES (1, 'Hurston Lagrange Point 1')")

    def _names(self, **kwargs) -> list[str]:
        from skills.uexcorp.uexcorp.tool.location_information import LocationInformation

        payload, _instant = LocationInformation().execute(**kwargs)
        return sorted(_names(payload))

    def test_space_station_and_gateway_types_together(self) -> None:
        self.assertEqual(
            self._names(filter_locations=["Stanton"], filter_location_types=["space_station", "gateway"]),
            ["Baijini Point", "Everus Harbor", "Pyro Gateway (Stanton)"],
        )
        self.assertEqual(
            self._names(filter_locations=["Stanton"], filter_location_types=["gateway"]),
            ["Pyro Gateway (Stanton)"],
        )

    def test_orbit_by_name(self) -> None:
        self.assertEqual(self._names(filter_locations=["Hurston Lagrange Point 1"]), ["Hurston Lagrange Point 1"])


def _seed_terminals(db) -> None:
    for terminal_id, name, terminal_type, star_system, planet, space_station, city, poi in TERMINALS:
        db.execute(
            """
            INSERT INTO terminal (id, name, type, is_available, star_system_name, planet_name, space_station_name, city_name, id_poi)
            VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (terminal_id, name, terminal_type, star_system, planet, space_station, city, poi),
        )


def main() -> None:
    suite = unittest.TestSuite()
    for case in (SqlFilterTest, ValidatorTest, CommodityInformationFilterTest, ItemInformationFilterTest, LocationInformationFilterTest):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(case))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
