"""Multi-stop and circular routes of uex_get_trade_routes.

The tool plans routes itself from the derived trade legs: max_stops allows several stops with buying
and selling at each, return_to_start asks for circular routes, and the start location limits where a
route begins, not every hop of it. Planner details are covered in test_route_planner."""

import pytest

from tests.skills.uexcorp.support import add_route, add_terminal, search, stop_names

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


@pytest.fixture
def market(db):
    for terminal_id, name in TERMINALS.items():
        add_terminal(db, terminal_id, name, star_system_name="Stanton")
    for index, (commodity_id, commodity, origin, destination, buy, sell, stock) in enumerate(LEGS, start=1):
        add_route(
            db, index, id_commodity=commodity_id, commodity_name=commodity,
            id_terminal_origin=origin, id_terminal_destination=destination,
            origin_terminal_name=TERMINALS[origin], destination_terminal_name=TERMINALS[destination],
            price_origin=buy, price_destination=sell, scu_origin=stock,
        )
    db.commit()


def plan(helper, ranking: str = "total_profit", **kwargs) -> list[dict]:
    helper.get_handler_config().ranking = ranking
    return search(helper, available_cargo_space_scu=10, **kwargs)


def test_a_multi_stop_route_buys_and_sells_along_the_way_and_adds_up(helper, market):
    route = next(route for route in plan(helper, max_stops=3) if route.get("stop_count") == 3)

    assert len(route["stops"]) == 4
    assert "buy" in route["stops"][0]
    assert "sell" in route["stops"][-1]
    sold = sum(sale["scu"] * sale["price_per_scu"] for stop in route["stops"] for sale in stop.get("sell", []))
    spent = sum(buy["scu"] * buy["price_per_scu"] for stop in route["stops"] for buy in stop.get("buy", []))
    assert route["estimated_profit"] == sold - spent


def test_total_profit_ranks_the_best_route_first(helper, market):
    routes = plan(helper, max_stops=3)

    profits = [route["estimated_profit"] for route in routes]
    assert profits == sorted(profits, reverse=True)
    assert stop_names(routes[0]) == ["Term A", "Term B", "Term C", "Term D"]
    assert routes[0]["estimated_profit"] == 350


def test_cargo_carried_past_a_stop_says_where_it_is_sold(helper, market):
    routes = plan(helper, max_stops=2, filter_start_location="Term A", filter_destination_location="Term C")

    route = next(route for route in routes if stop_names(route) == ["Term A", "Term B", "Term C"])
    gold = next(buy for buy in route["stops"][0]["buy"] if buy["commodity"] == "Gold")
    assert gold["sell_at"] == "Term C"
    assert route["stops"][2]["sell"][0]["commodity"] == "Gold"


def test_circular_routes_return_to_the_start(helper, market):
    routes = plan(helper, max_stops=3, return_to_start=True)

    assert routes
    for route in routes:
        assert stop_names(route)[0] == stop_names(route)[-1]
        assert route["circular"]


def test_the_start_location_limits_the_first_stop_only(helper, market):
    routes = plan(helper, max_stops=3, filter_start_location="Term B")

    assert routes
    assert all(stop_names(route)[0] == "Term B" for route in routes)
    assert any(len(route["stops"]) > 2 for route in routes)


def test_a_note_says_when_fewer_stops_rank_better(helper, market):
    # Per stop, A -> C with Gold (150 for 1 stop) beats every longer route
    routes = plan(helper, "profit_per_stop", max_stops=3)
    assert stop_names(routes[0]) == ["Term A", "Term C"]
    assert any("fewer than 3 stops" in note for note in helper.notes), helper.notes

    # By total profit the 3-stop route wins, nothing to explain
    routes = plan(helper, "total_profit", max_stops=3)
    assert routes[0]["stop_count"] == 3
    assert not any("fewer than" in note for note in helper.notes), helper.notes


def test_an_unknown_start_location_returns_a_note(helper, market):
    assert plan(helper, filter_start_location="Nowhere") == []

    assert any("Nowhere" in note for note in helper.notes), helper.notes
