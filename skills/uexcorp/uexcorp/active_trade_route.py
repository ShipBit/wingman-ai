"""The trade route the player is flying, with a cursor on the current stop.

Kept in a file outside the versioned data folder: the conversation history can lose old tool
responses (Core clears them when it gets long) and Core can restart (or update) mid-run, but
the player still needs the next stop.
"""

import asyncio
import json
import os
import re
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from skills.uexcorp.uexcorp.helper import Helper

HUD_TITLE = "Trade run"
# "SCU count limited to 69 (instead of 399) by estimated availability at buy location."
VOLUME_NOTE = re.compile(r"limited to (\d+) \(instead of (\d+)\) by estimated availability at (buy|sell|sell and buy) location")
# "SCU count limited to 2044 (instead of 2200) by available money (4,987,363 aUEC left for it at this stop)."
# Older notes (stored runs) said "X aUEC at this stop"; the rest may be kept for a later stop's purchases
MONEY_NOTE = re.compile(
    r"limited to (\d+) \(instead of (\d+)\) by available money \(([\d,]+) aUEC(?: left for it)?(?: at this stop)?"
    r"(?:, the rest is kept for the purchases at (.+))?\)\.?$"
)

# Reentrant: the methods hold it across load and save, and the file access takes it too
_lock = threading.RLock()

# The container notes of uex_get_trade_routes (CommodityRoute.__container_note), short for the HUD
_CONTAINER_NOTES = (
    (re.compile(r"at most (\d+) SCU: (.+), where you sell it, takes no bigger ones"),
     lambda m, here: f"max. {m[1]} SCU containers, {_short(m[2])} takes no bigger ones"),
    (re.compile(r"at most (\d+) SCU: bigger ones don't fit the (.+)\."),
     lambda m, here: f"max. {m[1]} SCU containers, bigger ones don't fit the {m[2]}"),
)


def _short(terminal: str) -> str:
    return terminal.removeprefix("Admin - ")


def _system(stop: dict) -> str:
    """The star system of a stop: the last part of its location ("MicroTech, Stanton")."""
    return (stop.get("location") or "").split(",")[-1].strip()


def _profit(stops: list[dict]) -> int:
    return round(
        sum(e["total_aUEC"] for s in stops for e in s.get("sell", []))
        - sum(e["total_aUEC"] for s in stops for e in s.get("buy", []))
    )


def _jumps(stops: list[dict]) -> int:
    """Changes of star system between stops (two systems without a direct gate count once)."""
    return sum(_system(a) != _system(b) for a, b in zip(stops, stops[1:]))


def _container_reason(note: str, here: str) -> str | None:
    for pattern, text in _CONTAINER_NOTES:
        match = pattern.search(note)
        if match:
            return text(match, here)
    return note.rstrip(".") or None


def _deviation(entry: dict, key: str) -> list[str]:
    """How a recorded trade differs from the plan. Another amount is compared per SCU: a total for fewer
    SCU is lower even at a worse price."""
    planned_scu, planned_price = entry.get("planned_trade_scu"), entry.get("planned_price_per_scu")
    if planned_scu is None or not planned_price or entry["scu"] == planned_scu:
        planned = entry.get("planned_aUEC")
        if planned is None or planned == entry["total_aUEC"]:
            return []
        difference = entry["total_aUEC"] - planned
        verb = "got" if key == "sell" else "paid"
        return [f"{verb} {abs(difference):,} aUEC {'more' if difference > 0 else 'less'} than planned"]
    parts = [f"{'sold' if key == 'sell' else 'bought'} {entry['scu']:,} SCU instead of {planned_scu:,}"]
    if entry["scu"]:
        difference = entry["total_aUEC"] / entry["scu"] - planned_price
        if abs(difference) >= 1:
            parts.append(f"{abs(difference):,.0f} aUEC {'more' if difference > 0 else 'less'} per SCU than planned")
    return parts


class ActiveTradeRoute:
    FILE_NAME = "active_trade_route.json"

    def __init__(self, helper: "Helper"):
        self.__helper = helper
        self.__path = os.path.join(helper.get_state_path(), self.FILE_NAME)

    # ---- storage

    def __load(self) -> dict:
        with _lock:
            try:
                with open(self.__path, "r", encoding="utf-8") as file:
                    state = json.load(file)
            except (OSError, ValueError):
                return {}
            # Valid JSON of another shape (e.g. []) would break every later call
            return state if isinstance(state, dict) else {}

    def __save(self, state: dict) -> None:
        # A new file swapped in: a crash while writing never leaves a half-written run behind
        with _lock:
            temporary = self.__path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as file:
                json.dump(state, file)
            os.replace(temporary, self.__path)

    def remember_search(self, routes: list[dict]) -> None:
        """The routes of the last search, so the player can pick one by its number."""
        with _lock:
            state = self.__load()
            state["last_routes"] = routes
            self.__save(state)

    def last_route_count(self) -> int:
        return len(self.__load().get("last_routes", []))

    def set(self, route_number: int) -> bool:
        with _lock:
            state = self.__load()
            routes = state.get("last_routes", [])
            if not 1 <= route_number <= len(routes):
                return False
            route = routes[route_number - 1]
            state["active"] = {"route": route, "step": 1, "planned_profit": route.get("estimated_profit")}
            self.__save(state)
            return True

    def get(self) -> dict | None:
        return self.__load().get("active")

    def go_to(self, step: int) -> dict | None:
        """Moves the cursor; past the last stop the route is complete and removed."""
        with _lock:
            state = self.__load()
            active = state.get("active")
            if not active:
                return None
            if step > len(active["route"]["stops"]):
                state.pop("active")
            else:
                active["step"] = max(1, step)
            self.__save(state)
            return state.get("active")

    def record(
        self, side: str, commodity: str, scu: int, total_price: float, correction: bool = False
    ) -> tuple[dict | None, str | None, list[str]]:
        """What the user really bought or sold at the current stop (prices and stock differ from UEX's).
        Each call is one purchase or sale and adds to those recorded before at this stop (cargo is often
        bought in several goes); a correction replaces them. A purchase changes the later sale of that
        cargo by the same SCU; the route profit follows.
        Returns (active route, None, notes) or (None, why not, []). Amounts that don't add up (more
        than the hold, more sold than aboard) are recorded anyway, the user saw the real numbers, but
        come with a warning to check them."""
        with _lock:
            state = self.__load()
            active = state.get("active")
            if not active:
                return None, "No active trade route.", []
            stops = active["route"]["stops"]
            index = active["step"] - 1
            stop = stops[index]
            entries, problem = self.__entries(stops, index, side, commodity)
            if problem:
                return None, problem, []
            entry = entries[0]
            warnings = []
            transactions = [{"scu": int(scu), "total_aUEC": round(total_price)}]
            if entry.get("recorded") and not correction:
                transactions = self.__transactions(entries) + transactions
                warnings.append(
                    f"Added to what was recorded here before: {'bought' if side == 'buy' else 'sold'} "
                    f"{sum(t['scu'] for t in transactions):,} SCU {entry['commodity']} for "
                    f"{sum(t['total_aUEC'] for t in transactions):,} aUEC in all at this stop."
                )
            warnings += self.__apply(stops, index, entries, transactions)
            scu = sum(t["scu"] for t in transactions)
            aboard = {c["commodity"]: c["scu"] for c in self.cargo_on_arrival(active)}
            if side == "sell" and int(scu) > aboard.get(entry["commodity"], 0):
                warnings.append(
                    f"{int(scu):,} SCU {entry['commodity']} sold, but only {aboard.get(entry['commodity'], 0):,} SCU "
                    f"should be aboard: check the amount with the user."
                )
            hold = active["route"].get("hold_scu")
            if hold:
                sold = {e["commodity"]: e["scu"] for e in stop.get("sell", [])}
                leaving = sum(max(0, scu_ - sold.get(name, 0)) for name, scu_ in aboard.items())
                leaving += sum(e["scu"] for e in stop.get("buy", []))
                if leaving > hold:
                    warnings.append(
                        f"With this, {leaving:,} SCU would be aboard, but the hold of the route's ship takes {hold:,} SCU: "
                        f"check the amount with the user."
                    )
            active["route"]["estimated_profit"] = _profit(stops)
            self.__save(state)
            return active, None, warnings

    def undo(
        self, side: str, commodity: str, scu: int | None = None, stop_number: int | None = None
    ) -> tuple[dict | None, str | None, list[str]]:
        """Takes back one recorded purchase or sale (the last one, or the last of that SCU) at the current
        stop or stop_number. With none left, the plan's amount and price are back.
        Returns (active route, None, notes) or (None, why not, [])."""
        with _lock:
            state = self.__load()
            active = state.get("active")
            if not active:
                return None, "No active trade route.", []
            stops = active["route"]["stops"]
            index = (stop_number or active["step"]) - 1
            if not 0 <= index < len(stops):
                return None, f"The route has {len(stops)} stops, there is no stop {index + 1}.", []
            entries, _ = self.__entries(stops, index, side, commodity)
            terminal = stops[index]["terminal"]
            if not entries or not entries[0].get("recorded"):
                recorded = [n for n, s in enumerate(stops, 1) for e in s.get(side, [])
                            if e["commodity"].lower() == commodity.strip().lower() and e.get("recorded")]
                hint = f" It is recorded at stop {recorded[0]}: pass stop_number {recorded[0]}." if recorded else ""
                return None, f"No {side} of {commodity} is recorded at stop {index + 1}, {terminal}.{hint}", []
            name = entries[0]["commodity"]
            transactions = self.__transactions(entries)
            matching = [i for i, t in enumerate(transactions) if scu is None or t["scu"] == scu]
            if not matching:
                listed = ", ".join(f"{t['scu']:,} SCU for {t['total_aUEC']:,} aUEC" for t in transactions)
                return None, f"No recorded {side} of {scu:,} SCU {name} at {terminal} (recorded: {listed}).", []
            removed = transactions.pop(matching[-1])
            verb = "purchase" if side == "buy" else "sale"
            notes = [f"Removed the {verb} of {removed['scu']:,} SCU {name} for {removed['total_aUEC']:,} aUEC at {terminal}."]
            if transactions:
                notes += self.__apply(stops, index, entries, transactions)
                notes.append(
                    f"Still recorded there: {sum(t['scu'] for t in transactions):,} SCU for "
                    f"{sum(t['total_aUEC'] for t in transactions):,} aUEC."
                )
            else:
                notes += self.__restore_plan(stops, index, entries)
                notes.append(f"Nothing recorded there anymore: the plan's {sum(e['scu'] for e in entries):,} SCU are back.")
            active["route"]["estimated_profit"] = _profit(stops)
            self.__save(state)
            return active, None, notes

    @staticmethod
    def __entries(stops: list[dict], index: int, side: str, commodity: str) -> tuple[list[dict], str | None]:
        """The entries of a commodity at a stop. One commodity can have two buys at a stop (part sold at
        one stop, the rest at another): a recorded amount fills them in order."""
        stop = stops[index]
        entries = [e for e in stop.get(side, []) if e["commodity"].lower() == commodity.strip().lower()]
        if entries:
            return entries, None
        planned = ", ".join(e["commodity"] for e in stop.get(side, [])) or "nothing"
        problem = f"The plan has no {side} of {commodity} at stop {index + 1}, {stop['terminal']} (planned: {planned})."
        elsewhere = [
            (number, other["terminal"]) for number, other in enumerate(stops, 1)
            if any(e["commodity"].lower() == commodity.strip().lower() for e in other.get(side, []))
        ]
        if elsewhere:
            number, terminal = elsewhere[0]
            problem += f" It is planned at stop {number}, {terminal}."
            if number > index + 1:
                problem += " If the user is there now, call next until that stop is current, then record it."
        return [], problem

    @staticmethod
    def __transactions(entries: list[dict]) -> list[dict]:
        """The recorded purchases or sales; a run recorded before they were kept counts as one."""
        return list(entries[0].get("transactions") or [
            {"scu": sum(e["scu"] for e in entries), "total_aUEC": sum(e["total_aUEC"] for e in entries)}
        ])

    def __apply(self, stops: list[dict], index: int, entries: list[dict], transactions: list[dict]) -> list[str]:
        """Sets the entries to the sum of the transactions; the last entry takes what the plan's split leaves."""
        scu = sum(t["scu"] for t in transactions)
        total_price = sum(t["total_aUEC"] for t in transactions)
        warnings = []
        left = scu
        for number, part in enumerate(entries):
            # The plan's split, also when an earlier recording changed the parts
            part_scu = left if number == len(entries) - 1 else min(left, part.get("planned_trade_scu", part["scu"]))
            left -= part_scu
            delta = part_scu - part["scu"]
            part.setdefault("planned_aUEC", part["total_aUEC"])  # what UEX expected, for the HUD
            # The plan at the time of recording (a sale already follows a changed purchase)
            part.setdefault("planned_trade_scu", part["scu"])
            part.setdefault("planned_price_per_scu", part.get("price_per_scu"))
            part.update(scu=part_scu, total_aUEC=round(total_price * part_scu / scu) if scu else 0, recorded=True)
            if scu:
                part["price_per_scu"] = round(total_price / scu, 2)
            warnings += self.__shift_sale(stops, index, part, delta)
        entries[0]["transactions"] = transactions
        return warnings

    def __restore_plan(self, stops: list[dict], index: int, entries: list[dict]) -> list[str]:
        warnings = []
        for part in entries:
            planned = part.get("planned_trade_scu", part["scu"])
            delta = planned - part["scu"]
            part.update(scu=planned, total_aUEC=part.get("planned_aUEC", part["total_aUEC"]),
                        price_per_scu=part.get("planned_price_per_scu", part.get("price_per_scu")))
            part.pop("recorded", None)
            part.pop("transactions", None)
            warnings += self.__shift_sale(stops, index, part, delta)
        return warnings

    def __shift_sale(self, stops: list[dict], index: int, part: dict, delta: int) -> list[str]:
        """A purchase of delta SCU more (or less) is sold later: that sale changes by the same SCU."""
        if not delta or not any(e is part for e in stops[index].get("buy", [])):
            return []
        sale_stop, sale = self.__sale_of(stops[index + 1:], part)
        if not sale or sale.get("recorded"):
            return []
        sale.setdefault("planned_scu", sale["scu"])
        sale["scu"] = max(0, sale["scu"] + delta)
        sale["total_aUEC"] = round(sale["scu"] * sale["price_per_scu"])
        if sale["scu"] > sale["planned_scu"]:
            unknown = " (UEX has no demand figure there)" if sale.get("demand_unknown") else ""
            return [f"{sale_stop['terminal']} was planned to take {sale['planned_scu']:,} SCU {sale['commodity']}, "
                    f"now {sale['scu']:,}: it may take less{unknown}."]
        return []

    def add_sell(
        self, terminal: str, location: str, commodity: str, scu: int | None, price_per_scu: float | None,
        total_price: float | None = None,
    ) -> tuple[dict | None, str | None, list[str]]:
        """A sale the plan doesn't have: for cargo the user couldn't sell as planned. It goes to the stop of
        that terminal from the current one on (the cargo stays aboard until then), else to a new stop right
        after the current one. Without scu it sells what no stop sells; more is taken off the later sales
        of it, the nearest first. With total_price the sale is done already and recorded.
        Returns (active route, None, notes) or (None, why not, [])."""
        with _lock:
            state = self.__load()
            active = state.get("active")
            if not active:
                return None, "No active trade route.", []
            route, step = active["route"], active["step"]
            stops = route["stops"]
            existing = next((n for n in range(step, len(stops) + 1) if stops[n - 1]["terminal"] == terminal), None)
            number = existing or step + 1
            aboard = {c["commodity"].lower(): c for c in self.cargo_on_arrival({"route": route, "step": number})}
            cargo = aboard.get(commodity.strip().lower())
            if not cargo:
                listed = ", ".join(f"{c['scu']:,} SCU {c['commodity']}" for c in aboard.values()) or "nothing"
                return None, (
                    f"The plan has no {commodity} aboard by then (aboard: {listed}). If the user sold less than "
                    f"planned, call record_sell with the real amount first, then add_sell."
                ), []
            name = cargo["commodity"]
            # The later sales of this cargo: up to the next stop that buys more of it
            later = []
            for n, s in enumerate(stops[number - 1:], number):
                later += [(n, s, e) for e in s.get("sell", []) if e["commodity"] == name]
                if any(e["commodity"] == name for e in s.get("buy", [])):
                    break
            spare = min(self.leftover(route).get(name, 0), cargo["scu"])
            if scu is None:
                if spare <= 0:
                    planned = ", ".join(f"{e['scu']:,} SCU at stop {n}, {s['terminal']}" for n, s, e in later)
                    return None, (
                        f"All {cargo['scu']:,} SCU {name} aboard are planned for sale ({planned}). To sell some at "
                        f"{terminal} instead, pass scu: the later sale shrinks by that."
                    ), []
                scu = spare
            if scu <= 0:
                return None, "scu must be more than 0.", []
            if scu > cargo["scu"]:
                return None, f"Only {cargo['scu']:,} SCU {name} should be aboard by then.", []

            entry = None
            if existing:
                entry = next((e for e in stops[existing - 1].get("sell", []) if e["commodity"] == name), None)
                if entry and (entry.get("recorded") or total_price is not None):
                    return None, (
                        f"{terminal} (stop {existing}) has a sale of {name} already. When the user is there, "
                        f"call record_sell with what was sold: it adds to the recorded one."
                    ), []
            notes = []
            # Cargo the plan sells later is sold here instead
            excess = scu - max(0, spare)
            for n, s, e in later:
                if excess <= 0:
                    break
                if e is entry or e.get("recorded"):
                    continue
                taken = min(excess, e["scu"])
                excess -= taken
                e.setdefault("planned_scu", e["scu"])
                e["scu"] -= taken
                e["total_aUEC"] = round(e["scu"] * e["price_per_scu"])
                # Numbered as after the new stop is in
                notes.append(f"Stop {n + (not existing)}, {s['terminal']}, now sells {e['scu']:,} SCU {name} instead of {e['scu'] + taken:,}.")
            if excess > 0:
                return None, (
                    f"At most {scu - excess:,} SCU {name} more can be sold at {terminal}: the rest aboard is sold "
                    f"there already or recorded as sold."
                ), []

            jumps_before = _jumps(stops)
            if entry:
                entry.setdefault("planned_scu", entry["scu"])
                entry["scu"] += scu
                entry["total_aUEC"] = round(entry["scu"] * entry["price_per_scu"])
                index = existing - 1
            else:
                entry = self.__new_entry(name, scu, price_per_scu, terminal, "record_sell")
                index = self.__place(stops, step, existing, terminal, location, "sell", entry)
            self.__drop_empty_stops(stops, index + 1, terminal, notes)
            if total_price is not None:
                notes += self.__apply(stops, index, [entry], [{"scu": int(scu), "total_aUEC": round(total_price)}])
            return self.__finish(state, index, total_price, jumps_before, notes)

    def add_buy(
        self, terminal: str, location: str, commodity: str, scu: int, price_per_scu: float | None,
        total_price: float | None = None,
    ) -> tuple[dict | None, str | None, list[str]]:
        """A purchase the plan doesn't have: at the stop of that terminal from the current one on, else at a
        new stop right after the current one. The later sale of the commodity takes it. With total_price
        the purchase is done already and recorded.
        Returns (active route, None, notes) or (None, why not, [])."""
        with _lock:
            state = self.__load()
            active = state.get("active")
            if not active:
                return None, "No active trade route.", []
            if not scu or scu <= 0:
                return None, "For add_buy pass scu, the SCU bought (or to buy).", []
            route, step = active["route"], active["step"]
            stops = route["stops"]
            existing = next((n for n in range(step, len(stops) + 1) if stops[n - 1]["terminal"] == terminal), None)
            if existing and any(e["commodity"].lower() == commodity.strip().lower() for e in stops[existing - 1].get("buy", [])):
                return None, (
                    f"{terminal} (stop {existing}) has a purchase of {commodity} planned already. When the user is "
                    f"there, call record_buy with what was bought: purchases add up."
                ), []
            name = next((e["commodity"] for s in stops for k in ("buy", "sell") for e in s.get(k, [])
                         if e["commodity"].lower() == commodity.strip().lower()), commodity.strip())
            jumps_before = _jumps(stops)
            entry = self.__new_entry(name, scu, price_per_scu, terminal, "record_buy")
            index = self.__place(stops, step, existing, terminal, location, "buy", entry)
            # The later sale of it takes the cargo
            notes = self.__shift_sale(stops, index, entry, scu)
            if not self.__sale_of(stops[index + 1:], entry)[1]:
                notes.append(f"No later stop sells {name}: add a sale for it with add_sell, or it stays aboard.")
            if total_price is not None:
                notes += self.__apply(stops, index, [entry], [{"scu": int(scu), "total_aUEC": round(total_price)}])
            return self.__finish(state, index, total_price, jumps_before, notes)

    @staticmethod
    def __new_entry(name: str, scu: int, price_per_scu: float | None, terminal: str, record_action: str) -> dict:
        entry = {"commodity": name, "scu": scu, "total_aUEC": round(scu * (price_per_scu or 0)),
                 "price_per_scu": price_per_scu or 0}
        if not price_per_scu:
            entry["warnings"] = [f"UEX has no price for {name} at {terminal}: record the real one with {record_action}."]
        return entry

    @staticmethod
    def __place(stops: list[dict], step: int, existing: int | None, terminal: str, location: str, side: str, entry: dict) -> int:
        """Puts the entry at the existing stop, or at a new one right after the current stop. Returns its index."""
        if existing:
            stops[existing - 1].setdefault(side, []).append(entry)
            return existing - 1
        stops.insert(step, {"terminal": terminal, "location": location, side: [entry]})
        return step

    @staticmethod
    def __drop_empty_stops(stops: list[dict], first_index: int, terminal: str, notes: list[str]) -> None:
        """A later stop with nothing left to do is no longer flown to."""
        for index in range(len(stops) - 1, first_index - 1, -1):
            stop = stops[index]
            stop["sell"] = [e for e in stop.get("sell", []) if e["scu"] or e.get("recorded")]
            if not stop["sell"]:
                stop.pop("sell")
                if not stop.get("buy"):
                    stops.pop(index)
                    notes.append(f"{stop['terminal']} is dropped from the route: nothing is left to sell there.")
                    for s in stops:
                        for buy in s.get("buy", []):
                            if buy.get("sell_at") == stop["terminal"]:
                                buy["sell_at"] = terminal

    def __finish(
        self, state: dict, index: int, total_price: float | None, jumps_before: int, notes: list[str]
    ) -> tuple[dict, None, list[str]]:
        """Route summary, hold check and save after a trade was added at stop index."""
        active = state["active"]
        route = active["route"]
        stops = route["stops"]
        if total_price is not None and active["step"] != index + 1:
            # Done there already: the user is at that stop
            active["step"] = index + 1
            notes.append(f"Stop {index + 1}, {stops[index]['terminal']}, is the current stop now.")
        route["path"] = " -> ".join(s["terminal"] for s in stops)
        route["systems"] = " -> ".join(
            system for i, system in enumerate(map(_system, stops)) if i == 0 or _system(stops[i - 1]) != system
        )
        route["stop_count"] = len(stops) - 1
        if "system_jumps" in route:
            route["system_jumps"] = max(0, route["system_jumps"] + _jumps(stops) - jumps_before)
        route["estimated_profit"] = _profit(stops)
        notes += self.hold_warnings(active)
        self.__save(state)
        return active, None, notes

    @classmethod
    def leftover(cls, route: dict) -> dict[str, int]:
        """Cargo no stop sells: still aboard after the last one."""
        return {c["commodity"]: c["scu"] for c in cls.cargo_on_arrival({"route": route, "step": len(route["stops"]) + 1})}

    @classmethod
    def hold_warnings(cls, active: dict) -> list[str]:
        """The first stop from the current one on that the route's ship would leave overloaded."""
        hold = active["route"].get("hold_scu")
        stops = active["route"]["stops"]
        for number in range(active["step"], len(stops) + 1):
            leaving = sum(c["scu"] for c in cls.cargo_on_arrival({"route": active["route"], "step": number + 1}))
            if hold and leaving > hold:
                return [f"Leaving stop {number}, {stops[number - 1]['terminal']}, {leaving:,} SCU would be aboard, but the "
                        f"hold takes {hold:,} SCU: buy less there or sell some earlier."]
        return []

    def sale_options(self, commodity: str) -> str | None:
        """For cargo the user couldn't sell as planned: how much stays aboard and the later stops that buy it."""
        active = self.get()
        if not active:
            return None
        name = next((n for n in self.leftover(active["route"]) if n.lower() == commodity.strip().lower()), None)
        if not name:
            return None
        stops = active["route"]["stops"]
        later = [f"stop {n}, {s['terminal']}" for n, s in enumerate(stops, 1)
                 if n > active["step"] and any(e["commodity"] == name for e in s.get("sell", []))]
        return (
            f"{self.leftover(active['route'])[name]:,} SCU {name} stay aboard that no stop sells. Ask the user where to "
            f"sell it, then call add_sell" + (f": a later stop of the route buys it ({', '.join(later)}), " if later else ": ")
            + "uex_get_commodity_information shows other places."
        )

    def ask_about_leftover(self) -> None:
        """Remembers that the user was asked about cargo still aboard after the last stop: the next
        next ends the run anyway."""
        with _lock:
            state = self.__load()
            active = state.get("active")
            if active:
                active["leftover_asked_at"] = len(active["route"]["stops"])
                self.__save(state)

    @staticmethod
    def __sale_of(later_stops: list[dict], buy: dict) -> tuple[dict | None, dict | None]:
        """The later stop and sell entry where a buy is sold: at its `sell_at` terminal, or (none
        given) the next stop that sells the commodity."""
        target = buy.get("sell_at")
        first = (None, None)
        for later in later_stops:
            sale = next((e for e in later.get("sell", []) if e["commodity"] == buy["commodity"]), None)
            if not sale:
                continue
            if not target or later.get("terminal") == target:
                return later, sale
            if first[0] is None:
                first = (later, sale)
        return first

    def get_last_ship(self) -> str | None:
        return self.__load().get("last_ship")

    def get_pending_ship(self) -> str | None:
        """A ship searched with once that differs from the remembered one, not confirmed yet."""
        return self.__load().get("pending_ship")

    def remember_ship(self, ship: str) -> bool:
        """Remember the ship of a search. A ship other than the last one is only taken on its second
        search in a row: a model may have guessed it. Returns False while it waits for that."""
        with _lock:
            state = self.__load()
            confirmed = state.get("last_ship") in (None, ship) or state.get("pending_ship") == ship
            if confirmed:
                state["last_ship"] = ship
                state.pop("pending_ship", None)
            else:
                state["pending_ship"] = ship
            self.__save(state)
            return confirmed

    def set_hud_visible(self, visible: bool) -> None:
        with _lock:
            state = self.__load()
            state["hud_visible"] = visible
            self.__save(state)

    def is_hud_visible(self) -> bool:
        return bool(self.__load().get("hud_visible", False))

    def clear(self) -> bool:
        with _lock:
            state = self.__load()
            had_route = state.pop("active", None) is not None
            self.__save(state)
            return had_route

    def prompt_note(self, tool_name: str) -> str:
        """One line for the skill prompt while a run is active, "" otherwise."""
        active = self.get()
        try:
            stops = active["route"]["stops"]
            stop = stops[active["step"] - 1]
            return (
                f"Active trade run: stop {active['step']} of {len(stops)} is {stop['terminal']}. "
                f"Call {tool_name} with action get before you guide the user on it, never guess its stops."
            )
        except (KeyError, IndexError, TypeError):
            return ""

    # ---- views

    @staticmethod
    def cargo_on_arrival(active: dict) -> list[dict]:
        """What should be aboard when the player reaches the current stop."""
        aboard: dict[str, int] = {}
        for stop in active["route"]["stops"][: active["step"] - 1]:
            for sale in stop.get("sell", []):
                aboard[sale["commodity"]] = aboard.get(sale["commodity"], 0) - sale["scu"]
            for buy in stop.get("buy", []):
                aboard[buy["commodity"]] = aboard.get(buy["commodity"], 0) + buy["scu"]
        return [{"commodity": name, "scu": scu} for name, scu in aboard.items() if scu > 0]

    @classmethod
    def for_ai(cls, active: dict, hud_visible: bool) -> dict:
        route, step = active["route"], active["step"]
        stops = route["stops"]
        summary_keys = ("path", "systems", "estimated_profit", "max_investment", "system_jumps", "warning")
        stop = stops[step - 1]
        instructions, notes = cls.stop_instructions(stop)
        return {
            "route": {key: route[key] for key in summary_keys if key in route},
            "step": step,
            "step_count": len(stops),
            "current_stop": {"terminal": stop["terminal"], "location": stop["location"]},
            # Ready-made sentences: a small model relays them reliably, it drops numbers from raw data
            "instructions": instructions,
            "notes": notes,
            "cargo_aboard_on_arrival": cls.cargo_on_arrival(active),
            "money": cls.money_text(active),
            "next_stop": stops[step]["terminal"] if step < len(stops) else None,
            "shown_on_hud": hud_visible,
        }

    @staticmethod
    def money(active: dict) -> tuple[int, int, int]:
        """(received at the current stop, paid there, the run's balance after it: below 0 = still invested)."""
        stops = active["route"]["stops"]
        stop = stops[active["step"] - 1]
        return (sum(e["total_aUEC"] for e in stop.get("sell", [])), sum(e["total_aUEC"] for e in stop.get("buy", [])),
                _profit(stops[: active["step"]]))

    @classmethod
    def money_text(cls, active: dict) -> str:
        """The money at the current stop as a sentence: the sales here pay for the purchases here."""
        received, paid, balance = cls.money(active)
        parts = []
        if received:
            parts.append(f"sales here bring about {received:,} aUEC" + (" first" if paid else ""))
        if paid:
            extra = paid - received
            parts.append(f"purchases cost about {paid:,} aUEC" + (
                "" if not received else f", {extra:,} more than the sales here bring" if extra > 0
                else ", paid from the sales here"
            ))
        parts.append(f"after this stop the run is at {balance:,} aUEC (below 0 = money still invested)")
        text = "; ".join(parts) + "."
        return text[0].upper() + text[1:]

    @staticmethod
    def stop_instructions(stop: dict) -> tuple[list[str], list[str]]:
        """(what to do at the stop, notes): sells first, as the sale makes room and money for the buys."""
        instructions, notes = [], []
        for label, key in (("Sell", "sell"), ("Buy", "buy")):
            for e in stop.get(key, []):
                line = f"{label} {e['scu']:,} SCU {e['commodity']} for about {e['total_aUEC']:,} aUEC"
                if e.get("recorded"):
                    line += " (done, recorded)"
                if key == "buy" and e.get("sell_at"):
                    line += f", keep it aboard until {e['sell_at']}"
                instructions.append(line + ".")
                if e.get("recorded"):
                    # The real amount replaces the plan's reasons for its amount
                    deviation = _deviation(e, key)
                    if deviation:
                        notes.append(f"{e['commodity']}: " + "; ".join(deviation) + ".")
                limit = None if e.get("recorded") else VOLUME_NOTE.search(e.get("volume_note") or "")
                if limit:
                    cause = {"buy": "stock", "sell": "demand"}.get(limit[3], "stock and demand")
                    notes.append(f"{e['commodity']}: only {int(limit[1]):,} SCU ({cause}).")
                money = None if e.get("recorded") else MONEY_NOTE.search(e.get("volume_note") or "")
                if money:
                    kept = f"; the rest is needed for the purchases at {money[4]}" if money[4] else ""
                    notes.append(f"{e['commodity']}: only {int(money[1]):,} SCU, all the money allows "
                                 f"({money[3]} aUEC left for it here{kept}; the hold has room for {int(money[2]):,}).")
                if e.get("container_note"):
                    notes.append(f"{e['commodity']}: {e['container_note']}")
                if e.get("demand_unknown") and not e.get("recorded"):
                    notes.append(f"{e['commodity']}: " + (
                        "UEX has no demand figure here, it may take less." if key == "sell"
                        else "UEX has no demand figure where it is sold, more than planned may not sell."
                    ))
                notes.extend(f"{e['commodity']}: {warning}" for warning in e.get("warnings") or [])
        return instructions, notes

    @classmethod
    def hud_text(cls, active: dict) -> str:
        """Markdown for the HUD info panel, built from the HUD's own blocks so it takes the look of the
        user's HUD profile: the route (```steps), the hold arriving and leaving (```bar), the stop's sell and
        buy tables, a line per commodity on why that amount and container size, the money (```stats)."""
        route, step = active["route"], active["step"]
        stops = route["stops"]
        stop = stops[step - 1]
        blocks = [f"### {_short(stop['terminal'])}", f"Stop {step} of {len(stops)} · {stop['location']}"]

        lines = []
        for number, entry in enumerate(stops, start=1):
            if number > 1 and _system(stops[number - 2]) != _system(entry):
                lines.append("jump | Jump")
            kind = "done" if number < step else "current" if number == step else "next"
            lines.append(f"{kind} | {_short(entry['terminal'])}")
        blocks.append("```steps\n" + "\n".join(lines) + "\n```")
        blocks.append(cls.__hold_bar(active))

        for label, key in (("Sell", "sell"), ("Buy", "buy")):
            entries = stop.get(key, [])
            if entries:
                rows = [f"| {label} | SCU | aUEC |", "|---|---:|---:|"]
                # A recorded trade shows its real figures in bold
                rows += [
                    f"| **{e['commodity']}** | **{e['scu']:,}** | **{e['total_aUEC']:,}** |" if e.get("recorded")
                    else f"| **{e['commodity']}** | {e['scu']:,} | {e['total_aUEC']:,} |"
                    for e in entries
                ]
                blocks.append("\n".join(rows))
        next_stop = stops[step] if step < len(stops) else None
        blocks += [f"*{reason}*" for reason in cls.__reasons(stop, route, next_stop)]

        received, paid, balance = cls.money(active)
        planned = active.get("planned_profit")
        profit = route["estimated_profit"]
        stats = []
        if stop.get("buy"):
            stats.append(f"Pay here | {paid:,}")
        if stop.get("sell"):
            stats.append(f"Received | {received:,}")
        stats.append(f"Balance after | {balance:,}")
        if planned not in (None, profit):
            stats.append(f"Planned | {planned:,}")
        stats.append(f"Profit | {profit:,} | accent")
        # Lines without "|" go under the figures, in the same card
        if next_stop:
            jump = _system(next_stop) != _system(stop)
            stats.append(f"**Next:** {_short(next_stop['terminal'])} · {next_stop['location']}"
                         + (f" · jump to {_system(next_stop)}" if jump else ""))
        else:
            stats.append("**Last stop** of the route.")
        blocks.append("```stats\n" + "\n".join(stats) + "\n```")
        return "\n\n".join(blocks)

    @classmethod
    def __hold_bar(cls, active: dict) -> str:
        """The hold arriving and leaving: sold here (text), staying aboard (muted), bought here (accent)."""
        stop = active["route"]["stops"][active["step"] - 1]
        sold = {e["commodity"]: e["scu"] for e in stop.get("sell", [])}
        arriving = cls.cargo_on_arrival(active)
        arriving_segments = [f"{c['scu']} {'text' if c['commodity'] in sold else 'muted'}"
                             for c in sorted(arriving, key=lambda c: c["commodity"] not in sold)]
        stays = [(c["commodity"], c["scu"] - sold.get(c["commodity"], 0)) for c in arriving]
        leaving_segments = [f"{scu} muted" for _, scu in stays if scu > 0]
        leaving_segments += [f"{e['scu']} accent" for e in stop.get("buy", []) if e["scu"] > 0]

        lines = []
        if active["route"].get("hold_scu"):
            lines.append(f"max: {active['route']['hold_scu']}")
        lines.append(" | ".join(["Arriving"] + arriving_segments))
        lines.append(" | ".join(["Leaving"] + leaving_segments))
        legend = [role for role, used in (
            ("text Sell here", any(" text" in s for s in arriving_segments)),
            ("accent Buy here", any(" accent" in s for s in leaving_segments)),
            ("muted Stays aboard", any(" muted" in s for s in leaving_segments)),
        ) if used]
        if legend:
            lines.append(" | ".join(["legend"] + legend))
        return "```bar\n" + "\n".join(lines) + "\n```"

    @staticmethod
    def __reasons(stop: dict, route: dict, next_stop: dict | None) -> list[str]:
        """A line per commodity of this stop, only where something needs saying: why that amount, why that
        container size, keep it aboard, illegal cargo, and how far a recorded trade was off the plan."""
        reasons = []
        illegal = set(route.get("illegal_commodities") or [])
        for key in ("sell", "buy"):
            for e in stop.get(key, []):
                parts = _deviation(e, key) if e.get("recorded") else []
                # The plan's reasons for its amount no longer apply once the real one is recorded
                planned_buy = key == "buy" and not e.get("recorded")
                limit = VOLUME_NOTE.search(e.get("volume_note") or "") if planned_buy else None
                if limit:
                    scu, room, side = f"{int(limit[1]):,}", f"{int(limit[2]):,}", limit[3]
                    buyer = _short(e.get("sell_at") or (next_stop or {}).get("terminal") or "the sell terminal")
                    parts.append({
                        "buy": f"only {scu} in stock here (room for {room})",
                        "sell": f"{buyer} only takes {scu} (room for {room})",
                    }.get(side, f"stock here and demand at {buyer} allow no more than {scu} (room for {room})"))
                money = MONEY_NOTE.search(e.get("volume_note") or "") if planned_buy else None
                if money:
                    kept = f", the rest is for {_short(money[4])}" if money[4] else ""
                    parts.append(f"all the money allows, {money[3]} aUEC left for it{kept} (room for {int(money[2]):,})")
                if key == "buy":
                    container = _container_reason(e.get("container_note") or "", stop["terminal"])
                    if container:
                        parts.append(container)
                    if e.get("sell_at"):
                        parts.append(f"keep it aboard until {_short(e['sell_at'])}")
                if e.get("demand_unknown") and not e.get("recorded"):
                    parts.append("demand here unknown to UEX, it may take less" if key == "sell"
                                 else "demand where it is sold unknown to UEX")
                if e["commodity"] in illegal:
                    parts.append("illegal cargo, a scan can mean fines or losing it")
                if parts:
                    reasons.append(f"{e['commodity']}: " + "; ".join(parts) + ".")
        return reasons

    # ---- HUD

    async def refresh_hud(self) -> bool:
        """Shows the current stop on the HUD info panel, or removes it. Never raises.
        True when the panel is on screen (False also when the HUD is off or this Wingman has no info panel)."""
        try:
            hud = self.__helper.get_handler_config().get_wingman().hud
            active = await asyncio.to_thread(self.get)
            if active and await asyncio.to_thread(self.is_hud_visible):
                return bool(await hud.add_info(HUD_TITLE, self.hud_text(active)))
            await hud.remove_info(HUD_TITLE)
        except Exception as e:
            self.__helper.get_handler_debug().write(f"Trade run HUD update failed: {e}")
        return False

    def hud_available(self) -> bool:
        """The HUD runs and this Wingman uses the info panel."""
        try:
            return bool(getattr(self.__helper.get_handler_config().get_wingman().hud, "info_enabled", True))
        except Exception:
            return False
