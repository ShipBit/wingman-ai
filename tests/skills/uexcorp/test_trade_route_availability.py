"""Stock and demand in uex_get_trade_routes ("Use Estimated Availability").

With the switch on, the traded volume is capped by the stock at the origin and the demand at the
destination, and a route with zero of either is no real option: it is mentioned as a note instead
("Normally X would be a good option, but ..."). Unknown stock or demand counts as available. With
the switch off only cargo space and budget limit the volume."""

import pytest

from tests.skills.uexcorp.support import add_route, add_terminal, buy_volume, first_buys, route_pairs, search, volume_note

CUTLASS = "Drake Cutlass Black"

# (route id, commodity, origin, destination, price origin, price destination, stock origin, demand destination)
ROUTES = [
    (1, "Gold", "Empty Origin", "Gold Buyer", 100, 200, 0, 500),  # best, but no stock
    (2, "Iron", "Iron Mine", "Iron Buyer", 10, 20, 500, 500),  # 10/SCU
    (3, "Tin", "Tin Mine", "Full Buyer", 10, 15, 500, 0),  # 5/SCU, but no demand
    (4, "Ice", "Ice Field", "Ice Buyer", 10, 11, None, None),  # 1/SCU, unknown availability
]


@pytest.fixture
def one_route(db):
    """10 SCU in stock at the origin, 5 SCU demand at the destination, 10 aUEC profit per SCU."""
    add_route(
        db, 1, id_terminal_origin=10, id_terminal_destination=11, origin_terminal_name="Origin TDD",
        destination_terminal_name="Destination TDD", price_origin=10, price_destination=20,
        scu_origin=10, scu_destination=5, profit=50, score=50, distance=1,
    )
    db.execute("INSERT INTO vehicle (id, name_full, is_loading_dock, scu) VALUES (1, 'Drake Cutlass Black', 0, 46)")
    db.commit()


@pytest.fixture
def market(db):
    for route_id, commodity, origin, destination, buy, sell, stock, demand in ROUTES:
        add_terminal(db, route_id * 10, origin)
        add_terminal(db, route_id * 10 + 1, destination)
        add_route(
            db, route_id, commodity_name=commodity, id_terminal_origin=route_id * 10, id_terminal_destination=route_id * 10 + 1,
            origin_terminal_name=origin, destination_terminal_name=destination, price_origin=buy, price_destination=sell,
            scu_origin=stock, scu_destination=demand, score=50, distance=1,
        )
    db.execute("INSERT INTO vehicle (id, name_full, is_loading_dock, scu) VALUES (1, 'Drake Cutlass Black', 0, 46)")
    db.commit()


def only_route(helper, use_estimated_availability: bool, **kwargs) -> dict:
    helper.get_handler_config().use_estimated_availability = use_estimated_availability
    routes = search(helper, **kwargs)
    assert len(routes) == 1
    return routes[0]


def test_stock_and_demand_cap_the_volume(helper, one_route):
    route = only_route(helper, True, used_ship=CUTLASS)

    assert buy_volume(route) == 5
    assert route["estimated_profit"] == 50


def test_with_the_switch_off_only_cargo_space_and_money_limit_the_volume(helper, one_route):
    route = only_route(helper, False, used_ship=CUTLASS)
    assert (buy_volume(route), route["estimated_profit"]) == (46, 460)
    assert volume_note(route) is None

    # Only one limit left: must not become SQLite's aggregate MIN()
    route = only_route(helper, False, available_money=300)
    assert (buy_volume(route), route["estimated_profit"]) == (30, 300)


@pytest.mark.parametrize("stock, demand, kwargs, volume, instead_of, where", [
    (10, 5, {"used_ship": CUTLASS}, 5, 46, "sell location"),
    (3, 20, {"used_ship": CUTLASS}, 3, 46, "buy location"),
    (7, 7, {"available_money": 1000}, 7, 100, "sell and buy location"),
])
def test_the_note_names_the_location_that_caps_the_volume(helper, db, one_route, stock, demand, kwargs, volume, instead_of, where):
    db.execute("UPDATE commodity_route SET scu_origin = ?, scu_destination = ? WHERE id = 1", (stock, demand))
    db.commit()

    route = only_route(helper, True, **kwargs)

    assert buy_volume(route) == volume
    assert volume_note(route) == f"SCU count limited to {volume} (instead of {instead_of}) by estimated availability at {where}."


def test_no_note_when_the_budget_or_the_space_is_the_limit(helper, one_route):
    route = only_route(helper, True, available_cargo_space_scu=4)

    assert buy_volume(route) == 4
    assert volume_note(route) is None


def normally_notes(helper) -> list[str]:
    return [note for note in helper.notes if note.startswith("Normally")]


def test_routes_without_stock_or_demand_are_no_options_but_are_mentioned(helper, market):
    routes = search(helper, used_ship=CUTLASS, limit=4)

    assert route_pairs(routes) == {("Iron Mine", "Iron Buyer"), ("Ice Field", "Ice Buyer")}
    notes = normally_notes(helper)
    assert len(notes) == 2  # fewer real routes than requested: every good route without availability is mentioned
    assert (
        "Normally Gold from Empty Origin to Gold Buyer would be a good option "
        "(about 4600 aUEC profit for 46 SCU), but UEX data shows no stock left to buy at Empty Origin."
    ) in notes
    assert any("no demand left at Full Buyer" in note for note in notes)


def test_unknown_availability_neither_hides_nor_caps(helper, market):
    routes = search(helper, used_ship=CUTLASS, limit=4)

    ice = next(route for route in routes if first_buys(route)[0]["commodity"] == "Ice")
    assert buy_volume(ice) == 46
    assert ice["estimated_profit"] == 46


def test_only_routes_that_would_have_ranked_are_mentioned(helper, market):
    # Shown: Iron (460). Gold (4600) would have beaten it, Tin (230) would not.
    routes = search(helper, used_ship=CUTLASS, limit=1)

    assert route_pairs(routes) == {("Iron Mine", "Iron Buyer")}
    notes = normally_notes(helper)
    assert len(notes) == 1
    assert "Gold" in notes[0]


def test_the_notes_respect_the_start_and_destination(helper, market):
    # Gold (no stock at Empty Origin) would be the best route, but the user starts at Iron Mine
    routes = search(helper, used_ship=CUTLASS, limit=4, filter_start_location="Iron Mine")
    assert route_pairs(routes) == {("Iron Mine", "Iron Buyer")}
    assert normally_notes(helper) == []

    assert search(helper, used_ship=CUTLASS, limit=4, filter_destination_location="Gold Buyer") == []
    assert len(normally_notes(helper)) == 1
    assert "Gold" in normally_notes(helper)[0]


def test_with_the_switch_off_the_routes_stay_and_no_note_is_given(helper, market):
    helper.get_handler_config().use_estimated_availability = False

    routes = search(helper, used_ship=CUTLASS, limit=1)

    assert route_pairs(routes) == {("Empty Origin", "Gold Buyer")}
    assert normally_notes(helper) == []


def test_only_routes_without_availability_left(helper, db, market):
    db.execute("UPDATE commodity_route SET scu_origin = 0 WHERE id IN (2, 4)")
    db.commit()

    assert search(helper, used_ship=CUTLASS, limit=2) == []

    assert len(normally_notes(helper)) == 3
