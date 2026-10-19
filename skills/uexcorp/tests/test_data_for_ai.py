"""What the AI sees of the data: stock/demand labels, ship rentals, ship makers, item units.

No pytest. Run from the project root:

    python3 -m skills.uexcorp.tests.test_data_for_ai

Exits non-zero on the first failed assertion or crash; prints "ALL OK" on success.

Why this exists
---------------
The status code is stored as TEXT, so the label lookup (int keys) never matched: the AI got the raw
UEX names, and read "Out of Stock (Empty)" on a sell terminal as "no demand" when it means the most.
Ship rentals were read from the purchase table: every buyable ship showed a rental at its shop
without a price, and real rental prices never showed. Each ship listed every ship of its maker,
and once rentals worked, up to 30 rental terminals.
UEX gives quantum speed in Mm/s and km/s, so the fastest drive and filter_attribute were off.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from skills.uexcorp.uexcorp.data_access.vehicle_rental_price_data_access import VehicleRentalPriceDataAccess
from skills.uexcorp.uexcorp.helper import Helper
from skills.uexcorp.uexcorp.model.commodity_status import CommodityStatus
from skills.uexcorp.uexcorp.model.item_attribute import ItemAttribute
from skills.uexcorp.uexcorp.model.vehicle import Vehicle
from skills.uexcorp.tests.test_commodity_route_auto_load import _FakeHelper


class DataForAiTest(unittest.TestCase):
    def setUp(self) -> None:
        from skills.uexcorp.uexcorp.database.database import Database

        self._original_helper = Helper._instance
        self._tmp_dir = tempfile.mkdtemp(prefix="uexcorp_data_for_ai_test_")
        self._helper = _FakeHelper()
        Helper._instance = self._helper
        self._db = Database(self._tmp_dir, version="test-data-for-ai", helper=self._helper)
        self._helper.set_database(self._db)
        self._seed()

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
        for code, name, is_buy in (("1", "Out of Stock (Empty)", 0), ("7", "Maximum Inventory (Full)", 1)):
            self._db.execute(
                "INSERT INTO commodity_status (code, name, percentage, is_buy) VALUES (?, ?, ?, ?)",
                (code, name, "0-14%" if code == "1" else "86-100%", is_buy),
            )
        self._db.execute(
            "INSERT INTO terminal (id, name, type, is_available) VALUES (1, 'New Deal', 'vehicle_buy', 1)"
        )
        self._db.execute(
            "INSERT INTO company (id, name, is_vehicle_manufacturer) VALUES (1, 'Drake Interplanetary', 1)"
        )
        self._db.execute(
            "INSERT INTO vehicle (id, id_company, name, name_full) VALUES (1, 1, 'Cutlass Black', 'Drake Cutlass Black'), "
            "(2, 1, 'Caterpillar', 'Drake Caterpillar')"
        )
        # Ship 1 is bought and rented, ship 2 only bought
        self._db.execute(
            "INSERT INTO vehicle_purchase_price (id, id_vehicle, id_terminal, price_buy) VALUES (1, 1, 1, 900000), (2, 2, 1, 15000000)"
        )
        self._db.execute(
            "INSERT INTO vehicle_rental_price (id, id_vehicle, id_terminal, price_rent) VALUES (1, 1, 1, 37485)"
        )

    def test_an_empty_sell_terminal_reads_as_high_demand(self) -> None:
        status = CommodityStatus(1, False, load=True).get_data_for_ai_minimal()
        self.assertTrue(status.startswith("extremely high demand"), status)

    def test_a_full_buy_terminal_reads_as_full_stock(self) -> None:
        status = CommodityStatus(7, True, load=True).get_data_for_ai_minimal()
        self.assertTrue(status.startswith("full stock"), status)

    def test_rentals_come_with_their_price(self) -> None:
        rentals = VehicleRentalPriceDataAccess().add_filter_by_id_vehicle(1).load()
        self.assertEqual([r.get_data_for_ai(show_vehicle_data=False)["price_rent"] for r in rentals], [37485])

    def test_a_ship_that_is_only_sold_has_no_rental(self) -> None:
        self.assertEqual(VehicleRentalPriceDataAccess().add_filter_by_id_vehicle(2).load(), [])

    def test_a_ship_names_its_maker_without_the_makers_other_ships(self) -> None:
        self.assertEqual(Vehicle(1, load=True).get_data_for_ai()["company"], "Drake Interplanetary")

    def test_a_ship_rented_in_many_places_lists_the_cheapest(self) -> None:
        for rental_id, price in enumerate((52920, 50274, 60000, 52920, 50000, 52920, 70000), start=2):
            self._db.execute(
                "INSERT INTO vehicle_rental_price (id, id_vehicle, id_terminal, price_rent) VALUES (?, 1, 1, ?)",
                (rental_id, price),
            )
        data = Vehicle(1, load=True).get_data_for_ai()
        self.assertEqual([r["price_rent"] for r in data["rental_options"]], [37485, 50000, 50274, 52920, 52920])
        self.assertEqual(data["rental_terminal_count"], 8)

    def test_units_are_one_per_quantity(self) -> None:
        for value, unit, expected in (
            ("242.00", "Mm/s", ("242000", "km/s")),
            ("205000", "km/s", ("205000", "km/s")),
            ("12", "KµSCU", ("12000", "µSCU")),
            ("480", "μSCU", ("480", "µSCU")),
            ("250", "mRem", ("0.25", "REM")),
            ("N/A", "Mm/s", ("N/A", "Mm/s")),  # no number: left as it is
            ("40", "%", ("40", "%")),
        ):
            row = {"value": value, "unit": unit}
            ItemAttribute.normalize_unit(row)
            self.assertEqual((row["value"], row["unit"]), expected)


def main() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DataForAiTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
