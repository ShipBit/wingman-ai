import copy

from skills.uexcorp.uexcorp import compression
from skills.uexcorp.uexcorp.active_trade_route import ActiveTradeRoute as ActiveTradeRouteStore
from skills.uexcorp.uexcorp.route_planner import Leg, RoutePlan, RoutePlanner
from skills.uexcorp.uexcorp.tool.tool import Tool
from skills.uexcorp.uexcorp.tool.validator import Validator


class CommodityRoute(Tool):
    REQUIRES_AUTHENTICATION = False
    TOOL_NAME = "uex_get_trade_routes"

    def __init__(self):
        super().__init__()

    def execute(
        self,
        filter_commodity_whitelist: list[str] | None = None,
        filter_commodity_blacklist: list[str] | None = None,
        filter_allow_illegal_commodities: bool | None = None,
        filter_star_system_whitelist: list[str] | None = None,
        filter_star_system_blacklist: list[str] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        used_ship: str | None = None,
        available_money: int | None = None,
        available_cargo_space_scu: int | None = None,
        max_system_jumps: int | None = None,
        filter_start_location: str | None = None,
        filter_destination_location: str | None = None,
        filter_location_blacklist: list[str] | None = None,
        filter_require_auto_load: bool | None = None,
        max_stops: int | None = None,
        return_to_start: bool | None = None,
    ) -> (str, str):
        from skills.uexcorp.uexcorp.data_access.vehicle_data_access import VehicleDataAccess
        from skills.uexcorp.uexcorp.data_access.terminal_data_access import TerminalDataAccess
        from skills.uexcorp.uexcorp.data_access.commodity_data_access import CommodityDataAccess
        from skills.uexcorp.uexcorp.data_access.commodity_route_data_access import CommodityRouteDataAccess
        from skills.uexcorp.uexcorp.model.terminal import Terminal
        from skills.uexcorp.uexcorp.helper import Helper

        helper = Helper.get_instance()

        commodity_route_data_access = CommodityRouteDataAccess()
        start_terminal_ids = []
        end_terminals_ids = []
        terminal_ids_exclude = []
        commodity_ids_exclude = []
        max_scu = None
        container_limit = None
        ship_container_sizes: set[int] = set()

        if available_cargo_space_scu:
            max_scu = available_cargo_space_scu

        if filter_commodity_whitelist:
            commodity_route_data_access.add_filter_by_commodity_name_whitelist(filter_commodity_whitelist)

        if filter_commodity_blacklist:
            commodity_route_data_access.add_filter_by_commodity_name_blacklist(filter_commodity_blacklist)

        # Blacklisted commodities (skill config file) are never traded; illegal ones only on request
        excluded_commodities = [CommodityDataAccess().add_filter_by_is_blacklisted(True)]
        if filter_allow_illegal_commodities is False:
            excluded_commodities.append(CommodityDataAccess().add_filter_by_is_illegal(True))
        for excluded_commodity_data_access in excluded_commodities:
            for commodity in excluded_commodity_data_access.load():
                commodity_ids_exclude.append(commodity.get_id())

        if filter_star_system_whitelist:
            commodity_route_data_access.add_filter_by_star_system_name_whitelist(filter_star_system_whitelist)

        if filter_star_system_blacklist:
            commodity_route_data_access.add_filter_by_star_system_name_blacklist(filter_star_system_blacklist)

        if max_system_jumps == 0:
            commodity_route_data_access.add_filter_by_in_same_star_system()

        # The ship of the last search is remembered: without it, a model may pick any of the user's ships
        try:
            store = ActiveTradeRouteStore(helper)
            last_ship, pending_ship = store.get_last_ship(), store.get_pending_ship()
        except Exception:
            store, last_ship, pending_ship = None, None, None
        ship_given = bool(used_ship)
        if not used_ship and not available_cargo_space_scu and last_ship:
            used_ship = last_ship
            note = f"No ship given, so the routes are for {last_ship} (ship of the last search). Say so."
            if pending_ship and pending_ship != last_ship:
                note += f" If the user flies the {pending_ship} (searched with before, not confirmed), search again with used_ship."
            helper.get_handler_tool().add_note(note)

        if used_ship:
            ship = VehicleDataAccess().load_by_property("name_full", used_ship)
            # Only a ship named for this search counts: the fallback must not clear a pending switch
            if ship and store and ship_given:
                try:
                    confirmed = store.remember_ship(ship.get_name_full())
                except Exception:
                    confirmed = True
                if not confirmed:
                    # A guessed ship must not replace the remembered one (searches without used_ship use it)
                    helper.get_handler_tool().add_note(
                        f"Ship changed from {last_ship} to {ship.get_name_full()}. If the user did not say they switched "
                        f"ships, ask which ship they fly before using these routes. Searches without used_ship stay on "
                        f"{last_ship} until the user confirms."
                    )
            if not ship:
                # Volume, loading dock and container filters all depend on the ship, so don't guess
                helper.get_handler_tool().add_note(
                    f"Ship '{used_ship}' was not found in the UEX data. Ask the user for the exact ship name or the available cargo space in SCU."
                )
                return compression.dumps([]), ""
            if ship.get_is_loading_dock():
                commodity_route_data_access.add_filter_by_has_loading_dock()
            if ship.get_max_container_size():
                # Silent when routes are found: they all fit the ship, there is nothing to check
                commodity_route_data_access.add_filter_by_max_container_size(ship.get_max_container_size())
                container_limit = (ship.get_max_container_size(), ship.get_name_full())
                ship_container_sizes = self.__sizes(ship.get_container_sizes())
            if ship.get_scu():
                max_scu = min(max_scu, ship.get_scu()) if max_scu is not None else ship.get_scu()
            elif max_scu is None:
                # No cargo data (or no cargo hold) and no cargo space given: nothing to plan with
                helper.get_handler_tool().add_note(
                    f"UEX has no cargo capacity for '{ship.get_name_full()}'. Ask the user for the available cargo space in SCU."
                )
                return compression.dumps([]), ""

        if filter_location_blacklist:
            # Collect the terminals at any blacklisted location, these are excluded below
            terminal_data_access = TerminalDataAccess()
            terminal_data_access.add_filter_by_location_name_whitelist(filter_location_blacklist)
            terminal_data_access.add_filter_by_type(Terminal.TYPE_COMMODITY)
            for terminal in terminal_data_access.load():
                terminal_ids_exclude.append(terminal.get_id())

        # Start/destination limit where a route begins/ends, not every hop of it, so they go
        # to the planner instead of filtering the legs
        for location, terminal_ids, kind in (
            (filter_start_location, start_terminal_ids, "start"),
            (filter_destination_location, end_terminals_ids, "destination"),
        ):
            if not location:
                continue
            terminal_data_access = TerminalDataAccess()
            terminal_data_access.add_filter_by_location_name_whitelist(location)
            terminal_data_access.add_filter_by_type(Terminal.TYPE_COMMODITY)
            terminal_data_access.add_filter_by_is_available(True)
            for terminal in terminal_data_access.load():
                terminal_ids.append(terminal.get_id())
            if not terminal_ids:
                helper.get_handler_tool().add_note(
                    f"No available commodity terminal found for {kind} location '{location}'. Ask the user for the exact location name."
                )
                return compression.dumps([]), ""

        if filter_require_auto_load:
            # Route rows have no is_auto_load; constrain both ends via terminal ids.
            auto_load_terminal_ids = []
            auto_load_terminal_data_access = TerminalDataAccess()
            auto_load_terminal_data_access.add_filter_by_is_auto_load(True)
            auto_load_terminal_data_access.add_filter_by_type(Terminal.TYPE_COMMODITY)
            auto_load_terminal_data_access.add_filter_by_is_available(True)
            for terminal in auto_load_terminal_data_access.load():
                auto_load_terminal_ids.append(terminal.get_id())

            if not auto_load_terminal_ids:
                helper.get_handler_tool().add_note(
                    "No available commodity terminals support ship hangar auto load/unload."
                )
                return compression.dumps([]), ""

            commodity_route_data_access.add_filter_by_id_terminal_origin(auto_load_terminal_ids)
            commodity_route_data_access.add_filter_by_id_terminal_destination(auto_load_terminal_ids)

        if terminal_ids_exclude:
            commodity_route_data_access.add_filter_by_id_terminal_origin(terminal_ids_exclude, operation="NOT IN")
            commodity_route_data_access.add_filter_by_id_terminal_destination(terminal_ids_exclude, operation="NOT IN")

        if commodity_ids_exclude:
            commodity_route_data_access.add_filter_by_id_commodity(commodity_ids_exclude, operation="NOT IN")

        if max_scu is None and available_money is None:
            max_scu = 1 # search for an example with 1 scu
            helper.get_handler_tool().add_note("Example route for 1 SCU. User should refine search with ship or/and budget information for better results.")

        config = helper.get_handler_config()
        use_availability = config.get_behavior_commodity_route_use_estimated_availability()
        ranking = config.get_behavior_commodity_route_ranking()
        requested_count = limit or config.get_behavior_commodity_route_default_count()
        max_stops = max(1, min(int(max_stops or config.get_behavior_commodity_route_default_max_stops()), self.MAX_STOPS))
        single_hop = max_stops == 1 and not return_to_start

        no_availability_data_access = None
        if use_availability:
            if single_hop and not offset:
                # Same filters, to find good routes that only fail on availability (reported as notes)
                no_availability_data_access = CommodityRouteDataAccess()
                no_availability_data_access.filter = copy.deepcopy(commodity_route_data_access.filter)
                # Single hop: start/destination are exactly the leg's ends (the planner handles them for the routes)
                if start_terminal_ids:
                    no_availability_data_access.add_filter_by_id_terminal_origin(start_terminal_ids)
                if end_terminals_ids:
                    no_availability_data_access.add_filter_by_id_terminal_destination(end_terminals_ids)
            # Legs without stock or demand are no real options
            commodity_route_data_access.add_filter_by_has_availability(True)

        legs = commodity_route_data_access.load_legs(self.LEG_COLUMNS)
        system_jumps = self.__system_jumps()
        illegal_ids = {commodity.get_id() for commodity in CommodityDataAccess().add_filter_by_is_illegal(True).load()}
        planner = RoutePlanner(
            [self.__to_leg(leg, system_jumps, illegal_ids) for leg in legs],
            cargo_scu=max_scu,
            budget=available_money,
            use_availability=use_availability,
            ranking=ranking,
            hop_info=self.__hop_info(helper, legs, system_jumps),
        )
        plans = planner.plan(
            max_stops=max_stops,
            return_to_start=bool(return_to_start),
            start_terminals=set(start_terminal_ids) if start_terminal_ids else None,
            end_terminals=set(end_terminals_ids) if end_terminals_ids else None,
            limit=(offset or 0) + requested_count,
            max_jumps=max_system_jumps,
        )[offset or 0:]

        if not plans:
            # The filters the user set are the likely reason; the ship's container limit is one more
            narrowing = [label for label, is_set in (
                ("commodities", filter_commodity_whitelist),
                ("auto loading only", filter_require_auto_load),
                ("start", filter_start_location),
                ("destination", filter_destination_location),
                ("round trip", return_to_start),
                ("excluded locations", filter_location_blacklist),
                ("star systems", filter_star_system_whitelist),
                ("no illegal cargo", filter_allow_illegal_commodities is False),
                (f"at most {max_system_jumps} system jumps", max_system_jumps is not None),
            ) if is_set]
            note = "No route found."
            if narrowing:
                note += f" Filters set: {', '.join(narrowing)}. Offer to leave one out."
            if container_limit:
                note += (
                    f" The ship also limits it: the {container_limit[1]} takes containers up to "
                    f"{container_limit[0]} SCU, so terminals that only load bigger containers were left out."
                )
            helper.get_handler_tool().add_note(note)
        if max_stops > 1 and plans and plans[0].stop_count < max_stops:
            helper.get_handler_tool().add_note(
                f"The best route has fewer than {max_stops} stops: shorter routes ranked better by {ranking.replace('_', ' ')} (skill setting)."
            )
        if no_availability_data_access is not None:
            for note in self.__get_no_availability_notes(
                no_availability_data_access, available_money, max_scu, plans, requested_count
            ):
                helper.get_handler_tool().add_note(note)

        terminals = self.__terminal_info(legs)
        advanced = config.get_behavior_commodity_route_advanced_info()
        commodities: dict[int, tuple[list[str], bool]] = {}
        # Containers both terminals of a leg take, per commodity (sizes differ by commodity)
        leg_container_sizes = {
            (leg["id_commodity"], leg["id_terminal_origin"], leg["id_terminal_destination"]):
                (self.__sizes(leg["container_sizes_origin"]), self.__sizes(leg["container_sizes_destination"]))
            for leg in legs
        }
        routes = [
            self.__plan_for_ai(plan, terminals, commodities, advanced, leg_container_sizes, ship_container_sizes,
                               container_limit[1] if container_limit else None)
            for plan in plans
        ]
        for number, route in enumerate(routes, start=1):
            route["route_number"] = number
            if max_scu:
                # The HUD's hold bar is this long; with the summary, the stops stay last
                stops = route.pop("stops")
                route["hold_scu"] = int(max_scu)
                route["stops"] = stops
        try:
            ActiveTradeRouteStore(helper).remember_search(routes)
        except Exception as e:
            # Only picking a route by number needs it, the routes themselves are fine
            helper.get_handler_debug().write(f"Could not remember the trade routes: {e}", True)
        illegal = sorted({name for route in routes for name in route.get("illegal_commodities", [])})
        if illegal:
            helper.get_handler_tool().add_note(
                f"Routes include illegal commodities ({', '.join(illegal)}). Clearly warn the user: carrying them is a crime, "
                "a cargo scan can lead to fines, crime stat or losing the cargo. "
                "For legal routes only, call again with filter_allow_illegal_commodities false."
            )
        return compression.dumps(routes), ""

    MAX_STOPS = 5
    MAX_SYSTEM_JUMPS = 10
    MAIN_CARGO_COUNT = 3
    ALTERNATIVE_END_COUNT = 4
    NO_AVAILABILITY_NOTE_LIMIT = 3
    # Columns read by __to_leg and __terminal_info
    LEG_COLUMNS = [
        "id_commodity", "commodity_name", "id_terminal_origin", "id_terminal_destination",
        "price_origin", "price_destination", "scu_origin", "scu_destination", "distance",
    ] + [
        column.format(side=side)
        for side in ("origin", "destination")
        for column in (
            "{side}_terminal_name", "{side}_planet_name", "{side}_orbit_name", "{side}_star_system_name",
            "{side}_faction_name", "is_monitored_{side}", "has_refuel_{side}", "container_sizes_{side}",
        )
    ]

    @staticmethod
    def __hop_info(helper, legs: list[dict], system_jumps: dict[tuple[str, str], int]):
        """(distance, jumps) between two terminals without a trade leg, for stops that only buy.
        Same orbit = 0 Gm, otherwise UEX's orbit distance (in either direction), None if unknown."""
        places: dict[int, tuple[str, str]] = {}
        for leg in legs:
            for side in ("origin", "destination"):
                places.setdefault(leg[f"id_terminal_{side}"], (leg[f"{side}_orbit_name"], leg[f"{side}_star_system_name"]))
        distances: dict[tuple[str, str], float] = {}
        try:
            rows = helper.get_database().execute_fetchall(
                "SELECT orbit_origin_name, orbit_destination_name, distance FROM orbit_distance WHERE distance IS NOT NULL"
            )
        except Exception:
            rows = []
        for origin, destination, distance in rows:
            distances[(origin, destination)] = distances[(destination, origin)] = distance

        def hop_info(origin: int, destination: int) -> tuple[float | None, int]:
            (orbit_a, system_a), (orbit_b, system_b) = places.get(origin, (None, None)), places.get(destination, (None, None))
            distance = 0.0 if orbit_a and orbit_a == orbit_b else distances.get((orbit_a, orbit_b))
            jumps = 0 if system_a == system_b else system_jumps.get((system_a, system_b), 1)
            return distance, jumps

        return hop_info

    @staticmethod
    def __system_jumps() -> dict[tuple[str, str], int]:
        """Fewest jumps between every pair of connected star systems. UEX lists each gateway as a
        jump point orbit named after the system it leads to, e.g. "Nyx Gateway (Stanton system)" in Stanton."""
        from skills.uexcorp.uexcorp.data_access.orbit_data_access import OrbitDataAccess
        from skills.uexcorp.uexcorp.data_access.star_system_data_access import StarSystemDataAccess

        systems = {star_system.get_name() for star_system in StarSystemDataAccess().load()}
        links: dict[str, set[str]] = {}
        for orbit in OrbitDataAccess().add_filter_by_is_jump_point(True).load():
            name, origin = orbit.get_name() or "", orbit.get_star_system_name()
            target = name.split(" Gateway")[0] if " Gateway" in name else None
            if origin in systems and target in systems and target != origin:
                links.setdefault(origin, set()).add(target)
                links.setdefault(target, set()).add(origin)

        jumps = {}
        for start in links:
            frontier, seen, depth = [start], {start}, 0
            while frontier:
                depth += 1
                frontier = [n for system in frontier for n in links[system] if n not in seen]
                for system in frontier:
                    seen.add(system)
                    jumps[(start, system)] = depth
        return jumps

    @staticmethod
    def __to_leg(row: dict, system_jumps: dict[tuple[str, str], int], illegal_ids: set[int]) -> Leg:
        origin_system, destination_system = row["origin_star_system_name"], row["destination_star_system_name"]
        return Leg(
            id_commodity=row["id_commodity"],
            commodity_name=row["commodity_name"],
            origin=row["id_terminal_origin"],
            destination=row["id_terminal_destination"],
            price_buy=row["price_origin"],
            price_sell=row["price_destination"],
            stock=row["scu_origin"],
            demand=row["scu_destination"] or None,  # 0 = not reported
            distance=row["distance"],
            # Unknown connection: at least one jump
            jumps=0 if origin_system == destination_system else system_jumps.get((origin_system, destination_system), 1),
            is_illegal=row["id_commodity"] in illegal_ids,
        )

    @staticmethod
    def __terminal_info(legs: list[dict]) -> dict[int, dict]:
        """Name and location of every terminal, taken from the legs (no extra queries)."""
        terminals = {}
        for leg in legs:
            for side in ("origin", "destination"):
                terminal_id = leg[f"id_terminal_{side}"]
                if terminal_id in terminals:
                    continue
                place = leg[f"{side}_planet_name"] or leg[f"{side}_orbit_name"]
                star_system = leg[f"{side}_star_system_name"]
                terminals[terminal_id] = {
                    "terminal": leg[f"{side}_terminal_name"],
                    "location": ", ".join(part for part in (place, star_system) if part),
                    "star_system": star_system,
                    "orbit": leg[f"{side}_orbit_name"],
                    "faction": leg[f"{side}_faction_name"],
                    "is_monitored": leg[f"is_monitored_{side}"],
                    "has_refuel": leg[f"has_refuel_{side}"],
                    "container_sizes_in_scu": leg[f"container_sizes_{side}"],
                }
        return terminals

    ILLEGAL_WARNING = "ILLEGAL commodity (contraband): crime to carry, risk of fines, crime stat and losing the cargo when scanned"

    @staticmethod
    def __sizes(value) -> set[int]:
        """Container sizes from a list like "1,2,4,8,16,24"."""
        return {int(size) for size in str(value or "").split(",") if size.strip().isdigit()}

    @staticmethod
    def __container_note(
        sizes: tuple[set[int], set[int]] | None, ship_sizes: set[int], sell_terminal: str | None, ship_name: str | None,
    ) -> str | None:
        """The container limit of a purchase with its real cause, as a sentence (a small model invents a
        cause when it only gets a number). Only when the buy terminal offers bigger containers than the
        ship or the sell terminal takes: then the user must pick smaller ones. Otherwise None."""
        if not sizes:
            return None
        offered, sellable = sizes
        known = [group for group in (offered, sellable, ship_sizes) if group]
        if len(known) < 2:
            return None
        common = set.intersection(*known)
        if not common:
            return None
        limit = max(common)
        largest_offered = max(offered) if offered else max(max(group) for group in known)
        if limit >= largest_offered:
            return None  # the buy terminal is the limit itself: nothing to choose
        both_terminals = (offered & sellable) if offered and sellable else sellable
        if both_terminals and max(both_terminals) == limit:
            cause = f"{sell_terminal or 'the sell terminal'}, where you sell it, takes no bigger ones"
        else:
            cause = f"bigger ones don't fit the {ship_name or 'ship'}"
        return f"Buy it in containers of at most {limit} SCU: {cause}."

    def __plan_for_ai(
        self,
        plan: RoutePlan,
        terminals: dict[int, dict],
        commodities: dict[int, tuple[list[str], bool]],
        advanced: bool,
        leg_container_sizes: dict[tuple, tuple[set[int], set[int]]] | None = None,
        ship_container_sizes: set[int] | None = None,
        ship_name: str | None = None,
    ) -> dict:
        from skills.uexcorp.uexcorp.model.commodity import Commodity

        def commodity_info(id_commodity: int | None) -> tuple[list[str], bool]:
            """Warnings and whether the commodity is illegal."""
            if not id_commodity:
                return [], False
            if id_commodity not in commodities:
                commodity = Commodity(id_commodity, load=True)
                if not commodity.get_name():
                    commodities[id_commodity] = ([], False)
                else:
                    is_illegal = bool(commodity.get_is_illegal())
                    warnings = ([self.ILLEGAL_WARNING] if is_illegal else []) + commodity.get_hazards()
                    commodities[id_commodity] = (warnings, is_illegal)
            return commodities[id_commodity]

        illegal_commodities = []

        stops = []
        for index, terminal_id in enumerate(plan.stops):
            info = terminals.get(terminal_id, {})
            stop = {"terminal": info.get("terminal"), "location": info.get("location")}
            if advanced:
                stop.update({key: info.get(key) for key in ("orbit", "faction", "is_monitored", "has_refuel")})
            sells = [trade for trade in plan.trades if trade.sell_stop == index]
            buys = [trade for trade in plan.trades if trade.buy_stop == index]
            if sells:
                # Same commodity bought at different stops is sold here in one go
                sold: dict[str, dict] = {}
                for trade in sells:
                    entry = sold.setdefault(trade.leg.commodity_name, {
                        "commodity": trade.leg.commodity_name, "scu": 0, "total_aUEC": 0, "price_per_scu": trade.leg.price_sell,
                    })
                    entry["scu"] += trade.scu
                    entry["total_aUEC"] = round(entry["scu"] * trade.leg.price_sell)
                stop["sell"] = list(sold.values())
            if buys:
                stop["buy"] = []
                for trade in buys:
                    buy = {
                        "commodity": trade.leg.commodity_name,
                        "scu": trade.scu,
                        "total_aUEC": round(trade.cost),
                        "price_per_scu": trade.leg.price_buy,
                        "sell_at": terminals.get(trade.leg.destination, {}).get("terminal") if trade.sell_stop != index + 1 else None,
                        "warnings": commodity_info(trade.leg.id_commodity)[0],
                    }
                    container_note = self.__container_note(
                        (leg_container_sizes or {}).get((trade.leg.id_commodity, trade.leg.origin, trade.leg.destination)),
                        ship_container_sizes or set(),
                        terminals.get(trade.leg.destination, {}).get("terminal"),
                        ship_name,
                    )
                    if container_note:
                        buy["container_note"] = container_note
                    if commodity_info(trade.leg.id_commodity)[1] and trade.leg.commodity_name not in illegal_commodities:
                        illegal_commodities.append(trade.leg.commodity_name)
                    if trade.availability_limit:
                        unlimited, location = trade.availability_limit
                        # Exactly planned cargo has no single "instead of" amount
                        instead = f" (instead of {unlimited})" if unlimited is not None else ""
                        buy["volume_note"] = (
                            f"SCU count limited to {trade.scu}{instead} "
                            f"by estimated availability at {location}."
                        )
                    elif trade.money_limit:
                        room, for_it, later = trade.money_limit
                        kept = terminals.get(later, {}).get("terminal") if later is not None else None
                        buy["volume_note"] = (
                            f"SCU count limited to {trade.scu} (instead of {room}) "
                            f"by available money ({for_it:,} aUEC left for it at this stop"
                            + (f", the rest is kept for the purchases at {kept}" if kept else "") + ")."
                        )
                    stop["buy"].append(buy)
            stops.append(stop)

        # The summary comes first: it is what the user decides on. The stops follow as details.
        route = {}
        if illegal_commodities:
            # First key, so it is read before anything else
            route["warning"] = f"Route with illegal cargo: {', '.join(illegal_commodities)}. Tell the user clearly."
            route["illegal_commodities"] = illegal_commodities
        route["route_number"] = None  # set by the caller
        systems = []
        for terminal_id in plan.stops:
            system = terminals.get(terminal_id, {}).get("star_system")
            if system and (not systems or systems[-1] != system):
                systems.append(system)
        cargo_profit: dict[str, float] = {}
        for trade in plan.trades:
            cargo_profit[trade.leg.commodity_name] = cargo_profit.get(trade.leg.commodity_name, 0) + trade.profit
        route.update({
            "path": " -> ".join(str(terminals.get(terminal_id, {}).get("terminal")) for terminal_id in plan.stops),
            "systems": " -> ".join(systems),
            "main_cargo": sorted(cargo_profit, key=cargo_profit.get, reverse=True)[:self.MAIN_CARGO_COUNT],
            "estimated_profit": round(plan.profit),
            "max_investment": round(plan.max_cash_needed),
            "stop_count": plan.stop_count,
            "system_jumps": plan.jump_count,
            "distance_in_giga_meters": plan.distance,
        })
        if plan.is_circular():
            route["circular"] = True
        if any(trade.availability_limit for trade in plan.trades):
            route["volume_limited"] = True
        if advanced:
            route["profit_per_stop"] = round(plan.profit / plan.stop_count)
            if plan.max_cash_needed:
                route["return_on_investment"] = round(plan.profit / plan.max_cash_needed * 100, 1)
        if plan.alternative_ends:
            route["last_sale_also_at"] = [
                str(terminals.get(terminal_id, {}).get("terminal"))
                for terminal_id in plan.alternative_ends[:self.ALTERNATIVE_END_COUNT]
            ]
        route["stops"] = stops
        return route

    def __get_no_availability_notes(
        self,
        data_access,
        available_money: int | None,
        max_scu: int | None,
        plans: list[RoutePlan],
        requested_count: int,
    ) -> list[str]:
        """Notes for single-hop routes that would rank among the results but have no stock or demand left."""
        limits = []
        if available_money:
            limits.append(f"CAST(({int(available_money)} / price_origin) AS INTEGER)")
        if max_scu is not None:
            limits.append(str(int(max_scu)))
        # Single-argument MIN() is SQLite's aggregate function, so only wrap multiple limits
        scu_without_availability = limits[0] if len(limits) == 1 else f"MIN({', '.join(limits)})"

        data_access.add_filter_by_has_availability(False)
        data_access.add_filter_by_is_profitable()
        data_access.add_col(f"{scu_without_availability} as 'scu_without_availability'")
        data_access.add_col(f"({scu_without_availability} * (price_destination - price_origin)) as 'profit'")
        data_access.limit(self.NO_AVAILABILITY_NOTE_LIMIT)
        data_access.order_by("profit", "DESC")
        data_access.order_by("distance", "ASC")

        # With a full result list, only mention routes that would have beaten one of the shown routes
        threshold = min(plan.profit for plan in plans) if plans and len(plans) >= requested_count else None
        from skills.uexcorp.uexcorp.model.commodity import Commodity

        notes = []
        for route in data_access.load():
            if threshold is not None and (route.get_profit() or 0) <= threshold:
                continue
            note = route.get_no_availability_note()
            if route.get_id_commodity() and Commodity(route.get_id_commodity(), load=True).get_is_illegal():
                note += f" Warning: {route.get_commodity_name()} is an {self.ILLEGAL_WARNING}."
            notes.append(note)
        return notes

    def get_mandatory_fields(self) -> dict[str, Validator]:
        return {}

    def get_optional_fields(self) -> dict[str, Validator]:
        return {
            "filter_commodity_whitelist": Validator(
                Validator.VALIDATE_COMMODITY,
                multiple=True,
                config={
                    "for_trading": True
                },
                prompt="Only trade these commodities, e.g. [\"Laranite\", \"Agricium\"].",
            ),
            "filter_commodity_blacklist": Validator(
                Validator.VALIDATE_COMMODITY,
                multiple=True,
                config={
                    "for_trading": True
                },
                prompt="Never trade these commodities, e.g. [\"Laranite\"].",
            ),
            "limit": Validator(
                Validator.VALIDATE_NUMBER,
                config={
                    "min": 1,
                    "max": 15
                },
                prompt="Number of routes to return, 1-15. Leave out to use the user's default.",
            ),
            "offset": Validator(
                Validator.VALIDATE_NUMBER,
                config={
                    "min": 0
                },
                prompt="Skip this many of the best routes, e.g. offset 1 = start with the second best. Use for 'show me another route'.",
            ),
            "used_ship": Validator(
                Validator.VALIDATE_SHIP,
                prompt="The ship the user flies for this trade, e.g. \"Drake Cutlass Black\" (a short name like \"Ironclad\" is matched). Sets cargo space and ship limits. Pass it whenever the user names their ship, also when it is the same as before. Only a ship the user named, never one picked from a list of owned ships. Leave out only if the user named none: then the ship of the last route search is used; if there was none, ask the user.",
            ),
            "available_money": Validator(
                Validator.VALIDATE_NUMBER,
                config={
                    "min": 1
                },
                prompt="The player's money for buying cargo in aUEC, e.g. 250000. Routes then only buy what this money allows.",
            ),
            "available_cargo_space_scu": Validator(
                Validator.VALIDATE_NUMBER,
                config={
                    "min": 1
                },
                prompt="Free cargo space in SCU, e.g. 96. Use when the ship is unknown or already partly loaded.",
            ),
            "max_system_jumps": Validator(
                Validator.VALIDATE_NUMBER,
                config={
                    "min": 0,
                    "max": self.MAX_SYSTEM_JUMPS,
                },
                prompt="Most jumps between star systems (e.g. Stanton to Pyro) on the whole route. 0 = the route stays in the star system it starts in: use 0 for 'stay in the system' or 'no jumps'. For named systems ('only Stanton', 'Stanton or Nyx') use filter_star_system_whitelist instead. If the start is not known, also set filter_start_location to that system, e.g. \"Stanton\". Leave out for no limit.",
            ),
            "filter_start_location": Validator(
                Validator.VALIDATE_LOCATION,
                config={
                    "for_trading": True
                },
                prompt="Where the route starts, e.g. \"Area18\", \"Hurston\", \"Nyx Gateway (Stanton)\" or \"Pyro\". Any place from a star system down to a terminal. Use the player's current location if known.",
            ),
            "filter_destination_location": Validator(
                Validator.VALIDATE_LOCATION,
                config={
                    "for_trading": True
                },
                prompt="Where the route must end, e.g. \"microTech\". With return_to_start: a place the route must pass through.",
            ),
            "filter_location_blacklist": Validator(
                Validator.VALIDATE_LOCATION,
                multiple=True,
                config={
                    "for_trading": True
                },
                prompt="Places the route must never stop at, e.g. [\"Hurston\", \"Bloom\"].",
            ),
            "max_stops": Validator(
                Validator.VALIDATE_NUMBER,
                config={
                    "min": 1,
                    "max": self.MAX_STOPS,
                },
                prompt="Most stops after the start, 1-5. Leave out to use the user's default. 1 = buy at A, sell at B. More stops = buy and/or sell along the way, e.g. collect cargo at two terminals and sell it at the last. Set it only when the user asks for a number of stops or a multi-stop, longer or round trip route.",
            ),
            "return_to_start": Validator(
                Validator.VALIDATE_BOOL,
                prompt="True = round trip that ends where it started, e.g. A -> B -> A or A -> B -> C -> A. The way back counts as a stop.",
            ),
            "filter_require_auto_load": Validator(
                Validator.VALIDATE_BOOL,
                prompt="True = only terminals with hangar auto load (cargo is loaded and unloaded automatically, no manual loading).",
            ),

            # Currently used unreliably by AI
            "filter_star_system_whitelist": Validator(
                Validator.VALIDATE_STAR_SYSTEM,
                multiple=True,
                prompt="Only these star systems, every stop in one of them: [\"Stanton\"] for 'only Stanton', [\"Stanton\", \"Nyx\"] for 'Stanton or Nyx'.",
            ),
            # "filter_star_system_blacklist": Validator(Validator.VALIDATE_STAR_SYSTEM, multiple=True),

            "filter_allow_illegal_commodities": Validator(
                Validator.VALIDATE_BOOL,
                prompt="False = only legal commodities. Leave out or true = illegal commodities (contraband) are included and marked with a warning.",
            ),
        }

    def get_description(self) -> str:
        return (
            "Finds the most profitable commodity trade routes for the player's ship, money and location. "
            "A route is a list of stops: at each stop the player sells and/or buys cargo (several commodities possible); "
            "a stop may only buy, e.g. to collect more of a commodity before selling it all later. "
            "Use it for 'best trade route', 'what should I haul' or 'where should I trade'. All parameters are optional: "
            "pass everything you know (ship, money, start location). A route in one star system only "
            "(e.g. 'only Stanton') is max_system_jumps 0. Illegal commodities are included and marked "
            "unless filter_allow_illegal_commodities is false. To only find where to buy or sell one commodity, "
            "use uex_get_commodity_information."
        )

    def get_prompt(self) -> str:
        return (
            "Best trade routes for the player's ship, money and location. "
            "Present each route as a short summary to decide on: path, system_jumps, estimated_profit, money needed "
            "(max_investment) and main_cargo. If volume_limited, say once that some volumes are limited by availability. "
            "Do not list the stops' cargo here. When the user picks a route, call uex_active_trade_route with action set "
            "and its route_number, then guide them with it. "
            "If a route has a 'warning' about illegal cargo, say so clearly before describing the route. "
            "last_sale_also_at: the last sale works there too, same cargo and profit: mention it in one short phrase."
        )
