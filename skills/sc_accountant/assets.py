"""
SC_Accountant — Asset Manager

Manages the fleet/equipment registry. Tracks ships, vehicles, components,
and equipment as capital assets with purchase price and market value.

Registering an asset creates a CAPEX transaction. Selling an asset records
realized P&L. Components can be linked to a parent ship for hierarchical
tracking.

Author: Mallachi
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Callable

from models import (
    CATEGORY_COMPONENT_PURCHASE,
    CATEGORY_ITEM_SALE,
    CATEGORY_SHIP_PURCHASE,
    Asset,
    Transaction,
)
from store import AccountantStore

logger = logging.getLogger(__name__)

_VALID_ASSET_TYPES = {"ship", "vehicle", "component", "equipment", "blueprint"}


class AssetManager:
    """Manages capital asset registration and lifecycle."""

    def __init__(
        self,
        store: AccountantStore,
        format_fn: Callable[[float], str],
    ) -> None:
        self._store = store
        self._format = format_fn

    def register_asset(
        self,
        asset_type: str,
        name: str,
        purchase_price: float,
        ship_model: str = "",
        location: str = "",
        parent_asset_id: str = "",
        notes: str = "",
        create_transaction: bool = True,
    ) -> tuple[Asset, Transaction | None]:
        """Register a new capital asset.

        Args:
            asset_type: One of "ship", "vehicle", "component", "equipment".
            name: Asset name (e.g. "Prospector", "Lancet MH1").
            purchase_price: Purchase cost in aUEC.
            ship_model: Ship model/manufacturer info.
            location: Where the asset is stored.
            parent_asset_id: For components, the parent ship's asset ID.
            notes: Optional notes.
            create_transaction: Whether to create a CAPEX transaction.

        Returns:
            Tuple of (Asset, optional Transaction).
        """
        now = datetime.now(tz=timezone.utc).isoformat()
        asset_id = str(uuid.uuid4())[:8]

        asset = Asset(
            id=asset_id,
            created_at=now,
            asset_type=asset_type,
            name=name,
            status="active",
            purchase_price=purchase_price,
            purchase_date=now,
            estimated_market_value=purchase_price,
            location=location,
            ship_model=ship_model,
            parent_asset_id=parent_asset_id or None,
            notes=notes,
        )

        txn = None
        if create_transaction and purchase_price > 0:
            category = (
                CATEGORY_SHIP_PURCHASE
                if asset_type in ("ship", "vehicle")
                else CATEGORY_COMPONENT_PURCHASE
            )
            txn = Transaction(
                id=str(uuid.uuid4())[:8],
                timestamp=now,
                category=category,
                transaction_type="expense",
                amount=purchase_price,
                description=f"Purchased {asset_type}: {name}",
                location=location,
                tags=["asset", asset_type],
                source="manual",
                linked_asset_id=asset_id,
                activity="general",
            )
            asset.purchase_transaction_id = txn.id
            self._store.append_transaction(txn)

        self._store.save_asset(asset)
        return asset, txn

    def sell_asset(
        self,
        asset_id: str,
        sell_price: float,
        location: str = "",
    ) -> tuple[Asset | None, Transaction | None, str]:
        """Record the sale of an asset with realized P&L.

        Args:
            asset_id: ID of the asset to sell.
            sell_price: Sale price in aUEC.
            location: Where the sale happened.

        Returns:
            Tuple of (updated Asset, sale Transaction, status message).
        """
        asset = self._store.get_asset(asset_id)
        if not asset:
            return None, None, f"Asset {asset_id} not found"
        if asset.status != "active":
            return asset, None, f"Asset {asset.name} is already {asset.status}"

        now = datetime.now(tz=timezone.utc).isoformat()
        asset.status = "sold"
        asset.sold_at = now
        asset.sold_price = sell_price

        realized_pnl = sell_price - asset.purchase_price
        pnl_label = "profit" if realized_pnl >= 0 else "loss"

        txn = Transaction(
            id=str(uuid.uuid4())[:8],
            timestamp=now,
            category=CATEGORY_ITEM_SALE,
            transaction_type="income",
            amount=sell_price,
            description=(
                f"Sold {asset.asset_type}: {asset.name} "
                f"({pnl_label}: {self._format(abs(realized_pnl))})"
            ),
            location=location,
            tags=["asset_sale", asset.asset_type],
            source="manual",
            linked_asset_id=asset_id,
            activity="general",
        )

        self._store.append_transaction(txn)
        self._store.save_asset(asset)

        msg = (
            f"Sold {asset.name} for {self._format(sell_price)}. "
            f"Realized {pnl_label}: {self._format(abs(realized_pnl))}"
        )
        return asset, txn, msg

    def update_asset(
        self,
        asset_id: str,
        name: str | None = None,
        asset_type: str | None = None,
        ship_model: str | None = None,
        location: str | None = None,
        purchase_price: float | None = None,
        estimated_market_value: float | None = None,
        notes: str | None = None,
    ) -> tuple[Asset | None, list[str]]:
        """Update fields on an existing asset.

        Only fields that are explicitly provided (not None) are modified.

        Args:
            asset_id: ID of the asset to update.
            name: New display name.
            asset_type: New type (ship/vehicle/component/equipment).
            ship_model: New ship model/manufacturer info.
            location: New storage location.
            purchase_price: New purchase price (also updates CAPEX transaction).
            estimated_market_value: New estimated market value.
            notes: New notes.

        Returns:
            Tuple of (updated Asset or None, list of changes made).
        """
        asset = self._store.get_asset(asset_id)
        if not asset:
            return None, []

        changes: list[str] = []

        if name is not None and name != asset.name:
            asset.name = name
            changes.append(f"name → {name}")

        if asset_type is not None:
            normalized = asset_type.lower().strip()
            if normalized in _VALID_ASSET_TYPES and normalized != asset.asset_type:
                asset.asset_type = normalized
                changes.append(f"type → {normalized}")

        if ship_model is not None and ship_model != asset.ship_model:
            asset.ship_model = ship_model
            changes.append(f"ship_model → {ship_model}")

        if location is not None and location != asset.location:
            asset.location = location
            changes.append(f"location → {location}")

        if purchase_price is not None and purchase_price != asset.purchase_price:
            old_price = asset.purchase_price
            asset.purchase_price = purchase_price
            # If market value was tracking purchase price, update it too
            if asset.estimated_market_value == old_price:
                asset.estimated_market_value = purchase_price
            changes.append(
                f"purchase_price → {self._format(purchase_price)} "
                f"(was {self._format(old_price)})"
            )

        if (
            estimated_market_value is not None
            and estimated_market_value != asset.estimated_market_value
        ):
            asset.estimated_market_value = estimated_market_value
            changes.append(f"market_value → {self._format(estimated_market_value)}")

        if notes is not None and notes != asset.notes:
            asset.notes = notes
            changes.append(f"notes → {notes}")

        if changes:
            self._store.save_asset(asset)

        return asset, changes

    def list_assets(
        self,
        asset_type: str = "",
        status: str = "active",
        limit: int = 50,
    ) -> list[Asset]:
        """List assets with optional filters."""
        return self._store.query_assets(
            asset_type=asset_type or None,
            status=status or None,
            limit=limit,
        )

    def get_fleet_summary(self) -> dict:
        """Get an aggregated fleet composition and value summary.

        Returns:
            Dict with total_count, total_value, by_type breakdown,
            and top assets by value.
        """
        active = self._store.query_assets(status="active", limit=500)

        by_type: dict[str, dict] = {}
        for asset in active:
            if asset.asset_type not in by_type:
                by_type[asset.asset_type] = {"count": 0, "value": 0.0}
            entry = by_type[asset.asset_type]
            entry["count"] += 1
            entry["value"] += asset.estimated_market_value or asset.purchase_price

        total_value = sum(e["value"] for e in by_type.values())
        total_count = sum(e["count"] for e in by_type.values())

        # Top 5 assets by value
        sorted_assets = sorted(
            active,
            key=lambda a: a.estimated_market_value or a.purchase_price,
            reverse=True,
        )
        top_assets = [
            {
                "id": a.id,
                "name": a.name,
                "type": a.asset_type,
                "value": round(a.estimated_market_value or a.purchase_price, 2),
            }
            for a in sorted_assets[:5]
        ]

        return {
            "total_count": total_count,
            "total_value": round(total_value, 2),
            "by_type": {
                t: {"count": d["count"], "value": round(d["value"], 2)}
                for t, d in sorted(
                    by_type.items(), key=lambda x: x[1]["value"], reverse=True
                )
            },
            "top_assets": top_assets,
        }

    def update_ship_market_values(self, market: object) -> int:
        """Update estimated_market_value for ship/vehicle assets using UEX prices.

        Looks up the average in-game purchase price across all dealers and
        stores it as the estimated market value. Called after each market refresh.

        Args:
            market: MarketData instance with get_vehicle_price().

        Returns:
            Count of assets updated.
        """
        if not market or not hasattr(market, "get_vehicle_price"):
            return 0

        assets = self._store.query_assets(status="active", limit=500)
        updated = 0
        for asset in assets:
            if asset.asset_type not in ("ship", "vehicle"):
                continue
            price = market.get_vehicle_price(asset.name)
            if price and price > 0:
                asset.estimated_market_value = round(price, 2)
                self._store.save_asset(asset)
                updated += 1
                logger.info(
                    "Market value updated: %s → %.0f aUEC", asset.name, price
                )

        if updated > 0:
            logger.info("Updated market values for %d fleet assets", updated)
        return updated

    def format_asset(self, asset: Asset) -> str:
        """Format a single asset for display."""
        value = asset.estimated_market_value or asset.purchase_price
        parts = [
            f"{asset.name} ({asset.asset_type})",
            f"  Status: {asset.status}",
            f"  Value: {self._format(value)}",
            f"  Purchase: {self._format(asset.purchase_price)}",
        ]
        if asset.location:
            parts.append(f"  Location: {asset.location}")
        if asset.parent_asset_id:
            parts.append(f"  Mounted on: {asset.parent_asset_id}")
        if asset.notes:
            parts.append(f"  Notes: {asset.notes}")
        return "\n".join(parts)
