"""The container sizes of uex_get_trade_routes.

A ship whose largest container is 4 SCU can't trade at a terminal whose smallest container is
8 SCU, so those routes are dropped when a used_ship is given. Unknown sizes must never hide a route."""

import pytest

from skills.uexcorp.uexcorp.model.commodity_route import CommodityRoute as CommodityRouteModel
from skills.uexcorp.uexcorp.model.vehicle import Vehicle
from tests.skills.uexcorp.support import add_route, first_buys, route_pairs, search

# (route id, origin name, destination name, smallest container origin, smallest container destination)
ROUTES = [
    (201, "Small Origin", "Small Destination", 1, 1),
    (202, "Large Origin", "Small Destination", 8, 1),
    (203, "Small Origin", "Large Destination", 1, 8),
    (204, "Unknown Origin", "Unknown Destination", None, None),
    (205, "Medium Origin", "Medium Destination", 4, 4),
]
STARLIFTER = "Crusader C2 Hercules Starlifter"
TITAN = "Aegis Avenger Titan"


@pytest.fixture
def market(db):
    for route_id, origin, destination, min_origin, min_destination in ROUTES:
        add_route(
            db, route_id, id_terminal_origin=route_id * 10, id_terminal_destination=route_id * 10 + 1,
            origin_terminal_name=origin, destination_terminal_name=destination,
            price_origin=10, price_destination=20, scu_origin=8, scu_destination=8, profit=80, score=50, distance=1,
            container_size_min_origin=min_origin, container_size_min_destination=min_destination,
        )
    db.execute(
        """
        INSERT INTO vehicle (id, name_full, is_loading_dock, scu, container_sizes) VALUES
            (1, 'Aegis Avenger Titan', 0, 8, '1,2,4'),
            (2, 'Crusader C2 Hercules Starlifter', 0, 696, '1,2,4,8,16,24,32'),
            (3, 'MISC Hull D', 0, 6912, ''),
            (4, 'Origin 600i Executive Edition', 0, 40, NULL),
            (5, 'Anvil Hornet', 0, NULL, NULL)
        """
    )
    db.commit()


def test_the_smallest_container_of_a_terminal_and_the_largest_of_a_ship_are_derived_from_the_lists(db, market):
    route = CommodityRouteModel(1)
    route.set_data({"container_sizes_origin": "16,8,32", "container_sizes_destination": "1,2,4,8,16"})
    assert (route.get_container_size_min_origin(), route.get_container_size_min_destination()) == (8, 1)
    route.set_data({"container_sizes_origin": "", "container_sizes_destination": None})
    assert route.get_container_size_min_origin() is None
    assert route.get_container_size_min_destination() is None

    assert Vehicle(1, load=True).get_max_container_size() == 4
    assert Vehicle(2, load=True).get_max_container_size() == 32
    assert Vehicle(3, load=True).get_max_container_size() is None
    assert Vehicle(4, load=True).get_max_container_size() is None


def test_a_small_ship_drops_routes_with_larger_minimum_containers(helper, market):
    pairs = route_pairs(search(helper, used_ship=TITAN))

    assert pairs == {
        ("Small Origin", "Small Destination"),
        ("Unknown Origin", "Unknown Destination"),
        ("Medium Origin", "Medium Destination"),
    }
    assert not any("container" in note for note in helper.notes)  # every route found fits: nothing to check


def test_the_container_limit_is_only_mentioned_when_no_route_fits(helper, db, market):
    db.execute(
        "DELETE FROM commodity_route WHERE COALESCE(container_size_min_origin, 0) <= 4 "
        "AND COALESCE(container_size_min_destination, 0) <= 4"
    )
    db.commit()

    assert search(helper, used_ship=TITAN) == []

    assert any("No route found" in note and "up to 4 SCU" in note for note in helper.notes)


def test_a_buy_names_the_largest_container_the_sell_terminal_takes(helper, db, market):
    # The ship and the buy terminal go up to 32 SCU, the sell terminal only to 24: 32 SCU boxes would be stuck
    db.execute(
        "UPDATE commodity_route SET container_sizes_origin = '1,2,4,8,16,24,32', "
        "container_sizes_destination = '1,2,4,8,16,24' WHERE id = 201"
    )
    db.execute(
        "UPDATE commodity_route SET container_sizes_origin = '1,2,4,8,16,24,32', "
        "container_sizes_destination = '8,16,24,32' WHERE id = 205"
    )
    # The buy terminal itself only has 16 SCU boxes: no choice to make
    db.execute(
        "UPDATE commodity_route SET container_sizes_origin = '1,2,4,8,16', "
        "container_sizes_destination = '1,2,4,8,16,24,32' WHERE id = 203"
    )
    db.commit()

    buys = {route["path"]: first_buys(route)[0] for route in search(helper, used_ship=STARLIFTER)}

    assert buys["Small Origin -> Small Destination"].get("container_note") == (
        "Buy it in containers of at most 24 SCU: Small Destination, where you sell it, takes no bigger ones."
    )
    # The buy terminal is the limit itself, or 32 SCU fits everywhere: nothing to choose, nothing to say
    assert "container_note" not in buys["Small Origin -> Large Destination"]
    assert "container_note" not in buys["Medium Origin -> Medium Destination"]

    # A small ship is the limit: it names the ship, not a terminal
    buys = {route["path"]: first_buys(route)[0] for route in search(helper, used_ship=TITAN)}
    assert buys["Small Origin -> Small Destination"].get("container_note") == (
        "Buy it in containers of at most 4 SCU: bigger ones don't fit the Aegis Avenger Titan."
    )


def test_a_ship_without_cargo_data_uses_the_cargo_space_given_or_asks(helper, market):
    # No SCU in UEX used to force cargo 0, even over cargo space the user gave
    assert search(helper, used_ship="Anvil Hornet", available_cargo_space_scu=4)

    assert search(helper, used_ship="Anvil Hornet") == []
    assert any("no cargo capacity" in note and "Anvil Hornet" in note for note in helper.notes)


@pytest.mark.parametrize("ship", ["MISC Hull D", "Origin 600i Executive Edition"], ids=["empty list", "no list"])
def test_a_ship_without_container_data_is_not_filtered(helper, market, ship):
    assert route_pairs(search(helper, used_ship=ship)) == route_pairs(search(helper))
    assert not any("container" in note for note in helper.notes)
