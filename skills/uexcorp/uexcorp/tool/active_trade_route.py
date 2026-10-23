import asyncio

from skills.uexcorp.uexcorp import compression
from skills.uexcorp.uexcorp.active_trade_route import ActiveTradeRoute as ActiveTradeRouteStore
from skills.uexcorp.uexcorp.tool.tool import Tool
from skills.uexcorp.uexcorp.tool.validator import Validator


class ActiveTradeRoute(Tool):
    REQUIRES_AUTHENTICATION = False
    TOOL_NAME = "uex_active_trade_route"
    ACTIONS = [
        "set", "get", "next", "record_buy", "record_sell", "undo_buy", "undo_sell", "add_buy", "add_sell", "clear",
        "show_hud", "hide_hud",
    ]

    def __init__(self):
        super().__init__()

    async def execute(
        self,
        action: str,
        route_number: int | None = None,
        stop_number: int | None = None,
        commodity: str | None = None,
        scu: int | None = None,
        total_price: int | None = None,
        location: str | None = None,
        correction: bool | None = None,
    ) -> (str, str):
        store = ActiveTradeRouteStore(self._helper)
        tool_handler = self._helper.get_handler_tool()

        if action in ("show_hud", "hide_hud"):
            # An action, not a skill setting, so the Wingman always knows whether the route is on screen
            visible = action == "show_hud"
            await asyncio.to_thread(store.set_hud_visible, visible)
            shown = await store.refresh_hud()
            if not visible:
                return "The trade route is no longer shown on the HUD.", ""
            if not store.hud_available():
                return (
                    "The HUD is off (or this Wingman has no info panel), so the trade route can't be shown. "
                    "Tell the user: it appears as soon as they switch the HUD on in the settings.",
                    "",
                )
            active = await asyncio.to_thread(store.get)
            if not active:
                return "No active trade route yet: it will be shown on the HUD as soon as one is set.", ""
            if not shown:
                return "Showing the trade route on the HUD failed. Tell the user it may not be visible.", ""
            return f"The trade route is shown on the HUD (stop {active['step']} of {len(active['route']['stops'])}).", ""

        if action in ("record_buy", "record_sell"):
            if not commodity or scu is None or total_price is None:
                return f"For {action} pass commodity, scu and total_price (what the user really paid or got).", ""
            side = "buy" if action == "record_buy" else "sell"
            active, problem, warnings = await asyncio.to_thread(store.record, side, commodity, scu, total_price, bool(correction))
            if problem:
                return problem, ""
            for warning in warnings:
                tool_handler.add_note(warning)
            await store.refresh_hud()
            tool_handler.add_note(
                f"Recorded: {'bought' if side == 'buy' else 'sold'} {scu:,} SCU {commodity} for {total_price:,} aUEC. "
                f"Route profit is now about {active['route']['estimated_profit']:,} aUEC."
            )
            # Sold less than planned: the rest needs a buyer
            options = await asyncio.to_thread(store.sale_options, commodity)
            if options:
                tool_handler.add_note(options)
            return compression.dumps(store.for_ai(active, await asyncio.to_thread(store.is_hud_visible) and store.hud_available())), ""

        if action in ("undo_buy", "undo_sell"):
            if not commodity:
                return f"For {action} pass commodity, and scu to pick one of several recorded amounts.", ""
            side = "buy" if action == "undo_buy" else "sell"
            active, problem, notes = await asyncio.to_thread(store.undo, side, commodity, scu, stop_number)
            if problem:
                return problem, ""
            for note in notes:
                tool_handler.add_note(note)
            await store.refresh_hud()
            tool_handler.add_note(f"Route profit is now about {active['route']['estimated_profit']:,} aUEC.")
            return compression.dumps(store.for_ai(active, await asyncio.to_thread(store.is_hud_visible) and store.hud_available())), ""

        if action in ("add_buy", "add_sell"):
            if not location or not commodity:
                return f"For {action} pass location (where the user buys or sells) and commodity.", ""
            side = "buy" if action == "add_buy" else "sell"
            terminal, place, name, price, problem = await asyncio.to_thread(self.__terminal, location, commodity, side)
            if problem:
                return problem, ""
            add = store.add_buy if side == "buy" else store.add_sell
            active, problem, notes = await asyncio.to_thread(add, terminal, place, name, scu, price, total_price)
            if problem:
                return problem, ""
            for note in notes:
                tool_handler.add_note(note)
            await store.refresh_hud()
            tool_handler.add_note(
                f"{'Purchase' if side == 'buy' else 'Sale'} at {terminal} ({place}) added to the route"
                + (" and recorded" if total_price is not None else "")
                + f". Route profit is now about {active['route']['estimated_profit']:,} aUEC."
            )
            return compression.dumps(store.for_ai(active, await asyncio.to_thread(store.is_hud_visible) and store.hud_available())), ""

        if action == "clear":
            had_route = await asyncio.to_thread(store.clear)
            await store.refresh_hud()
            return "Active trade route removed." if had_route else "There was no active trade route.", ""

        if action == "set":
            if route_number is None:
                return "Pass route_number: the number of the route from the last uex_get_trade_routes result.", ""
            if not await asyncio.to_thread(store.set, route_number):
                count = await asyncio.to_thread(store.last_route_count)
                return (
                    f"No route {route_number} in the last search ({count} route(s)). Search again with uex_get_trade_routes.",
                    "",
                )

        active = await asyncio.to_thread(store.get)
        if not active:
            return "No active trade route. Set one after the user picks a route from uex_get_trade_routes.", ""

        step = active["step"]
        stop_count = len(active["route"]["stops"])
        if stop_number is not None and stop_number > stop_count:
            # Only next completes a run: a wrong stop number must not end it
            return f"The route has {stop_count} stops, there is no stop {stop_number}. The run is unchanged.", ""
        if stop_number is not None:
            step = stop_number
        elif action == "next":
            step += 1
        if step > stop_count and active.get("leftover_asked_at") != stop_count:
            leftover = store.leftover(active["route"])
            if leftover:
                # Cargo the user couldn't sell as planned: the run isn't over unless the user says so
                await asyncio.to_thread(store.ask_about_leftover)
                cargo = ", ".join(f"{scu_:,} SCU {name}" for name, scu_ in leftover.items())
                return (
                    f"Not finished: {cargo} still aboard after the last stop. Ask the user whether to sell it "
                    f"somewhere else (add_sell with location and commodity) or end the run anyway "
                    f"(then call next again).",
                    "",
                )
        if step != active["step"]:
            profit = active["route"]["estimated_profit"]
            active = await asyncio.to_thread(store.go_to, step)
            if active is None:
                await store.refresh_hud()
                tool_handler.add_note(f"Trade route complete, estimated profit {profit:,} aUEC. It is no longer active.")
                return compression.dumps({"route_complete": True, "estimated_profit": profit}), ""

        await store.refresh_hud()
        return compression.dumps(store.for_ai(active, await asyncio.to_thread(store.is_hud_visible) and store.hud_available())), ""

    @staticmethod
    def __terminal(place: str, commodity: str, side: str) -> tuple[str | None, str | None, str | None, float | None, str | None]:
        """(terminal, location, commodity name, price per SCU, None) of the terminal at a place with the best
        price for the commodity (most paid when selling, least asked when buying), or (None, ..., why not).
        A single terminal UEX has no price for is taken unpriced."""
        from skills.uexcorp.uexcorp.data_access.commodity_price_data_access import CommodityPriceDataAccess
        from skills.uexcorp.uexcorp.data_access.terminal_data_access import TerminalDataAccess

        terminals = {
            t.get_id(): t for t in TerminalDataAccess().add_filter_by_location_name_whitelist(place).add_filter_by_type("commodity").load()
        }
        if not terminals:
            return None, None, None, None, f"No commodity terminal at {place}."
        prices = CommodityPriceDataAccess().add_filter_by_id_terminal(list(terminals))
        prices = prices.add_filter_by_is_sellable(True) if side == "sell" else prices.add_filter_by_is_buyable(True)
        prices = [p for p in prices.load() if (p.get_commodity_name() or "").lower() == commodity.strip().lower()]

        def price(p) -> float:
            return p.get_price_sell() if side == "sell" else -p.get_price_buy()

        # A blacklisted terminal only when the user named no other
        prices.sort(key=lambda p: (not terminals[p.get_id_terminal()].get_is_blacklisted(), price(p)), reverse=True)
        if prices:
            best = prices[0]
            terminal, name = terminals[best.get_id_terminal()], best.get_commodity_name()
            per_scu = best.get_price_sell() if side == "sell" else best.get_price_buy()
        elif len(terminals) == 1:
            terminal, name, per_scu = next(iter(terminals.values())), commodity.strip(), None
        else:
            return None, None, None, None, (
                f"UEX knows no terminal at {place} that {'buys' if side == 'sell' else 'sells'} {commodity}. "
                f"uex_get_commodity_information shows where it is traded."
            )
        place_name = terminal.get_planet_name() or terminal.get_orbit_name()
        location = ", ".join(part for part in (place_name, terminal.get_star_system_name()) if part)
        return str(terminal), location, name, per_scu, None

    def get_mandatory_fields(self) -> dict[str, Validator]:
        return {
            "action": Validator(
                Validator.VALIDATE_ENUM,
                config={"enum": self.ACTIONS},
                prompt="set = start the route the user picked, get = where the user is, next = current stop is done, "
                       "record_buy/record_sell = the user bought/sold another amount or price than planned, "
                       "undo_buy/undo_sell = take back a purchase/sale recorded by mistake, "
                       "add_buy/add_sell = a purchase/sale the plan doesn't have (another place, or a later stop), "
                       "clear = stop the run, "
                       "show_hud/hide_hud = only when the user asks to show or hide the route on the HUD (stays on for later routes).",
            ),
        }

    def get_optional_fields(self) -> dict[str, Validator]:
        return {
            "route_number": Validator(
                Validator.VALIDATE_NUMBER,
                config={"min": 1},
                prompt="For set: route_number of the picked route in the last uex_get_trade_routes result.",
            ),
            "stop_number": Validator(
                Validator.VALIDATE_NUMBER,
                config={"min": 1},
                prompt="Move to this stop number (1 = start terminal) when the user is at another stop than current_stop. "
                       "For undo_buy/undo_sell: the stop it was recorded at, if not current_stop.",
            ),
            "commodity": Validator(
                Validator.VALIDATE_STRING,
                prompt="For record_*, undo_*, add_*: the commodity, as in instructions or cargo_aboard_on_arrival.",
            ),
            "scu": Validator(
                Validator.VALIDATE_NUMBER,
                config={"min": 0},
                prompt="For record_buy/record_sell: SCU the user really bought or sold. For undo_buy/undo_sell: SCU of "
                       "the recorded purchase/sale to take back, leave out for the last one. For add_buy: SCU bought. "
                       "For add_sell: SCU to sell, leave out for all that no stop sells.",
            ),
            "total_price": Validator(
                Validator.VALIDATE_NUMBER,
                config={"min": 0},
                prompt="For record_buy/record_sell: total aUEC the user really paid or got (not per SCU). For "
                       "add_buy/add_sell: only when it is done already (records it).",
            ),
            "correction": Validator(
                Validator.VALIDATE_BOOL,
                prompt="For record_buy/record_sell: true only to fix an amount recorded wrong before at this stop "
                       "(replaces it). Leave out for a new purchase or sale: it adds to the recorded ones.",
            ),
            "location": Validator(
                Validator.VALIDATE_LOCATION,
                config={"for_trading": True},
                prompt="For add_buy/add_sell: the terminal or place, e.g. \"Area18\" or a later stop of the route. A place "
                       "with several terminals takes the one with the best price.",
            ),
        }

    def get_description(self) -> str:
        return (
            "The trade route the user is flying, with the current stop. Set it when the user picks a route, "
            "move on with next when a stop is done, get it when the details are no longer in the conversation."
        )

    def get_prompt(self) -> str:
        return (
            "Guides the user through the trade route they picked, one stop at a time, unless they ask for the whole route. "
            "1. User picks a route (e.g. 'take route 2'): call set with its route_number. "
            "2. Check the user is at current_stop: from the conversation or game events; if unclear, ask. "
            "Not there yet: only say where to fly (terminal and location). "
            "3. At the stop: say every line of instructions with its SCU and aUEC as written, then each of notes as its "
            "own fact (they are unrelated to each other). Price per SCU only when asked. Asked why (e.g. a container "
            "limit): give only the reason the note states, never one of your own. "
            "4. User paid, got or moved another amount than planned: call record_buy or record_sell with commodity, scu "
            "and total_price of that one purchase or sale; several at one stop add up. Later stops and the profit adapt. "
            "5. User says the stop is done: call next and go on with 2. route_complete = say the run is finished with estimated_profit. "
            "6. User couldn't sell cargo as planned: record_sell the real amount, ask where to sell the rest and call "
            "add_sell. User buys or sells somewhere the route doesn't plan it: add_buy/add_sell, with total_price if done. "
            "money = what the sales at this stop bring and its purchases cost: judge what the user can afford from it, "
            "never from the money of the route search. "
            "cargo_aboard_on_arrival = what the user should have aboard when arriving. "
            "Call get, never guess, when the user asks where they are or the stop details are not in the conversation. "
            "Use stop_number if the user is at another stop than current_stop. Call clear when the user cancels the run."
        )
