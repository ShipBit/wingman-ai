"""The filter parameters of the information tools and the validator.

A review of every filter found filters that crashed, matched everything or nothing, or combined
their conditions the wrong way (OR instead of AND, per commodity instead of per price)."""

import asyncio

import pytest

from skills.uexcorp.uexcorp.tool.commodity_information import CommodityInformation
from skills.uexcorp.uexcorp.tool.item_information import ItemInformation
from skills.uexcorp.uexcorp.tool.location_information import LocationInformation, _drop_repeats, _trim_offerings
from skills.uexcorp.uexcorp.tool.validator import Validator
from tests.skills.uexcorp.support import add_terminal, parse_routes

BUY_AT_MOST_150 = [(150, "<=")]


def names(payload) -> list[str]:
    if not payload:
        return []
    data = parse_routes(payload) if isinstance(payload, str) else payload
    return sorted(entry["name"] if isinstance(entry, dict) else entry.split(" (")[0] for entry in data)


def validate(logic: str, value, multiple: bool = False, config: dict | None = None):
    return asyncio.run(Validator(logic, multiple=multiple, config=config).validate(value))


# ── Validator ───────────────────────────────────────────────────────


def test_null_values_are_rejected_without_crashing(helper):
    assert validate(Validator.VALIDATE_NUMBER, None, config={"min": 1}) is None
    assert validate(Validator.VALIDATE_BOOL, None) is None
    assert validate(Validator.VALIDATE_BOOL, 1) is None


def test_number_limits(helper):
    assert validate(Validator.VALIDATE_NUMBER, -3, config={"min": 0}) is None
    assert validate(Validator.VALIDATE_NUMBER, 0, config={"min": 0}) == 0
    assert validate(Validator.VALIDATE_NUMBER, "12", config={"min": 1}) == 12
    assert validate(Validator.VALIDATE_NUMBER, 16, config={"min": 1, "max": 15}) is None


def test_operations_are_parsed_and_malformed_ones_rejected(helper):
    def operation(value):
        return validate(Validator.VALIDATE_OPERATION_INT, value, multiple=True)

    assert operation([{"operation": ">=", "value": 100}]) == [(100, ">=")]
    assert operation([{"operation": ">=", "value": "-5"}]) == [(-5, ">=")]
    assert operation([{"operation": "<", "value": "99.5"}]) == [(99, "<")]
    assert operation([{"operation": ">=", "value": "abc"}]) is None
    assert operation([{"operation": ">="}]) is None
    assert operation(["not a dict"]) is None
    assert operation([{"operation": "~", "value": 1}]) is None


def test_a_category_is_found_by_its_own_name(db):
    for category_id, section, name in ((1, "Personal Weapons", "Personal Weapons"), (2, "Personal Weapons", "Attachments")):
        db.execute(
            "INSERT INTO category (id, type, section, name, is_game_related, combined_name) VALUES (?, 'item', ?, ?, 1, ?)",
            (category_id, section, name, f"{section} {name}"),
        )

    # Categories are "<section> <name>": "Personal Weapons" is the first, not a question to the user
    assert validate(Validator.VALIDATE_CATEGORY, "Personal Weapons") == "Personal Weapons Personal Weapons"
    assert validate(Validator.VALIDATE_CATEGORY, "attachments") == "Personal Weapons Attachments"


# ── Commodities ─────────────────────────────────────────────────────

# (terminal id, name, type, star system, planet, space station, city)
TERMINALS = [
    (1, "Term Lorville", "commodity", "Stanton", "Hurston", None, "Lorville"),
    (2, "Term MIC-L1", "commodity", "Stanton", None, "MIC-L1", None),
    (3, "Term Ruin", "commodity", "Pyro", None, "Ruin Station", None),
    (4, "Term Spaceport", "item", "Stanton", "microTech", None, None),
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


def seed_terminals(db, poi: int | None = None) -> None:
    for terminal_id, name, terminal_type, star_system, planet, space_station, city in TERMINALS:
        add_terminal(
            db, terminal_id, name, type=terminal_type, star_system_name=star_system, planet_name=planet,
            space_station_name=space_station, city_name=city, id_poi=poi if terminal_id == 4 else None,
        )


@pytest.fixture
def commodities(helper, db):
    seed_terminals(db)
    for commodity_id, name in COMMODITIES:
        db.execute(
            "INSERT INTO commodity (id, name, is_illegal, is_blacklisted, is_buyable, is_sellable) VALUES (?, ?, 0, 0, 1, 1)",
            (commodity_id, name),
        )
    for price_id, (commodity_id, terminal_id, buy, sell) in enumerate(COMMODITY_PRICES, start=1):
        db.execute(
            "INSERT INTO commodity_price (id, id_commodity, id_terminal, price_buy, price_sell) VALUES (?, ?, ?, ?, ?)",
            (price_id, commodity_id, terminal_id, buy, sell),
        )
    db.commit()

    def find(**kwargs) -> list[str]:
        payload, _instant = CommodityInformation().execute(**kwargs)
        return names(payload)
    return find


def test_blacklisted_locations_are_left_out_of_the_commodity_prices(commodities):
    assert commodities(filter_location_blacklist=["Pyro"]) == ["Gold", "Tin", "Waste"]
    assert commodities(filter_location_blacklist=["Pyro", "MIC-L1"]) == ["Tin", "Waste"]


def test_a_price_is_checked_at_the_location(commodities):
    assert commodities(filter_buy_price=BUY_AT_MOST_150) == ["Gold", "Tin", "Waste"]
    assert commodities(filter_location_whitelist=["Lorville"], filter_buy_price=BUY_AT_MOST_150) == ["Tin"]
    assert commodities(filter_location_blacklist=["Pyro"], filter_buy_price=BUY_AT_MOST_150) == ["Tin", "Waste"]


def test_buy_and_sell_prices_may_match_at_different_terminals(commodities):
    assert commodities(filter_buy_price=[(100, "<=")], filter_sell_price=[(150, ">=")]) == ["Tin"]


def test_several_profit_conditions_must_all_match(commodities):
    assert commodities(filter_profit_margin_percent=[(10, ">="), (30, "<=")]) == ["Gold"]
    assert commodities(filter_profit_margin_percent=[(30, ">=")]) == ["Tin", "Waste"]


def test_empty_lists_are_no_filter(commodities):
    assert commodities(filter_commodities=[], filter_location_whitelist=[]) == ["Gold", "Tin", "Waste"]


def test_buyable_at_a_location_means_buyable_there(commodities):
    # Ruin sells Gold and buys Tin and Waste
    assert commodities(filter_location_whitelist=["Pyro"]) == ["Gold", "Tin", "Waste"]
    assert commodities(filter_location_whitelist=["Pyro"], filter_is_buyable=True) == ["Gold"]
    assert commodities(filter_location_whitelist=["Pyro"], filter_is_sellable=True) == ["Tin", "Waste"]


# ── Items ───────────────────────────────────────────────────────────

ITEMS = [(21, "Omnisky VI Cannon"), (22, "Omnisky IX Cannon"), (23, "Arrowhead Sniper Rifle"), (24, "P4-AR Rifle")]

# (item id, attribute, value)
ITEM_ATTRIBUTES = [
    (21, "Size", "1"), (21, "Grade", "A"), (21, "Rate of Fire", "120"), (21, "Quantum Fuel Burn", "6.54"),
    (22, "Size", "1"), (22, "Grade", "B"), (22, "Rate of Fire", ""),
    (23, "Size", "2"), (23, "Grade", "A"), (23, "Rate of Fire", "N/A (Beam)"),
    (24, "Size", "1"), (24, "Grade", "A"), (24, "Rate of Fire", "600"), (24, "Quantum Fuel Burn", "6"),
]


@pytest.fixture
def items(helper, db):
    seed_terminals(db, poi=90)
    db.execute("INSERT INTO poi (id, name) VALUES (90, 'New Babbage Interstellar Spaceport')")
    for item_id, name in ITEMS:
        db.execute("INSERT INTO item (id, name) VALUES (?, ?)", (item_id, name))
    for attribute_id, (item_id, attribute, value) in enumerate(ITEM_ATTRIBUTES, start=1):
        db.execute(
            "INSERT INTO item_attribute (id, id_item, attribute_name, value) VALUES (?, ?, ?, ?)",
            (attribute_id, item_id, attribute, value),
        )
    db.execute("INSERT INTO item_price (id, id_item, id_terminal, terminal_name, price_buy) VALUES (1, 23, 4, 'Term Spaceport', 5000)")
    db.execute("INSERT INTO item_price (id, id_item, id_terminal, terminal_name, price_buy) VALUES (2, 24, 4, 'Term Spaceport', NULL)")
    db.commit()

    def find(**kwargs) -> list[str]:
        payload, _instant = ItemInformation().execute(**kwargs)
        return names(payload)
    return find


def attribute(name: str, operator: str, value: str) -> dict:
    return {"attribute": name, "operator": operator, "value": value}


def test_a_name_search_needs_all_words_of_a_term(items):
    assert items(filter_name_search=["Omnisky "]) == ["Omnisky IX Cannon", "Omnisky VI Cannon"]
    assert items(filter_name_search=["Arrowhead  Sniper"]) == ["Arrowhead Sniper Rifle"]
    assert items(filter_name_search=["P4-AR"]) == ["P4-AR Rifle"]
    assert items(filter_name_search=["Omnisky VI", "P4-AR"]) == ["Omnisky VI Cannon", "P4-AR Rifle"]


def test_a_numeric_attribute_ignores_values_that_are_no_numbers_and_keeps_decimals(items):
    assert items(filter_attribute=[attribute("Rate of Fire", "<", "200")]) == ["Omnisky VI Cannon"]
    assert items(filter_attribute=[attribute("Quantum Fuel Burn", ">", "6")]) == ["Omnisky VI Cannon"]
    assert items(filter_attribute=[attribute("Quantum Fuel Burn", "<", "6.5")]) == ["P4-AR Rifle"]


def test_several_attributes_must_all_match(items):
    both = [attribute("Size", "=", "1"), attribute("Grade", "=", "A")]

    assert items(filter_attribute=both) == ["Omnisky VI Cannon", "P4-AR Rifle"]


def test_a_buy_location_matches_the_poi_and_needs_a_price(items):
    assert items(filter_buy_location=["New Babbage Interstellar Spaceport"]) == ["Arrowhead Sniper Rifle"]


# ── Locations ───────────────────────────────────────────────────────


@pytest.fixture
def locations(helper, db):
    for station_id, name in ((1, "Everus Harbor"), (2, "Baijini Point"), (3, "Pyro Gateway (Stanton)")):
        db.execute(
            "INSERT INTO space_station (id, name, star_system_name, is_available) VALUES (?, ?, 'Stanton', 1)",
            (station_id, name),
        )
    db.commit()

    def find(**kwargs) -> list[str]:
        payload, _instant = LocationInformation().execute(**kwargs)
        return names(payload)
    return find


def test_space_stations_and_gateways_can_be_asked_for_together(locations):
    assert locations(filter_locations=["Stanton"], filter_location_types=["space_station", "gateway"]) == [
        "Baijini Point", "Everus Harbor", "Pyro Gateway (Stanton)",
    ]
    assert locations(filter_locations=["Stanton"], filter_location_types=["gateway"]) == ["Pyro Gateway (Stanton)"]


def test_a_shared_parent_is_given_in_full_once():
    moon = {"name": "Daymar", "outposts": ["Kudre Ore", "Jumptown"]}

    results = _drop_repeats([
        {"name": "Kudre Ore", "located_at": dict(moon)},
        {"name": "Jumptown", "located_at": dict(moon)},
        {"name": "Lorville", "located_at": {"name": "Hurston"}},
    ])

    assert [r["located_at"] for r in results] == [moon, "Daymar", {"name": "Hurston"}]


def test_several_terminals_show_their_first_offerings():
    results = [{"name": "CBD", "offerings": {"commodity": list(range(30)), "item": [1, 2]}}, {"name": "Lorville", "offerings": ["Refuel"]}]

    assert _trim_offerings(results, 10)

    assert results[0]["offerings"] == {"commodity": list(range(10)), "commodity_count": 30, "item": [1, 2]}
    assert results[1]["offerings"] == ["Refuel"]  # a city's offerings are a list of services
