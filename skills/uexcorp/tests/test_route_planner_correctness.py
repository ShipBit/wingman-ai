"""Correctness of the trade route planner against an exact reference, on random markets.

No pytest. Run from the project root:

    python3 -m skills.uexcorp.tests.test_route_planner_correctness

Exits non-zero on the first failed assertion or crash; prints "ALL OK" on success.
Needs scipy (part of Wingman AI's requirements); takes ~20 s.

Why this exists
---------------
The planner is a heuristic (greedy cargo fill, beam search over stops). These tests
check it against route_oracle, an independent exact solver (integer program for the
cargo plan, brute force over all stop sequences), which itself is cross-checked by
plain enumeration on tiny instances. Three kinds of checks:

1. Hard rules, on every returned route: cargo space, stock, demand and cash are never
   exceeded, prices and trades come from real legs, cargo is only sold after it was
   bought, no terminal is visited twice, filters hold, ranking order is right, and the
   reported profit never exceeds what is actually possible.
2. Exactness where the method guarantees it: a single hop without budget is optimal.
3. Quality floors where it is a heuristic: how close it gets to the optimum, as a
   regression guard (measured values in the comments).
"""

from __future__ import annotations

import random
import statistics
import unittest

from skills.uexcorp.tests.route_oracle import (
    all_routes,
    best_route,
    brute_force_cargo_profit,
    by_pair,
    exact_cargo_profit,
    random_legs,
    score,
)
from skills.uexcorp.uexcorp.route_planner import (
    RANKING_PROFIT_PER_DISTANCE,
    RANKING_TOTAL_PROFIT,
    RANKINGS,
    RoutePlan,
    RoutePlanner,
)

EPSILON = 1e-6


def ratio(planner_value: float, exact_value: float) -> float:
    return 1.0 if exact_value <= EPSILON else planner_value / exact_value


def check_plan_rules(test: unittest.TestCase, plan: RoutePlan, legs_by_pair, cargo: int, budget: float | None,
                     use_availability: bool = True) -> None:
    """Every rule a cargo plan must follow, checked independently of the planner."""
    stops = plan.stops
    test.assertGreaterEqual(len(stops), 2)
    inner = stops[1:-1] if plan.is_circular() else stops[1:]
    test.assertEqual(len({stops[0], *inner}), len(inner) + 1, f"terminal visited twice: {stops}")

    aboard = [0] * (len(stops) - 1)
    stock_used, demand_used = {}, {}
    for trade in plan.trades:
        i, j, leg = trade.buy_stop, trade.sell_stop, trade.leg
        test.assertLess(i, j, "sold before bought")
        test.assertGreater(trade.scu, 0)
        test.assertIsInstance(trade.scu, int)
        test.assertIn(leg, legs_by_pair.get((stops[i], stops[j]), []), "trade not backed by a leg of these stops")
        test.assertGreater(leg.margin, 0)
        for k in range(i, j):
            aboard[k] += trade.scu
        stock_used[(leg.id_commodity, i)] = stock_used.get((leg.id_commodity, i), 0) + trade.scu
        demand_used[(leg.id_commodity, j)] = demand_used.get((leg.id_commodity, j), 0) + trade.scu
        if use_availability and leg.stock is not None:
            test.assertLessEqual(stock_used[(leg.id_commodity, i)], leg.stock, "stock exceeded")
        if use_availability and leg.demand is not None:
            test.assertLessEqual(demand_used[(leg.id_commodity, j)], leg.demand, "demand exceeded")
    test.assertLessEqual(max(aboard), cargo, f"cargo space exceeded: {aboard}")

    outlay, peak = 0.0, 0.0
    for stop in range(len(stops)):
        outlay -= sum(t.scu * t.leg.price_sell for t in plan.trades if t.sell_stop == stop)
        outlay += sum(t.scu * t.leg.price_buy for t in plan.trades if t.buy_stop == stop)
        peak = max(peak, outlay)
        if budget is not None:
            test.assertLessEqual(outlay, budget + EPSILON, f"cash below zero at stop {stop}")
    test.assertAlmostEqual(plan.max_cash_needed, peak, places=4)
    test.assertAlmostEqual(plan.profit, sum(t.scu * t.leg.margin for t in plan.trades), places=4)


class OracleSelfTest(unittest.TestCase):
    """The reference must be right before it can judge the planner."""

    def test_milp_matches_brute_force_on_tiny_instances(self) -> None:
        rng = random.Random(7)
        checked = 0
        while checked < 120:
            legs = random_legs(rng, terminals=3, commodities=2)
            pairs = by_pair(legs)
            if not pairs:
                continue
            cargo = rng.choice([2, 3, 5])
            budget = rng.choice([None, 60, 300])
            for stops in all_routes(pairs, 2):
                options = sum(len(pairs.get((stops[i], stops[j]), [])) for i in range(len(stops)) for j in range(i + 1, len(stops)))
                if options > 4:
                    continue  # brute force grows with (cargo + 1) ** options
                self.assertAlmostEqual(
                    exact_cargo_profit(stops, pairs, cargo, budget),
                    brute_force_cargo_profit(stops, pairs, cargo, budget),
                    places=4, msg=f"stops={stops} cargo={cargo} budget={budget}",
                )
                checked += 1


class CargoPlanTest(unittest.TestCase):
    def test_single_hop_without_budget_is_optimal(self) -> None:
        # Greedy by profit per SCU is exact when cargo space is the only shared limit
        rng = random.Random(11)
        for _ in range(150):
            legs = random_legs(rng, terminals=rng.randint(3, 6), commodities=rng.randint(1, 6))
            pairs = by_pair(legs)
            cargo = rng.choice([1, 4, 10, 46, 696])
            planner = RoutePlanner(legs, cargo_scu=cargo)
            for stops in all_routes(pairs, 1):
                plan = planner.plan_cargo(stops)
                check_plan_rules(self, plan, pairs, cargo, None)
                self.assertAlmostEqual(plan.profit, exact_cargo_profit(stops, pairs, cargo), places=4, msg=str(stops))

    def test_plans_follow_all_rules_and_never_beat_the_optimum(self) -> None:
        rng = random.Random(12)
        stats: dict[str, list[float]] = {}
        for _ in range(150):
            legs = random_legs(rng, terminals=rng.randint(3, 6), commodities=rng.randint(2, 6))
            cargo = rng.choice([4, 10, 46, 120])
            for budget in (None, rng.choice([200, 1000, 5000])):
                for use_availability in (True, False):
                    # Availability off: sold-out legs are fine to trade (stock/demand are ignored)
                    pairs = by_pair(legs, use_availability)
                    planner = RoutePlanner(legs, cargo_scu=cargo, budget=budget, use_availability=use_availability)
                    for stops in list(all_routes(pairs, 3))[:20]:
                        plan = planner.plan_cargo(stops)
                        check_plan_rules(self, plan, pairs, cargo, budget, use_availability)
                        exact = exact_cargo_profit(stops, pairs, cargo, budget, use_availability)
                        self.assertLessEqual(plan.profit, exact + EPSILON, "planner claims more than possible")
                        kind = f"{'hop' if len(stops) == 2 else 'multi-stop'}, budget={budget is not None}"
                        stats.setdefault(kind, []).append(ratio(plan.profit, exact))

        # Quality floors (heuristic). Measured: hop without budget 100 % optimal; hop with budget
        # mean 0.999 / 98 % optimal; multi-stop without budget mean 0.998 / 94 % optimal;
        # multi-stop with budget mean 0.96 / 68 % optimal.
        floors = {
            "hop, budget=False": (1.0, 1.0),
            "hop, budget=True": (0.99, 0.95),
            "multi-stop, budget=False": (0.99, 0.90),
            "multi-stop, budget=True": (0.93, 0.60),
        }
        for kind, (mean_floor, optimal_share_floor) in floors.items():
            values = stats[kind]
            optimal_share = sum(1 for v in values if v >= 1 - EPSILON) / len(values)
            print(f"  cargo plan {kind:28} n={len(values):5} mean={statistics.mean(values):.4f} optimal={optimal_share:.1%} worst={min(values):.3f}")
            self.assertGreaterEqual(statistics.mean(values), mean_floor - EPSILON, kind)
            self.assertGreaterEqual(optimal_share, optimal_share_floor - EPSILON, kind)


class RouteSearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Measures the optimizer against the exact optimum: purchases the planner leaves out on
        # purpose as fillers (tested in test_route_planner) would count as misses here
        cls._filler_shares = RoutePlanner.FILLER_SHARE, RoutePlanner.ILLEGAL_FILLER_SHARE
        RoutePlanner.FILLER_SHARE = RoutePlanner.ILLEGAL_FILLER_SHARE = 0

    @classmethod
    def tearDownClass(cls) -> None:
        RoutePlanner.FILLER_SHARE, RoutePlanner.ILLEGAL_FILLER_SHARE = cls._filler_shares

    def _check_routes(self, plans, pairs, cargo, budget, ranking, max_stops, return_to_start=False,
                      start_terminals=None, end_terminals=None) -> None:
        for plan in plans:
            check_plan_rules(self, plan, pairs, cargo, budget)
            self.assertGreater(plan.profit, 0)
            self.assertLessEqual(plan.stop_count, max(max_stops, 2 if return_to_start else 1))
            # A hop needs no leg (a stop may only buy), but every stop must buy or sell something
            self.assertFalse(plan.has_idle_stop(), "stop without any trade")
            if return_to_start:
                self.assertTrue(plan.is_circular())
                if end_terminals:
                    self.assertTrue(any(s in end_terminals for s in plan.stops[1:-1]))
            else:
                self.assertFalse(plan.is_circular())
                if end_terminals:
                    self.assertIn(plan.stops[-1], end_terminals)
            if start_terminals:
                self.assertIn(plan.stops[0], start_terminals)
            exact = exact_cargo_profit(plan.stops, pairs, cargo, budget)
            self.assertLessEqual(plan.profit, exact + EPSILON)
            # The planner's own score must match the documented metric
            self.assertAlmostEqual(plan.score(ranking), score(plan.profit, plan.stops, plan.distances, ranking), places=6)
        scores = [plan.score(ranking) for plan in plans]
        self.assertEqual(scores, sorted(scores, reverse=True), "routes not ordered by ranking")
        self.assertEqual(len({tuple(p.stops) for p in plans}), len(plans), "duplicate routes")

    def test_routes_follow_all_rules_and_get_close_to_the_best_route(self) -> None:
        rng = random.Random(21)
        stats: dict[str, list[float]] = {}
        for _ in range(60):
            legs = random_legs(rng, terminals=rng.randint(4, 6), commodities=rng.randint(2, 5))
            pairs = by_pair(legs)
            if not pairs:
                continue
            cargo = rng.choice([4, 10, 46])
            budget = rng.choice([None, None, 1000])
            for ranking in RANKINGS:
                for max_stops, circular in ((1, False), (2, False), (3, False), (3, True)):
                    planner = RoutePlanner(by_pair_list(pairs), cargo_scu=cargo, budget=budget, ranking=ranking)
                    plans = planner.plan(max_stops=max_stops, return_to_start=circular, limit=0)
                    self._check_routes(plans, pairs, cargo, budget, ranking, max_stops, circular)
                    best = best_route(pairs, cargo, budget, True, ranking, max_stops, return_to_start=circular)
                    got = plans[0].score(ranking) if plans else 0.0
                    self.assertLessEqual(got, (best[0] if best else 0.0) + EPSILON)
                    stats.setdefault(f"{ranking}, circular={circular}", []).append(ratio(got, best[0] if best else 0.0))

        # Quality floors (heuristic). Measured mean 0.98-0.999, best route found in 79-98 % of markets.
        for kind, values in sorted(stats.items()):
            optimal_share = sum(1 for v in values if v >= 1 - EPSILON) / len(values)
            print(f"  route search {kind:42} n={len(values):4} mean={statistics.mean(values):.4f} optimal={optimal_share:.1%} worst={min(values):.3f}")
            self.assertGreaterEqual(statistics.mean(values), 0.97, kind)
            self.assertGreaterEqual(optimal_share, 0.75, kind)

    def test_shown_routes_have_optimal_cargo_plans(self) -> None:
        # Shown routes get exact cargo plans (scipy MILP inside the planner) with a budget and on
        # multi-stop routes; a single hop without budget is provably optimal greedy. So every
        # shown route must match the independent reference exactly.
        rng = random.Random(24)
        checked = 0
        for _ in range(60):
            legs = random_legs(rng, terminals=rng.randint(4, 6), commodities=rng.randint(2, 5))
            pairs = by_pair(legs)
            if not pairs:
                continue
            cargo = rng.choice([4, 10, 46, 120])
            budget = rng.choice([None, 150, 500, 1000, 5000])
            for ranking in RANKINGS:
                for max_stops, circular in ((1, False), (3, False), (3, True)):
                    planner = RoutePlanner(by_pair_list(pairs), cargo_scu=cargo, budget=budget, ranking=ranking)
                    plans = planner.plan(max_stops=max_stops, return_to_start=circular, limit=5)
                    self._check_routes(plans, pairs, cargo, budget, ranking, max_stops, circular)
                    for plan in plans:
                        exact = exact_cargo_profit(plan.stops, pairs, cargo, budget)
                        self.assertAlmostEqual(plan.profit, exact, places=4, msg=f"{plan.stops} cargo={cargo} budget={budget}")
                        checked += 1
        print(f"  {checked} shown routes with exactly optimal cargo plans")

    def test_filters_hold_on_random_markets(self) -> None:
        rng = random.Random(22)
        for _ in range(60):
            legs = random_legs(rng, terminals=6, commodities=4)
            pairs = by_pair(legs)
            terminals = sorted({t for pair in pairs for t in pair})
            if len(terminals) < 3:
                continue
            start = {rng.choice(terminals)}
            end = {rng.choice(terminals)}
            for circular in (False, True):
                planner = RoutePlanner(by_pair_list(pairs), cargo_scu=20)
                plans = planner.plan(max_stops=3, return_to_start=circular, start_terminals=start, end_terminals=end, limit=0)
                self._check_routes(plans, pairs, 20, None, planner.ranking, 3, circular, start, end)
                # Nothing valid was left out: the planner finds a route whenever one exists
                exists = best_route(pairs, 20, None, True, planner.ranking, 3, return_to_start=circular,
                                    start_terminals=start, end_terminals=end)
                self.assertEqual(bool(plans), exists is not None, f"start={start} end={end} circular={circular}")

    def test_single_hop_search_returns_every_pair_in_ranked_order(self) -> None:
        rng = random.Random(23)
        for _ in range(40):
            legs = random_legs(rng, terminals=5, commodities=4)
            pairs = by_pair(legs)
            for ranking in (RANKING_TOTAL_PROFIT, RANKING_PROFIT_PER_DISTANCE):
                plans = RoutePlanner(by_pair_list(pairs), cargo_scu=30, ranking=ranking).plan(limit=0)
                self._check_routes(plans, pairs, 30, None, ranking, 1)
                # Without budget each hop's plan is optimal, so the ranking must be the exact one
                expected = sorted(
                    (score(exact_cargo_profit(list(pair), pairs, 30), list(pair), [pairs[pair][0].distance], ranking), pair)
                    for pair in pairs if exact_cargo_profit(list(pair), pairs, 30) > 0
                )
                self.assertEqual(
                    [round(s, 6) for s, _ in sorted(expected, reverse=True)],
                    [round(p.score(ranking), 6) for p in plans],
                )


def by_pair_list(pairs) -> list:
    return [leg for legs in pairs.values() for leg in legs]


def main() -> None:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(case) for case in (OracleSelfTest, CargoPlanTest, RouteSearchTest)
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
