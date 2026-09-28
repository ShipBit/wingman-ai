"""
SC_Accountant — Futures Manager

Auto-generates trade opportunities from market data, tracks acceptance,
and detects fulfillment when matching trades are captured from the game log.

Author: Mallachi
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from models import Opportunity, TradeOrder, Transaction
from store import AccountantStore

logger = logging.getLogger(__name__)


class FuturesManager:
    """Generates, tracks, and fulfills trade opportunities from market data."""

    def __init__(self, store: AccountantStore, market: object) -> None:
        """Initialize with shared store and market data module.

        Args:
            store: AccountantStore for persistence.
            market: MarketData instance for route queries.
        """
        self._store = store
        self._market = market

    # ------------------------------------------------------------------
    # Background: Opportunity Generation
    # ------------------------------------------------------------------

    def generate_opportunities(
        self,
        top_n: int = 20,
        min_margin: float = 0.5,
        location: str = "",
        star_system: str = "",
    ) -> int:
        """Generate new trade opportunities from current market data.

        Called automatically after market data refresh.

        Args:
            top_n: Number of top routes to consider. When a location or
                star_system is specified, this cap is removed so all
                routes for that filter are returned.
            min_margin: Minimum profit margin per SCU to qualify.
            location: Filter routes to those originating from this location
                (matched against terminal names). Empty = all locations.
            star_system: Filter routes to this star system. Empty = all.

        Returns:
            Count of new opportunities created.
        """
        # When filtering by location or system, fetch all routes (no cap)
        has_filter = bool(location or star_system)
        fetch_limit = 500 if has_filter else top_n * 2
        routes = self._market.get_best_trades(
            limit=fetch_limit, location=location, star_system=star_system or None
        )
        if not routes:
            return 0

        # Build fingerprints of existing available opportunities for dedup
        existing = self._store.query_opportunities(status="available", limit=500)
        existing_fingerprints: set[tuple[int, int, int]] = set()
        for opp in existing:
            fp = (opp.commodity_id, opp.buy_terminal_id, opp.sell_terminal_id)
            existing_fingerprints.add(fp)

        now = datetime.now(timezone.utc).isoformat()
        new_opps: list[Opportunity] = []

        for route in routes:
            commodity_id = route.get("id_commodity", 0)
            buy_terminal_id = route.get("id_terminal_origin", 0)
            sell_terminal_id = route.get("id_terminal_destination", 0)
            fingerprint = (commodity_id, buy_terminal_id, sell_terminal_id)

            if fingerprint in existing_fingerprints:
                continue

            buy_price = route.get("price_origin", 0) or 0
            sell_price = route.get("price_destination", 0) or 0
            margin = sell_price - buy_price

            if margin < min_margin:
                continue

            available_scu = min(
                route.get("scu_origin", 0) or 0,
                route.get("scu_destination", 0) or 0,
            )

            opp = Opportunity(
                id=str(uuid.uuid4()),
                created_at=now,
                status="available",
                commodity_name=route.get("commodity_name", "Unknown"),
                commodity_id=commodity_id,
                commodity_code=route.get("commodity_code", ""),
                buy_terminal=route.get("origin_terminal_name", ""),
                buy_terminal_id=buy_terminal_id,
                buy_location=route.get("origin_planet_name", "")
                or route.get("origin_star_system_name", ""),
                buy_price=buy_price,
                sell_terminal=route.get("destination_terminal_name", ""),
                sell_terminal_id=sell_terminal_id,
                sell_location=route.get("destination_planet_name", "")
                or route.get("destination_star_system_name", ""),
                sell_price=sell_price,
                margin_per_scu=margin,
                available_scu=available_scu,
                estimated_profit=round(margin * available_scu, 2),
                score=route.get("score", 0) or 0,
                route_id=route.get("id"),
            )

            new_opps.append(opp)
            existing_fingerprints.add(fingerprint)

            if not has_filter and len(new_opps) >= top_n:
                break

        if new_opps:
            self._store.bulk_save_opportunities(new_opps)
            logger.info("Generated %d new trade opportunities", len(new_opps))

        return len(new_opps)

    # ------------------------------------------------------------------
    # Background: Opportunity Expiry
    # ------------------------------------------------------------------

    def expire_stale_opportunities(
        self,
        price_change_threshold: float = 0.15,
    ) -> int:
        """Expire opportunities where market conditions have changed.

        Args:
            price_change_threshold: Fraction of margin change to trigger expiry.

        Returns:
            Count of opportunities expired.
        """
        available = self._store.query_opportunities(status="available", limit=500)
        if not available:
            return 0

        now = datetime.now(timezone.utc).isoformat()
        expired_count = 0

        for opp in available:
            reason = self._check_expiry(opp, price_change_threshold)
            if reason:
                opp.status = "expired"
                opp.expired_at = now
                opp.expiry_reason = reason
                self._store.save_opportunity(opp)
                expired_count += 1

        if expired_count > 0:
            logger.info("Expired %d stale opportunities", expired_count)

        return expired_count

    def _check_expiry(
        self,
        opp: Opportunity,
        threshold: float,
    ) -> str:
        """Check if an opportunity should expire based on current market data.

        Returns:
            Expiry reason string, or empty string if still valid.
        """
        if not self._market or not hasattr(self._market, "_conn"):
            return ""

        conn = self._market._conn
        if not conn:
            return ""

        # Look up current route by terminal pair
        row = conn.execute(
            """SELECT price_origin, price_destination, profit
            FROM commodity_route
            WHERE id_commodity = ?
              AND id_terminal_origin = ?
              AND id_terminal_destination = ?
            LIMIT 1""",
            (opp.commodity_id, opp.buy_terminal_id, opp.sell_terminal_id),
        ).fetchone()

        if not row:
            return "Route no longer available in market data"

        current_margin = (row["price_destination"] or 0) - (row["price_origin"] or 0)
        original_margin = opp.margin_per_scu

        if current_margin <= 0:
            return "Route no longer profitable"

        if original_margin > 0:
            pct_change = abs(current_margin - original_margin) / original_margin
            if pct_change > threshold:
                return (
                    f"Margin changed {pct_change * 100:.0f}% "
                    f"(was {original_margin:.2f}, now {current_margin:.2f})"
                )

        return ""

    # ------------------------------------------------------------------
    # Tool: List Opportunities
    # ------------------------------------------------------------------

    def list_opportunities(
        self,
        status: str = "available",
        commodity: str = "",
        limit: int = 10,
    ) -> list[dict]:
        """List trade opportunities with optional filters.

        Args:
            status: Filter by status, or "all" for all statuses.
            commodity: Filter by commodity name (partial match).
            limit: Maximum results.

        Returns:
            List of opportunity dicts formatted for tool response.
        """
        query_status = None if status == "all" else status
        query_commodity = commodity if commodity else None

        opps = self._store.query_opportunities(
            status=query_status,
            commodity_name=query_commodity,
            limit=limit,
        )

        return [self._format_opportunity(opp) for opp in opps]

    # ------------------------------------------------------------------
    # Tool: Accept Opportunity
    # ------------------------------------------------------------------

    def accept_opportunity(
        self,
        opp_id: str,
        create_trade_order: bool = True,
    ) -> dict:
        """Accept a trade opportunity.

        Args:
            opp_id: Full or partial opportunity ID.
            create_trade_order: Whether to create a linked TradeOrder.

        Returns:
            Dict with acceptance details.
        """
        opp = self._find_by_id(opp_id)
        if not opp:
            return {"error": f"Opportunity not found: {opp_id}"}

        if opp.status != "available":
            return {"error": f"Opportunity is {opp.status}, not available"}

        now = datetime.now(timezone.utc).isoformat()
        opp.status = "accepted"

        if create_trade_order:
            order = TradeOrder(
                id=str(uuid.uuid4()),
                created_at=now,
                status="open",
                order_type="buy",
                item_name=opp.commodity_name,
                quantity=opp.available_scu,
                quantity_unit="scu",
                target_price=opp.buy_price,
                target_location=opp.buy_terminal,
                notes=f"From opportunity {opp.id[:8]}",
            )
            self._store.save_trade_order(order)
            opp.trade_order_id = order.id

        self._store.save_opportunity(opp)

        result = {
            "status": "accepted",
            "opportunity_id": opp.id[:8],
            "commodity": opp.commodity_name,
            "buy_at": opp.buy_terminal,
            "buy_price": opp.buy_price,
            "sell_at": opp.sell_terminal,
            "sell_price": opp.sell_price,
            "estimated_profit": opp.estimated_profit,
        }
        if opp.trade_order_id:
            result["trade_order_id"] = opp.trade_order_id[:8]

        return result

    # ------------------------------------------------------------------
    # Tool: Dismiss Opportunity
    # ------------------------------------------------------------------

    def dismiss_opportunity(self, opp_id: str, reason: str = "") -> dict:
        """Dismiss a trade opportunity.

        Args:
            opp_id: Full or partial opportunity ID.
            reason: Reason for dismissal.

        Returns:
            Confirmation dict.
        """
        opp = self._find_by_id(opp_id)
        if not opp:
            return {"error": f"Opportunity not found: {opp_id}"}

        if opp.status != "available":
            return {"error": f"Opportunity is {opp.status}, not available"}

        opp.status = "dismissed"
        opp.dismissed_at = datetime.now(timezone.utc).isoformat()
        opp.notes = reason
        self._store.save_opportunity(opp)

        return {
            "status": "dismissed",
            "opportunity_id": opp.id[:8],
            "commodity": opp.commodity_name,
            "reason": reason or "No reason given",
        }

    # ------------------------------------------------------------------
    # Sync Hook: Check Fulfillment
    # ------------------------------------------------------------------

    def check_fulfillment(self, txn: Transaction) -> Opportunity | None:
        """Check if a captured trade fulfills an accepted opportunity.

        Called from _sync_from_logreader after each new commodity trade.

        Args:
            txn: The newly captured transaction.

        Returns:
            The fulfilled Opportunity, or None.
        """
        if txn.category not in ("commodity_purchase", "commodity_sale"):
            return None

        accepted = self._store.query_opportunities(status="accepted", limit=100)
        if not accepted:
            return None

        txn_name = (txn.item_name or "").lower()
        txn_location = (txn.location or txn.shop_name or "").lower()

        for opp in accepted:
            # Name match (primary signal)
            opp_name = opp.commodity_name.lower()
            if not (
                txn_name == opp_name or txn_name in opp_name or opp_name in txn_name
            ):
                continue

            # Location match (best-effort, not required)
            location_matched = False
            if txn_location:
                buy_terms = [
                    opp.buy_terminal.lower(),
                    opp.buy_location.lower(),
                ]
                sell_terms = [
                    opp.sell_terminal.lower(),
                    opp.sell_location.lower(),
                ]

                if txn.category == "commodity_purchase":
                    location_matched = any(
                        term and term in txn_location for term in buy_terms
                    ) or any(term and txn_location in term for term in buy_terms)
                else:
                    location_matched = any(
                        term and term in txn_location for term in sell_terms
                    ) or any(term and txn_location in term for term in sell_terms)

            # Name match alone is enough; location is bonus confirmation
            now = datetime.now(timezone.utc).isoformat()
            opp.status = "fulfilled"
            opp.fulfilled_at = now
            opp.fulfilled_transaction_id = txn.id
            if location_matched:
                opp.notes = (
                    opp.notes + f" Fulfilled at {txn.location or txn.shop_name}"
                ).strip()
            self._store.save_opportunity(opp)

            logger.info(
                "Opportunity %s fulfilled by transaction %s (%s)",
                opp.id[:8],
                txn.id[:8],
                opp.commodity_name,
            )
            return opp

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_by_id(self, opp_id: str) -> Opportunity | None:
        """Find an opportunity by full or partial ID."""
        # Try exact match first
        opp = self._store.get_opportunity(opp_id)
        if opp:
            return opp

        # Partial match (first N chars)
        for opp in self._store.query_opportunities(limit=500):
            if opp.id.startswith(opp_id):
                return opp

        return None

    def _format_opportunity(self, opp: Opportunity) -> dict:
        """Format an opportunity for tool response."""
        result = {
            "id": opp.id[:8],
            "status": opp.status,
            "commodity": opp.commodity_name,
            "commodity_code": opp.commodity_code,
            "buy_terminal": opp.buy_terminal,
            "buy_location": opp.buy_location,
            "buy_price_per_scu": opp.buy_price,
            "sell_terminal": opp.sell_terminal,
            "sell_location": opp.sell_location,
            "sell_price_per_scu": opp.sell_price,
            "margin_per_scu": opp.margin_per_scu,
            "available_scu": opp.available_scu,
            "estimated_profit": opp.estimated_profit,
            "score": opp.score,
            "created_at": opp.created_at,
        }

        if opp.trade_order_id:
            result["trade_order_id"] = opp.trade_order_id[:8]
        if opp.fulfilled_at:
            result["fulfilled_at"] = opp.fulfilled_at
        if opp.expired_at:
            result["expired_at"] = opp.expired_at
            result["expiry_reason"] = opp.expiry_reason
        if opp.dismissed_at:
            result["dismissed_at"] = opp.dismissed_at
        if opp.notes:
            result["notes"] = opp.notes

        return result
