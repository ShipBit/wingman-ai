"""
SC_Accountant — Haul Manager

Tracks cargo transport trips between locations with cost/revenue
accounting and route profitability analysis.

Author: Mallachi
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from models import Haul
from store import AccountantStore

logger = logging.getLogger(__name__)


class HaulManager:
    """Tracks cargo transport trips with cost and revenue accounting."""

    def __init__(self, store: AccountantStore) -> None:
        """Initialize with shared store.

        Args:
            store: AccountantStore for persistence.
        """
        self._store = store

    # ------------------------------------------------------------------
    # Tool: Log Haul
    # ------------------------------------------------------------------

    def log_haul(
        self,
        origin: str,
        destination: str,
        cargo_description: str,
        quantity: float = 0.0,
        quantity_unit: str = "scu",
        ship_name: str = "",
        fuel_cost: float = 0.0,
        other_costs: float = 0.0,
        revenue: float = 0.0,
        status: str = "delivered",
        notes: str = "",
    ) -> dict:
        """Log a cargo transport trip.

        Args:
            origin: Starting location.
            destination: Delivery location.
            cargo_description: What was hauled.
            quantity: Amount of cargo.
            quantity_unit: Unit of measurement (default 'scu').
            ship_name: Ship used for transport.
            fuel_cost: Fuel expenses for this haul.
            other_costs: Other expenses (landing fees, repairs, etc.).
            revenue: Payment received for hauling.
            status: Haul status — in_transit, delivered, or cancelled.
            notes: Additional notes.

        Returns:
            Confirmation dict with haul details.
        """
        if status not in ("in_transit", "delivered", "cancelled"):
            return {
                "error": f"Invalid status: {status}. "
                "Use 'in_transit', 'delivered', or 'cancelled'."
            }

        now = datetime.now(timezone.utc).isoformat()

        haul = Haul(
            id=str(uuid.uuid4()),
            started_at=now,
            status=status,
            origin=origin,
            destination=destination,
            cargo_description=cargo_description,
            quantity=quantity,
            quantity_unit=quantity_unit,
            ship_name=ship_name,
            fuel_cost=fuel_cost,
            other_costs=other_costs,
            revenue=revenue,
            completed_at=now if status == "delivered" else None,
            notes=notes,
        )

        self._store.save_haul(haul)

        net_profit = revenue - fuel_cost - other_costs
        logger.info(
            "Logged haul %s: %s → %s (%s, net: %.0f aUEC)",
            haul.id[:8],
            origin,
            destination,
            cargo_description,
            net_profit,
        )

        return {
            "status": "logged",
            "haul_id": haul.id[:8],
            "origin": origin,
            "destination": destination,
            "cargo": cargo_description,
            "quantity": quantity,
            "quantity_unit": quantity_unit,
            "revenue": round(revenue, 2),
            "total_costs": round(fuel_cost + other_costs, 2),
            "net_profit": round(net_profit, 2),
        }

    # ------------------------------------------------------------------
    # Tool: Complete Haul
    # ------------------------------------------------------------------

    def complete_haul(
        self,
        haul_id: str,
        revenue: float = 0.0,
        fuel_cost: float = 0.0,
        other_costs: float = 0.0,
        notes: str = "",
    ) -> dict:
        """Mark an in-transit haul as delivered and record final costs.

        Args:
            haul_id: Full or partial haul ID.
            revenue: Payment received (adds to existing).
            fuel_cost: Final fuel cost (adds to existing).
            other_costs: Final other costs (adds to existing).
            notes: Completion notes.

        Returns:
            Confirmation dict with final haul details.
        """
        haul = self._find_by_id(haul_id)
        if not haul:
            return {"error": f"Haul not found: {haul_id}"}

        if haul.status != "in_transit":
            return {"error": f"Haul is {haul.status}, not in_transit."}

        now = datetime.now(timezone.utc).isoformat()

        haul.status = "delivered"
        haul.completed_at = now
        haul.revenue += revenue
        haul.fuel_cost += fuel_cost
        haul.other_costs += other_costs
        if notes:
            haul.notes = (haul.notes + f" {notes}").strip()

        self._store.save_haul(haul)

        net_profit = haul.revenue - haul.fuel_cost - haul.other_costs
        logger.info(
            "Completed haul %s: %s → %s (net: %.0f aUEC)",
            haul.id[:8],
            haul.origin,
            haul.destination,
            net_profit,
        )

        return {
            "status": "delivered",
            "haul_id": haul.id[:8],
            "origin": haul.origin,
            "destination": haul.destination,
            "cargo": haul.cargo_description,
            "revenue": round(haul.revenue, 2),
            "total_costs": round(haul.fuel_cost + haul.other_costs, 2),
            "net_profit": round(net_profit, 2),
        }

    # ------------------------------------------------------------------
    # Tool: List Hauls
    # ------------------------------------------------------------------

    def list_hauls(
        self,
        status: str = "",
        limit: int = 20,
    ) -> list[dict]:
        """List hauls with optional status filter.

        Args:
            status: Filter — in_transit, delivered, cancelled, or empty for all.
            limit: Maximum results.

        Returns:
            List of haul dicts formatted for tool response.
        """
        query_status = status if status else None
        hauls = self._store.query_hauls(status=query_status, limit=limit)
        return [self._format_haul(h) for h in hauls]

    # ------------------------------------------------------------------
    # Tool: Hauling Summary
    # ------------------------------------------------------------------

    def get_hauling_summary(self, days_back: int = 30) -> dict:
        """Get aggregated hauling statistics.

        Args:
            days_back: Number of days to look back (default 30).

        Returns:
            Dict with total_hauls, total_revenue, total_fuel_cost,
            total_other_costs, net_hauling_profit, and top_routes.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()

        all_hauls = self._store.query_hauls(limit=500)
        # Filter to delivered hauls within the time window
        delivered = [
            h for h in all_hauls if h.status == "delivered" and h.started_at >= cutoff
        ]

        total_revenue = sum(h.revenue for h in delivered)
        total_fuel = sum(h.fuel_cost for h in delivered)
        total_other = sum(h.other_costs for h in delivered)
        net_profit = total_revenue - total_fuel - total_other

        # Aggregate by route
        route_stats: dict[str, dict] = {}
        for haul in delivered:
            route_key = f"{haul.origin} → {haul.destination}"
            if route_key not in route_stats:
                route_stats[route_key] = {
                    "revenue": 0.0,
                    "costs": 0.0,
                    "count": 0,
                    "total_cargo": 0.0,
                }
            stats = route_stats[route_key]
            stats["revenue"] += haul.revenue
            stats["costs"] += haul.fuel_cost + haul.other_costs
            stats["count"] += 1
            stats["total_cargo"] += haul.quantity

        # Sort routes by net profit
        top_routes = []
        for route, stats in sorted(
            route_stats.items(),
            key=lambda x: x[1]["revenue"] - x[1]["costs"],
            reverse=True,
        ):
            route_profit = stats["revenue"] - stats["costs"]
            top_routes.append(
                {
                    "route": route,
                    "haul_count": stats["count"],
                    "total_cargo": round(stats["total_cargo"], 1),
                    "revenue": round(stats["revenue"], 2),
                    "costs": round(stats["costs"], 2),
                    "net_profit": round(route_profit, 2),
                }
            )

        # Count active hauls
        active_hauls = [h for h in all_hauls if h.status == "in_transit"]

        return {
            "period_days": days_back,
            "total_hauls": len(delivered),
            "active_hauls": len(active_hauls),
            "total_revenue": round(total_revenue, 2),
            "total_fuel_cost": round(total_fuel, 2),
            "total_other_costs": round(total_other, 2),
            "net_hauling_profit": round(net_profit, 2),
            "top_routes": top_routes[:10],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_by_id(self, haul_id: str) -> Haul | None:
        """Find a haul by full or partial ID."""
        haul = self._store.get_haul(haul_id)
        if haul:
            return haul

        for haul in self._store.query_hauls(limit=500):
            if haul.id.startswith(haul_id):
                return haul

        return None

    def _format_haul(self, haul: Haul) -> dict:
        """Format a haul for tool response."""
        net_profit = haul.revenue - haul.fuel_cost - haul.other_costs

        result = {
            "id": haul.id[:8],
            "status": haul.status,
            "origin": haul.origin,
            "destination": haul.destination,
            "cargo": haul.cargo_description,
            "quantity": haul.quantity,
            "quantity_unit": haul.quantity_unit,
            "started_at": haul.started_at,
        }

        if haul.ship_name:
            result["ship"] = haul.ship_name

        if haul.status == "delivered":
            result["revenue"] = round(haul.revenue, 2)
            result["fuel_cost"] = round(haul.fuel_cost, 2)
            result["other_costs"] = round(haul.other_costs, 2)
            result["net_profit"] = round(net_profit, 2)
            if haul.completed_at:
                result["completed_at"] = haul.completed_at

        if haul.notes:
            result["notes"] = haul.notes

        return result
