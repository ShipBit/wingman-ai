"""The trade route planner (multi-commodity, multi-stop, circular, carry-over) on hand-built legs.

The planner is pure Python (no database, no Helper). Terminals are plain ints: A=1, B=2, C=3, D=4.
The hard rules on random markets are checked in test_route_planner_correctness."""

from __future__ import annotations

import sys

import pytest

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
        stock: float | None = None, demand: float | None = None, distance: float | None = 10, jumps: int = 0,
        is_illegal: bool = False) -> Leg:
    return Leg(
        id_commodity=commodity, commodity_name=f"C{commodity}", origin=origin, destination=destination,
        price_buy=buy, price_sell=sell, stock=stock, demand=demand, distance=distance, jumps=jumps,
        is_illegal=is_illegal,
    )


def cash_timeline(plan: RoutePlan, budget: float) -> list[float]:
    cash, timeline = budget, []
    for stop in range(len(plan.stops)):
        cash += sum(t.scu * t.leg.price_sell for t in plan.trades if t.sell_stop == stop)
        cash -= sum(t.cost for t in plan.trades if t.buy_stop == stop)
        timeline.append(cash)
    return timeline


def first_trades(legs: list[Leg], **settings) -> list:
    return RoutePlanner(legs, **settings).plan()[0].trades


# ── Filling the hold ────────────────────────────────────────────────


def test_the_best_margin_is_filled_first_then_the_next_commodity():
    legs = [leg(1, A, B, 10, 20, stock=5), leg(2, A, B, 10, 15, stock=100)]

    plan = RoutePlanner(legs, cargo_scu=20).plan()[0]

    assert {t.leg.id_commodity: t.scu for t in plan.trades} == {1: 5, 2: 15}
    assert plan.profit == 5 * 10 + 15 * 5


def test_a_known_demand_caps_the_volume_an_unknown_one_and_the_switch_off_do_not():
    assert first_trades([leg(1, A, B, 10, 20, stock=100, demand=7)], cargo_scu=50)[0].scu == 7
    assert first_trades([leg(1, A, B, 10, 20, stock=100, demand=None)], cargo_scu=50)[0].scu == 50
    assert first_trades([leg(1, A, B, 10, 20, stock=3, demand=2)], cargo_scu=50, use_availability=False)[0].scu == 50


def test_the_budget_limits_the_volume_and_names_the_limit():
    plan = RoutePlanner([leg(1, A, B, 100, 150, stock=1000)], cargo_scu=500, budget=1000).plan()[0]
    assert plan.trades[0].scu == 10
    assert plan.max_cash_needed == 1000
    # The hold takes 500, the money buys 10: the user should hear it was the money
    assert plan.trades[0].money_limit == (500, 1000, None)

    # When the hold, the stock or no budget is the limit, the money is not blamed
    limits = [
        first_trades([leg(1, A, B, 100, 150, stock=1000)], cargo_scu=5, budget=1000)[0].money_limit,
        first_trades([leg(1, A, B, 100, 150, stock=3)], cargo_scu=500, budget=1000)[0].money_limit,
        first_trades([leg(1, A, B, 100, 150, stock=1000)], cargo_scu=500)[0].money_limit,
    ]
    assert limits == [None, None, None]


def test_money_kept_for_a_later_purchase_is_not_counted_as_left_for_this_one():
    # C2 at B earns more per aUEC but only 3 SCU are in stock: of the 1000, 300 are kept for it,
    # so C1 at A (carried past B) gets 700, not the 1000 on hand at A
    legs = [leg(1, A, C, 100, 300, stock=1000), leg(2, B, C, 100, 500, stock=3)]
    planner = RoutePlanner(legs, cargo_scu=100, budget=1000)

    plan = next(p for p in planner.plan(max_stops=2, start_terminals={A}, end_terminals={C}, limit=0) if p.stops == [A, B, C])

    c1 = next(t for t in plan.trades if t.leg.id_commodity == 1)
    assert c1.scu == 7
    assert c1.money_limit[1:] == (700, B)


def test_a_purchase_that_earns_next_to_nothing_is_left_out():
    legs = [leg(1, A, B, 100, 200, stock=100), leg(2, A, B, 10, 11, stock=1000)]

    plan = RoutePlanner(legs, cargo_scu=101).plan()[0]

    assert [t.leg.id_commodity for t in plan.trades] == [1]  # not 1 SCU of C2 for 1 aUEC


def test_illegal_cargo_must_earn_more_to_stay():
    def legs(illegal: bool) -> list[Leg]:
        # C2 earns 3 % of the route: fine for legal cargo, not worth the risk for illegal cargo
        return [leg(1, A, B, 100, 200, stock=100), leg(2, A, B, 10, 40, stock=10, is_illegal=illegal)]

    kept = {t.leg.id_commodity for t in first_trades(legs(False), cargo_scu=110)}
    dropped = {t.leg.id_commodity for t in first_trades(legs(True), cargo_scu=110)}

    assert (kept, dropped) == ({1, 2}, {1})


def test_small_illegal_cargo_stays_when_the_route_is_illegal_anyway():
    # C2 earns 3 % like above, but C3 (illegal too) stays aboard: dropping C2 gains no legality
    legs = [leg(1, A, B, 100, 200, stock=100), leg(2, A, B, 10, 40, stock=10, is_illegal=True),
            leg(3, A, B, 100, 200, stock=50, is_illegal=True)]

    assert {t.leg.id_commodity for t in first_trades(legs, cargo_scu=160)} == {1, 2, 3}


def test_a_small_trade_that_keeps_a_stop_busy_stays():
    legs = [leg(1, A, B, 100, 200, stock=100), leg(2, B, C, 10, 11, stock=1)]

    plan = RoutePlanner(legs, cargo_scu=100).plan(max_stops=2, end_terminals={C})[0]

    assert plan.stops == [A, B, C]
    assert {t.leg.id_commodity for t in plan.trades} == {1, 2}


# ── Several stops ───────────────────────────────────────────────────


def test_cash_grows_with_the_profit_from_earlier_stops():
    legs = [leg(1, A, B, 100, 200, stock=1000), leg(2, B, C, 100, 200, stock=1000)]

    plan = RoutePlanner(legs, cargo_scu=1000, budget=1000).plan(max_stops=2, end_terminals={C})[0]

    assert plan.stops == [A, B, C]
    assert {t.leg.id_commodity: t.scu for t in plan.trades} == {1: 10, 2: 20}  # 1000 budget, then 1000 + 1000 profit
    assert all(cash >= 0 for cash in cash_timeline(plan, 1000))
    # Money on hand at B counts the sale there: 2000
    assert {t.leg.id_commodity: t.money_limit for t in plan.trades} == {1: (1000, 1000, None), 2: (1000, 2000, None)}


def test_circular_routes_end_at_their_start():
    legs = [leg(1, A, B, 10, 20), leg(2, B, C, 10, 20), leg(3, C, A, 10, 20), leg(4, B, A, 10, 12)]

    plans = RoutePlanner(legs, cargo_scu=10).plan(max_stops=3, return_to_start=True, limit=0)

    assert plans
    for plan in plans:
        assert plan.stops[0] == plan.stops[-1]
        assert plan.is_circular()
    assert [A, B, C, A] in [plan.stops for plan in plans]
    assert [A, B, A] in [plan.stops for plan in plans]


def test_a_circular_route_with_a_destination_passes_through_it():
    legs = [leg(1, A, B, 10, 50), leg(2, B, A, 10, 50), leg(3, A, C, 10, 20), leg(4, C, A, 10, 20)]

    plans = RoutePlanner(legs, cargo_scu=10).plan(max_stops=3, return_to_start=True, end_terminals={C}, limit=0)

    assert plans
    for plan in plans:
        assert C in plan.stops[1:-1], plan.stops  # A -> B -> A pays more but skips C


def test_a_round_trip_needs_at_least_two_stops():
    legs = [leg(1, A, B, 10, 20), leg(2, B, A, 10, 20)]

    plans = RoutePlanner(legs, cargo_scu=10).plan(max_stops=1, return_to_start=True)

    assert plans[0].stop_count == 2


# ── Carrying cargo past stops ───────────────────────────────────────


def test_carrying_cargo_past_a_stop_beats_selling_at_every_stop():
    legs = [
        leg(1, A, C, 10, 110, stock=1000),  # 100/SCU, but only sold at C
        leg(2, A, B, 10, 11, stock=1000),  # 1/SCU
        leg(3, B, C, 10, 11, stock=1000),  # 1/SCU
    ]

    plan = RoutePlanner(legs, cargo_scu=10).plan_cargo([A, B, C])

    assert plan.profit == 10 * 100
    trade = next(t for t in plan.trades if t.leg.id_commodity == 1)
    assert (trade.buy_stop, trade.sell_stop, trade.scu) == (0, 2, 10)


def test_short_trades_win_when_they_reuse_the_space():
    legs = [
        leg(1, A, D, 10, 40, stock=1000),  # 30/SCU over 3 segments
        leg(2, A, B, 10, 30, stock=1000),  # 20/SCU per segment
        leg(3, B, C, 10, 30, stock=1000),
        leg(4, C, D, 10, 30, stock=1000),
    ]

    plan = RoutePlanner(legs, cargo_scu=10).plan_cargo([A, B, C, D])

    assert plan.profit == 3 * 10 * 20


# ── The exact cargo plan ────────────────────────────────────────────

# Found by searching random markets for a small case every greedy ordering gets wrong: cargo 20,
# budget 1000. At B the best mix of the cheap and the expensive commodity is a two-constraint
# knapsack (cargo and cash), which greedy filling misses.
KNAPSACK_LEGS = [leg(1, A, B, 44.79, 45.68), leg(2, B, C, 25.55, 42.14), leg(3, B, C, 115.72, 157.45)]
GREEDY_PROFIT = 401.41
EXACT_PROFIT = 475.30


def knapsack_plan(**settings) -> RoutePlan:
    planner = RoutePlanner(KNAPSACK_LEGS, cargo_scu=20, budget=1000, ranking=RANKING_TOTAL_PROFIT, **settings)
    return next(p for p in planner.plan(max_stops=2, limit=0) if p.stops == [A, B, C])


def spy_on_exact_plans(planner: RoutePlanner) -> list:
    calls = []
    original = planner.exact_plan_cargo

    def spy(stops, time_limit=None):
        calls.append(list(stops))
        return original(stops, time_limit)

    planner.exact_plan_cargo = spy
    return calls


def test_the_exact_plan_beats_every_greedy_ordering():
    assert knapsack_plan(exact_candidates=0).profit == pytest.approx(GREEDY_PROFIT, abs=0.01)

    plan = knapsack_plan()

    assert plan.profit == pytest.approx(EXACT_PROFIT, abs=0.01)
    assert all(isinstance(t.scu, int) and t.scu > 0 for t in plan.trades)


def test_without_scipy_the_greedy_plan_is_used(monkeypatch):
    monkeypatch.setitem(sys.modules, "scipy", None)  # makes "import scipy..." raise ImportError
    monkeypatch.setitem(sys.modules, "scipy.optimize", None)

    assert knapsack_plan().profit == pytest.approx(GREEDY_PROFIT, abs=0.01)


def test_when_the_solver_fails_the_greedy_plan_is_used(monkeypatch):
    import scipy.optimize

    def broken(*args, **kwargs):
        raise RuntimeError("solver crashed")

    monkeypatch.setattr(scipy.optimize, "milp", broken)

    assert knapsack_plan().profit == pytest.approx(GREEDY_PROFIT, abs=0.01)


def test_only_routes_that_can_gain_from_it_get_an_exact_plan():
    # Without budget a single hop's greedy plan is provably optimal: only multi-stop routes
    planner = RoutePlanner(KNAPSACK_LEGS, cargo_scu=100, ranking=RANKING_TOTAL_PROFIT)
    calls = spy_on_exact_plans(planner)
    planner.plan(max_stops=2, limit=0)
    assert calls
    assert all(len(stops) > 2 for stops in calls), calls

    # With a budget every candidate (up to exact_candidates) is planned exactly
    planner = RoutePlanner(KNAPSACK_LEGS, cargo_scu=20, budget=1000, ranking=RANKING_TOTAL_PROFIT, exact_candidates=2)
    calls = spy_on_exact_plans(planner)
    planner.plan(max_stops=2, limit=0)
    assert len(calls) == 2


def test_the_exact_step_stops_at_the_total_time_budget():
    planner = RoutePlanner(KNAPSACK_LEGS, cargo_scu=20, budget=1000, ranking=RANKING_TOTAL_PROFIT)
    planner.EXACT_TOTAL_TIME = 0  # no time left: everything keeps its greedy plan
    calls = spy_on_exact_plans(planner)

    plan = next(p for p in planner.plan(max_stops=2, limit=0) if p.stops == [A, B, C])

    assert calls == []
    assert plan.profit == pytest.approx(GREEDY_PROFIT, abs=0.01)


# ── Ranking ─────────────────────────────────────────────────────────

FAR_AND_CLOSE = [
    leg(1, A, B, 10, 20, distance=100),  # 1 stop: 100 profit, far
    leg(2, C, D, 10, 18, distance=1),  # 1 stop: 80 profit, close
]


@pytest.mark.parametrize("ranking, expected", [
    (RANKING_TOTAL_PROFIT, [A, B]),
    (RANKING_PROFIT_PER_STOP, [A, B]),
    (RANKING_PROFIT_PER_DISTANCE, [C, D]),
])
def test_each_ranking_puts_its_own_route_first(ranking, expected):
    assert RoutePlanner(FAR_AND_CLOSE, cargo_scu=10, ranking=ranking).plan()[0].stops == expected


def test_per_stop_can_prefer_fewer_stops_and_total_profit_more():
    legs = [leg(1, A, B, 10, 20), leg(2, B, C, 10, 15)]  # A->B 100, A->B->C 150

    per_stop = RoutePlanner(legs, cargo_scu=10, ranking=RANKING_PROFIT_PER_STOP).plan(max_stops=2)[0]
    total = RoutePlanner(legs, cargo_scu=10, ranking=RANKING_TOTAL_PROFIT).plan(max_stops=2)[0]

    assert per_stop.stops == [A, B]
    assert total.stops == [A, B, C]


def test_an_unknown_distance_never_looks_most_efficient_and_is_reported_as_unknown():
    # Unknown distance used to count as 0 Gm and won profit per distance by far
    legs = [leg(1, A, B, 10, 20, distance=None), leg(2, C, D, 10, 19, distance=30)]

    plans = RoutePlanner(legs, cargo_scu=10, ranking=RANKING_PROFIT_PER_DISTANCE).plan()

    assert plans[0].stops == [C, D]
    assert next(plan for plan in plans if plan.stops == [A, B]).distance is None


def test_the_same_sale_at_other_terminals_is_one_route_with_alternatives():
    # 10 SCU bought at A sell at B, C or D for the same price; only B also takes a second cargo
    legs = [leg(1, A, B, 10, 20, stock=10, distance=30), leg(1, A, C, 10, 20, stock=10, distance=20),
            leg(1, A, D, 10, 20, stock=10, distance=10), leg(2, A, B, 10, 15, distance=30)]

    plans = RoutePlanner(legs, cargo_scu=20, ranking=RANKING_PROFIT_PER_DISTANCE).plan(limit=5)

    assert [plan.stops for plan in plans] == [[A, D], [A, B]]
    assert plans[0].alternative_ends == [C]  # the nearest one leads, C is the same sale
    assert plans[1].alternative_ends == []  # more cargo, another route


# ── System jumps and stops that only buy ────────────────────────────

# A -> B -> C crosses two systems, the direct A -> C hop only one
JUMP_LEGS = [leg(1, A, B, 10, 30, jumps=1), leg(2, B, C, 10, 30, jumps=1), leg(3, A, C, 10, 12, jumps=1), leg(4, A, D, 10, 11)]


def test_jumps_are_counted_per_hop_and_kept_by_the_exact_plan():
    planner = RoutePlanner(JUMP_LEGS, cargo_scu=10)

    plan = planner.plan(max_stops=2, start_terminals={A}, end_terminals={C})[0]

    assert plan.stops == [A, B, C]
    assert plan.jump_count == 2
    assert planner.exact_plan_cargo([A, B, C]).jumps == [1, 1]


def test_max_jumps_drops_routes_with_more_jumps():
    planner = RoutePlanner(JUMP_LEGS, cargo_scu=10)

    plans = planner.plan(max_stops=2, start_terminals={A}, end_terminals={C}, max_jumps=1, limit=0)

    assert [plan.stops for plan in plans] == [[A, C]]
    assert [plan.stops for plan in planner.plan(start_terminals={A}, max_jumps=0)] == [[A, D]]


# Not enough stock at A or B alone, both sell to C; nothing to sell between A and B (no leg)
COLLECT_LEGS = [leg(1, A, C, 10, 50, stock=5), leg(1, B, C, 10, 50, stock=5), leg(2, A, D, 10, 11)]


def test_a_stop_that_only_buys_fills_the_hold():
    plan = RoutePlanner(COLLECT_LEGS, cargo_scu=10).plan(max_stops=2, start_terminals={A}, end_terminals={C})[0]

    assert plan.stops == [A, B, C]
    assert sorted((t.buy_stop, t.sell_stop, t.scu) for t in plan.trades) == [(0, 2, 5), (1, 2, 5)]
    assert plan.profit == 400


def test_without_room_for_another_stop_it_stays_direct():
    plan = RoutePlanner(COLLECT_LEGS, cargo_scu=10).plan(max_stops=1, start_terminals={A}, end_terminals={C})[0]

    assert plan.stops == [A, C]


def test_a_hop_without_a_leg_takes_distance_and_jumps_from_hop_info():
    def hop_info(origin, destination):
        return 7.0, 1

    planner = RoutePlanner(COLLECT_LEGS, cargo_scu=10, hop_info=hop_info)

    plan = planner.plan(max_stops=2, start_terminals={A}, end_terminals={C})[0]
    assert (plan.distances, plan.jumps) == ([7.0, 10], [1, 0])
    # The jump to B is too many: the direct route stays
    assert planner.plan(max_stops=2, start_terminals={A}, end_terminals={C}, max_jumps=0)[0].stops == [A, C]
