"""Exact reference ("oracle") for the trade route planner tests.

Independent of the planner's own logic: the best cargo plan for a fixed sequence of
stops is solved as an integer program with scipy's MILP solver, and the best route is
found by brute force over all valid stop sequences. Only usable for small instances.

Model (same rules the planner promises to follow):
- a trade buys commodity c at stop i and sells it at a later stop j (cargo may stay
  aboard over stops in between); x = SCU of that trade, integer >= 0
- cargo space: the trades aboard on any segment (stop k to k+1) use <= cargo SCU
- stock: per commodity and buy stop, <= the leg's stock (if known and availability on)
- demand: per commodity and sell stop, <= the leg's demand (if known and availability on)
- cash: at every stop (sales first, then purchases) the money left is >= 0
"""

from __future__ import annotations

import itertools
import random

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from skills.uexcorp.uexcorp.route_planner import (
    RANKING_PROFIT_PER_DISTANCE,
    RANKING_TOTAL_PROFIT,
    STOP_OVERHEAD_GM,
    UNKNOWN_DISTANCE_GM,
    Leg,
)


def options_for(stops: list[int], legs_by_pair: dict[tuple[int, int], list[Leg]]) -> list[tuple[int, Leg, int]]:
    options = []
    for i in range(len(stops) - 1):
        for j in range(i + 1, len(stops)):
            for leg in legs_by_pair.get((stops[i], stops[j]), []):
                options.append((i, leg, j))
    return options


def exact_cargo_profit(
    stops: list[int],
    legs_by_pair: dict[tuple[int, int], list[Leg]],
    cargo: int,
    budget: float | None = None,
    use_availability: bool = True,
    carry_over: bool = True,
) -> float:
    """Maximum profit for a fixed sequence of stops (MILP)."""
    options = options_for(stops, legs_by_pair)
    if not carry_over:
        options = [o for o in options if o[2] == o[0] + 1]
    if not options:
        return 0.0
    n = len(options)
    margins = np.array([leg.margin for _, leg, _ in options], dtype=float)
    rows, upper = [], []

    for k in range(len(stops) - 1):  # cargo space per segment
        rows.append([1.0 if i <= k < j else 0.0 for i, _, j in options])
        upper.append(cargo)
    if use_availability:
        groups: dict[tuple, list[int]] = {}
        for index, (i, leg, j) in enumerate(options):
            if leg.stock is not None:
                groups.setdefault(("stock", leg.id_commodity, i, leg.stock), []).append(index)
            if leg.demand is not None:
                groups.setdefault(("demand", leg.id_commodity, j, leg.demand), []).append(index)
        for (kind, _commodity, _stop, limit), members in groups.items():
            rows.append([1.0 if index in members else 0.0 for index in range(n)])
            upper.append(limit)
    if budget is not None:
        for k in range(len(stops)):  # spent - earned up to stop k <= budget
            rows.append([
                (leg.price_buy if i <= k else 0.0) - (leg.price_sell if j <= k else 0.0)
                for i, leg, j in options
            ])
            upper.append(budget)

    result = milp(
        c=-margins,
        constraints=LinearConstraint(np.array(rows), -np.inf, np.array(upper, dtype=float)),
        integrality=np.ones(n),
        bounds=Bounds(0, np.inf),
        # HiGHS presolve (scipy 1.17) wrongly reports some feasible integer problems with
        # fractional coefficients as infeasible; brute_force_cargo_profit cross-checks this.
        options={"presolve": False, "mip_rel_gap": 0},  # exact, not within the default 0.01 %
    )
    assert result.success, result.message
    return float(-result.fun)


def brute_force_cargo_profit(
    stops: list[int],
    legs_by_pair: dict[tuple[int, int], list[Leg]],
    cargo: int,
    budget: float | None = None,
    use_availability: bool = True,
) -> float:
    """Same model as exact_cargo_profit by plain enumeration - only for tiny instances,
    to verify the MILP oracle itself."""
    options = options_for(stops, legs_by_pair)
    best = 0.0

    def feasible(amounts: list[int]) -> bool:
        for k in range(len(stops) - 1):
            if sum(x for (i, _, j), x in zip(options, amounts) if i <= k < j) > cargo:
                return False
        if use_availability:
            stock, demand = {}, {}
            for (i, leg, j), x in zip(options, amounts):
                if leg.stock is not None:
                    stock[(leg.id_commodity, i)] = stock.get((leg.id_commodity, i), 0) + x
                    if stock[(leg.id_commodity, i)] > leg.stock:
                        return False
                if leg.demand is not None:
                    demand[(leg.id_commodity, j)] = demand.get((leg.id_commodity, j), 0) + x
                    if demand[(leg.id_commodity, j)] > leg.demand:
                        return False
        if budget is not None:
            for k in range(len(stops)):
                spent = sum(x * (leg.price_buy if i <= k else 0) - x * (leg.price_sell if j <= k else 0)
                            for (i, leg, j), x in zip(options, amounts))
                if spent > budget + 1e-9:
                    return False
        return True

    for amounts in itertools.product(range(cargo + 1), repeat=len(options)):
        if feasible(list(amounts)):
            best = max(best, sum(x * leg.margin for (_, leg, _), x in zip(options, amounts)))
    return best


def score(profit: float, stops: list[int], distances: list[float | None], ranking: str) -> float:
    stop_count = len(stops) - 1
    if ranking == RANKING_TOTAL_PROFIT:
        return profit
    if ranking == RANKING_PROFIT_PER_DISTANCE:
        distance = sum(UNKNOWN_DISTANCE_GM if d is None else d for d in distances)
        return profit / (distance + stop_count * STOP_OVERHEAD_GM)
    return profit / stop_count


def all_routes(
    legs_by_pair: dict[tuple[int, int], list[Leg]],
    max_stops: int,
    return_to_start: bool = False,
    start_terminals: set[int] | None = None,
    end_terminals: set[int] | None = None,
):
    """Every stop sequence the planner may return: no terminal twice (a circular route only returns
    to its start at the end). Consecutive stops need no leg between them: a stop may only buy cargo
    that is sold later. Routes where a stop does nothing are skipped by the exact plan (no profit gain)."""
    terminals = sorted({t for pair in legs_by_pair for t in pair})
    starts = [t for t in terminals if start_terminals is None or t in start_terminals]
    if return_to_start:
        max_stops = max(2, max_stops)
    for start in starts:
        frontier = [[start]]
        for depth in range(max_stops):
            next_frontier = []
            for stops in frontier:
                for destination in terminals:
                    if destination == stops[-1]:
                        continue
                    route = stops + [destination]
                    if return_to_start:
                        if destination == start and depth >= 1:
                            if end_terminals is None or any(s in end_terminals for s in route[1:-1]):
                                yield route
                            continue
                        if destination in stops:
                            continue
                    else:
                        if destination in stops:
                            continue
                        if end_terminals is None or destination in end_terminals:
                            yield route
                    next_frontier.append(route)
            frontier = next_frontier


def best_route(legs_by_pair, cargo, budget, use_availability, ranking, max_stops, **route_filters):
    """(score, profit, stops) of the best route by exhaustive search with exact cargo plans."""
    best = None
    for stops in all_routes(legs_by_pair, max_stops, **route_filters):
        # Every stop must be able to buy or sell something on this route (the planner shows no idle stops)
        busy = {index for i, _, j in options_for(stops, legs_by_pair) for index in (i, j)}
        if len(busy) < len(stops):
            continue
        profit = exact_cargo_profit(stops, legs_by_pair, cargo, budget, use_availability)
        if profit <= 0:
            continue
        # A hop without a leg has no known distance (the planner without hop_info agrees)
        distances = [
            legs_by_pair[(stops[k], stops[k + 1])][0].distance if (stops[k], stops[k + 1]) in legs_by_pair else None
            for k in range(len(stops) - 1)
        ]
        candidate = (score(profit, stops, distances, ranking), profit, stops)
        if best is None or candidate[0] > best[0] + 1e-9:
            # A stop in between must earn something: without it the best plan makes less (else it is idle)
            if all(
                exact_cargo_profit(stops[:k] + stops[k + 1:], legs_by_pair, cargo, budget, use_availability) < profit - 1e-6
                for k in range(1, len(stops) - 1)
            ):
                best = candidate
    return best


def random_legs(rng: random.Random, terminals: int = 5, commodities: int = 4, known_stock: float = 0.7,
                known_demand: float = 0.3, unknown_distance: float = 0.1) -> list[Leg]:
    """Random market: each commodity has buy offers at some terminals and sell offers at others,
    every profitable (buy, sell) pair becomes a leg - like the derived commodity_route table."""
    ids = list(range(1, terminals + 1))
    distances = {}
    for a, b in itertools.combinations(ids, 2):
        distance = None if rng.random() < unknown_distance else float(rng.choice([0, rng.randint(5, 190)]))
        distances[(a, b)] = distances[(b, a)] = distance
    legs = []
    for commodity in range(1, commodities + 1):
        base = rng.randint(5, 200)
        buys = {t: base * rng.uniform(0.6, 1.1) for t in rng.sample(ids, rng.randint(1, min(3, len(ids))))}
        sells = {t: base * rng.uniform(0.9, 1.6) for t in rng.sample(ids, rng.randint(1, min(4, len(ids))))}
        # Like the real data: stock belongs to the buy terminal's price row, demand to the
        # sell terminal's, so every leg from/to that terminal shares the same value
        demands = {t: (rng.randint(1, 40) if rng.random() < known_demand else None) for t in sells}
        for origin, buy in buys.items():
            stock = rng.randint(0, 40) if rng.random() < known_stock else None
            for destination, sell in sells.items():
                if origin == destination or sell <= buy:
                    continue
                demand = demands[destination]
                legs.append(Leg(
                    id_commodity=commodity, commodity_name=f"C{commodity}", origin=origin, destination=destination,
                    price_buy=round(buy, 2), price_sell=round(sell, 2), stock=stock, demand=demand,
                    distance=distances[(origin, destination)],
                ))
    return legs


def by_pair(legs: list[Leg], use_availability: bool = True) -> dict[tuple[int, int], list[Leg]]:
    """Legs the planner considers: positive margin, and (availability on) not sold out."""
    pairs: dict[tuple[int, int], list[Leg]] = {}
    for leg in legs:
        if leg.margin <= 0:
            continue
        if use_availability and ((leg.stock is not None and leg.stock <= 0) or (leg.demand is not None and leg.demand <= 0)):
            continue
        pairs.setdefault((leg.origin, leg.destination), []).append(leg)
    return pairs
