import asyncio

from skills.uexcorp.uexcorp import compression
from skills.uexcorp.uexcorp.active_trade_route import ActiveTradeRoute as ActiveTradeRouteStore
from skills.uexcorp.uexcorp.tool.tool import Tool
from skills.uexcorp.uexcorp.tool.validator import Validator


class ActiveTradeRoute(Tool):
    REQUIRES_AUTHENTICATION = False
    TOOL_NAME = "uex_active_trade_route"
    ACTIONS = ["set", "get", "next", "record_buy", "record_sell", "clear", "show_hud", "hide_hud"]

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
            active, problem, warnings = await asyncio.to_thread(store.record, side, commodity, scu, total_price)
            if problem:
                return problem, ""
            for warning in warnings:
                tool_handler.add_note(warning)
            await store.refresh_hud()
            tool_handler.add_note(
                f"Recorded: {'bought' if side == 'buy' else 'sold'} {scu:,} SCU {commodity} for {total_price:,} aUEC. "
                f"Route profit is now about {active['route']['estimated_profit']:,} aUEC."
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
        if step != active["step"]:
            profit = active["route"]["estimated_profit"]
            active = await asyncio.to_thread(store.go_to, step)
            if active is None:
                await store.refresh_hud()
                tool_handler.add_note(f"Trade route complete, estimated profit {profit:,} aUEC. It is no longer active.")
                return compression.dumps({"route_complete": True, "estimated_profit": profit}), ""

        await store.refresh_hud()
        return compression.dumps(store.for_ai(active, await asyncio.to_thread(store.is_hud_visible) and store.hud_available())), ""

    def get_mandatory_fields(self) -> dict[str, Validator]:
        return {
            "action": Validator(
                Validator.VALIDATE_ENUM,
                config={"enum": self.ACTIONS},
                prompt="set = start the route the user picked, get = where the user is, next = current stop is done, "
                       "record_buy/record_sell = the user bought/sold another amount or price than planned, clear = stop the run, "
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
                prompt="Move to this stop number (1 = start terminal) when the user is at another stop than current_stop.",
            ),
            "commodity": Validator(
                Validator.VALIDATE_STRING,
                prompt="For record_buy/record_sell: the commodity, as in instructions.",
            ),
            "scu": Validator(
                Validator.VALIDATE_NUMBER,
                config={"min": 0},
                prompt="For record_buy/record_sell: SCU the user really bought or sold.",
            ),
            "total_price": Validator(
                Validator.VALIDATE_NUMBER,
                config={"min": 0},
                prompt="For record_buy/record_sell: total aUEC the user really paid or got (not per SCU).",
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
            "and total_price; later stops and the profit adapt. "
            "5. User says the stop is done: call next and go on with 2. route_complete = say the run is finished with estimated_profit. "
            "cargo_aboard_on_arrival = what the user should have aboard when arriving. "
            "Call get, never guess, when the user asks where they are or the stop details are not in the conversation. "
            "Use stop_number if the user is at another stop than current_stop. Call clear when the user cancels the run."
        )
