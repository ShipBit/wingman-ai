"""The route planner against an exact reference, on a few fixed random markets.

The planner is a heuristic (greedy cargo fill, beam search over stops). route_oracle is an
independent exact solver (integer program for the cargo plan, brute force over all stop
sequences), which itself is cross-checked by plain enumeration on tiny instances.

1. Hard rules, on every returned route: cargo space, stock, demand and cash are never exceeded,
   trades come from real legs, cargo is only sold after it was bought, no terminal is visited
   twice, the filters hold, the ranking order is right, and the reported profit never exceeds
   what is possible.
2. Exactness where the method guarantees it: a single hop without budget, and every shown route.
3. One quality floor on the fixed markets, as a regression guard for the search.

The markets are generated from fixed seeds, so the run is the same every time. They are few and
picked so that multi-stop routes, carried-over cargo and a binding budget all occur."""

from __future__ import annotations

import random
import statistics
from types import SimpleNamespace

import pytest

from skills.uexcorp.uexcorp.route_planner import RANKINGS, RoutePlan, RoutePlanner
from tests.skills.uexcorp.route_oracle import (
    all_routes,
    best_route,
    brute_force_cargo_profit,
    by_pair,
    exact_cargo_profit,
    random_legs,
    score,
)

EPSILON = 1e-6

# (seed, terminals, commodities, cargo, budget)
MARKETS = [
    (5, 4, 3, 10, 150),
    (12, 4, 3, 20, 500),
    (15, 4, 3, 46, 1000),
    (13, 4, 3, 20, None),
    (8, 5, 3, 20, 500),
]


def build_market(seed: int, terminals: int, commodities: int, cargo: int, budget: float | None) -> SimpleNamespace:
    legs = random_legs(random.Random(seed), terminals=terminals, commodities=commodities)
    pairs = by_pair(legs)
    # The legs the planner is given: the profitable ones that are not sold out, the oracle's view
    usable = [leg for legs_of_pair in pairs.values() for leg in legs_of_pair]
    return SimpleNamespace(legs=legs, usable=usable, pairs=pairs, cargo=cargo, budget=budget)


@pytest.fixture(scope="module")
def markets():
    return [build_market(*spec) for spec in MARKETS]


def check_plan_rules(plan: RoutePlan, legs_by_pair, cargo: int, budget: float | None, use_availability: bool = True) -> None:
    """Every rule a cargo plan must follow, checked independently of the planner."""
    stops = plan.stops
    assert len(stops) >= 2
    inner = stops[1:-1] if plan.is_circular() else stops[1:]
    assert len({stops[0], *inner}) == len(inner) + 1, f"terminal visited twice: {stops}"

    aboard = [0] * (len(stops) - 1)
    stock_used, demand_used = {}, {}
    for trade in plan.trades:
        i, j, leg = trade.buy_stop, trade.sell_stop, trade.leg
        assert i < j, "sold before bought"
        assert isinstance(trade.scu, int) and trade.scu > 0
        assert leg in legs_by_pair.get((stops[i], stops[j]), []), "trade not backed by a leg of these stops"
        assert leg.margin > 0
        for k in range(i, j):
            aboard[k] += trade.scu
        stock_used[(leg.id_commodity, i)] = stock_used.get((leg.id_commodity, i), 0) + trade.scu
        demand_used[(leg.id_commodity, j)] = demand_used.get((leg.id_commodity, j), 0) + trade.scu
        if use_availability and leg.stock is not None:
            assert stock_used[(leg.id_commodity, i)] <= leg.stock, "stock exceeded"
        if use_availability and leg.demand is not None:
            assert demand_used[(leg.id_commodity, j)] <= leg.demand, "demand exceeded"
    assert max(aboard) <= cargo, f"cargo space exceeded: {aboard}"

    outlay, peak = 0.0, 0.0
    for stop in range(len(stops)):
        outlay -= sum(t.scu * t.leg.price_sell for t in plan.trades if t.sell_stop == stop)
        outlay += sum(t.scu * t.leg.price_buy for t in plan.trades if t.buy_stop == stop)
        peak = max(peak, outlay)
        if budget is not None:
            assert outlay <= budget + EPSILON, f"cash below zero at stop {stop}"
    assert plan.max_cash_needed == pytest.approx(peak, abs=1e-4)
    assert plan.profit == pytest.approx(sum(t.scu * t.leg.margin for t in plan.trades), abs=1e-4)


def check_routes(plans, pairs, cargo, budget, ranking, max_stops, return_to_start=False,
                 start_terminals=None, end_terminals=None) -> None:
    for plan in plans:
        check_plan_rules(plan, pairs, cargo, budget)
        assert plan.profit > 0
        assert plan.stop_count <= max(max_stops, 2 if return_to_start else 1)
        # A hop needs no leg (a stop may only buy), but every stop must buy or sell something
        assert not plan.has_idle_stop(), "stop without any trade"
        if return_to_start:
            assert plan.is_circular()
            if end_terminals:
                assert any(s in end_terminals for s in plan.stops[1:-1])
        else:
            assert not plan.is_circular()
            if end_terminals:
                assert plan.stops[-1] in end_terminals
        if start_terminals:
            assert plan.stops[0] in start_terminals
        assert plan.profit <= exact_cargo_profit(plan.stops, pairs, cargo, budget) + EPSILON
        # The planner's own score must match the documented metric
        assert plan.score(ranking) == pytest.approx(score(plan.profit, plan.stops, plan.distances, ranking), abs=1e-6)
    scores = [plan.score(ranking) for plan in plans]
    assert scores == sorted(scores, reverse=True), "routes not ordered by ranking"
    assert len({tuple(p.stops) for p in plans}) == len(plans), "duplicate routes"


@pytest.fixture
def without_fillers(monkeypatch):
    """Measures the optimizer against the exact optimum: purchases the planner leaves out on purpose
    as fillers (tested in test_route_planner) would count as misses."""
    monkeypatch.setattr(RoutePlanner, "FILLER_SHARE", 0)
    monkeypatch.setattr(RoutePlanner, "ILLEGAL_FILLER_SHARE", 0)


def test_the_reference_matches_plain_enumeration_on_tiny_instances():
    rng = random.Random(7)
    checked = 0
    while checked < 10:
        legs = random_legs(rng, terminals=3, commodities=2)
        pairs = by_pair(legs)
        cargo = rng.choice([2, 3, 5])
        budget = rng.choice([None, 60, 300])
        for stops in all_routes(pairs, 2):
            options = sum(len(pairs.get((stops[i], stops[j]), [])) for i in range(len(stops)) for j in range(i + 1, len(stops)))
            if not 0 < options <= 4 or checked >= 10:
                continue  # brute force grows with (cargo + 1) ** options
            assert exact_cargo_profit(stops, pairs, cargo, budget) == pytest.approx(
                brute_force_cargo_profit(stops, pairs, cargo, budget), abs=1e-4
            ), f"stops={stops} cargo={cargo} budget={budget}"
            checked += 1


def test_a_single_hop_without_budget_is_optimal(markets):
    # Greedy by profit per SCU is exact when cargo space is the only shared limit
    for market in markets:
        planner = RoutePlanner(market.legs, cargo_scu=market.cargo)
        for stops in all_routes(market.pairs, 1):
            plan = planner.plan_cargo(stops)
            check_plan_rules(plan, market.pairs, market.cargo, None)
            assert plan.profit == pytest.approx(exact_cargo_profit(stops, market.pairs, market.cargo), abs=1e-4), stops


def test_cargo_plans_follow_all_rules_and_never_beat_the_optimum(markets):
    carried = budget_bound = multi_stop = 0
    for market in markets:
        for budget in (None, market.budget or 1000):
            for use_availability in (True, False):
                # Availability off: sold-out legs are fine to trade (stock and demand are ignored)
                pairs = by_pair(market.legs, use_availability)
                planner = RoutePlanner(market.legs, cargo_scu=market.cargo, budget=budget, use_availability=use_availability)
                for stops in list(all_routes(pairs, 3))[:12]:
                    plan = planner.plan_cargo(stops)
                    check_plan_rules(plan, pairs, market.cargo, budget, use_availability)
                    assert plan.profit <= exact_cargo_profit(stops, pairs, market.cargo, budget, use_availability) + EPSILON, \
                        "planner claims more than possible"
                    multi_stop += len(stops) > 2
                    carried += any(t.sell_stop - t.buy_stop > 1 for t in plan.trades)
                    if budget is not None and use_availability:
                        budget_bound += exact_cargo_profit(stops, pairs, market.cargo, budget) < exact_cargo_profit(stops, pairs, market.cargo) - EPSILON

    assert multi_stop and carried and budget_bound, "the fixed markets no longer cover every case"


def test_shown_routes_follow_all_rules_have_exact_cargo_plans_and_the_best_is_close(markets, without_fillers):
    # Shown routes get exact cargo plans (scipy MILP inside the planner) with a budget and on
    # multi-stop routes; a single hop without budget is provably optimal greedy. So every shown
    # route must match the independent reference exactly. The route search itself is a heuristic.
    ratios = []
    for market in markets:
        for ranking in RANKINGS:
            for max_stops, circular in ((1, False), (3, False), (3, True)):
                planner = RoutePlanner(market.usable, cargo_scu=market.cargo, budget=market.budget, ranking=ranking)
                plans = planner.plan(max_stops=max_stops, return_to_start=circular, limit=5)
                check_routes(plans, market.pairs, market.cargo, market.budget, ranking, max_stops, circular)
                for plan in plans:
                    exact = exact_cargo_profit(plan.stops, market.pairs, market.cargo, market.budget)
                    assert plan.profit == pytest.approx(exact, abs=1e-4), f"{plan.stops} cargo={market.cargo} budget={market.budget}"
                best = best_route(market.pairs, market.cargo, market.budget, True, ranking, max_stops, return_to_start=circular)
                got = plans[0].score(ranking) if plans else 0.0
                best_score = best[0] if best else 0.0
                assert got <= best_score + EPSILON
                ratios.append(1.0 if best_score <= EPSILON else got / best_score)

    # Regression floor for the search on the fixed markets (measured: mean 0.996, the best route in 93 % of the searches)
    assert statistics.mean(ratios) >= 0.97
    assert sum(r >= 1 - EPSILON for r in ratios) / len(ratios) >= 0.75


def test_start_and_end_filters_hold_and_nothing_valid_is_left_out(markets):
    rng = random.Random(22)
    for market in markets:
        terminals = sorted({t for pair in market.pairs for t in pair})
        start, end = {rng.choice(terminals)}, {rng.choice(terminals)}
        for circular in (False, True):
            planner = RoutePlanner(market.usable, cargo_scu=20)
            plans = planner.plan(max_stops=3, return_to_start=circular, start_terminals=start, end_terminals=end, limit=0)
            check_routes(plans, market.pairs, 20, None, planner.ranking, 3, circular, start, end)
            # The planner finds a route whenever one exists
            exists = best_route(market.pairs, 20, None, True, planner.ranking, 3, return_to_start=circular,
                                start_terminals=start, end_terminals=end)
            assert bool(plans) == (exists is not None), f"start={start} end={end} circular={circular}"


def test_a_single_hop_search_returns_every_pair_in_ranked_order(markets):
    for market in markets:
        for ranking in RANKINGS:
            plans = RoutePlanner(market.usable, cargo_scu=30, ranking=ranking).plan(limit=0)
            check_routes(plans, market.pairs, 30, None, ranking, 1)
            # Without budget each hop's plan is optimal, so the ranking must be the exact one
            expected = sorted(
                (score(exact_cargo_profit(list(pair), market.pairs, 30), list(pair), [market.pairs[pair][0].distance], ranking), pair)
                for pair in market.pairs if exact_cargo_profit(list(pair), market.pairs, 30) > 0
            )
            assert [round(s, 6) for s, _ in sorted(expected, reverse=True)] == [round(p.score(ranking), 6) for p in plans]
