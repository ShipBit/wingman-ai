"""
SC_Accountant — Accounting Dashboard API Server

FastAPI server that exposes REST endpoints for the standalone accounting
dashboard. Supports both read-only data display and manual data entry
via POST endpoints.

Author: Mallachi
"""

from __future__ import annotations

import json
import logging
import socket
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse

if TYPE_CHECKING:
    from collections.abc import Callable

    from assets import AssetManager
    from futures import FuturesManager
    from market_data import MarketData
    from positions import PositionManager
    from store import AccountantStore

logger = logging.getLogger(__name__)

_PERIOD_DAYS = {
    "today": 1,
    "week": 7,
    "month": 30,
    "quarter": 90,
    "year": 365,
    "all": 0,
}

_STATIC_DIR = Path(__file__).parent / "static"


def _reformat_terminal(name: str) -> str:
    """Reformat 'Admin - Lorville' to 'Lorville - Admin'."""
    if " - " in name:
        parts = name.split(" - ", 1)
        return f"{parts[1]} - {parts[0]}"
    return name


class AccountantServer:
    """FastAPI server for the accounting dashboard."""

    def __init__(
        self,
        store: "AccountantStore",
        format_fn: callable,
        port: int = 7863,
    ) -> None:
        self._store = store
        self._format = format_fn
        self._port = port
        self._thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None
        self._data_version: int = 0
        self._app = self._create_app()

        # Domain managers (injected after construction)
        self._positions: PositionManager | None = None
        self._futures: FuturesManager | None = None
        self._assets: AssetManager | None = None
        self._market: MarketData | None = None
        self._get_player_location: Callable[[], dict | None] | None = None

    def set_managers(
        self,
        positions: "PositionManager | None" = None,
        futures: "FuturesManager | None" = None,
        assets: "AssetManager | None" = None,
        market: "MarketData | None" = None,
        get_player_location: "Callable[[], dict | None] | None" = None,
    ) -> None:
        """Inject domain managers for data access."""
        self._positions = positions
        self._futures = futures
        self._assets = assets
        self._market = market
        self._get_player_location = get_player_location

    def _create_app(self) -> FastAPI:
        """Build the FastAPI application with all routes."""
        app = FastAPI(title="SC Accountant", docs_url=None, redoc_url=None)

        # Bump data version after any mutating request so all browsers refresh
        @app.middleware("http")
        async def bump_version_on_mutation(request: Request, call_next):
            response = await call_next(request)
            if request.method in ("POST", "PUT", "DELETE"):
                self._data_version += 1
            return response

        # --- API Endpoints ---

        @app.get("/api/balance")
        def get_balance() -> JSONResponse:
            balance = self._store.get_balance()
            return JSONResponse(
                {
                    "current_balance": balance.current_balance,
                    "formatted": self._format(balance.current_balance),
                    "lifetime_income": balance.total_lifetime_income,
                    "lifetime_expenses": balance.total_lifetime_expenses,
                    "last_updated": balance.last_updated or "",
                }
            )

        @app.get("/api/network")
        def get_network() -> JSONResponse:
            lan_ip = _get_lan_ip()
            lan_url = f"http://{lan_ip}:{self._port}"
            return JSONResponse(
                {
                    "lan_ip": lan_ip,
                    "lan_url": lan_url,
                    "qr_svg": _generate_qr_svg(lan_url),
                }
            )

        @app.get("/api/transactions")
        def get_transactions(
            page: int = Query(0, ge=0),
            page_size: int = Query(20, ge=1, le=100),
            period: str = Query("month"),
            activity: str = Query(""),
            sort: str = Query("date"),
            ascending: bool = Query(False),
        ) -> JSONResponse:
            days = _PERIOD_DAYS.get(period, 30)
            start = None
            if days > 0:
                start = datetime.now(tz=timezone.utc) - timedelta(days=days)

            txns = self._store.query_transactions(start=start, limit=500)

            # Activity filter
            if activity:
                from models import CATEGORY_ACTIVITY

                txns = [
                    t
                    for t in txns
                    if (
                        t.activity == activity
                        or CATEGORY_ACTIVITY.get(t.category, "").value == activity
                    )
                ]

            # Sort
            sort_keys = {
                "date": lambda t: t.timestamp,
                "amount": lambda t: t.amount,
                "category": lambda t: t.category,
                "type": lambda t: t.transaction_type,
            }
            key_fn = sort_keys.get(sort, sort_keys["date"])
            txns.sort(key=key_fn, reverse=not ascending)

            total = len(txns)
            offset = page * page_size
            page_txns = txns[offset : offset + page_size]

            return JSONResponse(
                {
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": max(1, (total + page_size - 1) // page_size),
                    "transactions": [
                        {
                            "id": t.id,
                            "timestamp": t.timestamp,
                            "date": t.timestamp[:10]
                            if len(t.timestamp) >= 10
                            else t.timestamp,
                            "type": t.transaction_type,
                            "category": t.category,
                            "amount": t.amount,
                            "formatted_amount": self._format(t.amount),
                            "description": t.description,
                            "location": t.location or "",
                            "notes": t.notes or "",
                            "tags": t.tags or [],
                            "activity": t.activity or "",
                            "linked_asset_id": t.linked_asset_id or "",
                        }
                        for t in page_txns
                    ],
                }
            )

        @app.get("/api/income-statement")
        def get_income_statement(
            period: str = Query("month"),
        ) -> JSONResponse:
            from statements import generate_income_statement

            days = _PERIOD_DAYS.get(period, 30)
            start = None
            if days > 0:
                start = datetime.now(tz=timezone.utc) - timedelta(days=days)
            txns = self._store.query_transactions(start=start, limit=500)
            stmt = generate_income_statement(txns, period)
            return JSONResponse(stmt)

        @app.get("/api/balance-sheet")
        def get_balance_sheet() -> JSONResponse:
            from statements import generate_balance_sheet

            balance = self._store.get_balance()
            assets = self._store.query_assets(status="active", limit=500)
            positions = self._store.query_positions(status="open", limit=500)

            bs = generate_balance_sheet(
                balance=balance,
                assets=assets,
                open_positions=positions,
            )
            return JSONResponse(bs)

        @app.get("/api/cash-flow")
        def get_cash_flow(
            period: str = Query("month"),
        ) -> JSONResponse:
            from statements import generate_cash_flow

            days = _PERIOD_DAYS.get(period, 30)
            start = None
            if days > 0:
                start = datetime.now(tz=timezone.utc) - timedelta(days=days)
            txns = self._store.query_transactions(start=start, limit=500)
            cf = generate_cash_flow(txns, period)
            return JSONResponse(cf)

        @app.get("/api/fleet")
        def get_fleet(
            status: str = Query("active"),
            asset_type: str = Query(""),
        ) -> JSONResponse:
            assets = self._store.query_assets(
                status=status or None,
                asset_type=asset_type or None,
                limit=200,
            )
            return JSONResponse(
                {
                    "total": len(assets),
                    "assets": [
                        {
                            "id": a.id,
                            "name": a.name,
                            "asset_type": a.asset_type,
                            "status": a.status,
                            "purchase_price": a.purchase_price,
                            "formatted_purchase_price": self._format(a.purchase_price),
                            "estimated_market_value": a.estimated_market_value
                            or a.purchase_price,
                            "formatted_market_value": self._format(
                                a.estimated_market_value or a.purchase_price
                            ),
                            "location": a.location or "",
                            "ship_model": a.ship_model or "",
                            "notes": a.notes or "",
                            "purchase_date": a.purchase_date or "",
                        }
                        for a in assets
                    ],
                }
            )

        @app.get("/api/fleet/summary")
        def get_fleet_summary() -> JSONResponse:
            if self._assets:
                return JSONResponse(self._assets.get_fleet_summary())
            return JSONResponse(
                {"total_count": 0, "total_value": 0, "by_type": {}, "top_assets": []}
            )

        @app.get("/api/positions")
        def get_positions() -> JSONResponse:
            positions = self._store.query_positions(status="open", limit=200)
            return JSONResponse(
                {
                    "total": len(positions),
                    "positions": [
                        {
                            "id": p.id,
                            "commodity_name": p.commodity_name,
                            "quantity": p.quantity,
                            "quantity_unit": p.quantity_unit or "scu",
                            "buy_price_per_unit": p.buy_price_per_unit,
                            "buy_total": p.buy_total,
                            "current_market_price": p.current_market_price,
                            "market_value": p.current_market_price * p.quantity,
                            "unrealized_pnl": p.unrealized_pnl,
                            "formatted_invested": self._format(p.buy_total),
                            "formatted_market": self._format(
                                p.current_market_price * p.quantity
                            ),
                            "formatted_pnl": self._format(p.unrealized_pnl),
                            "notes": p.notes,
                        }
                        for p in positions
                    ],
                }
            )

        @app.get("/api/opportunities")
        def get_opportunities(
            system: str = Query(""),
            location: str = Query(""),
            cargo_scu: float = Query(0, ge=0),
        ) -> JSONResponse:
            opps = self._store.query_opportunities(status="available", limit=200)

            # Star system filter — resolve system name to its planet set
            if system:
                system_planets: set[str] = set()
                if self._market:
                    for entry in self._market.get_terminal_locations():
                        if entry["star_system"].lower() == system.lower():
                            system_planets.add(entry["planet"].lower())
                # Also match the system name itself (fallback in location)
                system_planets.add(system.lower())
                opps = [
                    o
                    for o in opps
                    if (o.buy_location or "").lower() in system_planets
                    or (o.sell_location or "").lower() in system_planets
                ]

            # Location filter — matches terminal name or planet/location
            if location:
                loc_lower = location.lower()
                opps = [
                    o
                    for o in opps
                    if loc_lower in _reformat_terminal(o.buy_terminal or "").lower()
                    or loc_lower in _reformat_terminal(o.sell_terminal or "").lower()
                    or loc_lower in (o.buy_location or "").lower()
                    or loc_lower in (o.sell_location or "").lower()
                ]

            results = []
            for o in opps:
                # Effective SCU is always capped by available supply
                effective_scu = o.available_scu
                if cargo_scu > 0:
                    effective_scu = min(effective_scu, cargo_scu)
                adjusted_profit = o.margin_per_scu * effective_scu

                results.append(
                    {
                        "id": o.id,
                        "commodity_name": o.commodity_name,
                        "buy_terminal": _reformat_terminal(o.buy_terminal),
                        "sell_terminal": _reformat_terminal(o.sell_terminal),
                        "buy_location": o.buy_location or "",
                        "sell_location": o.sell_location or "",
                        "buy_price": o.buy_price,
                        "sell_price": o.sell_price,
                        "margin_per_scu": o.margin_per_scu,
                        "available_scu": o.available_scu,
                        "effective_scu": effective_scu,
                        "estimated_profit": adjusted_profit,
                        "formatted_available": f"{o.available_scu:,.0f} SCU",
                        "formatted_effective": f"{effective_scu:,.0f} SCU",
                        "formatted_margin": self._format(o.margin_per_scu),
                        "formatted_profit": self._format(adjusted_profit),
                        "status": o.status,
                    }
                )

            results.sort(key=lambda r: r["estimated_profit"], reverse=True)

            return JSONResponse(
                {
                    "total": len(results),
                    "opportunities": results,
                }
            )

        @app.post("/api/opportunities/refresh")
        async def refresh_opportunities(request: Request) -> JSONResponse:
            if not self._futures:
                return JSONResponse(
                    {"ok": False, "error": "Futures manager not available."},
                    status_code=500,
                )
            body = await request.json()
            location = body.get("location", "")
            system = body.get("system", "")
            new_count = self._futures.generate_opportunities(
                location=location, star_system=system
            )
            expired = self._futures.expire_stale_opportunities()
            return JSONResponse(
                {
                    "ok": True,
                    "generated": new_count,
                    "expired": expired,
                }
            )

        @app.get("/api/locations")
        def get_locations() -> JSONResponse:
            if not self._market:
                return JSONResponse({"systems": [], "terminals": []})

            raw = self._market.get_terminal_locations()
            # Group by star system
            systems: dict[str, list[str]] = {}
            for entry in raw:
                sys_name = entry["star_system"]
                planet = entry["planet"]
                systems.setdefault(sys_name, []).append(planet)

            terminals = self._market.get_terminals()
            for t in terminals:
                t["name"] = _reformat_terminal(t["name"])
            terminals.sort(key=lambda t: t["name"])

            return JSONResponse(
                {
                    "systems": [
                        {"name": name, "locations": locs}
                        for name, locs in sorted(systems.items())
                    ],
                    "terminals": terminals,
                }
            )

        @app.get("/api/player-location")
        def get_player_location() -> JSONResponse:
            if not self._get_player_location:
                return JSONResponse({"available": False})

            loc = self._get_player_location()
            if not loc:
                return JSONResponse({"available": False})

            return JSONResponse(
                {
                    "available": True,
                    "location_name": loc.get("location_name", ""),
                    "star_system": loc.get("star_system", ""),
                }
            )

        # --- Data Entry Endpoints ---

        @app.get("/api/categories")
        def get_categories() -> JSONResponse:
            """Serve category list for dropdown population."""
            from models import (
                CATEGORY_LABELS,
                INCOME_CATEGORIES,
                ALL_CATEGORIES,
            )

            categories = []
            for cat in sorted(ALL_CATEGORIES):
                categories.append(
                    {
                        "value": cat,
                        "label": CATEGORY_LABELS.get(
                            cat, cat.replace("_", " ").title()
                        ),
                        "type": "income" if cat in INCOME_CATEGORIES else "expense",
                    }
                )
            return JSONResponse(categories)

        @app.post("/api/transactions")
        async def post_transaction(request: Request) -> JSONResponse:
            """Record a transaction from the web dashboard."""
            from models import (
                ALL_CATEGORIES,
                CATEGORY_ACTIVITY,
                INCOME_CATEGORIES,
                Transaction,
            )

            body = await request.json()
            category = (body.get("category") or "").strip()
            amount = body.get("amount")
            description = (body.get("description") or "").strip()
            location = (body.get("location") or "").strip()
            tags_raw = (body.get("tags") or "").strip()

            # Validation
            if not category or category not in ALL_CATEGORIES:
                return JSONResponse(
                    {"error": "Invalid or missing category"}, status_code=400
                )
            try:
                amount = float(amount)
            except (TypeError, ValueError):
                return JSONResponse(
                    {"error": "Amount must be a number"}, status_code=400
                )
            if amount <= 0:
                return JSONResponse(
                    {"error": "Amount must be greater than 0"}, status_code=400
                )
            if not description:
                return JSONResponse(
                    {"error": "Description is required"}, status_code=400
                )

            txn_type = "income" if category in INCOME_CATEGORIES else "expense"
            activity_enum = CATEGORY_ACTIVITY.get(category)
            activity = activity_enum.value if activity_enum else None
            tags = (
                [t.strip() for t in tags_raw.split(",") if t.strip()]
                if tags_raw
                else []
            )

            txn = Transaction(
                id=str(uuid.uuid4())[:8],
                timestamp=datetime.now(tz=timezone.utc).isoformat(),
                category=category,
                transaction_type=txn_type,
                amount=amount,
                description=description,
                location=location,
                tags=tags,
                source="web_dashboard",
                activity=activity,
            )
            self._store.append_transaction(txn)

            # Update balance
            balance = self._store.get_balance()
            if txn_type == "income":
                balance.current_balance += amount
                balance.total_lifetime_income += amount
            else:
                balance.current_balance -= amount
                balance.total_lifetime_expenses += amount
            balance.last_updated = txn.timestamp
            self._store.save_balance(balance)

            # Open position if commodity purchase
            if category == "commodity_purchase" and self._positions:
                self._positions.open_position_from_purchase(txn)

            return JSONResponse({"ok": True, "id": txn.id})

        @app.post("/api/fleet")
        async def post_fleet(request: Request) -> JSONResponse:
            """Register an asset from the web dashboard."""
            if not self._assets:
                return JSONResponse(
                    {"error": "Asset manager not available"}, status_code=503
                )

            body = await request.json()
            asset_type = (body.get("asset_type") or "").strip()
            name = (body.get("name") or "").strip()
            purchase_price = body.get("purchase_price", 0)
            ship_model = (body.get("ship_model") or "").strip()
            location = (body.get("location") or "").strip()
            notes = (body.get("notes") or "").strip()

            valid_types = {"ship", "vehicle", "component", "equipment", "blueprint"}
            if not asset_type or asset_type not in valid_types:
                return JSONResponse(
                    {
                        "error": "asset_type must be ship, vehicle, component, equipment, or blueprint"
                    },
                    status_code=400,
                )
            if not name:
                return JSONResponse({"error": "Name is required"}, status_code=400)
            try:
                purchase_price = float(purchase_price)
            except (TypeError, ValueError):
                purchase_price = 0.0

            asset, txn = self._assets.register_asset(
                asset_type=asset_type,
                name=name,
                purchase_price=purchase_price,
                ship_model=ship_model,
                location=location,
                notes=notes,
            )

            # Update balance if a CAPEX transaction was created
            if txn:
                balance = self._store.get_balance()
                balance.current_balance -= txn.amount
                balance.total_lifetime_expenses += txn.amount
                balance.last_updated = txn.timestamp
                self._store.save_balance(balance)

            return JSONResponse({"ok": True, "id": asset.id})

        @app.post("/api/balance")
        async def post_balance(request: Request) -> JSONResponse:
            """Set the current balance from the web dashboard."""
            body = await request.json()
            amount = body.get("amount")
            try:
                amount = float(amount)
            except (TypeError, ValueError):
                return JSONResponse(
                    {"error": "Amount must be a number"}, status_code=400
                )

            balance = self._store.get_balance()
            balance.current_balance = amount
            balance.last_updated = datetime.now(tz=timezone.utc).isoformat()
            self._store.save_balance(balance)

            return JSONResponse({"ok": True, "balance": amount})

        @app.post("/api/positions")
        async def post_position(request: Request) -> JSONResponse:
            """Record a commodity purchase and open a position."""
            from models import (
                CATEGORY_ACTIVITY,
                Transaction,
            )

            if not self._positions:
                return JSONResponse(
                    {"error": "Position manager not available"}, status_code=503
                )

            body = await request.json()
            commodity_name = (body.get("commodity_name") or "").strip()
            quantity_scu = body.get("quantity_scu")
            price_per_scu = body.get("price_per_scu")
            location = (body.get("location") or "").strip()

            if not commodity_name:
                return JSONResponse(
                    {"error": "Commodity name is required"}, status_code=400
                )
            try:
                quantity_scu = float(quantity_scu)
                price_per_scu = float(price_per_scu)
            except (TypeError, ValueError):
                return JSONResponse(
                    {"error": "Quantity and price must be numbers"}, status_code=400
                )
            if quantity_scu <= 0 or price_per_scu <= 0:
                return JSONResponse(
                    {"error": "Quantity and price must be greater than 0"},
                    status_code=400,
                )

            total_cost = quantity_scu * price_per_scu
            activity_enum = CATEGORY_ACTIVITY.get("commodity_purchase")
            activity = activity_enum.value if activity_enum else None

            txn = Transaction(
                id=str(uuid.uuid4())[:8],
                timestamp=datetime.now(tz=timezone.utc).isoformat(),
                category="commodity_purchase",
                transaction_type="expense",
                amount=total_cost,
                description=f"Purchased {quantity_scu} SCU of {commodity_name}",
                location=location,
                source="web_dashboard",
                item_name=commodity_name,
                quantity=quantity_scu,
                quantity_unit="scu",
                activity=activity,
            )
            self._store.append_transaction(txn)

            # Update balance
            balance = self._store.get_balance()
            balance.current_balance -= total_cost
            balance.total_lifetime_expenses += total_cost
            balance.last_updated = txn.timestamp
            self._store.save_balance(balance)

            # Open position
            self._positions.open_position_from_purchase(txn)

            return JSONResponse({"ok": True, "id": txn.id})

        @app.post("/api/sales")
        async def post_sale(request: Request) -> JSONResponse:
            """Record a commodity sale and close positions (FIFO)."""
            from models import (
                CATEGORY_ACTIVITY,
                Transaction,
            )

            if not self._positions:
                return JSONResponse(
                    {"error": "Position manager not available"}, status_code=503
                )

            body = await request.json()
            commodity_name = (body.get("commodity_name") or "").strip()
            quantity_scu = body.get("quantity_scu")
            price_per_scu = body.get("price_per_scu")
            location = (body.get("location") or "").strip()

            if not commodity_name:
                return JSONResponse(
                    {"error": "Commodity name is required"}, status_code=400
                )
            try:
                quantity_scu = float(quantity_scu)
                price_per_scu = float(price_per_scu)
            except (TypeError, ValueError):
                return JSONResponse(
                    {"error": "Quantity and price must be numbers"}, status_code=400
                )
            if quantity_scu <= 0 or price_per_scu <= 0:
                return JSONResponse(
                    {"error": "Quantity and price must be greater than 0"},
                    status_code=400,
                )

            total_revenue = quantity_scu * price_per_scu
            activity_enum = CATEGORY_ACTIVITY.get("commodity_sale")
            activity = activity_enum.value if activity_enum else None

            txn = Transaction(
                id=str(uuid.uuid4())[:8],
                timestamp=datetime.now(tz=timezone.utc).isoformat(),
                category="commodity_sale",
                transaction_type="income",
                amount=total_revenue,
                description=f"Sold {quantity_scu} SCU of {commodity_name}",
                location=location,
                source="web_dashboard",
                item_name=commodity_name,
                quantity=quantity_scu,
                quantity_unit="scu",
                activity=activity,
            )
            self._store.append_transaction(txn)

            # Update balance
            balance = self._store.get_balance()
            balance.current_balance += total_revenue
            balance.total_lifetime_income += total_revenue
            balance.last_updated = txn.timestamp
            self._store.save_balance(balance)

            # Close positions (FIFO)
            self._positions.close_position_from_sale(txn)

            return JSONResponse({"ok": True, "id": txn.id})

        @app.put("/api/transactions/{txn_id}")
        async def put_transaction(txn_id: str, request: Request) -> JSONResponse:
            """Update an existing transaction."""
            from models import (
                ALL_CATEGORIES,
                CATEGORY_ACTIVITY,
                INCOME_CATEGORIES,
            )

            body = await request.json()
            updates: dict = {}

            # Only apply fields that were sent
            if "category" in body:
                category = (body["category"] or "").strip()
                if category not in ALL_CATEGORIES:
                    return JSONResponse({"error": "Invalid category"}, status_code=400)
                updates["category"] = category
                updates["transaction_type"] = (
                    "income" if category in INCOME_CATEGORIES else "expense"
                )
                activity_enum = CATEGORY_ACTIVITY.get(category)
                updates["activity"] = activity_enum.value if activity_enum else None

            if "amount" in body:
                try:
                    amount = float(body["amount"])
                except (TypeError, ValueError):
                    return JSONResponse(
                        {"error": "Amount must be a number"}, status_code=400
                    )
                if amount <= 0:
                    return JSONResponse(
                        {"error": "Amount must be greater than 0"}, status_code=400
                    )
                updates["amount"] = amount

            if "description" in body:
                desc = (body["description"] or "").strip()
                if not desc:
                    return JSONResponse(
                        {"error": "Description is required"}, status_code=400
                    )
                updates["description"] = desc

            if "location" in body:
                updates["location"] = (body["location"] or "").strip()

            if "tags" in body:
                tags_raw = (body["tags"] or "").strip()
                updates["tags"] = (
                    [t.strip() for t in tags_raw.split(",") if t.strip()]
                    if tags_raw
                    else []
                )

            if not updates:
                return JSONResponse({"error": "No fields to update"}, status_code=400)

            # Fetch old transaction to compute balance delta
            old_txns = self._store._read_all_transactions()
            old_txn = next((t for t in old_txns if t.id == txn_id), None)
            if not old_txn:
                return JSONResponse({"error": "Transaction not found"}, status_code=404)

            old_signed = (
                old_txn.amount
                if old_txn.transaction_type == "income"
                else -old_txn.amount
            )

            updated = self._store.update_transaction(txn_id, updates)
            if not updated:
                return JSONResponse({"error": "Transaction not found"}, status_code=404)

            # Adjust balance for the delta
            new_signed = (
                updated.amount
                if updated.transaction_type == "income"
                else -updated.amount
            )
            delta = new_signed - old_signed

            if delta != 0:
                balance = self._store.get_balance()
                balance.current_balance += delta
                # Adjust lifetime counters
                if old_txn.transaction_type == "income":
                    balance.total_lifetime_income -= old_txn.amount
                else:
                    balance.total_lifetime_expenses -= old_txn.amount
                if updated.transaction_type == "income":
                    balance.total_lifetime_income += updated.amount
                else:
                    balance.total_lifetime_expenses += updated.amount
                balance.last_updated = datetime.now(tz=timezone.utc).isoformat()
                self._store.save_balance(balance)

            return JSONResponse({"ok": True, "id": txn_id})

        @app.delete("/api/transactions/{txn_id}")
        async def delete_transaction(txn_id: str) -> JSONResponse:
            """Delete a transaction and reverse its balance impact."""
            deleted = self._store.delete_transaction(txn_id)
            if not deleted:
                return JSONResponse({"error": "Transaction not found"}, status_code=404)

            # Reverse balance impact
            balance = self._store.get_balance()
            if deleted.transaction_type == "income":
                balance.current_balance -= deleted.amount
                balance.total_lifetime_income -= deleted.amount
            else:
                balance.current_balance += deleted.amount
                balance.total_lifetime_expenses -= deleted.amount
            balance.last_updated = datetime.now(tz=timezone.utc).isoformat()
            self._store.save_balance(balance)

            return JSONResponse({"ok": True, "id": txn_id})

        @app.put("/api/fleet/{asset_id}")
        async def put_fleet(asset_id: str, request: Request) -> JSONResponse:
            """Update an existing asset."""
            if not self._assets:
                return JSONResponse(
                    {"error": "Asset manager not available"}, status_code=503
                )

            body = await request.json()

            asset, changes = self._assets.update_asset(
                asset_id=asset_id,
                name=body.get("name"),
                asset_type=body.get("asset_type"),
                ship_model=body.get("ship_model"),
                location=body.get("location"),
                purchase_price=(
                    float(body["purchase_price"]) if "purchase_price" in body else None
                ),
                estimated_market_value=(
                    float(body["estimated_market_value"])
                    if "estimated_market_value" in body
                    else None
                ),
                notes=body.get("notes"),
            )

            if not asset:
                return JSONResponse({"error": "Asset not found"}, status_code=404)

            return JSONResponse({"ok": True, "id": asset_id, "changes": changes})

        @app.delete("/api/fleet/{asset_id}")
        async def delete_fleet_asset(asset_id: str) -> JSONResponse:
            """Delete an asset from the registry."""
            deleted = self._store.delete_asset(asset_id)
            if not deleted:
                return JSONResponse({"error": "Asset not found"}, status_code=404)
            return JSONResponse({"ok": True, "id": asset_id, "name": deleted.name})

        @app.put("/api/positions/{pos_id}")
        async def put_position(pos_id: str, request: Request) -> JSONResponse:
            """Update commodity name, quantity, or notes on an open position.

            Quantity edits recalculate buy_price_per_unit from the existing
            buy_total so the cost basis stays accurate.
            """
            pos = self._store.get_position(pos_id)
            if not pos:
                return JSONResponse({"error": "Position not found"}, status_code=404)

            body = await request.json()

            if "commodity_name" in body:
                name = (body["commodity_name"] or "").strip()
                if name:
                    pos.commodity_name = name

            if "quantity" in body:
                try:
                    new_qty = float(body["quantity"])
                except (TypeError, ValueError):
                    return JSONResponse(
                        {"error": "Quantity must be a number"}, status_code=400
                    )
                if new_qty <= 0:
                    return JSONResponse(
                        {"error": "Quantity must be greater than 0"}, status_code=400
                    )
                pos.quantity = new_qty
                pos.buy_price_per_unit = (
                    pos.buy_total / new_qty if new_qty > 0 else pos.buy_total
                )

            if "notes" in body:
                pos.notes = body["notes"] or ""

            self._store.save_position(pos)
            return JSONResponse({"ok": True, "id": pos_id})

        @app.get("/api/statistics")
        def get_statistics(
            date_from: str = Query(""),
            date_to: str = Query(""),
            granularity: str = Query("daily"),
        ) -> JSONResponse:
            """Aggregated statistics for charts."""
            from models import (
                CATEGORY_ACTIVITY,
                CATEGORY_LABELS,
            )

            # Parse date range
            start = None
            end = None
            if date_from:
                try:
                    start = datetime.fromisoformat(date_from)
                    if start.tzinfo is None:
                        start = start.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
            if date_to:
                try:
                    end = datetime.fromisoformat(date_to)
                    if end.tzinfo is None:
                        end = end.replace(tzinfo=timezone.utc)
                    # Include the full end day
                    end = end.replace(hour=23, minute=59, second=59)
                except ValueError:
                    pass

            txns = self._store.query_transactions(start=start, end=end, limit=50000)

            if not txns:
                return JSONResponse(
                    {
                        "timeline": [],
                        "income_by_category": {},
                        "expense_by_category": {},
                        "activity_breakdown": {},
                        "top_commodities": [],
                        "totals": {
                            "income": 0,
                            "expenses": 0,
                            "net": 0,
                            "transaction_count": 0,
                        },
                    }
                )

            # --- Timeline aggregation ---
            from collections import defaultdict

            bucket_fmt = {
                "daily": "%Y-%m-%d",
                "weekly": None,  # handled specially
                "monthly": "%Y-%m",
            }.get(granularity, "%Y-%m-%d")

            def bucket_key(ts: str) -> str:
                dt = datetime.fromisoformat(ts)
                if granularity == "weekly":
                    # ISO week: Monday-start
                    iso = dt.isocalendar()
                    return f"{iso[0]}-W{iso[1]:02d}"
                return dt.strftime(bucket_fmt)

            timeline_income: dict[str, float] = defaultdict(float)
            timeline_expense: dict[str, float] = defaultdict(float)
            running_balance: dict[str, float] = defaultdict(float)
            income_by_cat: dict[str, float] = defaultdict(float)
            expense_by_cat: dict[str, float] = defaultdict(float)
            activity_income: dict[str, float] = defaultdict(float)
            activity_expense: dict[str, float] = defaultdict(float)
            commodity_profit: dict[str, float] = defaultdict(float)

            total_income = 0.0
            total_expenses = 0.0

            # Sort chronologically for running balance
            sorted_txns = sorted(txns, key=lambda t: t.timestamp)
            cumulative = 0.0

            for t in sorted_txns:
                key = bucket_key(t.timestamp)
                label = CATEGORY_LABELS.get(t.category, t.category)
                act_enum = CATEGORY_ACTIVITY.get(t.category)
                act_label = act_enum.value if act_enum else "other"

                if t.transaction_type == "income":
                    timeline_income[key] += t.amount
                    income_by_cat[label] += t.amount
                    activity_income[act_label] += t.amount
                    total_income += t.amount
                    cumulative += t.amount
                else:
                    timeline_expense[key] += t.amount
                    expense_by_cat[label] += t.amount
                    activity_expense[act_label] += t.amount
                    total_expenses += t.amount
                    cumulative -= t.amount

                running_balance[key] = cumulative

                # Commodity tracking
                if t.category in ("commodity_sale",) and t.item_name:
                    commodity_profit[t.item_name] += t.amount
                elif t.category in ("commodity_purchase",) and t.item_name:
                    commodity_profit[t.item_name] -= t.amount

            # Build sorted timeline
            all_keys = sorted(
                set(timeline_income) | set(timeline_expense) | set(running_balance)
            )
            timeline = []
            for k in all_keys:
                inc = round(timeline_income.get(k, 0), 2)
                exp = round(timeline_expense.get(k, 0), 2)
                timeline.append(
                    {
                        "date": k,
                        "income": inc,
                        "expenses": exp,
                        "net": round(inc - exp, 2),
                        "balance": round(running_balance.get(k, 0), 2),
                    }
                )

            # Top commodities by net profit
            top_commodities = sorted(
                [
                    {"name": name, "profit": round(profit, 2)}
                    for name, profit in commodity_profit.items()
                ],
                key=lambda c: c["profit"],
                reverse=True,
            )[:15]

            # Activity breakdown
            all_activities = sorted(set(activity_income) | set(activity_expense))
            activity_breakdown = {
                act: {
                    "income": round(activity_income.get(act, 0), 2),
                    "expenses": round(activity_expense.get(act, 0), 2),
                    "net": round(
                        activity_income.get(act, 0) - activity_expense.get(act, 0),
                        2,
                    ),
                }
                for act in all_activities
            }

            return JSONResponse(
                {
                    "timeline": timeline,
                    "income_by_category": {
                        k: round(v, 2)
                        for k, v in sorted(
                            income_by_cat.items(),
                            key=lambda x: x[1],
                            reverse=True,
                        )
                    },
                    "expense_by_category": {
                        k: round(v, 2)
                        for k, v in sorted(
                            expense_by_cat.items(),
                            key=lambda x: x[1],
                            reverse=True,
                        )
                    },
                    "activity_breakdown": activity_breakdown,
                    "top_commodities": top_commodities,
                    "totals": {
                        "income": round(total_income, 2),
                        "expenses": round(total_expenses, 2),
                        "net": round(total_income - total_expenses, 2),
                        "transaction_count": len(txns),
                    },
                }
            )

        @app.get("/api/ships")
        def get_ships() -> JSONResponse:
            ships_file = _STATIC_DIR / "ships.json"
            if not ships_file.exists():
                return JSONResponse([])
            with open(ships_file, encoding="utf-8") as f:
                ships = json.load(f)
            # Sort by name for display
            ships.sort(key=lambda s: s.get("name", ""))
            return JSONResponse(ships)

        # --- Full reset (destructive) ---

        @app.post("/api/reset")
        async def reset_all(request: Request) -> JSONResponse:
            """Wipe every accountant data file. Requires confirmation token.

            Used after a Star Citizen economy reset to start with a clean
            ledger. Reference data (market cache, GUID map) is preserved.
            """
            try:
                body = await request.json()
            except (ValueError, TypeError):
                body = {}
            if body.get("confirmation") != "RESET":
                return JSONResponse(
                    {"ok": False, "error": "Missing or invalid confirmation token."},
                    status_code=400,
                )
            deleted = self._store.reset_all_data()
            return JSONResponse({"ok": True, "deleted": deleted})

        # --- Data version endpoint for live refresh polling ---

        @app.get("/api/version")
        def data_version() -> JSONResponse:
            """Return current data version counter for change detection."""
            return JSONResponse(
                {"version": self._data_version},
                headers={"Cache-Control": "no-store"},
            )

        # --- Static files ---

        _no_cache = {"Cache-Control": "no-cache, no-store, must-revalidate"}

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(_STATIC_DIR / "index.html", headers=_no_cache)

        @app.get("/favicon.ico")
        def favicon() -> FileResponse:
            return FileResponse(_STATIC_DIR / "wingman-ai.ico")

        @app.get("/static/{filename:path}")
        def static_file(filename: str) -> FileResponse:
            return FileResponse(_STATIC_DIR / filename, headers=_no_cache)

        return app

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the server in a background thread."""
        if self._thread and self._thread.is_alive():
            return

        _ensure_firewall_rule(self._port)

        config = uvicorn.Config(
            self._app,
            host="0.0.0.0",
            port=self._port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)

        self._thread = threading.Thread(
            target=self._server.run,
            name="sc-accountant-ui",
            daemon=True,
        )
        self._thread.start()
        logger.info("Accountant UI server started on port %d", self._port)

    def stop(self) -> None:
        """Stop the server."""
        if self._server:
            self._server.should_exit = True
            self._server = None
        self._thread = None
        logger.info("Accountant UI server stopped")

    def notify_refresh(self) -> None:
        """Bump the data version so polling clients detect the change."""
        self._data_version += 1

    @property
    def port(self) -> int:
        """Port the server is listening on."""
        return self._port

    @property
    def url(self) -> str:
        """Base URL for local browser access."""
        return f"http://127.0.0.1:{self._port}"

    @property
    def lan_url(self) -> str:
        """URL for LAN access from other devices."""
        return f"http://{_get_lan_ip()}:{self._port}"

    @property
    def is_running(self) -> bool:
        """Whether the server thread is alive."""
        return self._thread is not None and self._thread.is_alive()


def _ensure_firewall_rule(port: int) -> None:
    """Add a Windows Firewall inbound allow rule for *port* if one doesn't exist.

    Triggers a one-time UAC elevation prompt so the user only needs to click
    "Yes" once. No-ops on non-Windows platforms.
    """
    if sys.platform != "win32":
        return

    rule_name = "SCAccountantUI"

    # Check whether the rule already exists (exit code 0 means found).
    check = subprocess.run(
        ["netsh", "advfirewall", "firewall", "show", "rule", f"name={rule_name}"],
        capture_output=True,
    )
    if check.returncode == 0:
        return

    # Rule missing. Add it via a UAC-elevated netsh process.
    try:
        subprocess.run(
            [
                "powershell",
                "-Command",
                (
                    f"Start-Process netsh "
                    f"-ArgumentList 'advfirewall firewall add rule "
                    f"name={rule_name} dir=in action=allow protocol=TCP localport={port}' "
                    f"-Verb RunAs -Wait"
                ),
            ],
            timeout=60,
        )
    except Exception:
        logger.warning("Could not add firewall rule for port %d automatically", port)


def _get_lan_ip() -> str:
    """Detect the machine's LAN IP address."""
    try:
        # Connect to a public DNS to determine the outbound interface
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _generate_qr_svg(url: str) -> str:
    """Generate a QR code SVG string using the vendored qrcodegen library."""
    try:
        from accountant_ui.qrcodegen import QrCode  # type: ignore[import]

        qr = QrCode.encode_text(url, QrCode.Ecc.LOW)
        size = qr.get_size()
        scale = 4
        border = 2
        svg_size = (size + 2 * border) * scale
        rects = []
        for y in range(size):
            for x in range(size):
                if qr.get_module(x, y):
                    rx = (x + border) * scale
                    ry = (y + border) * scale
                    rects.append(f'<rect x="{rx}" y="{ry}" width="{scale}" height="{scale}"/>')
        modules = "\n".join(rects)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_size} {svg_size}"'
            f' style="shape-rendering:crispEdges">'
            f'<rect width="{svg_size}" height="{svg_size}" fill="#fff"/>'
            f'<g fill="#000">{modules}</g>'
            f"</svg>"
        )
    except Exception:
        logger.warning("QR code generation failed", exc_info=True)
        return ""
