"""Tests for the active trade route (uex_active_trade_route) and its HUD panel (actions show_hud / hide_hud).

No pytest. Run from the project root:

    python3 -m skills.uexcorp.tests.test_active_trade_route

Exits non-zero on the first failed assertion or crash; prints "ALL OK" on success.

Why this exists
---------------
A multi-stop run spans many turns. Core clears old tool responses once the history
gets long, so the Wingman lost the later stops. The route and the stop the player is
at now live in a file, and the Wingman (not a setting) decides what the HUD shows.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest

from skills.uexcorp.uexcorp.active_trade_route import HUD_TITLE, ActiveTradeRoute as Store
from skills.uexcorp.uexcorp.tool.active_trade_route import ActiveTradeRoute
from skills.uexcorp.uexcorp.tool.commodity_route import CommodityRoute
from skills.uexcorp.tests.test_commodity_route_auto_load import _parse_routes
from skills.uexcorp.tests.test_system_jumps_and_name_matching import N1, S1, S2, _DatabaseTest


class _FakeHud:
    def __init__(self):
        self.panels: dict[str, str] = {}

    async def add_info(self, title: str, text: str = "", **kwargs) -> bool:
        self.panels[title] = text
        return True

    async def remove_info(self, title: str) -> bool:
        self.panels.pop(title, None)
        return True


class ActiveTradeRouteTest(_DatabaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._helper.get_data_path = lambda: self._tmp_dir
        self._helper.wingman.hud = self._hud = _FakeHud()
        names = {S1: "Stanton One", S2: "Stanton Two", N1: "Nyx One"}
        systems = {S1: "Stanton", S2: "Stanton", N1: "Nyx"}
        for terminal_id, name in names.items():
            self._db.execute(
                "INSERT INTO terminal (id, name, type, is_available) VALUES (?, ?, 'commodity', 1)", (terminal_id, name)
            )
        # Stanton One -> Stanton Two -> Nyx One beats the direct hop per stop; Gold is short at Stanton Two
        for route_id, (commodity, origin, destination, buy, sell, stock) in enumerate((
            ("Laranite", S1, S2, 10, 12, 100),
            ("Laranite", S1, N1, 10, 30, 100),
            ("Gold", S2, N1, 10, 60, 4),
            ("Tin", S2, N1, 10, 50, 100),
        ), start=101):
            self._db.execute(
                """
                INSERT INTO commodity_route (
                    id, id_terminal_origin, id_terminal_destination, commodity_name,
                    origin_terminal_name, destination_terminal_name,
                    origin_star_system_name, destination_star_system_name,
                    price_origin, price_destination, scu_origin, scu_destination, distance, id_commodity
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 100, 5, ?)
                """,
                (route_id, origin, destination, commodity, names[origin], names[destination],
                 systems[origin], systems[destination], buy, sell, stock, route_id),
            )
        self._db.commit()

    def _search(self) -> list[dict]:
        payload, _instant = CommodityRoute().execute(
            filter_start_location="Stanton One", filter_destination_location="Nyx One",
            max_stops=2, available_cargo_space_scu=10, limit=2,
        )
        return _parse_routes(payload)

    def _active(self, **kwargs) -> dict:
        response, _instant = asyncio.run(ActiveTradeRoute().execute(**kwargs))
        try:
            return _parse_routes(response)
        except ValueError:
            return {"text": response}

    def test_routes_are_numbered_for_picking(self) -> None:
        routes = self._search()
        self.assertEqual([route["route_number"] for route in routes], [1, 2])
        self.assertEqual(routes[0]["path"], "Stanton One -> Stanton Two -> Nyx One")

    def test_set_get_next_walks_the_route(self) -> None:
        self._search()
        first = self._active(action="set", route_number=1)
        self.assertEqual((first["step"], first["step_count"]), (1, 3))
        self.assertEqual(first["current_stop"]["terminal"], "Stanton One")
        self.assertEqual(first["next_stop"], "Stanton Two")
        self.assertFalse(first["shown_on_hud"])

        second = self._active(action="next")
        self.assertEqual(second["current_stop"]["terminal"], "Stanton Two")
        self.assertEqual(second["cargo_aboard_on_arrival"], [{"commodity": "Laranite", "scu": 10}])
        # A new search does not touch the run, and a fresh store reads the same file
        self._search()
        self.assertEqual(self._active(action="get")["step"], 2)

        self._active(action="next")
        done = self._active(action="next")
        self.assertTrue(done["route_complete"])
        self.assertIsNone(Store(self._helper).get())

    def test_stop_number_jumps_and_clear_ends_the_run(self) -> None:
        self._search()
        self._active(action="set", route_number=1)
        self.assertEqual(self._active(action="get", stop_number=3)["current_stop"]["terminal"], "Nyx One")
        # A stop past the last one is a mistake, not the end of the run
        self.assertIn("there is no stop 9", self._active(action="get", stop_number=9)["text"])
        self.assertEqual(self._active(action="get")["current_stop"]["terminal"], "Nyx One")
        self.assertIn("removed", self._active(action="clear")["text"])
        self.assertIn("No active trade route", self._active(action="get")["text"])

    def test_unknown_route_number_says_how_many_there_are(self) -> None:
        self._search()
        self.assertIn("2 route(s)", self._active(action="set", route_number=5)["text"])

    def test_hud_is_switched_by_the_tool_and_follows_the_cursor(self) -> None:
        self._search()
        self._active(action="set", route_number=1)
        self.assertNotIn(HUD_TITLE, self._hud.panels)

        self._active(action="show_hud")
        self.assertIn("Stop 1 of 3 ·", self._hud.panels[HUD_TITLE])
        self.assertTrue(self._active(action="next")["shown_on_hud"])
        self.assertIn("Stop 2 of 3 ·", self._hud.panels[HUD_TITLE])

        self._active(action="hide_hud")
        self.assertNotIn(HUD_TITLE, self._hud.panels)
        self._active(action="show_hud")
        self._active(action="clear")
        self.assertNotIn(HUD_TITLE, self._hud.panels)

    def test_instructions_carry_the_amounts_and_prices(self) -> None:
        self._search()
        first = self._active(action="set", route_number=1)
        planned = Store(self._helper).get()["route"]["stops"][0]["buy"]
        self.assertEqual(
            first["instructions"],
            [f"Buy {e['scu']:,} SCU {e['commodity']} for about {e['total_aUEC']:,} aUEC"
             + (f", keep it aboard until {e['sell_at']}" if e.get("sell_at") else "") + "." for e in planned],
        )

    def test_a_money_limit_is_explained_in_the_notes_and_on_the_hud(self) -> None:
        stop = {"terminal": "Admin - Starlight Service", "location": "Bloom, Pyro", "buy": [{
            "commodity": "Nitrogen", "scu": 2044, "total_aUEC": 4985316, "price_per_scu": 2439.0, "sell_at": None,
            "warnings": [],
            "volume_note": "SCU count limited to 2044 (instead of 2200) by available money (4,987,363 aUEC left for it at this stop).",
        }]}
        last = {"terminal": "Admin - ARC-L4", "location": "ArcCorp, Stanton",
                "sell": [{"commodity": "Nitrogen", "scu": 2044, "total_aUEC": 7971600, "price_per_scu": 3900.0}]}
        _, notes = Store.stop_instructions(stop)
        self.assertEqual(notes, ["Nitrogen: only 2,044 SCU, all the money allows "
                                 "(4,987,363 aUEC left for it here; the hold has room for 2,200)."])
        text = Store.hud_text({"route": {"estimated_profit": 2986284, "hold_scu": 2200, "stops": [stop, last]}, "step": 1})
        self.assertIn("*Nitrogen: all the money allows, 4,987,363 aUEC left for it (room for 2,200).*", text)

        # Money kept for a later stop's purchases: that stop is named (its name has parentheses)
        stop["buy"][0]["volume_note"] = (
            "SCU count limited to 48 (instead of 2200) by available money (2,119,488 aUEC left for it at this "
            "stop, the rest is kept for the purchases at Admin - Nyx Gateway (Stanton))."
        )
        _, notes = Store.stop_instructions(stop)
        self.assertIn("the rest is needed for the purchases at Admin - Nyx Gateway (Stanton);", notes[0])
        text = Store.hud_text({"route": {"estimated_profit": 1, "hold_scu": 2200, "stops": [stop, last]}, "step": 1})
        self.assertIn("2,119,488 aUEC left for it, the rest is for Nyx Gateway (Stanton) (room for 2,200)", text)

    def test_show_hud_says_so_when_the_hud_is_off(self) -> None:
        self._search()
        self._active(action="set", route_number=1)
        self._hud.info_enabled = False
        self.assertIn("The HUD is off", self._active(action="show_hud")["text"])
        self.assertFalse(self._active(action="get")["shown_on_hud"])

    def test_recorded_amounts_that_do_not_add_up_come_with_a_warning(self) -> None:
        self._search()
        self._active(action="set", route_number=1)
        notes = self._helper.get_handler_tool().notes
        route = Store(self._helper).get()["route"]
        bought = route["stops"][0]["buy"][0]
        notes.clear()
        self._active(action="record_buy", commodity=bought["commodity"], scu=route["hold_scu"] + 5, total_price=999)
        self.assertTrue(any("the hold of the route's ship takes" in note for note in notes), notes)
        self.assertTrue(any("it may take less" in note for note in notes), notes)  # the later sale grew past the plan

        self._active(action="next")
        sale = Store(self._helper).get()["route"]["stops"][1]["sell"]
        notes.clear()
        self._active(action="record_sell", commodity=sale[0]["commodity"], scu=10_000, total_price=1)
        self.assertTrue(any("should be aboard" in note for note in notes), notes)

    def test_a_route_file_of_another_shape_counts_as_no_route(self) -> None:
        with open(os.path.join(self._tmp_dir, Store.FILE_NAME), "w", encoding="utf-8") as file:
            file.write("[]")
        self.assertIn("No active trade route", self._active(action="get")["text"])
        self.assertIn("There was no active trade route", self._active(action="clear")["text"])

    def test_recorded_trades_change_the_later_sale_and_the_profit(self) -> None:
        self._search()
        self._active(action="set", route_number=1)
        route = Store(self._helper).get()["route"]
        bought = route["stops"][0]["buy"][0]
        sale = next(e for s in route["stops"][1:] for e in s.get("sell", []) if e["commodity"] == bought["commodity"])

        # Bought 4 SCU less, for another price
        result = self._active(action="record_buy", commodity=bought["commodity"].upper(), scu=bought["scu"] - 4, total_price=50)
        self.assertIn("(done, recorded)", result["instructions"][0])
        route = Store(self._helper).get()["route"]
        new_sale = next(e for s in route["stops"][1:] for e in s.get("sell", []) if e["commodity"] == bought["commodity"])
        self.assertEqual(new_sale["scu"], sale["scu"] - 4)
        self.assertEqual(new_sale["total_aUEC"], round(new_sale["scu"] * sale["price_per_scu"]))
        sells = sum(e["total_aUEC"] for s in route["stops"] for e in s.get("sell", []))
        buys = sum(e["total_aUEC"] for s in route["stops"] for e in s.get("buy", []))
        self.assertEqual(route["estimated_profit"], sells - buys)
        self.assertTrue(any("Route profit is now about" in note for note in self._helper.get_handler_tool().notes))

        # Sold for another price at that later stop
        while self._active(action="get")["current_stop"]["terminal"] != next(
            s["terminal"] for s in route["stops"] if new_sale in s.get("sell", [])
        ):
            self._active(action="next")
        self._active(action="record_sell", commodity=bought["commodity"], scu=new_sale["scu"], total_price=999)
        route = Store(self._helper).get()["route"]
        self.assertEqual(
            next(e for s in route["stops"] for e in s.get("sell", []) if e["commodity"] == bought["commodity"])["total_aUEC"], 999
        )

    def test_recording_an_unplanned_commodity_explains_the_plan(self) -> None:
        self._search()
        self._active(action="set", route_number=1)
        text = self._active(action="record_buy", commodity="Quantainium", scu=5, total_price=100)["text"]
        self.assertIn("The plan has no buy of Quantainium", text)
        self.assertIn("planned:", text)

    def test_the_last_ship_is_used_and_a_switch_is_flagged(self) -> None:
        self._db.execute(
            "INSERT INTO vehicle (id, name_full, scu, container_sizes) VALUES (1, 'Gatac Railen', 10, ''), (2, 'Drake Golem Ox', 5, '')"
        )
        self._db.commit()
        notes = self._helper.get_handler_tool().notes

        def search(**kwargs) -> list[dict]:
            notes.clear()
            payload, _instant = CommodityRoute().execute(
                filter_start_location="Stanton One", filter_destination_location="Nyx One", limit=1, **kwargs
            )
            return _parse_routes(payload)

        search(used_ship="Gatac Railen")
        self.assertEqual(Store(self._helper).get_last_ship(), "Gatac Railen")
        self.assertEqual(search()[0]["stops"][0]["buy"][0]["scu"], 10)  # the Railen's cargo, not 1 SCU
        self.assertTrue(any("Gatac Railen (ship of the last search)" in note for note in notes))
        search(used_ship="Drake Golem Ox")
        self.assertTrue(any("Ship changed from Gatac Railen to Drake Golem Ox" in note for note in notes))
        # A ship the user may not have named (a guess) does not replace the remembered one ...
        self.assertEqual(search()[0]["stops"][0]["buy"][0]["scu"], 10)
        self.assertEqual(Store(self._helper).get_last_ship(), "Gatac Railen")
        self.assertTrue(any("If the user flies the Drake Golem Ox" in note for note in notes))
        # ... until it is named again (a search without a ship in between doesn't reset that)
        search(used_ship="Drake Golem Ox")
        self.assertFalse(any("Ship changed" in note for note in notes))
        self.assertEqual(Store(self._helper).get_last_ship(), "Drake Golem Ox")

    def test_default_stop_count_comes_from_the_setting(self) -> None:
        config = self._helper.get_handler_config()
        self.assertEqual(self._search()[0]["stop_count"], 2)  # max_stops=2 given
        payload, _instant = CommodityRoute().execute(
            filter_start_location="Stanton One", filter_destination_location="Nyx One", available_cargo_space_scu=10, limit=1,
        )
        self.assertEqual(_parse_routes(payload)[0]["stop_count"], 1)
        config.get_behavior_commodity_route_default_max_stops = lambda: 2
        payload, _instant = CommodityRoute().execute(
            filter_start_location="Stanton One", filter_destination_location="Nyx One", available_cargo_space_scu=10, limit=1,
        )
        self.assertEqual(_parse_routes(payload)[0]["stop_count"], 2)

    def test_hud_text_lays_out_the_stop(self) -> None:
        route = {
            "path": "A -> B -> C", "estimated_profit": 1234567, "max_investment": 50000, "system_jumps": 1,
            "stops": [
                {"terminal": "Admin - Alpha", "location": "Hurston, Stanton", "buy": [
                    {"commodity": "Gold", "scu": 4, "total_aUEC": 40,
                     "volume_note": "SCU count limited to 4 (instead of 10) by estimated availability at buy location.",
                     "container_note": "Buy it in containers of at most 24 SCU: Admin - Charlie, where you sell it, takes no bigger ones.",
                     "sell_at": "Admin - Charlie"},
                ]},
                {"terminal": "Bravo", "location": "Crusader, Stanton"},
                {"terminal": "Admin - Charlie", "location": "Delamar, Nyx", "sell": [
                    {"commodity": "Gold", "scu": 4, "total_aUEC": 240},
                ]},
            ],
        }
        route["hold_scu"] = 10
        nl = chr(10)
        text = Store.hud_text({"route": route, "step": 1})
        self.assertIn("### Alpha" + nl + nl + "Stop 1 of 3 · Hurston, Stanton", text)
        # The route as the HUD's steps block: a jump where two stops are in different systems
        self.assertIn("```steps" + nl + "current | Alpha" + nl + "next | Bravo" + nl + "jump | Jump" + nl + "next | Charlie" + nl + "```", text)
        # The hold as the HUD's bar block: empty on arrival, Gold bought here
        self.assertIn("```bar" + nl + "max: 10" + nl + "Arriving" + nl + "Leaving | 4 accent" + nl + "legend | accent Buy here" + nl + "```", text)
        self.assertIn("| Buy | SCU | aUEC |" + nl + "|---|---:|---:|" + nl + "| **Gold** | 4 | 40 |", text)
        # Why that amount and why that container size, for this stop only
        self.assertIn("*Gold: only 4 in stock here (room for 10); max. 24 SCU containers, Charlie takes no bigger ones; "
                      "keep it aboard until Charlie.*", text)
        # The money and the next stop in one card
        self.assertIn("```stats" + nl + "Pay here | 40" + nl + "Profit | 1,234,567 | accent" + nl
                      + "**Next:** Bravo · Crusader, Stanton" + nl + "```", text)

        later = Store.hud_text({"route": route, "step": 3, "planned_profit": 1300000})
        self.assertIn("done | Alpha" + nl + "done | Bravo" + nl + "jump | Jump" + nl + "current | Charlie", later)
        self.assertIn("Arriving | 4 text", later)  # Gold is sold here
        self.assertNotIn("in stock here", later)  # the lines are about the current stop only
        self.assertIn("Planned | 1,300,000", later)
        self.assertIn("**Last stop** of the route.", later)

        gold = route["stops"][0]["buy"][0]
        gold.update(recorded=True, planned_aUEC=50)
        recorded = Store.hud_text({"route": route, "step": 1})
        self.assertIn("| **Gold** | **4** | **40** |", recorded)
        self.assertIn("Gold: paid 10 aUEC less than planned;", recorded)
        json.dumps(text)  # plain text, no objects


def main() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ActiveTradeRouteTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
