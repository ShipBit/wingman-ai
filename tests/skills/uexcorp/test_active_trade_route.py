"""The active trade route (uex_active_trade_route) and its HUD panel.

A multi-stop run spans many turns. Core clears old tool responses once the history gets long, so the
Wingman lost the later stops. The route and the stop the player is at now live in a file, and the
Wingman (not a setting) decides what the HUD shows."""

import asyncio
import os
from types import SimpleNamespace

import pytest

from skills.uexcorp.uexcorp.active_trade_route import HUD_TITLE, ActiveTradeRoute as Store
from skills.uexcorp.uexcorp.tool.active_trade_route import ActiveTradeRoute
from tests.skills.uexcorp.support import add_route, add_terminal, parse_routes, search

S1, S2, N1 = 11, 12, 13


@pytest.fixture
def market(db):
    """Stanton One -> Stanton Two -> Nyx One beats the direct hop per stop; Gold is short at Stanton Two."""
    names = {S1: "Stanton One", S2: "Stanton Two", N1: "Nyx One"}
    systems = {S1: "Stanton", S2: "Stanton", N1: "Nyx"}
    for terminal_id, name in names.items():
        add_terminal(db, terminal_id, name)
    for route_id, (commodity, origin, destination, buy, sell, stock) in enumerate((
        ("Laranite", S1, S2, 10, 12, 100),
        ("Laranite", S1, N1, 10, 30, 100),
        ("Gold", S2, N1, 10, 60, 4),
        ("Tin", S2, N1, 10, 50, 100),
    ), start=101):
        add_route(
            db, route_id, id_commodity=route_id, commodity_name=commodity, id_terminal_origin=origin,
            id_terminal_destination=destination, origin_terminal_name=names[origin], destination_terminal_name=names[destination],
            origin_star_system_name=systems[origin], destination_star_system_name=systems[destination],
            price_origin=buy, price_destination=sell, scu_origin=stock, scu_destination=100, distance=5,
        )
    db.commit()


def find_routes(helper, **kwargs) -> list[dict]:
    return search(helper, **{
        "filter_start_location": "Stanton One", "filter_destination_location": "Nyx One",
        "max_stops": 2, "available_cargo_space_scu": 10, "limit": 2, **kwargs,
    })


def act(**kwargs) -> dict:
    response, _instant = asyncio.run(ActiveTradeRoute().execute(**kwargs))
    try:
        return parse_routes(response)
    except ValueError:
        return {"text": response}


def stored_route(helper) -> dict:
    return Store(helper).get()["route"]


def test_the_run_walks_the_route_stop_by_stop(helper, market):
    assert [route["route_number"] for route in find_routes(helper)] == [1, 2]

    first = act(action="set", route_number=1)
    assert (first["step"], first["step_count"]) == (1, 3)
    assert first["current_stop"]["terminal"] == "Stanton One"
    assert first["next_stop"] == "Stanton Two"
    assert not first["shown_on_hud"]

    second = act(action="next")
    assert second["current_stop"]["terminal"] == "Stanton Two"
    assert second["cargo_aboard_on_arrival"] == [{"commodity": "Laranite", "scu": 10}]
    find_routes(helper)  # a new search does not touch the run, and a fresh store reads the same file
    assert act(action="get")["step"] == 2

    act(action="next")
    assert act(action="next")["route_complete"]
    assert Store(helper).get() is None


def test_a_stop_number_jumps_and_clear_ends_the_run(helper, market):
    find_routes(helper)
    act(action="set", route_number=1)

    assert act(action="get", stop_number=3)["current_stop"]["terminal"] == "Nyx One"
    assert "there is no stop 9" in act(action="get", stop_number=9)["text"]  # a mistake, not the end of the run
    assert act(action="get")["current_stop"]["terminal"] == "Nyx One"
    assert "removed" in act(action="clear")["text"]
    assert "No active trade route" in act(action="get")["text"]


def test_an_unknown_route_number_says_how_many_there_are(helper, market):
    find_routes(helper)

    assert "2 route(s)" in act(action="set", route_number=5)["text"]


def test_a_route_file_of_another_shape_counts_as_no_route(helper):
    with open(os.path.join(helper.get_data_path(), Store.FILE_NAME), "w", encoding="utf-8") as file:
        file.write("[]")

    assert "No active trade route" in act(action="get")["text"]
    assert "There was no active trade route" in act(action="clear")["text"]


def test_the_hud_is_switched_by_the_tool_and_follows_the_cursor(helper, market):
    panels = helper.wingman.hud.panels
    find_routes(helper)
    act(action="set", route_number=1)
    assert HUD_TITLE not in panels

    act(action="show_hud")
    assert "Stop 1 of 3 ·" in panels[HUD_TITLE]
    assert act(action="next")["shown_on_hud"]
    assert "Stop 2 of 3 ·" in panels[HUD_TITLE]

    act(action="hide_hud")
    assert HUD_TITLE not in panels
    act(action="show_hud")
    act(action="clear")
    assert HUD_TITLE not in panels


def test_show_hud_says_so_when_the_hud_is_off(helper, market):
    find_routes(helper)
    act(action="set", route_number=1)
    helper.wingman.hud.info_enabled = False

    assert "The HUD is off" in act(action="show_hud")["text"]
    assert not act(action="get")["shown_on_hud"]


def test_the_instructions_carry_the_amounts_and_prices(helper, market):
    find_routes(helper)

    first = act(action="set", route_number=1)

    planned = stored_route(helper)["stops"][0]["buy"]
    assert first["instructions"] == [
        f"Buy {e['scu']:,} SCU {e['commodity']} for about {e['total_aUEC']:,} aUEC"
        + (f", keep it aboard until {e['sell_at']}" if e.get("sell_at") else "") + "."
        for e in planned
    ]


def test_recorded_trades_change_the_later_sale_and_the_profit(helper, market):
    find_routes(helper)
    act(action="set", route_number=1)
    route = stored_route(helper)
    bought = route["stops"][0]["buy"][0]
    sale = next(e for s in route["stops"][1:] for e in s.get("sell", []) if e["commodity"] == bought["commodity"])

    # Bought 4 SCU less, for another price
    result = act(action="record_buy", commodity=bought["commodity"].upper(), scu=bought["scu"] - 4, total_price=50)

    assert "(done, recorded)" in result["instructions"][0]
    route = stored_route(helper)
    new_sale = next(e for s in route["stops"][1:] for e in s.get("sell", []) if e["commodity"] == bought["commodity"])
    assert new_sale["scu"] == sale["scu"] - 4
    assert new_sale["total_aUEC"] == round(new_sale["scu"] * sale["price_per_scu"])
    sells = sum(e["total_aUEC"] for s in route["stops"] for e in s.get("sell", []))
    buys = sum(e["total_aUEC"] for s in route["stops"] for e in s.get("buy", []))
    assert route["estimated_profit"] == sells - buys
    assert any("Route profit is now about" in note for note in helper.notes)

    # Sold for another price at that later stop
    sale_stop = next(s["terminal"] for s in route["stops"] if new_sale in s.get("sell", []))
    while act(action="get")["current_stop"]["terminal"] != sale_stop:
        act(action="next")
    act(action="record_sell", commodity=bought["commodity"], scu=new_sale["scu"], total_price=999)
    route = stored_route(helper)
    assert next(e for s in route["stops"] for e in s.get("sell", []) if e["commodity"] == bought["commodity"])["total_aUEC"] == 999


def test_recorded_amounts_that_do_not_add_up_come_with_a_warning(helper, market):
    find_routes(helper)
    act(action="set", route_number=1)
    route = stored_route(helper)
    helper.notes.clear()

    act(action="record_buy", commodity=route["stops"][0]["buy"][0]["commodity"], scu=route["hold_scu"] + 5, total_price=999)
    assert any("the hold of the route's ship takes" in note for note in helper.notes), helper.notes
    assert any("it may take less" in note for note in helper.notes), helper.notes  # the later sale grew past the plan

    act(action="next")
    sale = stored_route(helper)["stops"][1]["sell"]
    helper.notes.clear()
    act(action="record_sell", commodity=sale[0]["commodity"], scu=10_000, total_price=1)
    assert any("should be aboard" in note for note in helper.notes), helper.notes


def test_recording_an_unplanned_commodity_explains_the_plan(helper, market):
    find_routes(helper)
    act(action="set", route_number=1)

    text = act(action="record_buy", commodity="Quantainium", scu=5, total_price=100)["text"]

    assert "The plan has no buy of Quantainium" in text
    assert "planned:" in text


def test_a_sale_recorded_before_next_names_the_stop_it_belongs_to(helper, market):
    find_routes(helper)
    act(action="set", route_number=1)
    stops = stored_route(helper)["stops"]
    number, sale = next((n, s["sell"][0]) for n, s in enumerate(stops, 1) if s.get("sell"))

    text = act(action="record_sell", commodity=sale["commodity"], scu=sale["scu"], total_price=1)["text"]

    assert f"It is planned at stop {number}" in text
    assert "call next" in text
    assert Store(helper).get()["step"] == 1  # nothing recorded, nothing skipped


def test_the_last_ship_is_used_and_a_switch_is_flagged(helper, db, market):
    db.execute("INSERT INTO vehicle (id, name_full, scu, container_sizes) VALUES (1, 'Gatac Railen', 10, ''), (2, 'Drake Golem Ox', 5, '')")
    db.commit()

    def find(**kwargs) -> list[dict]:
        return search(helper, filter_start_location="Stanton One", filter_destination_location="Nyx One", limit=1, **kwargs)

    find(used_ship="Gatac Railen")
    assert Store(helper).get_last_ship() == "Gatac Railen"
    assert find()[0]["stops"][0]["buy"][0]["scu"] == 10  # the Railen's cargo, not 1 SCU
    assert any("Gatac Railen (ship of the last search)" in note for note in helper.notes)
    find(used_ship="Drake Golem Ox")
    assert any("Ship changed from Gatac Railen to Drake Golem Ox" in note for note in helper.notes)
    # A ship the user may not have named (a guess) does not replace the remembered one ...
    assert find()[0]["stops"][0]["buy"][0]["scu"] == 10
    assert Store(helper).get_last_ship() == "Gatac Railen"
    assert any("If the user flies the Drake Golem Ox" in note for note in helper.notes)
    # ... until it is named again (a search without a ship in between doesn't reset that)
    find(used_ship="Drake Golem Ox")
    assert not any("Ship changed" in note for note in helper.notes)
    assert Store(helper).get_last_ship() == "Drake Golem Ox"


# ── What the Wingman and the HUD are told about a stop ──────────────

NITROGEN_STOP = {"terminal": "Admin - Starlight Service", "location": "Bloom, Pyro", "buy": [{
    "commodity": "Nitrogen", "scu": 2044, "total_aUEC": 4985316, "price_per_scu": 2439.0, "sell_at": None,
    "warnings": [],
    "volume_note": "SCU count limited to 2044 (instead of 2200) by available money (4,987,363 aUEC left for it at this stop).",
}]}


def nitrogen_stops(stop: dict, sold_scu: int = 2044, sold_aUEC: int = 7971600) -> list[dict]:
    last = {"terminal": "Admin - ARC-L4", "location": "ArcCorp, Stanton",
            "sell": [{"commodity": "Nitrogen", "scu": sold_scu, "total_aUEC": sold_aUEC, "price_per_scu": 3900.0}]}
    return [stop, last]


def test_a_money_limit_is_explained_in_the_notes_and_on_the_hud():
    stop = {**NITROGEN_STOP, "buy": [dict(NITROGEN_STOP["buy"][0])]}
    _, notes = Store.stop_instructions(stop)
    assert notes == ["Nitrogen: only 2,044 SCU, all the money allows (4,987,363 aUEC left for it here; the hold has room for 2,200)."]
    text = Store.hud_text({"route": {"estimated_profit": 2986284, "hold_scu": 2200, "stops": nitrogen_stops(stop)}, "step": 1})
    assert "*Nitrogen: all the money allows, 4,987,363 aUEC left for it (room for 2,200).*" in text

    # Money kept for a later stop's purchases: that stop is named (its name has parentheses)
    stop["buy"][0]["volume_note"] = (
        "SCU count limited to 48 (instead of 2200) by available money (2,119,488 aUEC left for it at this "
        "stop, the rest is kept for the purchases at Admin - Nyx Gateway (Stanton))."
    )
    _, notes = Store.stop_instructions(stop)
    assert "the rest is needed for the purchases at Admin - Nyx Gateway (Stanton);" in notes[0]
    text = Store.hud_text({"route": {"estimated_profit": 1, "hold_scu": 2200, "stops": nitrogen_stops(stop)}, "step": 1})
    assert "2,119,488 aUEC left for it, the rest is for Nyx Gateway (Stanton) (room for 2,200)" in text


def test_another_amount_is_compared_per_scu_and_the_plan_reason_goes():
    stop = {**NITROGEN_STOP, "buy": [{
        **NITROGEN_STOP["buy"][0], "scu": 2000, "total_aUEC": 4900000, "price_per_scu": 2450.0, "recorded": True,
        "planned_aUEC": 4985316, "planned_trade_scu": 2044, "planned_price_per_scu": 2439.0,
    }]}

    text = Store.hud_text({
        "route": {"estimated_profit": 2900000, "hold_scu": 2200, "stops": nitrogen_stops(stop, 2000, 7800000)}, "step": 1,
    })

    # 85,316 aUEC less in total, but more per SCU
    assert "bought 2,000 SCU instead of 2,044; 11 aUEC more per SCU than planned" in text
    assert "all the money allows" not in text
    _, notes = Store.stop_instructions(stop)  # the same for the Wingman
    assert notes == ["Nitrogen: bought 2,000 SCU instead of 2,044; 11 aUEC more per SCU than planned."]


def test_the_hud_text_lays_out_the_stop():
    route = {
        "path": "A -> B -> C", "estimated_profit": 1234567, "max_investment": 50000, "system_jumps": 1, "hold_scu": 10,
        "stops": [
            {"terminal": "Admin - Alpha", "location": "Hurston, Stanton", "buy": [
                {"commodity": "Gold", "scu": 4, "total_aUEC": 40,
                 "volume_note": "SCU count limited to 4 (instead of 10) by estimated availability at buy location.",
                 "container_note": "Buy it in containers of at most 24 SCU: Admin - Charlie, where you sell it, takes no bigger ones.",
                 "sell_at": "Admin - Charlie"},
            ]},
            {"terminal": "Bravo", "location": "Crusader, Stanton"},
            {"terminal": "Admin - Charlie", "location": "Delamar, Nyx", "sell": [{"commodity": "Gold", "scu": 4, "total_aUEC": 240}]},
        ],
    }
    nl = chr(10)

    text = Store.hud_text({"route": route, "step": 1})

    assert "### Alpha" + nl + nl + "Stop 1 of 3 · Hurston, Stanton" in text
    # The route as the HUD's steps block: a jump where two stops are in different systems
    assert "```steps" + nl + "current | Alpha" + nl + "next | Bravo" + nl + "jump | Jump" + nl + "next | Charlie" + nl + "```" in text
    # The hold as the HUD's bar block: empty on arrival, Gold bought here
    assert "```bar" + nl + "max: 10" + nl + "Arriving" + nl + "Leaving | 4 accent" + nl + "legend | accent Buy here" + nl + "```" in text
    assert "| Buy | SCU | aUEC |" + nl + "|---|---:|---:|" + nl + "| **Gold** | 4 | 40 |" in text
    # Why that amount and why that container size, for this stop only
    assert ("*Gold: only 4 in stock here (room for 10); max. 24 SCU containers, Charlie takes no bigger ones; "
            "keep it aboard until Charlie.*") in text
    # The money and the next stop in one card
    assert ("```stats" + nl + "Pay here | 40" + nl + "Profit | 1,234,567 | accent" + nl
            + "**Next:** Bravo · Crusader, Stanton" + nl + "```") in text

    later = Store.hud_text({"route": route, "step": 3, "planned_profit": 1300000})
    assert "done | Alpha" + nl + "done | Bravo" + nl + "jump | Jump" + nl + "current | Charlie" in later
    assert "Arriving | 4 text" in later  # Gold is sold here
    assert "in stock here" not in later  # the lines are about the current stop only
    assert "Planned | 1,300,000" in later
    assert "**Last stop** of the route." in later

    route["stops"][0]["buy"][0].update(recorded=True, planned_aUEC=50)
    recorded = Store.hud_text({"route": route, "step": 1})
    assert "| **Gold** | **4** | **40** |" in recorded
    assert "Gold: paid 10 aUEC less than planned;" in recorded


# ── A purchase the plan split in two ────────────────────────────────


def _gold_split_in_two(tmp_path) -> Store:
    """Stop 1 buys 1000 Gold in two parts: 300 for stop 2 (short on demand), 700 for stop 3."""
    store = Store(SimpleNamespace(get_data_path=lambda: str(tmp_path)))
    stops = [
        {"terminal": "A", "buy": [
            {"commodity": "Gold", "scu": 300, "total_aUEC": 3000, "price_per_scu": 10, "sell_at": None},
            {"commodity": "Gold", "scu": 700, "total_aUEC": 7000, "price_per_scu": 10, "sell_at": "C"},
        ]},
        {"terminal": "B", "sell": [{"commodity": "Gold", "scu": 300, "total_aUEC": 6000, "price_per_scu": 20}]},
        {"terminal": "C", "sell": [{"commodity": "Gold", "scu": 700, "total_aUEC": 14000, "price_per_scu": 20}]},
    ]
    store.remember_search([{"stops": stops, "estimated_profit": 10000, "hold_scu": 1000}])
    assert store.set(1)
    return store


def _sales(active: dict) -> list[int]:
    return [stop["sell"][0]["scu"] for stop in active["route"]["stops"][1:]]


def test_a_purchase_the_plan_split_in_two_is_recorded_as_planned(tmp_path):
    store = _gold_split_in_two(tmp_path)

    active, problem, warnings = store.record("buy", "Gold", 1000, 10000)

    assert problem is None
    assert warnings == []
    assert [e["scu"] for e in active["route"]["stops"][0]["buy"]] == [300, 700]
    assert _sales(active) == [300, 700]
    assert active["route"]["estimated_profit"] == 10000


def test_a_smaller_purchase_takes_the_missing_cargo_from_the_last_part(tmp_path):
    store = _gold_split_in_two(tmp_path)

    active, _, warnings = store.record("buy", "Gold", 900, 9900)

    assert [e["scu"] for e in active["route"]["stops"][0]["buy"]] == [300, 600]
    assert _sales(active) == [300, 600]
    assert active["route"]["estimated_profit"] == 300 * 20 + 600 * 20 - 9900
    assert warnings == []
