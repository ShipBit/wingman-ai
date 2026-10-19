"""The trade route the player is flying, with a cursor on the current stop.

Kept in a file next to the database: the conversation history can lose old tool
responses (Core clears them when it gets long) and Core can restart mid-run, but
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
        self.__path = os.path.join(helper.get_data_path(), self.FILE_NAME)

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

    def record(self, side: str, commodity: str, scu: int, total_price: float) -> tuple[dict | None, str | None, list[str]]:
        """What the user really bought or sold at the current stop (prices and stock differ from UEX's).
        A purchase changes the later sale of that cargo by the same SCU; the route profit follows.
        Returns (active route, None, warnings) or (None, why not, []). Amounts that don't add up (more
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
            # One commodity can have two buys at a stop (part sold at one stop, the rest at another):
            # the recorded amount fills them in order, the last takes what is left over
            entries = [e for e in stop.get(side, []) if e["commodity"].lower() == commodity.strip().lower()]
            if not entries:
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
                return None, problem, []
            entry = entries[0]
            warnings = []
            left = int(scu)
            for number, part in enumerate(entries):
                part_scu = left if number == len(entries) - 1 else min(left, part["scu"])
                left -= part_scu
                delta = part_scu - part["scu"]
                part.setdefault("planned_aUEC", part["total_aUEC"])  # what UEX expected, for the HUD
                # The plan at the time of recording (a sale already follows a changed purchase)
                part.setdefault("planned_trade_scu", part["scu"])
                part.setdefault("planned_price_per_scu", part.get("price_per_scu"))
                part.update(scu=part_scu, total_aUEC=round(total_price * part_scu / scu) if scu else 0, recorded=True)
                if scu:
                    part["price_per_scu"] = round(total_price / scu, 2)
                if side == "buy" and delta:
                    sale_stop, sale = self.__sale_of(stops[index + 1:], part)
                    if sale and not sale.get("recorded"):
                        sale.setdefault("planned_scu", sale["scu"])
                        sale["scu"] = max(0, sale["scu"] + delta)
                        sale["total_aUEC"] = round(sale["scu"] * sale["price_per_scu"])
                        if sale["scu"] > sale["planned_scu"]:
                            warnings.append(
                                f"{sale_stop['terminal']} was planned to take {sale['planned_scu']:,} SCU {sale['commodity']}, "
                                f"now {sale['scu']:,}: it may take less."
                            )
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
            active["route"]["estimated_profit"] = round(
                sum(e["total_aUEC"] for s in stops for e in s.get("sell", []))
                - sum(e["total_aUEC"] for s in stops for e in s.get("buy", []))
            )
            self.__save(state)
            return active, None, warnings

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
            "next_stop": stops[step]["terminal"] if step < len(stops) else None,
            "shown_on_hud": hud_visible,
        }

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

        paid = sum(e["total_aUEC"] for e in stop.get("buy", []))
        received = sum(e["total_aUEC"] for e in stop.get("sell", []))
        planned = active.get("planned_profit")
        profit = route["estimated_profit"]
        stats = []
        if stop.get("buy"):
            stats.append(f"Pay here | {paid:,}")
        if stop.get("sell"):
            stats.append(f"Received | {received:,}")
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
