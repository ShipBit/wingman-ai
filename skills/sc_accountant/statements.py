"""
SC_Accountant — Three-Statement Financial Report Engine

Generates the three core financial statements adapted for Star Citizen:
- Income Statement ("Operations Report"): Revenue - COGS = Gross Margin - OpEx
- Balance Sheet ("Hangar Report"): Assets vs Liabilities vs Equity
- Cash Flow Statement ("aUEC Flow"): Operating vs Investing cash flow

Also provides per-asset P&L for ship-level profitability analysis.

All functions are pure — they take data in and return dicts out. No side
effects, no persistence, no HUD rendering.

Author: Mallachi
"""

from __future__ import annotations

from models import (
    CATEGORY_ACTIVITY,
    CATEGORY_CLASSIFICATION,
    CATEGORY_LABELS,
    AccountBalance,
    Activity,
    Asset,
    Position,
    StatementClass,
    Transaction,
)


def generate_income_statement(
    transactions: list[Transaction],
    period_label: str = "",
) -> dict:
    """Generate an income statement with per-activity margin analysis.

    The killer feature: shows which gameplay loop actually makes money
    vs. which just feels profitable.

    Args:
        transactions: Filtered transactions for the reporting period.
        period_label: Human-readable period label (e.g. "March 2026").

    Returns:
        Dict with revenue, cogs, gross_margin, opex, net_operating_profit,
        capex, activity_margins, and transaction_count.
    """
    revenue = 0.0
    cogs = 0.0
    opex = 0.0
    capex = 0.0
    revenue_by_cat: dict[str, float] = {}
    cogs_by_cat: dict[str, float] = {}
    opex_by_cat: dict[str, float] = {}
    capex_by_cat: dict[str, float] = {}

    # Per-activity accumulators
    activity_data: dict[str, dict[str, float | int]] = {}

    for txn in transactions:
        classification = CATEGORY_CLASSIFICATION.get(txn.category)
        activity_key = (
            txn.activity or CATEGORY_ACTIVITY.get(txn.category, Activity.GENERAL).value
        )
        label = CATEGORY_LABELS.get(txn.category, txn.category)

        # Accumulate by statement class
        if classification == StatementClass.REVENUE:
            revenue += txn.amount
            revenue_by_cat[label] = revenue_by_cat.get(label, 0.0) + txn.amount
        elif classification == StatementClass.COGS:
            cogs += txn.amount
            cogs_by_cat[label] = cogs_by_cat.get(label, 0.0) + txn.amount
        elif classification == StatementClass.OPEX:
            opex += txn.amount
            opex_by_cat[label] = opex_by_cat.get(label, 0.0) + txn.amount
        elif classification == StatementClass.CAPEX:
            capex += txn.amount
            capex_by_cat[label] = capex_by_cat.get(label, 0.0) + txn.amount

        # Accumulate by activity
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

    gross_margin = revenue - cogs
    net_operating_profit = gross_margin - opex

    # Build per-activity margin list sorted by margin descending
    activity_margins = []
    for act_key, data in activity_data.items():
        act_revenue = float(data["revenue"])
        act_costs = float(data["costs"])
        margin = act_revenue - act_costs
        margin_pct = (margin / act_revenue * 100) if act_revenue > 0 else 0.0
        activity_margins.append(
            {
                "activity": act_key,
                "revenue": round(act_revenue, 2),
                "costs": round(act_costs, 2),
                "margin": round(margin, 2),
                "margin_pct": round(margin_pct, 1),
                "txn_count": int(data["txn_count"]),
            }
        )
    activity_margins.sort(key=lambda a: a["margin"], reverse=True)

    # Sort category breakdowns by amount descending
    def _sort_dict(d: dict[str, float]) -> dict[str, float]:
        return dict(sorted(d.items(), key=lambda x: x[1], reverse=True))

    return {
        "period": period_label,
        "revenue": round(revenue, 2),
        "revenue_by_category": _sort_dict(revenue_by_cat),
        "cogs": round(cogs, 2),
        "cogs_by_category": _sort_dict(cogs_by_cat),
        "gross_margin": round(gross_margin, 2),
        "gross_margin_pct": round(
            (gross_margin / revenue * 100) if revenue > 0 else 0.0, 1
        ),
        "opex": round(opex, 2),
        "opex_by_category": _sort_dict(opex_by_cat),
        "net_operating_profit": round(net_operating_profit, 2),
        "net_margin_pct": round(
            (net_operating_profit / revenue * 100) if revenue > 0 else 0.0, 1
        ),
        "capex": round(capex, 2),
        "capex_by_category": _sort_dict(capex_by_cat),
        "activity_margins": activity_margins,
        "transaction_count": len(transactions),
    }


def generate_balance_sheet(
    balance: AccountBalance,
    assets: list[Asset],
    open_positions: list[Position],
) -> dict:
    """Generate a balance sheet (Hangar Report).

    Assets = Cash + Ships + Components + Vehicles + Cargo
    Equity = Total Assets

    Args:
        balance: Current account balance.
        assets: All registered assets.
        open_positions: Currently open trading positions.

    Returns:
        Dict with assets and equity sections.
    """
    cash = balance.current_balance

    active_assets = [a for a in assets if a.status == "active"]
    ships_value = sum(
        a.estimated_market_value or a.purchase_price
        for a in active_assets
        if a.asset_type == "ship"
    )
    components_value = sum(
        a.estimated_market_value or a.purchase_price
        for a in active_assets
        if a.asset_type in ("component", "equipment")
    )
    vehicles_value = sum(
        a.estimated_market_value or a.purchase_price
        for a in active_assets
        if a.asset_type == "vehicle"
    )

    cargo_value = sum(p.current_market_price * p.quantity for p in open_positions)

    total_assets = cash + ships_value + components_value + vehicles_value + cargo_value

    asset_details = [
        {
            "name": a.name,
            "type": a.asset_type,
            "status": a.status,
            "value": round(a.estimated_market_value or a.purchase_price, 2),
            "purchase_price": round(a.purchase_price, 2),
        }
        for a in active_assets
    ]

    return {
        "assets": {
            "cash": round(cash, 2),
            "ships": round(ships_value, 2),
            "ships_count": len([a for a in active_assets if a.asset_type == "ship"]),
            "components": round(components_value, 2),
            "vehicles": round(vehicles_value, 2),
            "cargo": round(cargo_value, 2),
            "total": round(total_assets, 2),
        },
        "equity": {
            "net_worth": round(total_assets, 2),
        },
        "asset_details": asset_details,
    }


def generate_cash_flow(
    transactions: list[Transaction],
    period_label: str = "",
) -> dict:
    """Generate a cash flow statement (aUEC Flow).

    Operating = gameplay earnings minus gameplay costs (Revenue - COGS - OpEx)
    Investing = asset purchases minus asset sales (CapEx)

    Args:
        transactions: Filtered transactions for the reporting period.
        period_label: Human-readable period label.

    Returns:
        Dict with operating, investing, and net_cash_change sections.
    """
    op_inflows = 0.0
    op_outflows = 0.0
    inv_outflows = 0.0
    inv_inflows = 0.0

    for txn in transactions:
        classification = CATEGORY_CLASSIFICATION.get(txn.category)

        if classification == StatementClass.REVENUE:
            op_inflows += txn.amount
        elif classification == StatementClass.COGS:
            op_outflows += txn.amount
        elif classification == StatementClass.OPEX:
            op_outflows += txn.amount
        elif classification == StatementClass.CAPEX:
            inv_outflows += txn.amount

    op_net = op_inflows - op_outflows
    inv_net = inv_inflows - inv_outflows
    net_cash_change = op_net + inv_net

    return {
        "period": period_label,
        "operating": {
            "inflows": round(op_inflows, 2),
            "outflows": round(op_outflows, 2),
            "net": round(op_net, 2),
        },
        "investing": {
            "outflows": round(inv_outflows, 2),
            "inflows": round(inv_inflows, 2),
            "net": round(inv_net, 2),
        },
        "net_cash_change": round(net_cash_change, 2),
    }


def generate_asset_pnl(
    asset: Asset,
    transactions: list[Transaction],
) -> dict:
    """Generate P&L for a single asset (per-ship profitability).

    Args:
        asset: The asset to analyze.
        transactions: Transactions linked to this asset.

    Returns:
        Dict with asset info, revenue, costs, net profit, and margin.
    """
    revenue = 0.0
    costs = 0.0
    revenue_by_cat: dict[str, float] = {}
    cost_by_cat: dict[str, float] = {}

    for txn in transactions:
        label = CATEGORY_LABELS.get(txn.category, txn.category)
        classification = CATEGORY_CLASSIFICATION.get(txn.category)

        if classification == StatementClass.REVENUE:
            revenue += txn.amount
            revenue_by_cat[label] = revenue_by_cat.get(label, 0.0) + txn.amount
        elif classification in (
            StatementClass.COGS,
            StatementClass.OPEX,
        ):
            costs += txn.amount
            cost_by_cat[label] = cost_by_cat.get(label, 0.0) + txn.amount

    net_profit = revenue - costs

    return {
        "asset_id": asset.id,
        "asset_name": asset.name,
        "asset_type": asset.asset_type,
        "purchase_price": round(asset.purchase_price, 2),
        "revenue": round(revenue, 2),
        "revenue_by_category": dict(
            sorted(revenue_by_cat.items(), key=lambda x: x[1], reverse=True)
        ),
        "costs": round(costs, 2),
        "cost_by_category": dict(
            sorted(cost_by_cat.items(), key=lambda x: x[1], reverse=True)
        ),
        "net_profit": round(net_profit, 2),
        "margin_pct": round((net_profit / revenue * 100) if revenue > 0 else 0.0, 1),
        "roi_pct": round(
            (net_profit / asset.purchase_price * 100)
            if asset.purchase_price > 0
            else 0.0,
            1,
        ),
        "transaction_count": len(transactions),
    }
