"""
SC_Accountant — Financial Report Generators

Produces P&L statements, expense/revenue breakdowns, budget-vs-actual
comparisons, portfolio reports, and opportunity pipeline summaries.

Author: Mallachi
"""

from __future__ import annotations

from models import (
    CATEGORY_LABELS,
    EXPENSE_CATEGORIES,
    INCOME_CATEGORIES,
    Budget,
    Opportunity,
    Position,
    Transaction,
)


def generate_pnl(transactions: list[Transaction]) -> dict:
    """Generate a Profit & Loss statement.

    Args:
        transactions: Filtered list of transactions for the period.

    Returns:
        Dict with total_income, total_expenses, net_profit,
        income_by_category, expense_by_category, and transaction_count.
    """
    total_income = 0.0
    total_expenses = 0.0
    income_by_cat: dict[str, float] = {}
    expense_by_cat: dict[str, float] = {}

    for txn in transactions:
        label = CATEGORY_LABELS.get(txn.category, txn.category)
        if txn.transaction_type == "income":
            total_income += txn.amount
            income_by_cat[label] = income_by_cat.get(label, 0.0) + txn.amount
        else:
            total_expenses += txn.amount
            expense_by_cat[label] = expense_by_cat.get(label, 0.0) + txn.amount

    # Sort by amount descending
    income_by_cat = dict(
        sorted(income_by_cat.items(), key=lambda x: x[1], reverse=True)
    )
    expense_by_cat = dict(
        sorted(expense_by_cat.items(), key=lambda x: x[1], reverse=True)
    )

    return {
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_profit": total_income - total_expenses,
        "transaction_count": len(transactions),
        "income_by_category": income_by_cat,
        "expense_by_category": expense_by_cat,
    }


def generate_expense_breakdown(transactions: list[Transaction]) -> dict:
    """Generate a detailed expense breakdown.

    Args:
        transactions: Filtered list of transactions for the period.

    Returns:
        Dict with total_expenses, categories (list of dicts with
        category, amount, percentage, count), and transaction_count.
    """
    expense_txns = [t for t in transactions if t.category in EXPENSE_CATEGORIES]
    total = sum(t.amount for t in expense_txns)

    # Group by category
    by_cat: dict[str, dict] = {}
    for txn in expense_txns:
        label = CATEGORY_LABELS.get(txn.category, txn.category)
        if label not in by_cat:
            by_cat[label] = {"amount": 0.0, "count": 0}
        by_cat[label]["amount"] += txn.amount
        by_cat[label]["count"] += 1

    categories = []
    for cat_label, data in sorted(
        by_cat.items(), key=lambda x: x[1]["amount"], reverse=True
    ):
        pct = (data["amount"] / total * 100) if total > 0 else 0.0
        categories.append(
            {
                "category": cat_label,
                "amount": data["amount"],
                "percentage": round(pct, 1),
                "count": data["count"],
            }
        )

    return {
        "total_expenses": total,
        "categories": categories,
        "transaction_count": len(expense_txns),
    }


def generate_revenue_breakdown(transactions: list[Transaction]) -> dict:
    """Generate a detailed revenue breakdown.

    Args:
        transactions: Filtered list of transactions for the period.

    Returns:
        Dict with total_revenue, categories (list of dicts with
        category, amount, percentage, count), and transaction_count.
    """
    income_txns = [t for t in transactions if t.category in INCOME_CATEGORIES]
    total = sum(t.amount for t in income_txns)

    by_cat: dict[str, dict] = {}
    for txn in income_txns:
        label = CATEGORY_LABELS.get(txn.category, txn.category)
        if label not in by_cat:
            by_cat[label] = {"amount": 0.0, "count": 0}
        by_cat[label]["amount"] += txn.amount
        by_cat[label]["count"] += 1

    categories = []
    for cat_label, data in sorted(
        by_cat.items(), key=lambda x: x[1]["amount"], reverse=True
    ):
        pct = (data["amount"] / total * 100) if total > 0 else 0.0
        categories.append(
            {
                "category": cat_label,
                "amount": data["amount"],
                "percentage": round(pct, 1),
                "count": data["count"],
            }
        )

    return {
        "total_revenue": total,
        "categories": categories,
        "transaction_count": len(income_txns),
    }


def generate_budget_vs_actual(
    budgets: list[Budget],
    transactions: list[Transaction],
) -> list[dict]:
    """Compare budget allocations against actual spending.

    Args:
        budgets: Active budgets for the period.
        transactions: Transactions within the budget periods.

    Returns:
        List of dicts with budget_id, category, allocated, spent,
        remaining, percentage_used, and status.
    """
    results = []
    for budget in budgets:
        # Find transactions matching this budget's category and period
        matching = [
            t
            for t in transactions
            if t.category == budget.category
            and t.timestamp >= budget.period_start
            and t.timestamp < budget.period_end
        ]
        spent = sum(t.amount for t in matching if t.transaction_type == "expense")
        remaining = budget.allocated_amount - spent
        pct = (
            (spent / budget.allocated_amount * 100)
            if budget.allocated_amount > 0
            else 0.0
        )

        if pct >= 100:
            status = "over_budget"
        elif pct >= 80:
            status = "warning"
        else:
            status = "on_track"

        results.append(
            {
                "budget_id": budget.id,
                "category": CATEGORY_LABELS.get(budget.category, budget.category),
                "period_type": budget.period_type,
                "allocated": budget.allocated_amount,
                "spent": spent,
                "remaining": remaining,
                "percentage_used": round(pct, 1),
                "status": status,
            }
        )

    return results


def generate_portfolio_report(positions: list[Position]) -> dict:
    """Generate a portfolio report from open positions.

    Args:
        positions: List of open Position objects.

    Returns:
        Dict with total_invested, total_market_value, total_unrealized_pnl,
        position_count, and by_commodity breakdown.
    """
    by_commodity: dict[str, dict] = {}

    for pos in positions:
        name = pos.commodity_name
        if name not in by_commodity:
            by_commodity[name] = {
                "invested": 0.0,
                "market_value": 0.0,
                "unrealized_pnl": 0.0,
                "quantity": 0.0,
                "count": 0,
            }
        entry = by_commodity[name]
        entry["invested"] += pos.buy_total
        entry["market_value"] += pos.current_market_price * pos.quantity
        entry["unrealized_pnl"] += pos.unrealized_pnl
        entry["quantity"] += pos.quantity
        entry["count"] += 1

    total_invested = sum(e["invested"] for e in by_commodity.values())
    total_market = sum(e["market_value"] for e in by_commodity.values())
    total_pnl = sum(e["unrealized_pnl"] for e in by_commodity.values())

    # Sort by absolute unrealized P&L descending
    commodities = []
    for name, data in sorted(
        by_commodity.items(),
        key=lambda x: abs(x[1]["unrealized_pnl"]),
        reverse=True,
    ):
        pct = (
            (data["unrealized_pnl"] / data["invested"] * 100)
            if data["invested"] > 0
            else 0.0
        )
        commodities.append(
            {
                "commodity": name,
                "quantity": round(data["quantity"], 1),
                "invested": round(data["invested"], 2),
                "market_value": round(data["market_value"], 2),
                "unrealized_pnl": round(data["unrealized_pnl"], 2),
                "pnl_percent": round(pct, 1),
                "position_count": data["count"],
            }
        )

    return {
        "total_invested": round(total_invested, 2),
        "total_market_value": round(total_market, 2),
        "total_unrealized_pnl": round(total_pnl, 2),
        "pnl_percent": round(
            (total_pnl / total_invested * 100) if total_invested > 0 else 0.0, 1
        ),
        "position_count": len(positions),
        "by_commodity": commodities,
    }


def generate_opportunity_report(opportunities: list[Opportunity]) -> dict:
    """Generate an opportunity pipeline summary.

    Args:
        opportunities: List of Opportunity objects (any status).

    Returns:
        Dict with status counts, top available by score, and recently fulfilled.
    """
    by_status: dict[str, int] = {}
    total_estimated = 0.0

    for opp in opportunities:
        by_status[opp.status] = by_status.get(opp.status, 0) + 1
        if opp.status == "available":
            total_estimated += opp.estimated_profit

    # Top available opportunities
    available = [o for o in opportunities if o.status == "available"]
    available.sort(key=lambda o: o.score, reverse=True)
    top_available = [
        {
            "commodity": o.commodity_name,
            "margin_per_scu": round(o.margin_per_scu, 2),
            "estimated_profit": round(o.estimated_profit, 2),
            "buy_terminal": o.buy_terminal,
            "sell_terminal": o.sell_terminal,
            "score": o.score,
        }
        for o in available[:5]
    ]

    # Recently fulfilled
    fulfilled = [o for o in opportunities if o.status == "fulfilled"]
    fulfilled.sort(key=lambda o: o.fulfilled_at or "", reverse=True)
    recent_fulfilled = [
        {
            "commodity": o.commodity_name,
            "estimated_profit": round(o.estimated_profit, 2),
            "fulfilled_at": o.fulfilled_at,
        }
        for o in fulfilled[:5]
    ]

    return {
        "by_status": by_status,
        "total_available_count": by_status.get("available", 0),
        "total_estimated_profit": round(total_estimated, 2),
        "top_available": top_available,
        "recently_fulfilled": recent_fulfilled,
    }
