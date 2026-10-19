"""Tests for the trade route planner (multi-commodity, multi-stop, circular, carry-over).

No pytest. Run from the project root:

    python3 -m skills.uexcorp.tests.test_route_planner

Exits non-zero on the first failed assertion or crash; prints "ALL OK" on success.

The planner is pure Python (no database, no Helper), so the legs are built by hand.
Terminals are plain ints: A=1, B=2, C=3, D=4.
"""

from __future__ import annotations

import unittest

from skills.uexcorp.uexcorp.route_planner import (
    RANKING_PROFIT_PER_DISTANCE,
    RANKING_PROFIT_PER_STOP,
    RANKING_TOTAL_PROFIT,
    Leg,
    RoutePlan,
    RoutePlanner,
)

A, B, C, D = 1, 2, 3, 4


def leg(commodity: int, origin: int, destination: int, buy: float, sell: float,
        stock: float | None = None, demand: float | None = None, distance: float | None = 10, jumps: int = 0) -> Leg:
    return Leg(
        id_commodity=commodity, commodity_name=f"C{commodity}", origin=origin, destination=destination,
        price_buy=buy, price_sell=sell, stock=stock, demand=demand, distance=distance, jumps=jumps,
    )


def segment_loads(plan: RoutePlan) -> list[int]:
    loads = [0] * plan.stop_count
    for trade in plan.trades:
        for k in range(trade.buy_stop, trade.sell_stop):
            loads[k] += trade.scu
    return loads


def cash_timeline(plan: RoutePlan, budget: float) -> list[float]:
    cash, timeline = budget, []
    for stop in range(len(plan.stops)):
        cash += sum(t.scu * t.leg.price_sell for t in plan.trades if t.sell_stop == stop)
        cash -= sum(t.cost for t in plan.trades if t.buy_stop == stop)
        timeline.append(cash)
    return timeline


class LegFillTest(unittest.TestCase):
    def test_fills_best_margin_first_then_next_commodity(self) -> None:
        legs = [leg(1, A, B, 10, 20, stock=5), leg(2, A, B, 10, 15, stock=100)]
        plan = RoutePlanner(legs, cargo_scu=20).plan()[0]
        self.assertEqual({t.leg.id_commodity: t.scu for t in plan.trades}, {1: 5, 2: 15})
        self.assertEqual(plan.profit, 5 * 10 + 15 * 5)

    def test_known_demand_caps_and_unknown_does_not(self) -> None:
        planner = RoutePlanner([leg(1, A, B, 10, 20, stock=100, demand=7)], cargo_scu=50)
        self.assertEqual(planner.plan()[0].trades[0].scu, 7)
        planner = RoutePlanner([leg(1, A, B, 10, 20, stock=100, demand=None)], cargo_scu=50)
        self.assertEqual(planner.plan()[0].trades[0].scu, 50)

    def test_availability_off_ignores_stock_and_demand(self) -> None:
        planner = RoutePlanner([leg(1, A, B, 10, 20, stock=3, demand=2)], cargo_scu=50, use_availability=False)
        self.assertEqual(planner.plan()[0].trades[0].scu, 50)

    def test_availability_limit_names_the_capping_location(self) -> None:
        trade = RoutePlanner([leg(1, A, B, 10, 20, stock=5, demand=500)], cargo_scu=46).plan()[0].trades[0]
        self.assertEqual(trade.availability_limit, (46, "buy location"))
        trade = RoutePlanner([leg(1, A, B, 10, 20, stock=500, demand=5)], cargo_scu=46).plan()[0].trades[0]
        self.assertEqual(trade.availability_limit, (46, "sell location"))
        trade = RoutePlanner([leg(1, A, B, 10, 20, stock=7, demand=7)], cargo_scu=46).plan()[0].trades[0]
        self.assertEqual(trade.availability_limit, (46, "sell and buy location"))
        trade = RoutePlanner([leg(1, A, B, 10, 20, stock=500)], cargo_scu=46).plan()[0].trades[0]
        self.assertIsNone(trade.availability_limit)

    def test_budget_limits_volume(self) -> None:
        plan = RoutePlanner([leg(1, A, B, 100, 150, stock=1000)], cargo_scu=500, budget=1000).plan()[0]
        self.assertEqual(plan.trades[0].scu, 10)
        self.assertEqual(plan.max_cash_needed, 1000)

    def test_a_purchase_that_earns_next_to_nothing_is_left_out(self) -> None:
        legs = [leg(1, A, B, 100, 200, stock=100), leg(2, A, B, 10, 11, stock=1000)]
        plan = RoutePlanner(legs, cargo_scu=101).plan()[0]
        self.assertEqual([t.leg.id_commodity for t in plan.trades], [1])  # not 1 SCU of C2 for 1 aUEC

    def test_illegal_cargo_must_earn_more_to_stay(self) -> None:
        def legs(illegal: bool) -> list[Leg]:
            # C2 earns 3 % of the route: fine for legal cargo, not worth the risk for illegal cargo
            return [leg(1, A, B, 100, 200, stock=100),
                    Leg(id_commodity=2, commodity_name="C2", origin=A, destination=B, price_buy=10, price_sell=40,
                        stock=10, distance=10, is_illegal=illegal)]
        kept = {t.leg.id_commodity for t in RoutePlanner(legs(False), cargo_scu=110).plan()[0].trades}
        dropped = {t.leg.id_commodity for t in RoutePlanner(legs(True), cargo_scu=110).plan()[0].trades}
        self.assertEqual((kept, dropped), ({1, 2}, {1}))

    def test_small_illegal_cargo_stays_when_the_route_is_illegal_anyway(self) -> None:
        def illegal(commodity: int, buy: float, sell: float, stock: float) -> Leg:
            return Leg(id_commodity=commodity, commodity_name=f"C{commodity}", origin=A, destination=B, price_buy=buy,
                       price_sell=sell, stock=stock, distance=10, is_illegal=True)
        # C2 earns 3 % like in the test above, but C3 (illegal too) stays aboard: dropping C2 gains no legality
        legs = [leg(1, A, B, 100, 200, stock=100), illegal(2, 10, 40, 10), illegal(3, 100, 200, 50)]
        plan = RoutePlanner(legs, cargo_scu=160).plan()[0]
        self.assertEqual({t.leg.id_commodity for t in plan.trades}, {1, 2, 3})

    def test_a_small_trade_that_keeps_a_stop_busy_stays(self) -> None:
        legs = [leg(1, A, B, 100, 200, stock=100), leg(2, B, C, 10, 11, stock=1)]
        plan = RoutePlanner(legs, cargo_scu=100).plan(max_stops=2, end_terminals={C})[0]
        self.assertEqual(plan.stops, [A, B, C])
        self.assertEqual({t.leg.id_commodity for t in plan.trades}, {1, 2})

    def test_money_limit_names_the_room_and_the_money_on_hand(self) -> None:
        # The hold takes 500, the money buys 10: the user should hear it was the money
        trade = RoutePlanner([leg(1, A, B, 100, 150, stock=1000)], cargo_scu=500, budget=1000).plan()[0].trades[0]
        self.assertEqual(trade.money_limit, (500, 1000, None))

    def test_money_kept_for_a_later_purchase_is_not_counted_as_left_for_this_one(self) -> None:
        # C2 at B earns more per aUEC but only 3 SCU are in stock: of the 1000, 300 are kept for it,
        # so C1 at A (carried past B) gets 700, not the 1000 on hand at A
        legs = [leg(1, A, C, 100, 300, stock=1000), leg(2, B, C, 100, 500, stock=3)]
        planner = RoutePlanner(legs, cargo_scu=100, budget=1000)
        plan = next(p for p in planner.plan(max_stops=2, start_terminals={A}, end_terminals={C}, limit=0) if p.stops == [A, B, C])
        c1 = next(t for t in plan.trades if t.leg.id_commodity == 1)
        self.assertEqual(c1.scu, 7)
        self.assertEqual(c1.money_limit[1:], (700, B))

    def test_no_money_limit_when_the_hold_or_the_stock_is_the_limit(self) -> None:
        full = RoutePlanner([leg(1, A, B, 100, 150, stock=1000)], cargo_scu=5, budget=1000).plan()[0].trades[0]
        stock = RoutePlanner([leg(1, A, B, 100, 150, stock=3)], cargo_scu=500, budget=1000).plan()[0].trades[0]
        no_budget = RoutePlanner([leg(1, A, B, 100, 150, stock=1000)], cargo_scu=500).plan()[0].trades[0]
        self.assertEqual([full.money_limit, stock.money_limit, no_budget.money_limit], [None, None, None])


class MultiStopTest(unittest.TestCase):
    def test_cash_grows_with_profit_from_earlier_stops(self) -> None:
        legs = [leg(1, A, B, 100, 200, stock=1000), leg(2, B, C, 100, 200, stock=1000)]
        plan = RoutePlanner(legs, cargo_scu=1000, budget=1000).plan(max_stops=2, end_terminals={C})[0]
        self.assertEqual(plan.stops, [A, B, C])
        scu = {t.leg.id_commodity: t.scu for t in plan.trades}
        self.assertEqual(scu[1], 10)  # 1000 budget
        self.assertEqual(scu[2], 20)  # 1000 + 1000 profit
        self.assertTrue(all(cash >= 0 for cash in cash_timeline(plan, 1000)))
        # Money on hand at B counts the sale there: 2000
        self.assertEqual({t.leg.id_commodity: t.money_limit for t in plan.trades}, {1: (1000, 1000, None), 2: (1000, 2000, None)})

    def test_no_terminal_visited_twice(self) -> None:
        legs = [leg(1, A, B, 10, 20), leg(1, B, A, 10, 20), leg(2, B, C, 10, 20), leg(2, C, A, 10, 20)]
        for plan in RoutePlanner(legs, cargo_scu=10).plan(max_stops=3, limit=0):
            self.assertEqual(len(plan.stops), len(set(plan.stops)), plan.stops)

    def test_circular_routes_end_at_start(self) -> None:
        legs = [leg(1, A, B, 10, 20), leg(2, B, C, 10, 20), leg(3, C, A, 10, 20), leg(4, B, A, 10, 12)]
        plans = RoutePlanner(legs, cargo_scu=10).plan(max_stops=3, return_to_start=True, limit=0)
        self.assertTrue(plans)
        for plan in plans:
            self.assertEqual(plan.stops[0], plan.stops[-1])
            self.assertTrue(plan.is_circular())
        self.assertIn([A, B, C, A], [plan.stops for plan in plans])
        self.assertIn([A, B, A], [plan.stops for plan in plans])

    def test_circular_routes_with_destination_pass_through_it(self) -> None:
        legs = [leg(1, A, B, 10, 50), leg(2, B, A, 10, 50), leg(3, A, C, 10, 20), leg(4, C, A, 10, 20)]
        plans = RoutePlanner(legs, cargo_scu=10).plan(max_stops=3, return_to_start=True, end_terminals={C}, limit=0)
        self.assertTrue(plans)
        for plan in plans:
            self.assertIn(C, plan.stops[1:-1], plan.stops)  # A -> B -> A pays more but skips C

    def test_return_to_start_needs_at_least_two_stops(self) -> None:
        legs = [leg(1, A, B, 10, 20), leg(2, B, A, 10, 20)]
        plans = RoutePlanner(legs, cargo_scu=10).plan(max_stops=1, return_to_start=True)
        self.assertEqual(plans[0].stop_count, 2)

    def test_start_and_end_terminals(self) -> None:
        legs = [leg(1, A, B, 10, 20), leg(2, B, C, 10, 50), leg(3, C, D, 10, 20), leg(4, D, B, 10, 90)]
        plans = RoutePlanner(legs, cargo_scu=10).plan(max_stops=3, start_terminals={A}, end_terminals={C}, limit=0)
        self.assertTrue(plans)
        for plan in plans:
            self.assertEqual(plan.stops[0], A)
            self.assertEqual(plan.stops[-1], C)


class CarryOverTest(unittest.TestCase):
    def test_carrying_cargo_past_a_stop_beats_selling_at_every_stop(self) -> None:
        legs = [
            leg(1, A, C, 10, 110, stock=1000),  # 100/SCU, but only sold at C
            leg(2, A, B, 10, 11, stock=1000),  # 1/SCU
            leg(3, B, C, 10, 11, stock=1000),  # 1/SCU
        ]
        planner = RoutePlanner(legs, cargo_scu=10)
        plan = planner.plan_cargo([A, B, C])
        self.assertEqual(plan.profit, 10 * 100)
        trade = next(t for t in plan.trades if t.leg.id_commodity == 1)
        self.assertEqual((trade.buy_stop, trade.sell_stop, trade.scu), (0, 2, 10))

    def test_short_trades_win_when_they_reuse_the_space(self) -> None:
        legs = [
            leg(1, A, D, 10, 40, stock=1000),  # 30/SCU over 3 segments
            leg(2, A, B, 10, 30, stock=1000),  # 20/SCU per segment
            leg(3, B, C, 10, 30, stock=1000),
            leg(4, C, D, 10, 30, stock=1000),
        ]
        plan = RoutePlanner(legs, cargo_scu=10).plan_cargo([A, B, C, D])
        self.assertEqual(plan.profit, 3 * 10 * 20)

    def test_segment_capacity_and_cash_are_never_exceeded(self) -> None:
        legs = [
            leg(1, A, C, 10, 60, stock=8), leg(2, A, B, 10, 30, stock=20), leg(3, B, D, 5, 45, stock=15),
            leg(4, B, C, 20, 50, stock=9), leg(5, C, D, 10, 25, stock=30), leg(6, A, D, 10, 70, stock=4),
        ]
        budget = 400
        plan = RoutePlanner(legs, cargo_scu=25, budget=budget).plan_cargo([A, B, C, D])
        self.assertTrue(plan.trades)
        self.assertTrue(all(load <= 25 for load in segment_loads(plan)), segment_loads(plan))
        self.assertTrue(all(cash >= 0 for cash in cash_timeline(plan, budget)), cash_timeline(plan, budget))
        bought = {}
        for trade in plan.trades:
            bought[(trade.leg.id_commodity, trade.buy_stop)] = bought.get((trade.leg.id_commodity, trade.buy_stop), 0) + trade.scu
            self.assertLessEqual(bought[(trade.leg.id_commodity, trade.buy_stop)], trade.leg.stock)


class ExactCargoTest(unittest.TestCase):
    """With a budget the best routes get an exact cargo plan (scipy MILP), with fallback."""

    # Found by searching random markets for a small case every greedy ordering gets wrong:
    # cargo 20, budget 1000. At B the best mix of the cheap and the expensive commodity is a
    # two-constraint knapsack (cargo and cash), which greedy filling misses.
    LEGS = [
        leg(1, A, B, 44.79, 45.68),
        leg(2, B, C, 25.55, 42.14),
        leg(3, B, C, 115.72, 157.45),
    ]
    GREEDY_PROFIT = 401.41
    EXACT_PROFIT = 475.30

    def _plan(self, **kwargs) -> RoutePlan:
        planner = RoutePlanner(self.LEGS, cargo_scu=20, budget=1000, ranking=RANKING_TOTAL_PROFIT, **kwargs)
        return next(p for p in planner.plan(max_stops=2, limit=0) if p.stops == [A, B, C])

    def test_exact_plan_beats_every_greedy_ordering(self) -> None:
        self.assertAlmostEqual(self._plan(exact_candidates=0).profit, self.GREEDY_PROFIT, places=2)
        plan = self._plan()
        self.assertAlmostEqual(plan.profit, self.EXACT_PROFIT, places=2)
        self.assertTrue(all(isinstance(t.scu, int) and t.scu > 0 for t in plan.trades))

    def test_falls_back_to_greedy_without_scipy(self) -> None:
        import sys

        saved = {name: sys.modules.get(name) for name in ("scipy", "scipy.optimize")}
        sys.modules["scipy"] = None  # makes "import scipy..." raise ImportError
        sys.modules["scipy.optimize"] = None
        try:
            self.assertAlmostEqual(self._plan().profit, self.GREEDY_PROFIT, places=2)
        finally:
            for name, module in saved.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

    def test_falls_back_to_greedy_when_the_solver_fails(self) -> None:
        import scipy.optimize

        original = scipy.optimize.milp

        def broken(*args, **kwargs):
            raise RuntimeError("solver crashed")

        scipy.optimize.milp = broken
        try:
            self.assertAlmostEqual(self._plan().profit, self.GREEDY_PROFIT, places=2)
        finally:
            scipy.optimize.milp = original

    @staticmethod
    def _spy(planner: RoutePlanner) -> list:
        calls = []
        original = planner.exact_plan_cargo

        def spy(stops, time_limit=None):
            calls.append(list(stops))
            return original(stops, time_limit)

        planner.exact_plan_cargo = spy
        return calls

    def test_exact_step_scope(self) -> None:
        # Without budget a single hop's greedy plan is provably optimal: only multi-stop routes
        planner = RoutePlanner(self.LEGS, cargo_scu=100, ranking=RANKING_TOTAL_PROFIT)
        calls = self._spy(planner)
        planner.plan(max_stops=2, limit=0)
        self.assertTrue(calls)
        self.assertTrue(all(len(stops) > 2 for stops in calls), calls)
        # With a budget every candidate (up to exact_candidates) is planned exactly
        planner = RoutePlanner(self.LEGS, cargo_scu=20, budget=1000, ranking=RANKING_TOTAL_PROFIT, exact_candidates=2)
        calls = self._spy(planner)
        planner.plan(max_stops=2, limit=0)
        self.assertEqual(len(calls), 2)

    def test_exact_step_stops_at_the_total_time_budget(self) -> None:
        planner = RoutePlanner(self.LEGS, cargo_scu=20, budget=1000, ranking=RANKING_TOTAL_PROFIT)
        planner.EXACT_TOTAL_TIME = 0  # no time left: everything keeps its greedy plan
        calls = self._spy(planner)
        plan = next(p for p in planner.plan(max_stops=2, limit=0) if p.stops == [A, B, C])
        self.assertEqual(calls, [])
        self.assertAlmostEqual(plan.profit, self.GREEDY_PROFIT, places=2)

    def test_exact_plan_keeps_the_availability_note(self) -> None:
        # Stock of 5 caps the trade; cargo 46 and the budget would allow 46
        planner = RoutePlanner([leg(1, A, B, 10, 20, stock=5)], cargo_scu=46, budget=100_000)
        trade = planner.plan()[0].trades[0]
        self.assertEqual((trade.scu, trade.availability_limit), (5, (46, "buy location")))
        # Budget for only 3 SCU: availability is not the limit, so no note
        trade = RoutePlanner([leg(1, A, B, 10, 20, stock=5)], cargo_scu=46, budget=30).plan()[0].trades[0]
        self.assertEqual((trade.scu, trade.availability_limit), (3, None))


class RankingTest(unittest.TestCase):
    LEGS = [
        leg(1, A, B, 10, 20, distance=100),  # 1 stop: 100 profit, far
        leg(2, C, D, 10, 18, distance=1),  # 1 stop: 80 profit, close
    ]

    def test_total_profit_and_per_stop_prefer_the_bigger_profit(self) -> None:
        for ranking in (RANKING_TOTAL_PROFIT, RANKING_PROFIT_PER_STOP):
            first = RoutePlanner(self.LEGS, cargo_scu=10, ranking=ranking).plan()[0]
            self.assertEqual(first.stops, [A, B], ranking)

    def test_profit_per_distance_prefers_the_short_route(self) -> None:
        first = RoutePlanner(self.LEGS, cargo_scu=10, ranking=RANKING_PROFIT_PER_DISTANCE).plan()[0]
        self.assertEqual(first.stops, [C, D])

    def test_per_stop_can_prefer_fewer_stops_total_profit_more(self) -> None:
        legs = [leg(1, A, B, 10, 20), leg(2, B, C, 10, 15)]  # A->B 100, A->B->C 150
        per_stop = RoutePlanner(legs, cargo_scu=10, ranking=RANKING_PROFIT_PER_STOP).plan(max_stops=2)[0]
        total = RoutePlanner(legs, cargo_scu=10, ranking=RANKING_TOTAL_PROFIT).plan(max_stops=2)[0]
        self.assertEqual(per_stop.stops, [A, B])
        self.assertEqual(total.stops, [A, B, C])

    def test_stop_without_trades_is_dropped(self) -> None:
        # A -> B -> C makes its 300 by carrying C1 from A to C: nothing happens at B, so it is no route
        legs = [leg(1, A, C, 10, 40), leg(2, A, B, 10, 11), leg(3, B, C, 10, 11)]
        plans = RoutePlanner(legs, cargo_scu=10, ranking=RANKING_TOTAL_PROFIT).plan(max_stops=2, limit=0)
        self.assertEqual(plans[0].stops, [A, C])
        self.assertTrue(all(not plan.has_idle_stop() for plan in plans))

    def test_unknown_distance_never_looks_most_efficient(self) -> None:
        # Unknown distance used to count as 0 Gm and won profit per distance by far
        legs = [leg(1, A, B, 10, 20, distance=None), leg(2, C, D, 10, 19, distance=30)]
        first = RoutePlanner(legs, cargo_scu=10, ranking=RANKING_PROFIT_PER_DISTANCE).plan()[0]
        self.assertEqual(first.stops, [C, D])

    def test_unknown_distance_is_reported_as_unknown(self) -> None:
        plan = RoutePlanner([leg(1, A, B, 10, 20, distance=None)], cargo_scu=10).plan()[0]
        self.assertIsNone(plan.distance)


    def test_the_same_sale_at_other_terminals_is_one_route_with_alternatives(self) -> None:
        # 10 SCU bought at A sell at B, C or D for the same price; only B also takes a second cargo
        legs = [leg(1, A, B, 10, 20, stock=10, distance=30), leg(1, A, C, 10, 20, stock=10, distance=20),
                leg(1, A, D, 10, 20, stock=10, distance=10), leg(2, A, B, 10, 15, distance=30)]
        plans = RoutePlanner(legs, cargo_scu=20, ranking=RANKING_PROFIT_PER_DISTANCE).plan(limit=5)
        self.assertEqual([plan.stops for plan in plans], [[A, D], [A, B]])
        self.assertEqual(plans[0].alternative_ends, [C])  # the nearest one leads, C is the same sale
        self.assertEqual(plans[1].alternative_ends, [])  # more cargo, another route


class SystemJumpTest(unittest.TestCase):
    # A -> B -> C crosses two systems, the direct A -> C hop only one
    LEGS = [
        leg(1, A, B, 10, 30, jumps=1),
        leg(2, B, C, 10, 30, jumps=1),
        leg(3, A, C, 10, 12, jumps=1),
        leg(4, A, D, 10, 11),
    ]

    def test_jumps_are_counted_per_hop(self) -> None:
        plan = RoutePlanner(self.LEGS, cargo_scu=10).plan(max_stops=2, start_terminals={A}, end_terminals={C})[0]
        self.assertEqual(plan.stops, [A, B, C])
        self.assertEqual(plan.jump_count, 2)

    def test_max_jumps_drops_routes_with_more_jumps(self) -> None:
        planner = RoutePlanner(self.LEGS, cargo_scu=10)
        plans = planner.plan(max_stops=2, start_terminals={A}, end_terminals={C}, max_jumps=1, limit=0)
        self.assertEqual([plan.stops for plan in plans], [[A, C]])
        self.assertEqual([plan.stops for plan in planner.plan(start_terminals={A}, max_jumps=0)], [[A, D]])

    def test_exact_cargo_plan_keeps_the_jumps(self) -> None:
        planner = RoutePlanner(self.LEGS, cargo_scu=10)
        self.assertEqual(planner.exact_plan_cargo([A, B, C]).jumps, [1, 1])


class CollectStopTest(unittest.TestCase):
    # Not enough stock at A or B alone, both sell to C; nothing to sell between A and B (no leg)
    LEGS = [leg(1, A, C, 10, 50, stock=5), leg(1, B, C, 10, 50, stock=5), leg(2, A, D, 10, 11)]

    def test_a_stop_that_only_buys_fills_the_hold(self) -> None:
        plan = RoutePlanner(self.LEGS, cargo_scu=10).plan(max_stops=2, start_terminals={A}, end_terminals={C})[0]
        self.assertEqual(plan.stops, [A, B, C])
        self.assertEqual(sorted((t.buy_stop, t.sell_stop, t.scu) for t in plan.trades), [(0, 2, 5), (1, 2, 5)])
        self.assertEqual(plan.profit, 400)

    def test_without_room_for_another_stop_it_stays_direct(self) -> None:
        plan = RoutePlanner(self.LEGS, cargo_scu=10).plan(max_stops=1, start_terminals={A}, end_terminals={C})[0]
        self.assertEqual(plan.stops, [A, C])

    def test_hop_without_leg_takes_distance_and_jumps_from_hop_info(self) -> None:
        planner = RoutePlanner(self.LEGS, cargo_scu=10, hop_info=lambda origin, destination: (7.0, 1))
        plan = planner.plan(max_stops=2, start_terminals={A}, end_terminals={C})[0]
        self.assertEqual((plan.distances, plan.jumps), ([7.0, 10], [1, 0]))
        # The jump to B is too many: the direct route stays
        planner = RoutePlanner(self.LEGS, cargo_scu=10, hop_info=lambda origin, destination: (7.0, 1))
        plan = planner.plan(max_stops=2, start_terminals={A}, end_terminals={C}, max_jumps=0)[0]
        self.assertEqual(plan.stops, [A, C])


def main() -> None:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(case)
        for case in (LegFillTest, MultiStopTest, CarryOverTest, ExactCargoTest, RankingTest, SystemJumpTest, CollectStopTest)
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
