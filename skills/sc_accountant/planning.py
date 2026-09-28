"""
SC_Accountant — Planning & Forecasting Engine

Higher-level analytics built on the three-statement data:
- Break-even analysis: how long until an asset pays for itself
- Activity ROI comparison: which gameplay loop earns the most per hour
- What-if scenarios: simple projections for upgrade/purchase decisions

Author: Mallachi
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from models import (
    CATEGORY_ACTIVITY,
    CATEGORY_CLASSIFICATION,
    Activity,
    Asset,
    StatementClass,
    Transaction,
)
from store import AccountantStore

logger = logging.getLogger(__name__)


class PlanningEngine:
    """Provides planning and forecasting analytics."""

    def __init__(
        self,
        store: AccountantStore,
        format_fn: Callable[[float], str],
    ) -> None:
        self._store = store
        self._format = format_fn

    def break_even_analysis(
        self,
        asset: Asset,
        transactions: list[Transaction],
    ) -> dict:
        """Calculate break-even timeline for an asset.

        Uses historical revenue and costs linked to the asset to project
        when (or if) it will pay for itself.

        Args:
            asset: The asset to analyze.
            transactions: Transactions linked to this asset.

        Returns:
            Dict with purchase price, net profit, remaining, daily rate,
            and estimated break-even date.
        """
        revenue = 0.0
        costs = 0.0

        for txn in transactions:
            classification = CATEGORY_CLASSIFICATION.get(txn.category)
            if classification == StatementClass.REVENUE:
                revenue += txn.amount
            elif classification in (StatementClass.COGS, StatementClass.OPEX):
                costs += txn.amount

        net_profit = revenue - costs
        remaining = asset.purchase_price - net_profit

        # Calculate daily earning rate from transaction history
        avg_daily_profit = 0.0
        est_days: float | None = None
        est_date: str | None = None

        if transactions:
            timestamps = sorted(t.timestamp for t in transactions)
            first = datetime.fromisoformat(timestamps[0])
            last = datetime.fromisoformat(timestamps[-1])
            days_span = max((last - first).total_seconds() / 86400, 1)
            avg_daily_profit = net_profit / days_span

            if avg_daily_profit > 0 and remaining > 0:
                est_days = remaining / avg_daily_profit
                from datetime import timedelta

                est_date_dt = datetime.now(tz=timezone.utc) + timedelta(days=est_days)
                est_date = est_date_dt.strftime("%Y-%m-%d")

        already_paid = net_profit >= asset.purchase_price

        return {
            "asset_name": asset.name,
            "asset_type": asset.asset_type,
            "purchase_price": round(asset.purchase_price, 2),
            "total_revenue": round(revenue, 2),
            "total_costs": round(costs, 2),
            "net_profit_to_date": round(net_profit, 2),
            "remaining_to_break_even": round(max(remaining, 0), 2),
            "avg_daily_profit": round(avg_daily_profit, 2),
            "est_days_to_break_even": round(est_days, 1) if est_days else None,
            "est_break_even_date": est_date,
            "already_paid_off": already_paid,
            "roi_pct": round(
                (net_profit / asset.purchase_price * 100)
                if asset.purchase_price > 0
                else 0.0,
                1,
            ),
        }

    def activity_roi_comparison(
        self,
        transactions: list[Transaction],
    ) -> list[dict]:
        """Compare profitability across gameplay activities.

        Args:
            transactions: Transactions for the analysis period.

        Returns:
            List of activity dicts sorted by net margin descending, each
            with revenue, costs, net, margin_pct, and txn_count.
        """
        activity_data: dict[str, dict[str, float | int]] = {}

        for txn in transactions:
            activity_key = (
                txn.activity
                or CATEGORY_ACTIVITY.get(txn.category, Activity.GENERAL).value
            )
            classification = CATEGORY_CLASSIFICATION.get(txn.category)

            if activity_key not in activity_data:
                activity_data[activity_key] = {
                    "revenue": 0.0,
                    "costs": 0.0,
                    "txn_count": 0,
                }

            entry = activity_data[activity_key]
            entry["txn_count"] = int(entry["txn_count"]) + 1

            if classification == StatementClass.REVENUE:
                entry["revenue"] = float(entry["revenue"]) + txn.amount
            elif classification in (StatementClass.COGS, StatementClass.OPEX):
                entry["costs"] = float(entry["costs"]) + txn.amount

        results = []
        for act_key, data in activity_data.items():
            act_revenue = float(data["revenue"])
            act_costs = float(data["costs"])
            net = act_revenue - act_costs
            margin_pct = (net / act_revenue * 100) if act_revenue > 0 else 0.0

            # Skip activities with no meaningful data
            if act_revenue == 0 and act_costs == 0:
                continue

            results.append(
                {
                    "activity": act_key,
                    "activity_label": act_key.replace("_", " ").title(),
                    "revenue": round(act_revenue, 2),
                    "costs": round(act_costs, 2),
                    "net_profit": round(net, 2),
                    "margin_pct": round(margin_pct, 1),
                    "txn_count": int(data["txn_count"]),
                }
            )

        results.sort(key=lambda r: r["net_profit"], reverse=True)
        return results

    def what_if_scenario(
        self,
        scenario_type: str,
        parameters: dict,
        transactions: list[Transaction] | None = None,
    ) -> dict:
        """Run a simple what-if scenario.

        Supported scenarios:
        - "upgrade": If I spend X on an upgrade that improves yield by Y%,
          how long until payback?
        - "ship_purchase": If I buy ship X for Y aUEC, based on my current
          earning rate for activity Z, how long to break even?
        - "trade": If I buy X units of commodity at price A and sell at B,
          what's the profit after costs?

        Args:
            scenario_type: Type of scenario.
            parameters: Scenario-specific parameters.
            transactions: Historical transactions for context.

        Returns:
            Dict with scenario results.
        """
        if scenario_type == "upgrade":
            return self._what_if_upgrade(parameters, transactions or [])
        elif scenario_type == "ship_purchase":
            return self._what_if_ship_purchase(parameters, transactions or [])
        elif scenario_type == "trade":
            return self._what_if_trade(parameters)
        else:
            return {
                "error": f"Unknown scenario: {scenario_type}",
                "supported": ["upgrade", "ship_purchase", "trade"],
            }

    def _what_if_upgrade(
        self,
        params: dict,
        transactions: list[Transaction],
    ) -> dict:
        """What-if: upgrade cost vs yield improvement."""
        cost = float(params.get("cost", 0))
        improvement_pct = float(params.get("improvement_pct", 0))
        activity = params.get("activity", "trading")

        # Calculate current daily earnings for the activity
        activity_txns = [
            t
            for t in transactions
            if (
                t.activity == activity
                or CATEGORY_ACTIVITY.get(t.category, Activity.GENERAL).value == activity
            )
        ]

        current_daily = 0.0
        if activity_txns:
            timestamps = sorted(t.timestamp for t in activity_txns)
            first = datetime.fromisoformat(timestamps[0])
            last = datetime.fromisoformat(timestamps[-1])
            days = max((last - first).total_seconds() / 86400, 1)
            revenue = sum(
                t.amount
                for t in activity_txns
                if CATEGORY_CLASSIFICATION.get(t.category) == StatementClass.REVENUE
            )
            current_daily = revenue / days

        added_daily = current_daily * (improvement_pct / 100)
        payback_days = cost / added_daily if added_daily > 0 else None

        return {
            "scenario": "upgrade",
            "cost": round(cost, 2),
            "improvement_pct": improvement_pct,
            "activity": activity,
            "current_daily_revenue": round(current_daily, 2),
            "added_daily_revenue": round(added_daily, 2),
            "payback_days": round(payback_days, 1) if payback_days else None,
            "recommendation": (
                f"Payback in ~{payback_days:.0f} days"
                if payback_days and payback_days < 365
                else "Not enough data or payback exceeds 1 year"
            ),
        }

    def _what_if_ship_purchase(
        self,
        params: dict,
        transactions: list[Transaction],
    ) -> dict:
        """What-if: new ship purchase with projected earnings."""
        purchase_price = float(params.get("price", 0))
        activity = params.get("activity", "trading")

        # Use historical earnings for the target activity
        roi = self.activity_roi_comparison(transactions)
        matching = [r for r in roi if r["activity"] == activity]

        if not matching:
            return {
                "scenario": "ship_purchase",
                "price": round(purchase_price, 2),
                "activity": activity,
                "error": f"No historical data for activity: {activity}",
            }

        act_data = matching[0]
        # Estimate daily profit from transaction count and period
        daily_profit = act_data["net_profit"] / 30  # rough monthly estimate
        payback_days = purchase_price / daily_profit if daily_profit > 0 else None

        return {
            "scenario": "ship_purchase",
            "price": round(purchase_price, 2),
            "activity": activity,
            "activity_net_profit": round(act_data["net_profit"], 2),
            "est_daily_profit": round(daily_profit, 2),
            "payback_days": round(payback_days, 1) if payback_days else None,
            "recommendation": (
                f"Estimated payback: ~{payback_days:.0f} days"
                if payback_days and payback_days < 365
                else "Payback exceeds 1 year or insufficient data"
            ),
        }

    def _what_if_trade(self, params: dict) -> dict:
        """What-if: single trade calculation."""
        buy_price = float(params.get("buy_price", 0))
        sell_price = float(params.get("sell_price", 0))
        quantity = float(params.get("quantity", 1))
        fuel_cost = float(params.get("fuel_cost", 0))
        other_costs = float(params.get("other_costs", 0))

        revenue = sell_price * quantity
        cost = (buy_price * quantity) + fuel_cost + other_costs
        profit = revenue - cost
        margin_pct = (profit / revenue * 100) if revenue > 0 else 0.0
        roi_pct = (profit / cost * 100) if cost > 0 else 0.0

        return {
            "scenario": "trade",
            "buy_price_per_unit": round(buy_price, 2),
            "sell_price_per_unit": round(sell_price, 2),
            "quantity": round(quantity, 1),
            "total_revenue": round(revenue, 2),
            "total_cost": round(cost, 2),
            "fuel_cost": round(fuel_cost, 2),
            "other_costs": round(other_costs, 2),
            "profit": round(profit, 2),
            "margin_pct": round(margin_pct, 1),
            "roi_pct": round(roi_pct, 1),
        }
