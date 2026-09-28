"""
SC_Accountant — Position Manager

Tracks commodity investment positions with unrealized P&L. Auto-opens
positions on commodity purchases and auto-closes on sales using FIFO.

Author: Mallachi
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from models import Position, Transaction
from store import AccountantStore

logger = logging.getLogger(__name__)


class PositionManager:
    """Tracks commodity investment positions with unrealized P&L."""

    def __init__(self, store: AccountantStore, market: object) -> None:
        """Initialize with shared store and market data module.

        Args:
            store: AccountantStore for persistence.
            market: MarketData instance for price lookups.
        """
        self._store = store
        self._market = market

    # ------------------------------------------------------------------
    # Sync Hook: Auto-open on Purchase
    # ------------------------------------------------------------------

    def open_position_from_purchase(self, txn: Transaction) -> Position | None:
        """Open or extend a position from a commodity purchase.

        If an open position already exists for the same commodity, the
        purchase is added to it with a weighted-average cost basis.

        Args:
            txn: The commodity_purchase transaction.

        Returns:
            The new or updated Position, or None on error.
        """
        if txn.category != "commodity_purchase":
            return None

        item_name = txn.item_name or txn.description or "Unknown"
        raw_qty = txn.quantity if txn.quantity and txn.quantity > 0 else 1.0
        unit = txn.quantity_unit or "scu"
        if unit == "cscu":
            quantity = raw_qty / 100.0
            unit = "scu"
        else:
            quantity = raw_qty
        price_per_unit = txn.amount / quantity if quantity > 0 else txn.amount

        # Check for existing open position for same commodity
        open_positions = self._store.query_positions(
            status="open",
            commodity_name=item_name,
            limit=10,
        )

        # Find exact name match among open positions
        existing: Position | None = None
        for pos in open_positions:
            if pos.commodity_name.lower() == item_name.lower():
                existing = pos
                break

        if existing:
            # Weighted-average cost basis
            new_total = existing.buy_total + txn.amount
            new_qty = existing.quantity + quantity
            existing.buy_price_per_unit = new_total / new_qty if new_qty > 0 else 0
            existing.buy_total = new_total
            existing.quantity = new_qty
            self._store.save_position(existing)
            logger.info(
                "Extended position %s: +%.1f %s of %s",
                existing.id[:8],
                quantity,
                txn.quantity_unit or "scu",
                item_name,
            )
            return existing

        # Look up commodity ID from market data
        commodity_id = None
        if self._market and hasattr(self._market, "find_commodity"):
            commodity = self._market.find_commodity(item_name)
            if commodity:
                commodity_id = commodity.get("id")

        pos = Position(
            id=str(uuid.uuid4()),
            opened_at=txn.timestamp,
            status="open",
            commodity_name=item_name,
            commodity_id=commodity_id,
            quantity=quantity,
            quantity_unit=unit,
            buy_price_per_unit=price_per_unit,
            buy_total=txn.amount,
            buy_location=txn.location or txn.shop_name or "",
            buy_transaction_id=txn.id,
        )

        self._store.save_position(pos)
        logger.info(
            "Opened position %s: %.1f %s of %s at %s",
            pos.id[:8],
            quantity,
            pos.quantity_unit,
            item_name,
            pos.buy_location,
        )
        return pos

    # ------------------------------------------------------------------
    # Sync Hook: Auto-close on Sale (FIFO)
    # ------------------------------------------------------------------

    def close_position_from_sale(self, txn: Transaction) -> Position | None:
        """Close positions from a commodity sale using FIFO.

        Oldest open positions for the matching commodity are closed first.
        Partial closes split the position into a closed and remaining portion.

        Args:
            txn: The commodity_sale transaction.

        Returns:
            The last closed Position, or None if no match.
        """
        if txn.category != "commodity_sale":
            return None

        item_name = txn.item_name or txn.description or "Unknown"
        sale_qty = txn.quantity if txn.quantity and txn.quantity > 0 else 1.0
        sale_price_per_unit = txn.amount / sale_qty if sale_qty > 0 else txn.amount
        remaining_qty = sale_qty

        # Load open positions for this commodity, sorted FIFO (oldest first)
        all_open = self._store.query_positions(status="open", limit=200)
        matching = [
            p for p in all_open if p.commodity_name.lower() == item_name.lower()
        ]
        matching.sort(key=lambda p: p.opened_at)

        if not matching:
            logger.debug("No open position found for sale of %s", item_name)
            return None

        now = datetime.now(timezone.utc).isoformat()
        sell_location = txn.location or txn.shop_name or ""
        last_closed: Position | None = None

        for pos in matching:
            if remaining_qty <= 0:
                break

            if remaining_qty >= pos.quantity:
                # Full close
                sold_qty = pos.quantity
                sell_revenue = sale_price_per_unit * sold_qty
                pos.sell_price_per_unit = sale_price_per_unit
                pos.sell_total = sell_revenue
                pos.realized_pnl = sell_revenue - pos.buy_total
                pos.sell_location = sell_location
                pos.sell_transaction_id = txn.id
                pos.closed_at = now
                pos.status = "closed"
                remaining_qty -= sold_qty
                self._store.save_position(pos)
                last_closed = pos
                logger.info(
                    "Closed position %s: %.1f %s of %s (P&L: %.2f)",
                    pos.id[:8],
                    sold_qty,
                    pos.quantity_unit,
                    item_name,
                    pos.realized_pnl,
                )
            else:
                # Partial close — split the position
                sold_qty = remaining_qty
                kept_qty = pos.quantity - sold_qty

                # Create closed portion
                closed_portion = Position(
                    id=str(uuid.uuid4()),
                    opened_at=pos.opened_at,
                    status="closed",
                    commodity_name=pos.commodity_name,
                    commodity_id=pos.commodity_id,
                    quantity=sold_qty,
                    quantity_unit=pos.quantity_unit,
                    buy_price_per_unit=pos.buy_price_per_unit,
                    buy_total=pos.buy_price_per_unit * sold_qty,
                    buy_location=pos.buy_location,
                    buy_transaction_id=pos.buy_transaction_id,
                    sell_price_per_unit=sale_price_per_unit,
                    sell_total=sale_price_per_unit * sold_qty,
                    sell_location=sell_location,
                    sell_transaction_id=txn.id,
                    closed_at=now,
                    realized_pnl=(sale_price_per_unit * sold_qty)
                    - (pos.buy_price_per_unit * sold_qty),
                    notes=f"Split from position {pos.id[:8]}",
                )
                self._store.save_position(closed_portion)

                # Reduce remaining portion
                pos.quantity = kept_qty
                pos.buy_total = pos.buy_price_per_unit * kept_qty
                self._store.save_position(pos)

                last_closed = closed_portion
                remaining_qty = 0

                logger.info(
                    "Partial close %s: sold %.1f, kept %.1f %s of %s",
                    pos.id[:8],
                    sold_qty,
                    kept_qty,
                    pos.quantity_unit,
                    item_name,
                )

        return last_closed

    # ------------------------------------------------------------------
    # Background: Update Unrealized P&L
    # ------------------------------------------------------------------

    def update_unrealized_pnl(self) -> int:
        """Update unrealized P&L for all open positions using market prices.

        Called after market data refresh.

        Returns:
            Count of positions updated.
        """
        open_positions = self._store.query_positions(status="open", limit=200)
        if not open_positions:
            return 0

        if not self._market or not hasattr(self._market, "get_commodity_prices"):
            return 0

        now = datetime.now(timezone.utc).isoformat()
        updated = 0

        for pos in open_positions:
            prices = self._market.get_commodity_prices(pos.commodity_name)
            if not prices:
                continue

            # Average sell price across all terminals that have a sell price
            sell_prices = [
                p.get("price_sell", 0) or 0
                for p in prices
                if (p.get("price_sell", 0) or 0) > 0
            ]
            if not sell_prices:
                continue

            avg_sell = sum(sell_prices) / len(sell_prices)
            pos.current_market_price = avg_sell
            pos.unrealized_pnl = (avg_sell * pos.quantity) - pos.buy_total
            pos.last_price_update = now
            self._store.save_position(pos)
            updated += 1

        if updated > 0:
            logger.info("Updated unrealized P&L for %d positions", updated)

        return updated

    # ------------------------------------------------------------------
    # Tool: List Positions
    # ------------------------------------------------------------------

    def list_positions(
        self,
        status: str = "open",
        commodity: str = "",
        limit: int = 20,
    ) -> list[dict]:
        """List positions with optional filters.

        Args:
            status: Filter by status — open, closed, or all.
            commodity: Filter by commodity name (partial match).
            limit: Maximum results.

        Returns:
            List of position dicts formatted for tool response.
        """
        query_status = None if status == "all" else status
        query_commodity = commodity if commodity else None

        positions = self._store.query_positions(
            status=query_status,
            commodity_name=query_commodity,
            limit=limit,
        )

        return [self._format_position(p) for p in positions]

    # ------------------------------------------------------------------
    # Tool: Portfolio Summary
    # ------------------------------------------------------------------

    def get_portfolio_summary(self) -> dict:
        """Get aggregated portfolio summary of all open positions.

        Returns:
            Dict with total_invested, total_market_value,
            total_unrealized_pnl, position_count, and positions list.
        """
        open_positions = self._store.query_positions(status="open", limit=200)

        total_invested = 0.0
        total_market_value = 0.0
        total_unrealized_pnl = 0.0
        positions_detail: list[dict] = []

        for pos in open_positions:
            total_invested += pos.buy_total
            market_value = pos.current_market_price * pos.quantity
            total_market_value += market_value
            total_unrealized_pnl += pos.unrealized_pnl

            pnl_pct = (
                (pos.unrealized_pnl / pos.buy_total * 100) if pos.buy_total > 0 else 0.0
            )

            positions_detail.append(
                {
                    "commodity": pos.commodity_name,
                    "quantity": pos.quantity,
                    "quantity_unit": pos.quantity_unit,
                    "cost_basis": round(pos.buy_total, 2),
                    "market_value": round(market_value, 2),
                    "unrealized_pnl": round(pos.unrealized_pnl, 2),
                    "pnl_percent": round(pnl_pct, 1),
                    "buy_price_per_unit": round(pos.buy_price_per_unit, 2),
                    "current_price": round(pos.current_market_price, 2),
                }
            )

        # Sort by absolute unrealized P&L descending
        positions_detail.sort(
            key=lambda p: abs(p["unrealized_pnl"]),
            reverse=True,
        )

        return {
            "total_invested": round(total_invested, 2),
            "total_market_value": round(total_market_value, 2),
            "total_unrealized_pnl": round(total_unrealized_pnl, 2),
            "pnl_percent": round(
                (total_unrealized_pnl / total_invested * 100)
                if total_invested > 0
                else 0.0,
                1,
            ),
            "position_count": len(open_positions),
            "positions": positions_detail,
        }

    # ------------------------------------------------------------------
    # Tool: Manual Close
    # ------------------------------------------------------------------

    def close_position_manual(
        self,
        pos_id: str,
        sell_price: float,
        sell_location: str = "",
    ) -> dict:
        """Manually close an open position.

        Args:
            pos_id: Full or partial position ID.
            sell_price: Total aUEC received for the sale.
            sell_location: Where the sale happened.

        Returns:
            Confirmation dict.
        """
        pos = self._find_by_id(pos_id)
        if not pos:
            return {"error": f"Position not found: {pos_id}"}

        if pos.status != "open":
            return {"error": f"Position is {pos.status}, not open"}

        now = datetime.now(timezone.utc).isoformat()
        pos.sell_total = sell_price
        pos.sell_price_per_unit = (
            sell_price / pos.quantity if pos.quantity > 0 else sell_price
        )
        pos.sell_location = sell_location
        pos.realized_pnl = sell_price - pos.buy_total
        pos.closed_at = now
        pos.status = "closed"
        pos.notes = (pos.notes + " Manually closed").strip()
        self._store.save_position(pos)

        return {
            "status": "closed",
            "position_id": pos.id[:8],
            "commodity": pos.commodity_name,
            "quantity": pos.quantity,
            "buy_total": round(pos.buy_total, 2),
            "sell_total": round(pos.sell_total, 2),
            "realized_pnl": round(pos.realized_pnl, 2),
        }

    # ------------------------------------------------------------------
    # Tool: Adjust Position
    # ------------------------------------------------------------------

    def adjust_position(
        self,
        pos_id: str,
        quantity: float | None = None,
        buy_price: float | None = None,
        notes: str = "",
    ) -> dict:
        """Adjust an open position's details for corrections.

        Args:
            pos_id: Full or partial position ID.
            quantity: New quantity (None = no change).
            buy_price: New buy price per unit (None = no change).
            notes: Reason for adjustment.

        Returns:
            Confirmation dict.
        """
        pos = self._find_by_id(pos_id)
        if not pos:
            return {"error": f"Position not found: {pos_id}"}

        if pos.status != "open":
            return {"error": f"Position is {pos.status}, not open"}

        changes: list[str] = []

        if quantity is not None and quantity > 0:
            old_qty = pos.quantity
            pos.quantity = quantity
            pos.buy_total = pos.buy_price_per_unit * quantity
            changes.append(f"quantity: {old_qty} -> {quantity}")

        if buy_price is not None and buy_price > 0:
            old_price = pos.buy_price_per_unit
            pos.buy_price_per_unit = buy_price
            pos.buy_total = buy_price * pos.quantity
            changes.append(f"buy_price: {old_price:.2f} -> {buy_price:.2f}")

        if notes:
            pos.notes = (pos.notes + f" Adjusted: {notes}").strip()

        self._store.save_position(pos)

        return {
            "status": "adjusted",
            "position_id": pos.id[:8],
            "commodity": pos.commodity_name,
            "changes": changes or ["No changes"],
            "new_quantity": pos.quantity,
            "new_buy_price_per_unit": round(pos.buy_price_per_unit, 2),
            "new_buy_total": round(pos.buy_total, 2),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_by_id(self, pos_id: str) -> Position | None:
        """Find a position by full or partial ID."""
        pos = self._store.get_position(pos_id)
        if pos:
            return pos

        for pos in self._store.query_positions(limit=500):
            if pos.id.startswith(pos_id):
                return pos

        return None

    def _format_position(self, pos: Position) -> dict:
        """Format a position for tool response."""
        result = {
            "id": pos.id[:8],
            "status": pos.status,
            "commodity": pos.commodity_name,
            "quantity": pos.quantity,
            "quantity_unit": pos.quantity_unit,
            "buy_price_per_unit": round(pos.buy_price_per_unit, 2),
            "buy_total": round(pos.buy_total, 2),
            "buy_location": pos.buy_location,
            "opened_at": pos.opened_at,
        }

        if pos.status == "open":
            result["current_market_price"] = round(pos.current_market_price, 2)
            result["unrealized_pnl"] = round(pos.unrealized_pnl, 2)
            if pos.last_price_update:
                result["last_price_update"] = pos.last_price_update

        if pos.status == "closed":
            result["sell_price_per_unit"] = round(pos.sell_price_per_unit, 2)
            result["sell_total"] = round(pos.sell_total, 2)
            result["sell_location"] = pos.sell_location
            result["realized_pnl"] = round(pos.realized_pnl, 2)
            result["closed_at"] = pos.closed_at

        if pos.notes:
            result["notes"] = pos.notes

        return result
