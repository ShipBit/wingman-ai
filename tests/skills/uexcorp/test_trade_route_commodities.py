"""Illegal and blacklisted commodities in uex_get_trade_routes.

Routes are derived from all prices, so they include illegal commodities. By default they stay in
the results, but every route carrying one must say so clearly, so the AI never suggests contraband
without a warning. filter_allow_illegal_commodities false removes them; commodities blacklisted in
the skill config are never traded."""

import pytest

from skills.uexcorp.uexcorp.tool.commodity_route import CommodityRoute
from tests.skills.uexcorp.support import add_route, add_terminal, bought, search

TERMINALS = {1: "Term A", 2: "Term B", 3: "Term C"}

# (commodity id, name, is_illegal, is_blacklisted)
COMMODITIES = [(11, "Xenon", 0, 0), (12, "WiDoW", 1, 0), (13, "Gold", 0, 1)]

# (route id, commodity id, origin, destination, buy, sell, stock, demand)
LEGS = [
    (1, 11, 1, 2, 10, 20, 1000, None),  # legal: 10/SCU
    (2, 12, 1, 3, 10, 50, 1000, None),  # illegal: 40/SCU, best legal-or-not option
    (3, 13, 1, 2, 10, 90, 1000, None),  # blacklisted: 80/SCU, must never show up
    (4, 12, 2, 3, 10, 60, 0, None),  # illegal, no stock left: only a note
]


@pytest.fixture
def market(db):
    for terminal_id, name in TERMINALS.items():
        add_terminal(db, terminal_id, name, star_system_name="Stanton")
    names = {}
    for commodity_id, name, is_illegal, is_blacklisted in COMMODITIES:
        names[commodity_id] = name
        db.execute(
            "INSERT INTO commodity (id, name, is_illegal, is_blacklisted) VALUES (?, ?, ?, ?)",
            (commodity_id, name, is_illegal, is_blacklisted),
        )
    for route_id, commodity_id, origin, destination, buy, sell, stock, demand in LEGS:
        add_route(
            db, route_id, id_commodity=commodity_id, commodity_name=names[commodity_id],
            id_terminal_origin=origin, id_terminal_destination=destination,
            origin_terminal_name=TERMINALS[origin], destination_terminal_name=TERMINALS[destination],
            price_origin=buy, price_destination=sell, scu_origin=stock, scu_destination=demand,
        )
    db.commit()


def test_illegal_commodities_stay_in_the_results_with_warnings(helper, market):
    routes = search(helper, available_cargo_space_scu=10)

    illegal_route = next(route for route in routes if "WiDoW" in bought(route))
    assert next(iter(illegal_route)) == "warning"  # first key, names the commodity
    assert "illegal" in illegal_route["warning"]
    assert "WiDoW" in illegal_route["warning"]
    assert illegal_route["illegal_commodities"] == ["WiDoW"]
    buy = next(buy for stop in illegal_route["stops"] for buy in stop.get("buy", []) if buy["commodity"] == "WiDoW")
    assert buy["warnings"][0] == CommodityRoute.ILLEGAL_WARNING
    # A note for the user, with how to get legal routes only
    note = next(note for note in helper.notes if note.startswith("Routes include illegal commodities"))
    assert "WiDoW" in note
    assert "filter_allow_illegal_commodities" in note
    # Legal routes carry no warning
    legal_route = next(route for route in routes if bought(route) == {"Xenon"})
    assert "warning" not in legal_route
    assert "illegal_commodities" not in legal_route
    assert CommodityRoute.ILLEGAL_WARNING not in legal_route["stops"][0]["buy"][0].get("warnings", [])
    # The commodity without stock is only a note, and that warns as well
    note = next(note for note in helper.notes if note.startswith("Normally WiDoW"))
    assert CommodityRoute.ILLEGAL_WARNING in note


def test_a_multi_stop_route_with_an_illegal_leg_is_marked(helper, market):
    routes = search(helper, available_cargo_space_scu=10, max_stops=2)

    marked = [route for route in routes if "WiDoW" in bought(route)]
    assert marked
    assert all(route["illegal_commodities"] == ["WiDoW"] for route in marked)


def test_the_filter_removes_illegal_commodities(helper, market):
    routes = search(helper, available_cargo_space_scu=10, filter_allow_illegal_commodities=False)

    assert routes
    assert all("WiDoW" not in bought(route) for route in routes)
    assert not any("illegal" in note.lower() for note in helper.notes)


@pytest.mark.parametrize("kwargs", [{}, {"max_stops": 3}], ids=["one hop", "planned stops"])
def test_blacklisted_commodities_are_never_traded(helper, market, kwargs):
    routes = search(helper, available_cargo_space_scu=10, **kwargs)

    assert routes
    assert all("Gold" not in bought(route) for route in routes)
