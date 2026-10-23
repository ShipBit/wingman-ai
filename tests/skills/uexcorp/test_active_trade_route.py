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
    with open(os.path.join(helper.get_state_path(), Store.FILE_NAME), "w", encoding="utf-8") as file:
        file.write("[]")

    assert "No active trade route" in act(action="get")["text"]
    assert "There was no active trade route" in act(action="clear")["text"]


def test_after_a_restart_the_prompt_names_the_run_and_its_stop(tmp_path):
    _gold_split_in_two(tmp_path).go_to(2)

    restarted = Store(SimpleNamespace(get_state_path=lambda: str(tmp_path)))
    assert "stop 2 of 3 is B" in restarted.prompt_note(ActiveTradeRoute.TOOL_NAME)

    restarted.clear()
    assert restarted.prompt_note(ActiveTradeRoute.TOOL_NAME) == ""


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
    assert ("```stats" + nl + "Pay here | 40" + nl + "Balance after | -40" + nl + "Profit | 1,234,567 | accent" + nl
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
    store = Store(SimpleNamespace(get_state_path=lambda: str(tmp_path)))
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




def test_a_second_purchase_at_a_stop_adds_to_the_first(tmp_path):
    """Cargo is often bought in several goes, and each one is reported on its own."""
    store = _gold_split_in_two(tmp_path)

    store.record("buy", "Gold", 200, 2000)
    active, _, notes = store.record("buy", "Gold", 800, 8400)

    assert [e["scu"] for e in active["route"]["stops"][0]["buy"]] == [300, 700]
    assert sum(e["total_aUEC"] for e in active["route"]["stops"][0]["buy"]) == 10400
    assert _sales(active) == [300, 700]
    assert "1,000 SCU Gold for 10,400 aUEC in all" in notes[0]


def test_a_correction_replaces_what_was_recorded(tmp_path):
    store = _gold_split_in_two(tmp_path)
    store.record("buy", "Gold", 1000, 10000)

    active, _, _ = store.record("buy", "Gold", 900, 9000, correction=True)

    assert sum(e["scu"] for e in active["route"]["stops"][0]["buy"]) == 900
    assert _sales(active) == [300, 600]


def test_undo_takes_back_a_sale_recorded_twice(tmp_path):
    store = _gold_split_in_two(tmp_path)
    store.go_to(3)
    store.record("sell", "Gold", 300, 6000)
    store.record("sell", "Gold", 400, 8000)
    store.record("sell", "Gold", 400, 8000)  # the same game event twice

    active, problem, notes = store.undo("sell", "gold")

    assert problem is None
    sale = active["route"]["stops"][2]["sell"][0]
    assert (sale["scu"], sale["total_aUEC"], sale["recorded"]) == (700, 14000, True)
    assert active["route"]["estimated_profit"] == 6000 + 14000 - 10000
    assert "Still recorded there: 700 SCU for 14,000 aUEC." in notes


def test_undo_picks_a_recorded_amount_by_its_scu(tmp_path):
    store = _gold_split_in_two(tmp_path)
    store.record("buy", "Gold", 600, 6000)
    store.record("buy", "Gold", 400, 4400)

    assert "recorded: 600 SCU for 6,000 aUEC, 400 SCU for 4,400 aUEC" in store.undo("buy", "Gold", 50)[1]
    active, _, _ = store.undo("buy", "Gold", 600)

    assert [e["scu"] for e in active["route"]["stops"][0]["buy"]] == [300, 100]
    assert sum(e["total_aUEC"] for e in active["route"]["stops"][0]["buy"]) == 4400
    assert _sales(active) == [300, 100]


def test_undoing_the_only_purchase_brings_the_plan_back(tmp_path):
    store = _gold_split_in_two(tmp_path)
    store.record("buy", "Gold", 900, 9900)
    store.go_to(2)

    # Recorded at another stop than the current one
    assert "pass stop_number 1" in store.undo("buy", "Gold")[1]
    active, problem, notes = store.undo("buy", "Gold", stop_number=1)

    assert problem is None
    buys = active["route"]["stops"][0]["buy"]
    assert [(e["scu"], e["total_aUEC"], e.get("recorded")) for e in buys] == [(300, 3000, None), (700, 7000, None)]
    assert _sales(active) == [300, 700]
    assert active["route"]["estimated_profit"] == 10000
    assert "the plan's 1,000 SCU are back" in notes[-1]


def test_a_total_recorded_before_transactions_were_kept_counts_as_one(tmp_path):
    store = _gold_split_in_two(tmp_path)
    store.record("buy", "Gold", 1000, 10000)
    state = store._ActiveTradeRoute__load()
    state["active"]["route"]["stops"][0]["buy"][0].pop("transactions")
    store._ActiveTradeRoute__save(state)
    store.record("buy", "Gold", 50, 500)

    active, _, _ = store.undo("buy", "Gold")

    assert sum(e["scu"] for e in active["route"]["stops"][0]["buy"]) == 1000
    assert all(e.get("recorded") for e in active["route"]["stops"][0]["buy"])


# ── Trade run: a stop added for cargo not sold as planned ───────────


def _run(tmp_path, stops: list[dict], step: int = 1) -> Store:
    store = Store(SimpleNamespace(get_state_path=lambda: str(tmp_path)))
    store.remember_search([{"stops": stops, "estimated_profit": 0, "hold_scu": 200, "path": "", "system_jumps": 0}])
    assert store.set(1)
    store.go_to(step)
    return store


def _sale(commodity: str, scu: int, price: int) -> dict:
    return {"commodity": commodity, "scu": scu, "total_aUEC": scu * price, "price_per_scu": price}


def test_cargo_left_after_a_short_sale_is_sold_at_an_added_stop(tmp_path):
    store = _run(tmp_path, [
        {"terminal": "A", "location": "Hurston, Stanton", "buy": [_sale("Gold", 100, 10)]},
        {"terminal": "B", "location": "Hurston, Stanton", "sell": [_sale("Gold", 100, 20)]},
    ], step=2)
    store.record("sell", "Gold", 80, 1600)

    active, problem, notes = store.add_sell("C", "Pyro I, Pyro", "gold", None, 18)

    assert problem is None and notes == []
    assert active["step"] == 2
    stops = active["route"]["stops"]
    assert [s["terminal"] for s in stops] == ["A", "B", "C"]
    assert stops[2]["sell"] == [{"commodity": "Gold", "scu": 20, "total_aUEC": 360, "price_per_scu": 18}]
    assert active["route"]["estimated_profit"] == 1600 + 360 - 1000
    assert (active["route"]["path"], active["route"]["systems"], active["route"]["system_jumps"]) == (
        "A -> B -> C", "Stanton -> Pyro", 1)
    assert Store.cargo_on_arrival({"route": active["route"], "step": 4}) == []


def test_planned_cargo_sold_elsewhere_comes_off_the_later_sale(tmp_path):
    store = _run(tmp_path, [
        {"terminal": "A", "location": "Hurston, Stanton", "buy": [_sale("Gold", 100, 10), _sale("Tin", 10, 1)]},
        {"terminal": "B", "location": "Hurston, Stanton", "sell": [_sale("Gold", 100, 20)]},
        {"terminal": "C", "location": "Hurston, Stanton", "sell": [_sale("Tin", 10, 2)]},
    ])
    # Without scu: nothing is left over, all of it is planned for B
    assert "planned for sale" in store.add_sell("X", "Hurston, Stanton", "Gold", None, 25)[1]
    assert "Only 100 SCU" in store.add_sell("X", "Hurston, Stanton", "Gold", 150, 25)[1]

    active, problem, notes = store.add_sell("X", "Hurston, Stanton", "Gold", 100, 25)

    assert problem is None
    # B had nothing else to do there
    assert [s["terminal"] for s in active["route"]["stops"]] == ["A", "X", "C"]
    assert any("B is dropped" in note for note in notes)
    assert active["route"]["estimated_profit"] == 2500 + 20 - 1010


def test_cargo_of_a_later_purchase_is_not_counted_as_the_left_over_one(tmp_path):
    """Methane left over at stop 2, more Methane bought at stop 3 for a sale at stop 4."""
    store = _run(tmp_path, [
        {"terminal": "A", "location": "Hurston, Stanton", "buy": [_sale("Gold", 100, 10)]},
        {"terminal": "B", "location": "Hurston, Stanton", "sell": [_sale("Gold", 100, 20)]},
        {"terminal": "C", "location": "Hurston, Stanton", "buy": [_sale("Gold", 50, 10)]},
        {"terminal": "D", "location": "Hurston, Stanton", "sell": [_sale("Gold", 50, 30)]},
    ], step=2)
    store.record("sell", "Gold", 60, 1200)

    active, problem, notes = store.add_sell("X", "Hurston, Stanton", "Gold", None, 18)

    assert problem is None and notes == []
    stops = active["route"]["stops"]
    assert [s["terminal"] for s in stops] == ["A", "B", "X", "C", "D"]
    assert stops[2]["sell"][0]["scu"] == 40
    assert stops[4]["sell"][0]["scu"] == 50
    # The cargo of the later purchase isn't aboard yet
    assert "Only 40 SCU Gold" in store.add_sell("Y", "Hurston, Stanton", "Gold", 80, 18)[1]


def test_a_sale_at_the_next_stop_joins_it_at_the_planned_price(tmp_path):
    store = _run(tmp_path, [
        {"terminal": "A", "location": "Hurston, Stanton", "buy": [_sale("Gold", 100, 10)]},
        {"terminal": "B", "location": "Hurston, Stanton", "sell": [_sale("Gold", 60, 20)]},
        {"terminal": "C", "location": "Hurston, Stanton", "sell": [_sale("Gold", 40, 30)]},
    ])

    active, problem, notes = store.add_sell("B", "Hurston, Stanton", "Gold", 40, 99)

    assert problem is None
    assert [s["terminal"] for s in active["route"]["stops"]] == ["A", "B"]
    assert active["route"]["stops"][1]["sell"][0]["scu"] == 100
    assert active["route"]["stops"][1]["sell"][0]["total_aUEC"] == 2000
    assert notes == ["Stop 3, C, now sells 0 SCU Gold instead of 40.", "C is dropped from the route: nothing is left to sell there."]


def test_a_sale_of_cargo_not_aboard_says_to_record_the_short_sale_first(tmp_path):
    store = _run(tmp_path, [
        {"terminal": "A", "location": "Hurston, Stanton", "buy": [_sale("Gold", 100, 10)]},
        {"terminal": "B", "location": "Hurston, Stanton", "sell": [_sale("Gold", 100, 20)]},
    ], step=2)

    active, problem, _ = store.add_sell("C", "Hurston, Stanton", "Gold", None, 18)

    assert active is None
    assert "call record_sell with the real amount first" in problem
    assert len(store.get()["route"]["stops"]) == 2


def _tool_helper(tmp_path, monkeypatch) -> SimpleNamespace:
    from skills.uexcorp.uexcorp.helper import Helper

    null = SimpleNamespace(write=lambda *a, **k: None)
    helper = SimpleNamespace(
        get_state_path=lambda: str(tmp_path),
        get_handler_tool=lambda: SimpleNamespace(add_note=lambda note: None),
        get_handler_debug=lambda: null,
        get_handler_error=lambda: null,
        get_handler_config=lambda: SimpleNamespace(get_wingman=lambda: SimpleNamespace(hud=None)),
    )
    monkeypatch.setattr(Helper, "_instance", helper)
    return helper


def test_next_at_the_last_stop_with_cargo_aboard_asks_before_it_ends_the_run(tmp_path, monkeypatch):
    from skills.uexcorp.uexcorp.tool.active_trade_route import ActiveTradeRoute as Tool

    _tool_helper(tmp_path, monkeypatch)
    store = _run(tmp_path, [
        {"terminal": "A", "location": "Hurston, Stanton", "buy": [_sale("Gold", 100, 10)]},
        {"terminal": "B", "location": "Hurston, Stanton", "sell": [_sale("Gold", 100, 20)]},
    ], step=2)
    store.record("sell", "Gold", 80, 1600)

    text, _ = asyncio.run(Tool().execute(action="next"))
    assert text.startswith("Not finished: 20 SCU Gold still aboard")
    assert store.get()["step"] == 2

    text, _ = asyncio.run(Tool().execute(action="next"))
    assert "route_complete" in text
    assert store.get() is None


def test_add_sell_takes_the_terminal_of_the_place_that_pays_most(tmp_path, monkeypatch):
    from skills.uexcorp.uexcorp.database.database import Database
    from skills.uexcorp.uexcorp.tool.active_trade_route import ActiveTradeRoute as Tool

    helper = _tool_helper(tmp_path, monkeypatch)
    helper.is_ready = lambda: True
    helper.get_handler_import = lambda: SimpleNamespace(has_data=lambda: True, get_common_data=lambda: {})
    database = Database(str(tmp_path), version="test-add-stop", helper=helper)
    helper.get_database = lambda: database
    try:
        for terminal_id, name, blacklisted in ((1, "Low", 0), (2, "High", 0), (3, "Blacklisted", 1)):
            database.execute(
                "INSERT INTO terminal (id, name, type, is_available, is_blacklisted, city_name, planet_name, star_system_name) "
                "VALUES (?, ?, 'commodity', 1, ?, 'Area18', 'ArcCorp', 'Stanton')", (terminal_id, name, blacklisted),
            )
            database.execute(
                "INSERT INTO commodity_price (id, id_commodity, id_terminal, price_buy, price_sell, commodity_name, terminal_name) "
                "VALUES (?, 7, ?, ?, ?, 'Gold', ?)",
                (terminal_id, terminal_id, (9, 12, 5)[terminal_id - 1], (10, 20, 30)[terminal_id - 1], name),
            )
        database.commit()
        store = _run(tmp_path, [
            {"terminal": "A", "location": "Hurston, Stanton", "buy": [_sale("Gold", 100, 10)]},
            {"terminal": "B", "location": "Hurston, Stanton", "sell": [_sale("Gold", 100, 20)]},
        ], step=2)
        store.record("sell", "Gold", 80, 1600)

        asyncio.run(Tool().execute(action="add_sell", location="Area18", commodity="Gold"))

        added = store.get()["route"]["stops"][2]
        assert (added["terminal"], added["location"]) == ("High", "ArcCorp, Stanton")
        assert added["sell"][0]["total_aUEC"] == 400

        # Buying: the cheapest terminal there, the later sale of it takes the cargo
        asyncio.run(Tool().execute(action="add_buy", location="Area18", commodity="Gold", scu=10))

        stops = store.get()["route"]["stops"]
        assert [s["terminal"] for s in stops] == ["A", "B", "Low", "High"]
        assert stops[2]["buy"][0]["total_aUEC"] == 90
        assert stops[3]["sell"][0]["scu"] == 30
    finally:
        database.destroy()


def test_left_over_cargo_can_wait_for_a_later_stop_that_buys_it(tmp_path):
    """The run's case: Methane left at ARC-L1, Levski at the end buys Methane too."""
    store = _run(tmp_path, [
        {"terminal": "A", "location": "Hurston, Stanton", "buy": [_sale("Methane", 100, 10)]},
        {"terminal": "B", "location": "Hurston, Stanton", "sell": [_sale("Methane", 100, 20)]},
        {"terminal": "C", "location": "Hurston, Stanton", "buy": [_sale("Laranite", 150, 10), _sale("Methane", 50, 10)]},
        {"terminal": "D", "location": "Hurston, Stanton", "sell": [_sale("Laranite", 150, 20), _sale("Methane", 50, 30)]},
    ], step=2)
    store.record("sell", "Methane", 60, 1200)
    assert store.sale_options("methane").startswith("40 SCU Methane stay aboard that no stop sells")
    assert "a later stop of the route buys it (stop 4, D)" in store.sale_options("Methane")

    active, problem, notes = store.add_sell("D", "Hurston, Stanton", "Methane", None, 99)

    assert problem is None
    stops = active["route"]["stops"]
    assert [s["terminal"] for s in stops] == ["A", "B", "C", "D"]
    assert (stops[3]["sell"][1]["scu"], stops[3]["sell"][1]["total_aUEC"]) == (90, 2700)  # at the planned price
    assert store.sale_options("Methane") is None
    assert notes == ["Leaving stop 3, C, 240 SCU would be aboard, but the hold takes 200 SCU: buy less there or sell some earlier."]


def test_a_purchase_somewhere_else_is_added_recorded_and_sold_later(tmp_path):
    store = _run(tmp_path, [
        {"terminal": "A", "location": "Hurston, Stanton", "buy": [_sale("Gold", 100, 10)]},
        {"terminal": "B", "location": "Hurston, Stanton", "sell": [_sale("Gold", 100, 20)]},
    ])

    active, problem, notes = store.add_buy("X", "Crusader, Stanton", "gold", 50, 9, 480)

    assert problem is None
    stops = active["route"]["stops"]
    assert [s["terminal"] for s in stops] == ["A", "X", "B"]
    assert (stops[1]["buy"][0]["scu"], stops[1]["buy"][0]["total_aUEC"], stops[1]["buy"][0]["recorded"]) == (50, 480, True)
    assert active["step"] == 2  # bought there already: the user is at X
    assert stops[2]["sell"][0]["scu"] == 150
    assert active["route"]["estimated_profit"] == 3000 - 1000 - 480
    assert "Stop 2, X, is the current stop now." in notes
    # A purchase the plan has there already is recorded, not added
    assert "call record_buy" in store.add_buy("X", "Crusader, Stanton", "Gold", 5, 10)[1]


def test_the_money_at_a_stop_counts_its_sales_first(tmp_path):
    """The Wingman judged a purchase by the search's money and forgot the sales before it."""
    store = _run(tmp_path, [
        {"terminal": "A", "location": "Hurston, Stanton", "buy": [_sale("Gold", 100, 10)]},
        {"terminal": "B", "location": "Hurston, Stanton", "sell": [_sale("Gold", 100, 20)], "buy": [_sale("Tin", 50, 30)]},
        {"terminal": "C", "location": "Hurston, Stanton", "sell": [_sale("Tin", 50, 40)]},
    ], step=2)

    assert Store.for_ai(store.get(), False)["money"] == (
        "Sales here bring about 2,000 aUEC first; purchases cost about 1,500 aUEC, paid from the sales here; "
        "after this stop the run is at -500 aUEC (below 0 = money still invested)."
    )
    assert "Balance after | -500" in Store.hud_text(store.get())


def test_a_trade_without_a_demand_figure_says_so():
    stop = {"terminal": "Levski", "location": "Delamar, Nyx",
            "sell": [{**_sale("Methane", 1558, 3700), "demand_unknown": True}],
            "buy": [{**_sale("Tin", 10, 5), "demand_unknown": True}]}

    _, notes = Store.stop_instructions(stop)

    assert "Methane: UEX has no demand figure here, it may take less." in notes
    assert "Tin: UEX has no demand figure where it is sold, more than planned may not sell." in notes


def test_route_filters_that_contradict_each_other_are_named(tmp_path, monkeypatch):
    """The Wingman added "only Stanton" to a search starting at Levski, in Nyx, and heard only "no route"."""
    from skills.uexcorp.uexcorp.database.database import Database
    from skills.uexcorp.uexcorp.tool.commodity_route import CommodityRoute

    helper = _tool_helper(tmp_path, monkeypatch)
    notes = []
    helper.get_handler_tool = lambda: SimpleNamespace(add_note=notes.append)
    helper.is_ready = lambda: True
    helper.get_handler_import = lambda: SimpleNamespace(has_data=lambda: True, get_common_data=lambda: {})
    database = Database(str(tmp_path), version="test-filters", helper=helper)
    helper.get_database = lambda: database
    try:
        for system_id, name in ((1, "Stanton"), (2, "Nyx"), (3, "Pyro")):
            database.execute("INSERT INTO star_system (id, name, is_available) VALUES (?, ?, 1)", (system_id, name))
        # Stanton links to Nyx and Pyro: Nyx to Pyro is two jumps
        for orbit_id, name in ((21, "Nyx Gateway (Stanton system)"), (22, "Pyro Gateway (Stanton system)")):
            database.execute(
                "INSERT INTO orbit (id, name, id_star_system, star_system_name, is_jump_point) VALUES (?, ?, 1, 'Stanton', 1)",
                (orbit_id, name),
            )
        for terminal_id, name, system, auto_load in ((1, "Levski", "Nyx", 0), (2, "ARC-L1", "Stanton", 1), (3, "Ruin", "Pyro", 1)):
            database.execute(
                "INSERT INTO terminal (id, name, type, is_available, is_auto_load, star_system_name) VALUES (?, ?, 'commodity', 1, ?, ?)",
                (terminal_id, name, auto_load, system),
            )
        database.commit()

        def search(**filters) -> str:
            notes.clear()
            assert CommodityRoute().execute(available_cargo_space_scu=10, **filters)[0] == "[]"
            return " ".join(notes)

        note = search(filter_start_location="Levski", filter_star_system_whitelist=["Stanton"])
        assert "the filters contradict each other. The start Levski is in Nyx, but the search is limited to Stanton." in note
        assert "are 2 system jumps apart, but at most 1 are allowed" in search(
            filter_start_location="Levski", filter_destination_location="Ruin", max_system_jumps=1)
        assert "are in different star systems, but no system jumps are allowed" in search(
            filter_start_location="Levski", filter_destination_location="ARC-L1", max_system_jumps=0)
        assert "gold: both the only commodities to trade and excluded." in search(
            filter_commodity_whitelist=["Gold"], filter_commodity_blacklist=["gold"])
        assert "No terminal at the start Levski has auto loading." in search(
            filter_start_location="Levski", filter_require_auto_load=True)
    finally:
        database.destroy()
