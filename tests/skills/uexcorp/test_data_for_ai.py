"""What the AI sees of the data: stock and demand labels, ship rentals, ship makers, item units.

The status code is stored as TEXT, so the label lookup never matched and "Out of Stock (Empty)" on
a sell terminal was read as "no demand" when it means the most. Ship rentals were read from the
purchase table, every ship listed every ship of its maker, and UEX gives quantum speed in Mm/s and km/s."""

import pytest

from skills.uexcorp.uexcorp.data_access.vehicle_rental_price_data_access import VehicleRentalPriceDataAccess
from skills.uexcorp.uexcorp.model.commodity_status import CommodityStatus
from skills.uexcorp.uexcorp.model.item_attribute import ItemAttribute
from skills.uexcorp.uexcorp.model.vehicle import Vehicle


@pytest.fixture
def data(db):
    for code, name, is_buy in (("1", "Out of Stock (Empty)", 0), ("7", "Maximum Inventory (Full)", 1)):
        db.execute(
            "INSERT INTO commodity_status (code, name, percentage, is_buy) VALUES (?, ?, ?, ?)",
            (code, name, "0-14%" if code == "1" else "86-100%", is_buy),
        )
    db.execute("INSERT INTO terminal (id, name, type, is_available) VALUES (1, 'New Deal', 'vehicle_buy', 1)")
    db.execute("INSERT INTO company (id, name, is_vehicle_manufacturer) VALUES (1, 'Drake Interplanetary', 1)")
    db.execute(
        "INSERT INTO vehicle (id, id_company, name, name_full) VALUES (1, 1, 'Cutlass Black', 'Drake Cutlass Black'), "
        "(2, 1, 'Caterpillar', 'Drake Caterpillar')"
    )
    # Ship 1 is bought and rented, ship 2 only bought
    db.execute("INSERT INTO vehicle_purchase_price (id, id_vehicle, id_terminal, price_buy) VALUES (1, 1, 1, 900000), (2, 2, 1, 15000000)")
    db.execute("INSERT INTO vehicle_rental_price (id, id_vehicle, id_terminal, price_rent) VALUES (1, 1, 1, 37485)")
    return db


@pytest.mark.parametrize("code, is_buy, expected", [
    (1, False, "extremely high demand"),  # an empty sell terminal wants the most
    (7, True, "full stock"),
])
def test_stock_and_demand_read_the_way_a_trader_means_them(data, code, is_buy, expected):
    assert CommodityStatus(code, is_buy, load=True).get_data_for_ai_minimal().startswith(expected)


def test_a_ship_that_is_only_sold_has_no_rental(data):
    assert VehicleRentalPriceDataAccess().add_filter_by_id_vehicle(2).load() == []


def test_a_ship_names_its_maker_without_the_makers_other_ships(data):
    assert Vehicle(1, load=True).get_data_for_ai()["company"] == "Drake Interplanetary"


def test_a_ship_rented_in_many_places_lists_the_cheapest(data):
    for rental_id, price in enumerate((52920, 50274, 60000, 52920, 50000, 52920, 70000), start=2):
        data.execute(
            "INSERT INTO vehicle_rental_price (id, id_vehicle, id_terminal, price_rent) VALUES (?, 1, 1, ?)",
            (rental_id, price),
        )

    info = Vehicle(1, load=True).get_data_for_ai()

    assert [r["price_rent"] for r in info["rental_options"]] == [37485, 50000, 50274, 52920, 52920]
    assert info["rental_terminal_count"] == 8


@pytest.mark.parametrize("value, unit, expected", [
    ("242.00", "Mm/s", ("242000", "km/s")),
    ("12", "KµSCU", ("12000", "µSCU")),
    ("480", "μSCU", ("480", "µSCU")),  # the Greek letter mu
    ("250", "mRem", ("0.25", "REM")),
    ("N/A", "Mm/s", ("N/A", "Mm/s")),  # no number: left as it is
])
def test_units_are_one_per_quantity(value, unit, expected):
    row = {"value": value, "unit": unit}

    ItemAttribute.normalize_unit(row)

    assert (row["value"], row["unit"]) == expected
