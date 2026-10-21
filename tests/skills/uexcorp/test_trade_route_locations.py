"""Where uex_get_trade_routes may go: blacklisted locations, star systems and system jumps.

More than one blacklisted location crashed with "row value misused". With one location, terminals
with any empty location column (NULL != x is NULL in SQL) fell out of the "not blacklisted" set,
and routes excluded that set instead of the blacklisted terminals, so blacklisted terminals still
showed up in routes. Routes also crossed systems without saying so."""

import pytest

from skills.uexcorp.uexcorp.data_access.terminal_data_access import TerminalDataAccess
from tests.skills.uexcorp.support import add_route, add_terminal, search, stop_names

# (terminal id, name, star system, planet, space station, city)
TERMINALS = [
    (1, "Term Lorville", "Stanton", "Hurston", None, "Lorville"),
    (2, "Term Ruin", "Pyro", "Pyro V", "Ruin Station", None),
    (3, "Term Everus", "Stanton", "Hurston", "Everus Harbor", None),
    (4, "Term Levski", "Nyx", "Delamar", None, "Levski"),
]
NAMES = {terminal[0]: terminal[1] for terminal in TERMINALS}
SYSTEMS = {terminal[0]: terminal[2] for terminal in TERMINALS}

# (route id, origin, destination, buy, sell)
LEGS = [
    (1, 1, 2, 10, 90),  # best margin, but into Pyro
    (2, 2, 4, 10, 80),  # out of Pyro
    (3, 1, 3, 10, 30),
    (4, 3, 4, 10, 40),
]


@pytest.fixture
def market(db):
    for terminal_id, name, star_system, planet, space_station, city in TERMINALS:
        add_terminal(
            db, terminal_id, name, star_system_name=star_system, planet_name=planet,
            space_station_name=space_station, city_name=city,
        )
    db.execute("INSERT INTO commodity (id, name, is_illegal, is_blacklisted) VALUES (11, 'Tin', 0, 0)")
    for route_id, origin, destination, buy, sell in LEGS:
        add_route(
            db, route_id, id_commodity=11, commodity_name="Tin", id_terminal_origin=origin, id_terminal_destination=destination,
            origin_terminal_name=NAMES[origin], destination_terminal_name=NAMES[destination],
            origin_star_system_name=SYSTEMS[origin], destination_star_system_name=SYSTEMS[destination],
            price_origin=buy, price_destination=sell, scu_origin=1000, scu_destination=None,
        )
    db.commit()


def used_terminals(routes: list[dict]) -> set[str]:
    return set().union(*(set(stop_names(route)) | set(route.get("last_sale_also_at", [])) for route in routes))


def not_blacklisted(locations) -> set[int]:
    data_access = TerminalDataAccess()
    data_access.add_filter_by_location_name_blacklist(locations)
    return {terminal.get_id() for terminal in data_access.load()}


def test_the_terminal_filter_keeps_terminals_with_empty_location_columns(market):
    assert not_blacklisted(["Pyro"]) == {1, 3, 4}


def test_the_terminal_filter_takes_several_locations_or_a_single_name(market):
    assert not_blacklisted(["Pyro", "Terminus", "Ruin Station"]) == {1, 3, 4}
    assert not_blacklisted(["Lorville", "Everus Harbor"]) == {2, 4}
    assert not_blacklisted("Nyx") == {1, 2, 3}


def test_a_blacklisted_location_keeps_the_other_terminals_in_the_routes(helper, market):
    assert "Term Ruin" in used_terminals(search(helper, available_cargo_space_scu=10, max_stops=3))  # the control

    routes = search(helper, available_cargo_space_scu=10, max_stops=1, filter_location_blacklist=["Pyro"])

    assert used_terminals(routes) == {"Term Lorville", "Term Everus", "Term Levski"}


@pytest.mark.parametrize("max_stops", [1, 3])
def test_several_blacklisted_locations_keep_their_terminals_out_of_the_routes(helper, market, max_stops):
    blacklist = ["Pyro", "Terminus", "Ruin Station"]

    routes = search(helper, available_cargo_space_scu=10, max_stops=max_stops, filter_location_blacklist=blacklist)

    assert routes
    assert "Term Ruin" not in used_terminals(routes)


def test_the_star_system_whitelist_keeps_every_stop_in_those_systems(helper, market):
    routes = search(helper, available_cargo_space_scu=10, max_stops=3, filter_star_system_whitelist=["Stanton", "Nyx"])

    assert used_terminals(routes) == {"Term Lorville", "Term Everus", "Term Levski"}


# ── System jumps ────────────────────────────────────────────────────

S1, S2, N1, P1 = 11, 12, 13, 14


@pytest.fixture
def systems(db):
    """Stanton links to Nyx and Pyro, Nyx and Pyro only through Stanton."""
    for system_id, name in ((1, "Stanton"), (2, "Nyx"), (3, "Pyro")):
        db.execute("INSERT INTO star_system (id, name, is_available) VALUES (?, ?, 1)", (system_id, name))
    for orbit_id, name, system_id, system in (
        (21, "Nyx Gateway (Stanton system)", 1, "Stanton"),
        (22, "Stanton Gateway (Nyx system)", 2, "Nyx"),
        (23, "Pyro Gateway (Stanton system)", 1, "Stanton"),
        (24, "Stanton Gateway (Pyro system)", 3, "Pyro"),
    ):
        db.execute(
            "INSERT INTO orbit (id, name, id_star_system, star_system_name, is_jump_point) VALUES (?, ?, ?, ?, 1)",
            (orbit_id, name, system_id, system),
        )
    names = {S1: "Stanton One", S2: "Stanton Two", N1: "Nyx One", P1: "Pyro One"}
    in_system = {S1: "Stanton", S2: "Stanton", N1: "Nyx", P1: "Pyro"}
    for terminal_id, name in names.items():
        add_terminal(db, terminal_id, name)
    for route_id, (origin, destination, sell) in enumerate(((S1, S2, 12), (S1, N1, 30), (P1, N1, 40)), start=101):
        add_route(
            db, route_id, id_terminal_origin=origin, id_terminal_destination=destination,
            origin_terminal_name=names[origin], destination_terminal_name=names[destination],
            origin_star_system_name=in_system[origin], destination_star_system_name=in_system[destination],
            price_origin=10, price_destination=sell, scu_origin=100, scu_destination=100, distance=5,
        )
    db.commit()


def jumps(helper, **kwargs) -> dict[tuple[str, ...], int]:
    routes = search(helper, available_cargo_space_scu=10, **kwargs)
    return {tuple(stop_names(route)): route["system_jumps"] for route in routes}


def test_every_route_says_its_system_jumps(helper, systems):
    assert jumps(helper) == {
        ("Stanton One", "Stanton Two"): 0,
        ("Stanton One", "Nyx One"): 1,
        ("Pyro One", "Nyx One"): 2,  # no direct jump: through Stanton
    }


def test_max_system_jumps_limits_the_whole_route(helper, systems):
    assert set(jumps(helper, max_system_jumps=0)) == {("Stanton One", "Stanton Two")}
    assert set(jumps(helper, max_system_jumps=1)) == {("Stanton One", "Stanton Two"), ("Stanton One", "Nyx One")}


def test_a_route_starts_with_a_summary_and_ends_with_the_stops(helper, systems):
    route = search(helper, available_cargo_space_scu=10, filter_start_location="Pyro One")[0]

    assert route["path"] == "Pyro One -> Nyx One"
    assert route["systems"] == "Pyro -> Nyx"
    assert route["main_cargo"] == ["Laranite"]
    assert list(route)[-1] == "stops"
    # Totals are what the user hears, the price per SCU stays for questions
    assert route["stops"][0]["buy"][0]["total_aUEC"] == 100
    assert route["stops"][1]["sell"][0]["total_aUEC"] == 400


