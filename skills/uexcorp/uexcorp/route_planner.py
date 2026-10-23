"""Trade route planner: multi-commodity, multi-stop and circular routes built from trade legs.

A leg is one commodity bought at one terminal and sold at another (the derived
commodity_route rows). The planner never touches the database or the Helper, so it
can be tested with hand-made legs.

1. Path search: beam search over terminal sequences. Each hop is scored with a quick
   greedy multi-commodity fill, cash grows with the realized profit per stop.
2. Cargo plan per candidate path: allocates trades (commodity, buy stop, sell stop),
   including cargo carried past stops, respecting cargo space on every segment, stock,
   demand and the cash available at every stop. The best of a few greedy orderings wins.
3. Stops that only buy are tried on the best candidates: e.g. Cobalt at two terminals with too little
   stock each, both sold at the destination. The path search can't find them (each hop needs a sale).
4. Candidates are ranked by the configured metric.
"""

import time
from dataclasses import dataclass, field
from typing import Callable

RANKING_PROFIT_PER_STOP = "profit_per_stop"
RANKING_PROFIT_PER_DISTANCE = "profit_per_distance"
RANKING_TOTAL_PROFIT = "total_profit"
RANKINGS = (RANKING_PROFIT_PER_STOP, RANKING_PROFIT_PER_DISTANCE, RANKING_TOTAL_PROFIT)

# Fixed effort per stop for profit per distance (landing, loading, takeoff), in Gm,
# so short hops don't look infinitely efficient.
STOP_OVERHEAD_GM = 20

# Ranking value for a hop without known distance (e.g. some cross-system pairs). Longer
# than any known hop (max ~191 Gm), so unknown never looks like the most efficient option.
UNKNOWN_DISTANCE_GM = 250

UNLIMITED = float("inf")


def _ranking_distance(distance: float | None) -> float:
    return UNKNOWN_DISTANCE_GM if distance is None else distance


@dataclass(frozen=True)
class Leg:
    id_commodity: int
    commodity_name: str
    origin: int  # terminal id
    destination: int  # terminal id
    price_buy: float
    price_sell: float
    stock: float | None = None  # SCU available at origin, None = unknown
    demand: float | None = None  # SCU the destination takes, None = unknown
    distance: float | None = None  # Gm, None = unknown
    jumps: int = 0  # star system jumps from origin to destination
    is_illegal: bool = False

    @property
    def margin(self) -> float:
        return self.price_sell - self.price_buy


@dataclass
class Trade:
    leg: Leg
    buy_stop: int  # index into RoutePlan.stops
    sell_stop: int
    scu: int
    # Set when estimated availability capped this trade: (scu without availability or None, location)
    availability_limit: tuple[int | None, str] | None = None
    # Set when the money ran out first: (scu the cargo space allows, aUEC left for this purchase,
    # the later stop whose purchases need the rest of the money, or None)
    money_limit: tuple[int, int, int | None] | None = None

    @property
    def profit(self) -> float:
        return self.scu * self.leg.margin

    @property
    def cost(self) -> float:
        return self.scu * self.leg.price_buy


@dataclass
class RoutePlan:
    stops: list[int]
    trades: list[Trade] = field(default_factory=list)
    distances: list[float | None] = field(default_factory=list)  # per hop
    jumps: list[int] = field(default_factory=list)  # star system jumps per hop
    alternative_ends: list[int] = field(default_factory=list)  # other last terminals, same cargo and profit

    @property
    def profit(self) -> float:
        return sum(trade.profit for trade in self.trades)

    @property
    def stop_count(self) -> int:
        return len(self.stops) - 1

    @property
    def distance(self) -> float | None:
        """Total distance, None if any hop distance is unknown."""
        if any(distance is None for distance in self.distances):
            return None
        return sum(self.distances)

    @property
    def jump_count(self) -> int:
        return sum(self.jumps)

    @property
    def ranking_distance(self) -> float:
        """Total distance for ranking: unknown hops count as UNKNOWN_DISTANCE_GM."""
        return sum(_ranking_distance(distance) for distance in self.distances)

    @property
    def max_cash_needed(self) -> float:
        """Highest amount of money tied up in cargo at any stop."""
        outlay = 0.0
        peak = 0.0
        for stop in range(len(self.stops)):
            outlay -= sum(t.scu * t.leg.price_sell for t in self.trades if t.sell_stop == stop)
            outlay += sum(t.cost for t in self.trades if t.buy_stop == stop)
            peak = max(peak, outlay)
        return peak

    def has_idle_stop(self) -> bool:
        """A stop where nothing is bought or sold: flying there is pointless."""
        busy = {t.buy_stop for t in self.trades} | {t.sell_stop for t in self.trades}
        return any(stop not in busy for stop in range(len(self.stops)))

    def is_circular(self) -> bool:
        return len(self.stops) > 2 and self.stops[0] == self.stops[-1]

    def score(self, ranking: str) -> float:
        return _score(self.profit, self.stop_count, self.ranking_distance, ranking)


def _score(profit: float, stop_count: int, distance: float, ranking: str) -> float:
    if ranking == RANKING_TOTAL_PROFIT:
        return profit
    if ranking == RANKING_PROFIT_PER_DISTANCE:
        return profit / (distance + stop_count * STOP_OVERHEAD_GM)
    return profit / max(stop_count, 1)


class RoutePlanner:
    EXACT_TIME_LIMIT = 0.5  # seconds per exact cargo plan; on timeout the greedy plan stays
    EXACT_TOTAL_TIME = 1.5  # seconds for all exact plans of one search (keeps voice answers quick)
    COLLECT_PLANS = 10  # best plans that get a buy-only stop tried
    COLLECT_SOURCES = 5  # terminals tried per stop that could sell their cargo
    COLLECT_SEEDS = 20  # one-way routes extended to the destination (or back to the start) by a collect stop
    COLLECT_END_TERMINALS = 5  # more destination terminals (e.g. a whole planet): no extended routes
    FILLER_SHARE = 0.005  # a purchase earning less than this share of the route's profit is left out
    ILLEGAL_FILLER_SHARE = 0.05  # the same for illegal cargo

    def __init__(
        self,
        legs: list[Leg],
        cargo_scu: float | None,
        budget: float | None = None,
        use_availability: bool = True,
        ranking: str = RANKING_PROFIT_PER_STOP,
        beam_width: int = 5,
        candidate_count: int = 200,
        exact_candidates: int = 20,
        hop_info: Callable[[int, int], tuple[float | None, int]] | None = None,
    ):
        """hop_info(origin, destination) -> (distance in Gm or None, star system jumps), for hops
        between terminals without a trade leg (a buy-only stop); legs carry their own."""
        self.cargo = UNLIMITED if cargo_scu is None else max(0, int(cargo_scu))
        self.__hop_info = hop_info
        self.budget = None if budget is None else max(0.0, float(budget))
        self.use_availability = use_availability
        self.ranking = ranking if ranking in RANKINGS else RANKING_PROFIT_PER_STOP
        self.beam_width = beam_width
        self.candidate_count = candidate_count
        self.exact_candidates = exact_candidates

        self.__legs: dict[tuple[int, int], list[Leg]] = {}
        for leg in legs:
            if leg.margin > 0 and leg.origin != leg.destination:
                self.__legs.setdefault((leg.origin, leg.destination), []).append(leg)
        for pair_legs in self.__legs.values():
            pair_legs.sort(key=lambda leg: leg.margin, reverse=True)
        self.__outgoing: dict[int, list[int]] = {}
        self.__incoming: dict[int, list[int]] = {}
        for origin, destination in self.__legs:
            self.__outgoing.setdefault(origin, []).append(destination)
            self.__incoming.setdefault(destination, []).append(origin)
        self.__sources: dict[int, list[int]] = {}
        self.__commodity_source_cache: dict[tuple[int, int], list[int]] = {}

    # ---- public

    def plan(
        self,
        max_stops: int = 1,
        return_to_start: bool = False,
        start_terminals: set[int] | None = None,
        end_terminals: set[int] | None = None,
        limit: int = 5,
        max_jumps: int | None = None,
    ) -> list[RoutePlan]:
        max_stops = max(1, int(max_stops))
        if return_to_start:
            max_stops = max(2, max_stops)  # going there and back needs two stops
        candidates = self.__search(max_stops, return_to_start, start_terminals, end_terminals, max_jumps)

        plans = []
        seen = set()
        for stops in candidates:
            key = tuple(stops)
            if key in seen:
                continue
            seen.add(key)
            plan = self.plan_cargo(stops)
            if plan.trades and plan.profit > 0:
                plans.append(plan)
        plans.sort(key=self.__rank_key, reverse=True)

        # A stop that only buys can also be what makes a route reach its destination at all: cargo for
        # the way back of a loop, or to the destination after the last sale. So the collect stops are
        # also tried on routes that fly the last hop empty, and on loops that miss the destination.
        seeds = []
        if max_stops > 1:
            # Shared fairly between the starts (the search ranks them), so one busy start can't take every seed
            start_count = len(start_terminals) if start_terminals is not None else len(self.__outgoing)
            per_start_limit = max(2, self.COLLECT_SEEDS // max(1, start_count))
            per_start: dict[int, int] = {}
            open_paths = []
            for stops in self.__search(max_stops - 1, False, start_terminals, None, max_jumps):
                if per_start.get(stops[0], 0) < per_start_limit and len(open_paths) < self.COLLECT_SEEDS:
                    per_start[stops[0]] = per_start.get(stops[0], 0) + 1
                    open_paths.append(stops)
            if return_to_start:
                seeds += [stops + [stops[0]] for stops in open_paths]
                if end_terminals is not None:
                    seeds += self.__search(max_stops, True, start_terminals, None, max_jumps)[: self.COLLECT_SEEDS]
            elif end_terminals is not None and len(end_terminals) <= self.COLLECT_END_TERMINALS:
                seeds += [stops + [end] for stops in open_paths for end in sorted(end_terminals) if end not in stops]
        extra = [self.plan_cargo(stops) for stops in seeds if tuple(stops) not in seen]
        extra = sorted((plan for plan in extra if plan.trades and plan.profit > 0), key=self.__rank_key, reverse=True)
        # Own slots for the seeds: flying a hop empty ranks them low, they would never get a turn
        bases = plans[: self.COLLECT_PLANS] + extra[: self.COLLECT_PLANS]
        for variant in self.__collect_stop_variants(
            bases, max_stops, return_to_start, start_terminals, end_terminals, max_jumps
        ):
            if tuple(variant.stops) not in seen:
                seen.add(tuple(variant.stops))
                plans.append(variant)
        plans = [plan for plan in plans if not plan.has_idle_stop()]
        plans.sort(key=self.__rank_key, reverse=True)

        if self.exact_candidates:
            # Greedy cargo plans can miss a lot: with a budget (measured on real data: multi-stop
            # down to 65 %, single hop down to 83 % of the possible profit) and on multi-stop routes
            # (random markets: down to 78 %). So the best candidates get an exact plan (~3 ms each).
            # Only a single hop without budget is skipped: there the greedy plan is provably optimal.
            deadline = time.monotonic() + self.EXACT_TOTAL_TIME
            for index, plan in enumerate(plans[: self.exact_candidates]):
                if self.budget is None and plan.stop_count < 2:
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break  # never hold up the voice answer for long: the rest keeps its greedy plan
                exact = self.exact_plan_cargo(plan.stops, time_limit=min(self.EXACT_TIME_LIMIT, remaining))
                if exact is not None and exact.profit > plan.profit + 1e-6:
                    plans[index] = exact
            # The best cargo plan skips a stop: the route without it is the real one (and a candidate itself)
            plans = [plan for plan in plans if not plan.has_idle_stop()]
        plans = [self.__drop_fillers(plan) for plan in plans]
        plans.sort(key=self.__rank_key, reverse=True)
        plans = self.__group_alternative_ends(plans)
        plans = plans[:limit] if limit else plans
        for plan in plans:
            self.__mark_money_limits(plan)
        return plans

    @staticmethod
    def __group_alternative_ends(plans: list[RoutePlan]) -> list[RoutePlan]:
        """Routes that only differ in the terminal of the last sale, at the same profit, are one route
        with alternatives: else five results can be one purchase sold at five neighbours. The best
        ranked one stays (plans come sorted)."""
        grouped = []
        first_of: dict[tuple, RoutePlan] = {}
        for plan in plans:
            if plan.is_circular():
                grouped.append(plan)
                continue
            key = (
                tuple(plan.stops[:-1]),
                tuple(sorted((t.leg.id_commodity, t.buy_stop, t.sell_stop, t.scu) for t in plan.trades)),
                round(plan.profit),
            )
            first = first_of.get(key)
            if first is None:
                first_of[key] = plan
                grouped.append(plan)
            elif plan.stops[-1] not in first.alternative_ends:
                first.alternative_ends.append(plan.stops[-1])
        return grouped

    def __collect_stop_variants(
        self, plans: list[RoutePlan], max_stops: int, return_to_start: bool,
        start_terminals: set[int] | None, end_terminals: set[int] | None, max_jumps: int | None,
    ) -> list[RoutePlan]:
        """The best plans with extra stops that only buy, e.g. a second terminal with the same commodity
        when the first one has too little stock. The path search never finds them, as it only follows
        hops with something to sell at the next stop. One stop at a time, while it raises the profit."""

        def valid(plan: RoutePlan) -> bool:
            # A loop must pass a destination; any other route already ends at one (its end never changes)
            return not (return_to_start and end_terminals is not None) or any(
                stop in end_terminals for stop in plan.stops[1:-1]
            )

        waypoints = sorted(end_terminals) if return_to_start and end_terminals is not None else []
        variants = []
        for plan in plans:
            current = plan
            while current.stop_count < max_stops:
                best = None
                # Before the start (a new start), or between two stops; a loop keeps its start
                for position in range(1 if return_to_start else 0, len(current.stops)):
                    options = self.__collect_options(current, position)
                    options += [t for t in waypoints if t not in current.stops and t not in options]
                    for terminal in options:
                        if position == 0 and start_terminals is not None and terminal not in start_terminals:
                            continue
                        stops = current.stops[:position] + [terminal] + current.stops[position:]
                        if max_jumps is not None and sum(
                            self.__jumps(stops[i], stops[i + 1]) for i in range(len(stops) - 1)
                        ) > max_jumps:
                            continue
                        candidate = self.plan_cargo(stops)
                        if candidate.has_idle_stop():
                            continue
                        # A loop that passes its destination beats one that doesn't, then profit decides
                        rival = best or current
                        if (valid(candidate), candidate.profit) > (valid(rival), rival.profit + 1e-6):
                            best = candidate
                if best is None:
                    break
                if valid(best):
                    variants.append(best)
                current = best
        return variants

    def __collect_options(self, plan: RoutePlan, position: int) -> list[int]:
        """Terminals worth a buy-only stop before plan.stops[position]: first more of a commodity that
        ran out of stock (sold at that stop or later), then the best sources of cargo for those stops."""
        stops = plan.stops
        options = []

        def add(terminals: list[int]) -> None:
            options.extend(t for t in terminals if t not in stops and t not in options)

        for trade in plan.trades:
            limit = trade.availability_limit
            if trade.sell_stop >= position and limit and "buy" in limit[1]:
                add(self.__commodity_sources(stops[trade.sell_stop], trade.leg.id_commodity))
        for target in dict.fromkeys(stops[position:]):
            add(self.__best_sources(target))
        return options

    def __best_sources(self, destination: int) -> list[int]:
        """Terminals that earn the most with one full hop to this destination."""
        if destination not in self.__sources:
            earnings = [
                (self.__fill(self.__legs[(origin, destination)], None)[0], origin)
                for origin in self.__incoming.get(destination, [])
            ]
            earnings.sort(reverse=True)
            self.__sources[destination] = [origin for profit, origin in earnings[: self.COLLECT_SOURCES] if profit > 0]
        return self.__sources[destination]

    def __commodity_sources(self, destination: int, id_commodity: int) -> list[int]:
        """Terminals with the most to earn on this commodity when sold at this destination."""
        key = (destination, id_commodity)
        if key not in self.__commodity_source_cache:
            earnings = []
            for origin in self.__incoming.get(destination, []):
                for leg in self.__legs[(origin, destination)]:
                    if leg.id_commodity == id_commodity:
                        earnings.append((leg.margin * self.__cap(leg, self.cargo if self.cargo != UNLIMITED else 1), origin))
            earnings.sort(reverse=True)
            self.__commodity_source_cache[key] = [origin for _, origin in earnings[: self.COLLECT_SOURCES]]
        return self.__commodity_source_cache[key]

    def __rank_key(self, plan: RoutePlan) -> tuple:
        # Ties: fewer stops, then shorter distance (same money for less flying)
        return plan.score(self.ranking), plan.profit, -plan.stop_count, -plan.ranking_distance

    def plan_cargo(self, stops: list[int]) -> RoutePlan:
        """Best cargo plan for a fixed sequence of stops, carrying cargo past stops if it pays (greedy)."""
        distances = [self.__distance(stops[i], stops[i + 1]) for i in range(len(stops) - 1)]
        jumps = [self.__jumps(stops[i], stops[i + 1]) for i in range(len(stops) - 1)]
        # Greedy orderings, the best result wins:
        # - profit per SCU: best when cargo space is the limit
        # - profit per aUEC spent: best when money is the limit
        # - both per occupied segment: frees cargo space for short trades on multi-stop routes
        # - each of them stop by stop in travel order: profit from earlier stops funds later purchases
        keys = [lambda o: o[1].margin, lambda o: o[1].margin / o[1].price_buy]
        option_sets = [self.__options(stops, carry_over=False)]
        if len(stops) > 2:
            option_sets.append(self.__options(stops, carry_over=True))
            keys += [lambda o: o[1].margin / (o[2] - o[0]), lambda o: o[1].margin / o[1].price_buy / (o[2] - o[0])]
        orderings = [sorted(options, key=key, reverse=True) for options in option_sets for key in keys]
        if len(stops) > 2 and self.budget is not None:
            orderings += [
                sorted(options, key=lambda o, key=key: (o[0], -key(o))) for options in option_sets for key in keys
            ]
        best = None
        for options in orderings:
            plan = RoutePlan(stops=list(stops), trades=self.__allocate(stops, options), distances=distances, jumps=jumps)
            if best is None or plan.profit > best.profit:
                best = plan
        return best

    def exact_plan_cargo(self, stops: list[int], time_limit: float | None = None) -> RoutePlan | None:
        """Optimal cargo plan for a fixed sequence of stops, solved as an integer program
        (scipy's MILP solver, shipped with Wingman AI).

        Variables: SCU per trade (commodity, buy stop, sell stop). Maximize profit, with cargo
        space per segment, stock per commodity and buy stop, demand per commodity and sell stop,
        and cash >= 0 at every stop. Returns None whenever the solver is unavailable, fails or
        its result breaks a rule, so callers keep the greedy plan.
        """
        try:
            import numpy as np
            from scipy.optimize import Bounds, LinearConstraint, milp
        except Exception:
            return None

        options = self.__options(stops, carry_over=True)
        if not options:
            return None
        count = len(options)
        buy_stops = np.array([i for i, _, _ in options])
        sell_stops = np.array([j for _, _, j in options])
        rows, upper = [], []
        for k in range(len(stops) - 1):  # cargo space per segment
            rows.append(((buy_stops <= k) & (k < sell_stops)).astype(float))
            upper.append(self.cargo)
        if self.use_availability:
            groups: dict[tuple, tuple[float, list[int]]] = {}
            for index, (i, leg, j) in enumerate(options):
                if leg.stock is not None:
                    groups.setdefault(("stock", leg.id_commodity, i), (leg.stock, []))[1].append(index)
                if leg.demand is not None:
                    groups.setdefault(("demand", leg.id_commodity, j), (leg.demand, []))[1].append(index)
            for limit, members in groups.values():
                row = np.zeros(count)
                row[members] = 1.0
                rows.append(row)
                upper.append(limit)
        if self.budget is not None:
            buy_prices = np.array([leg.price_buy for _, leg, _ in options])
            sell_prices = np.array([leg.price_sell for _, leg, _ in options])
            for k in range(len(stops)):  # money spent minus earned up to stop k <= budget
                rows.append(np.where(buy_stops <= k, buy_prices, 0.0) - np.where(sell_stops <= k, sell_prices, 0.0))
                upper.append(self.budget)

        try:
            result = milp(
                c=-np.array([leg.margin for _, leg, _ in options], dtype=float),
                constraints=LinearConstraint(np.array(rows), -np.inf, np.array(upper, dtype=float)),
                integrality=np.ones(count),
                bounds=Bounds(0, np.inf),
                # HiGHS presolve (scipy 1.17) wrongly reports some feasible problems as infeasible;
                # mip_rel_gap 0: really optimal, not just within the default 0.01 %
                options={"presolve": False, "mip_rel_gap": 0,
                         "time_limit": self.EXACT_TIME_LIMIT if time_limit is None else time_limit},
            )
        except Exception:
            return None
        if result.x is None:
            return None

        trades = [
            Trade(leg=leg, buy_stop=i, sell_stop=j, scu=int(round(amount)))
            for (i, leg, j), amount in zip(options, result.x)
            if round(amount) > 0
        ]
        distances = [self.__distance(stops[i], stops[i + 1]) for i in range(len(stops) - 1)]
        jumps = [self.__jumps(stops[i], stops[i + 1]) for i in range(len(stops) - 1)]
        plan = RoutePlan(stops=list(stops), trades=trades, distances=distances, jumps=jumps)
        if not self.__follows_rules(plan):
            return None
        self.__mark_availability_limits(plan)
        return plan

    def __follows_rules(self, plan: RoutePlan) -> bool:
        """Independent check of a cargo plan (guards against solver tolerance or rounding issues)."""
        load = [0] * plan.stop_count
        stock_used: dict[tuple[int, int], int] = {}
        demand_used: dict[tuple[int, int], int] = {}
        for trade in plan.trades:
            for k in range(trade.buy_stop, trade.sell_stop):
                load[k] += trade.scu
            stock_key, demand_key = (trade.leg.id_commodity, trade.buy_stop), (trade.leg.id_commodity, trade.sell_stop)
            stock_used[stock_key] = stock_used.get(stock_key, 0) + trade.scu
            demand_used[demand_key] = demand_used.get(demand_key, 0) + trade.scu
            if self.use_availability:
                if trade.leg.stock is not None and stock_used[stock_key] > trade.leg.stock:
                    return False
                if trade.leg.demand is not None and demand_used[demand_key] > trade.leg.demand:
                    return False
        if load and max(load) > self.cargo:
            return False
        if self.budget is not None:
            outlay = 0.0
            for stop in range(len(plan.stops)):
                outlay -= sum(t.scu * t.leg.price_sell for t in plan.trades if t.sell_stop == stop)
                outlay += sum(t.cost for t in plan.trades if t.buy_stop == stop)
                if outlay > self.budget + 1e-6:
                    return False
        return True

    def __mark_availability_limits(self, plan: RoutePlan) -> None:
        """Flag trades capped by estimated stock or demand, with the SCU they could carry if
        only cargo space and cash counted (rest of the plan unchanged) - like the greedy notes."""
        if not self.use_availability:
            return
        load = [0] * plan.stop_count
        outlay = []
        spent = 0.0
        stock_used: dict[tuple[int, int], int] = {}
        demand_used: dict[tuple[int, int], int] = {}
        for trade in plan.trades:
            for k in range(trade.buy_stop, trade.sell_stop):
                load[k] += trade.scu
            stock_key, demand_key = (trade.leg.id_commodity, trade.buy_stop), (trade.leg.id_commodity, trade.sell_stop)
            stock_used[stock_key] = stock_used.get(stock_key, 0) + trade.scu
            demand_used[demand_key] = demand_used.get(demand_key, 0) + trade.scu
        for stop in range(len(plan.stops)):
            spent -= sum(t.scu * t.leg.price_sell for t in plan.trades if t.sell_stop == stop)
            spent += sum(t.cost for t in plan.trades if t.buy_stop == stop)
            outlay.append(spent)

        for trade in plan.trades:
            stock_bound = trade.leg.stock is not None and stock_used[(trade.leg.id_commodity, trade.buy_stop)] >= trade.leg.stock
            demand_bound = trade.leg.demand is not None and demand_used[(trade.leg.id_commodity, trade.sell_stop)] >= trade.leg.demand
            if not stock_bound and not demand_bound:
                continue
            segments = range(trade.buy_stop, trade.sell_stop)
            extra = min(self.cargo - load[k] for k in segments)
            if self.budget is not None:
                extra = min(extra, min(self.budget - outlay[k] for k in segments) // trade.leg.price_buy)
            if extra == UNLIMITED or extra <= 0:
                continue  # cargo space or cash would cap it anyway
            location = "sell and buy location" if stock_bound and demand_bound else (
                "buy location" if stock_bound else "sell location")
            trade.availability_limit = (trade.scu + int(extra), location)

    def __drop_fillers(self, plan: RoutePlan) -> RoutePlan:
        """Leave out purchases that earn next to nothing, e.g. 1 SCU bought with the last aUEC: one more
        thing to load for a few aUEC. Illegal cargo must earn more, as it puts the whole route at risk.
        Only while every stop keeps something to do and the plan still follows the rules."""
        for trade in sorted(plan.trades, key=lambda t: t.profit):
            # The higher bar for illegal cargo only when leaving it out makes the route legal
            others_illegal = any(t.leg.is_illegal for t in plan.trades if t is not trade)
            share = self.ILLEGAL_FILLER_SHARE if trade.leg.is_illegal and not others_illegal else self.FILLER_SHARE
            # Of the route as it is now: several small drops never add up to a big loss
            if trade.profit >= plan.profit * share:
                continue
            candidate = RoutePlan(
                stops=plan.stops, trades=[t for t in plan.trades if t is not trade],
                distances=plan.distances, jumps=plan.jumps,
            )
            if candidate.trades and not candidate.has_idle_stop() and self.__follows_rules(candidate):
                plan = candidate
        return plan

    def __mark_money_limits(self, plan: RoutePlan) -> None:
        """Flag the last purchase at each stop where the cargo space had room for more but the money
        ran out: the user then sees why less is bought than fits. Only with a budget and a known hold."""
        for trade in plan.trades:
            trade.money_limit = None
        if self.budget is None or self.cargo == UNLIMITED:
            return
        load = [0] * plan.stop_count
        for trade in plan.trades:
            for k in range(trade.buy_stop, trade.sell_stop):
                load[k] += trade.scu
        outlay = []  # money spent so far, after each stop
        spent = 0.0
        for stop in range(len(plan.stops)):
            spent -= sum(t.scu * t.leg.price_sell for t in plan.trades if t.sell_stop == stop)
            spent += sum(t.cost for t in plan.trades if t.buy_stop == stop)
            outlay.append(spent)

        for stop in range(len(plan.stops)):
            buys = [t for t in plan.trades if t.buy_stop == stop and not t.availability_limit]
            if not buys:
                continue
            trade = buys[-1]
            segments = range(trade.buy_stop, trade.sell_stop)
            room = min(self.cargo - load[k] for k in segments)
            # Cash after each stop while this cargo is aboard: the lowest one limits the purchase,
            # which can be a later stop that needs money for its own purchases
            cash = [self.budget - outlay[k] for k in segments]
            low = min(cash)
            if room > 0 and low // trade.leg.price_buy < room:
                limiting = segments[cash.index(low)]
                later = plan.stops[limiting] if limiting > trade.buy_stop and low < cash[0] else None
                trade.money_limit = (trade.scu + int(room), round(trade.cost + low), later)

    # ---- path search

    def __search(self, max_stops, return_to_start, start_terminals, end_terminals, max_jumps) -> list[list[int]]:
        starts = [t for t in self.__outgoing if start_terminals is None or t in start_terminals]
        # state: (stops, cash, profit, distance, jumps)
        states = [([start], self.budget, 0.0, 0.0, 0) for start in starts]
        complete: list[tuple[float, list[int]]] = []

        for depth in range(max_stops):
            last_hop = depth == max_stops - 1
            expanded = []
            for stops, cash, profit, distance, jumps in states:
                for destination in self.__outgoing.get(stops[-1], []):
                    closes_loop = destination == stops[0]
                    if destination in stops and not (return_to_start and closes_loop and depth >= 1):
                        continue
                    new_jumps = jumps + self.__jumps(stops[-1], destination)
                    if max_jumps is not None and new_jumps > max_jumps:
                        continue
                    hop_profit, _ = self.__quick_fill(stops[-1], destination, cash)
                    if hop_profit <= 0:
                        continue
                    new_cash = None if cash is None else cash + hop_profit
                    new_stops = stops + [destination]
                    new_profit = profit + hop_profit
                    new_distance = distance + _ranking_distance(self.__distance(stops[-1], destination))
                    score = _score(new_profit, depth + 1, new_distance, self.ranking)
                    is_end = end_terminals is None or destination in end_terminals
                    if return_to_start:
                        if closes_loop:
                            # A loop ends at its start, so a destination means "passes through it"
                            if end_terminals is None or any(stop in end_terminals for stop in new_stops[1:-1]):
                                complete.append((score, new_stops))
                            continue
                    elif is_end:
                        complete.append((score, new_stops))
                    if not last_hop:
                        expanded.append((score, (new_stops, new_cash, new_profit, new_distance, new_jumps)))
            # Keep the best few per end terminal: diverse and bounded
            by_end: dict[int, list] = {}
            for entry in expanded:
                by_end.setdefault(entry[1][0][-1], []).append(entry)
            states = []
            for entries in by_end.values():
                entries.sort(key=lambda entry: entry[0], reverse=True)
                states.extend(state for _, state in entries[: self.beam_width])
            if not states:
                break

        complete.sort(key=lambda entry: entry[0], reverse=True)
        return [stops for _, stops in complete[: self.candidate_count]]

    def __quick_fill(self, origin: int, destination: int, cash: float | None) -> tuple[float, float]:
        """Greedy multi-commodity fill of one hop: (profit, cost)."""
        legs = self.__legs.get((origin, destination), [])
        if cash is None:
            return self.__fill(legs, None)
        # With a budget, profit per aUEC spent can beat profit per SCU
        by_return = sorted(legs, key=lambda leg: leg.margin / leg.price_buy, reverse=True)
        return max(self.__fill(legs, cash), self.__fill(by_return, cash))

    def __fill(self, legs: list[Leg], cash: float | None) -> tuple[float, float]:
        free = self.cargo
        profit = cost = 0.0
        for leg in legs:
            scu = self.__cap(leg, free)
            if cash is not None:
                scu = min(scu, (cash - cost) // leg.price_buy)
            scu = int(scu) if scu != UNLIMITED else 0
            if scu <= 0:
                continue
            profit += scu * leg.margin
            cost += scu * leg.price_buy
            free -= scu
            if free <= 0:
                break
        return profit, cost

    # ---- cargo allocation

    def __options(self, stops: list[int], carry_over: bool) -> list[tuple[int, Leg, int]]:
        """(buy stop, leg, sell stop) for every profitable trade along the path."""
        options = []
        for i in range(len(stops) - 1):
            last = len(stops) if carry_over else i + 2
            for j in range(i + 1, last):
                for leg in self.__legs.get((stops[i], stops[j]), []):
                    options.append((i, leg, j))
        return options

    def __allocate(self, stops: list[int], options: list[tuple[int, Leg, int]]) -> list[Trade]:
        segments = len(stops) - 1
        free = [self.cargo] * segments  # cargo space between stop k and k+1
        # cash[k]: money left after trading at stop k (sales first, then purchases)
        cash = None if self.budget is None else [self.budget] * len(stops)
        stock_left: dict[tuple[int, int], float] = {}
        demand_left: dict[tuple[int, int], float] = {}
        trades = []

        for i, leg, j in options:
            unlimited = min(free[i:j])
            if cash is not None:
                unlimited = min(unlimited, min(cash[i:j]) // leg.price_buy)
            if unlimited == UNLIMITED or unlimited <= 0:
                continue
            unlimited = int(unlimited)

            scu = unlimited
            stock_key, demand_key = (leg.id_commodity, i), (leg.id_commodity, j)
            if self.use_availability:
                stock = stock_left.get(stock_key, leg.stock)
                demand = demand_left.get(demand_key, leg.demand)
                if stock is not None:
                    scu = min(scu, int(stock))
                if demand is not None:
                    scu = min(scu, int(demand))
            if scu <= 0:
                continue

            limit = None
            if scu < unlimited:
                stock = stock_left.get(stock_key, leg.stock)
                demand = demand_left.get(demand_key, leg.demand)
                if demand is None or (stock is not None and stock < demand):
                    location = "buy location"
                elif stock is None or stock > demand:
                    location = "sell location"
                else:
                    location = "sell and buy location"
                limit = (unlimited, location)

            for k in range(i, j):
                free[k] -= scu
            if cash is not None:
                for k in range(i, len(stops)):
                    cash[k] -= scu * leg.price_buy
                for k in range(j, len(stops)):
                    cash[k] += scu * leg.price_sell
            if self.use_availability:
                if leg.stock is not None:
                    stock_left[stock_key] = stock_left.get(stock_key, leg.stock) - scu
                if leg.demand is not None:
                    demand_left[demand_key] = demand_left.get(demand_key, leg.demand) - scu
            trades.append(Trade(leg=leg, buy_stop=i, sell_stop=j, scu=scu, availability_limit=limit))
        return trades

    # ---- helpers

    def __cap(self, leg: Leg, free: float) -> float:
        scu = free
        if self.use_availability:
            if leg.stock is not None:
                scu = min(scu, leg.stock)
            if leg.demand is not None:
                scu = min(scu, leg.demand)
        return scu

    def __distance(self, origin: int, destination: int) -> float | None:
        legs = self.__legs.get((origin, destination))
        if legs:
            return legs[0].distance
        return self.__hop_info(origin, destination)[0] if self.__hop_info else None

    def __jumps(self, origin: int, destination: int) -> int:
        legs = self.__legs.get((origin, destination))
        if legs:
            return legs[0].jumps
        return self.__hop_info(origin, destination)[1] if self.__hop_info else 0
