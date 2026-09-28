"""
SC_Accountant - Persistence Layer

Transactions use JSONL. New transactions are appended (atomic on most
filesystems), while the rarer update/delete rewrites the whole file through
an atomic temp-file replace, so a crash can never leave it truncated or
partially written.

JSON read-modify-write for mutable entities (trade orders, budgets, sessions,
balance, opportunities, positions, hauls, assets). These rewrites go through
the same atomic replace, so a reader never observes a half-written file.

Author: Mallachi
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from atomic_io import atomic_write_text
from models import (
    AccountBalance,
    Asset,
    Budget,
    Haul,
    Opportunity,
    Position,
    TradeOrder,
    TradingSession,
    Transaction,
)

logger = logging.getLogger(__name__)

# TypeVar for generic read/write — all models implement to_dict/from_dict
T = TypeVar("T")


class AccountantStore:
    """Persistent storage for the SC_Accountant skill."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

        self._transactions_path = base_dir / "transactions.jsonl"
        self._trade_orders_path = base_dir / "trade_orders.json"
        self._budgets_path = base_dir / "budgets.json"
        self._sessions_path = base_dir / "sessions.json"
        self._balance_path = base_dir / "balance.json"
        self._sync_cursor_path = base_dir / "sync_cursor.json"
        self._opportunities_path = base_dir / "opportunities.json"
        self._positions_path = base_dir / "positions.json"
        self._hauls_path = base_dir / "hauls.json"
        self._assets_path = base_dir / "assets.json"

    # ------------------------------------------------------------------
    # Generic JSON list I/O (DRY foundation for all mutable entities)
    # ------------------------------------------------------------------

    def _read_json_list(self, path: Path, model_cls: type[T]) -> list[T]:
        """Read a JSON array file and deserialize each element via model_cls.from_dict.

        Returns an empty list if the file doesn't exist or contains invalid JSON.
        """
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [model_cls.from_dict(d) for d in data]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.exception("Failed to read %s: %s", path.name, exc)
            return []

    def _write_json_list(self, path: Path, items: list) -> None:
        """Serialize a list of model objects to a JSON array file."""
        try:
            atomic_write_text(
                path, json.dumps([item.to_dict() for item in items], indent=2)
            )
        except OSError as exc:
            logger.exception("Failed to write %s: %s", path.name, exc)

    # ------------------------------------------------------------------
    # Transactions (JSONL append-only — immutable audit trail)
    # ------------------------------------------------------------------

    def append_transaction(self, txn: Transaction) -> None:
        """Append a single transaction to the JSONL file."""
        try:
            with open(self._transactions_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(txn.to_dict()) + "\n")
        except OSError as exc:
            logger.exception(
                "Failed to append transaction to %s: %s",
                self._transactions_path,
                exc,
            )

    def query_transactions(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        location: str | None = None,
        source: str | None = None,
        session_id: str | None = None,
        linked_asset_id: str | None = None,
        limit: int = 100,
    ) -> list[Transaction]:
        """Query transactions with filters. Returns most recent first."""
        entries = self._read_all_transactions()

        if start:
            start_iso = start.isoformat()
            entries = [e for e in entries if e.timestamp >= start_iso]
        if end:
            end_iso = end.isoformat()
            entries = [e for e in entries if e.timestamp < end_iso]
        if category:
            entries = [e for e in entries if e.category == category]
        if tags:
            tag_set = set(tags)
            entries = [e for e in entries if tag_set.intersection(e.tags)]
        if location:
            loc_lower = location.lower()
            entries = [e for e in entries if loc_lower in e.location.lower()]
        if source:
            entries = [e for e in entries if e.source == source]
        if session_id:
            entries = [e for e in entries if e.session_id == session_id]
        if linked_asset_id:
            entries = [e for e in entries if e.linked_asset_id == linked_asset_id]

        entries.reverse()
        return entries[:limit]

    def update_transaction(self, txn_id: str, updates: dict) -> Transaction | None:
        """Update a transaction by ID. Rewrites the JSONL file.

        Args:
            txn_id: The transaction ID to update.
            updates: Dict of field names to new values.

        Returns:
            The updated Transaction, or None if not found.
        """
        entries = self._read_all_transactions()
        updated = None
        for i, txn in enumerate(entries):
            if txn.id == txn_id:
                data = txn.to_dict()
                data.update(updates)
                entries[i] = Transaction.from_dict(data)
                updated = entries[i]
                break

        if updated is None:
            return None

        try:
            text = "".join(json.dumps(txn.to_dict()) + "\n" for txn in entries)
            atomic_write_text(self._transactions_path, text)
        except OSError as exc:
            logger.exception("Failed to rewrite transactions file: %s", exc)

        return updated

    def delete_transaction(self, txn_id: str) -> Transaction | None:
        """Delete a transaction by ID. Rewrites the JSONL file.

        Returns:
            The deleted Transaction, or None if not found.
        """
        entries = self._read_all_transactions()
        deleted = None
        remaining = []
        for txn in entries:
            if txn.id == txn_id and deleted is None:
                deleted = txn
            else:
                remaining.append(txn)

        if deleted is None:
            return None

        try:
            text = "".join(json.dumps(txn.to_dict()) + "\n" for txn in remaining)
            atomic_write_text(self._transactions_path, text)
        except OSError as exc:
            logger.exception("Failed to rewrite transactions file: %s", exc)

        return deleted

    def _read_all_transactions(self) -> list[Transaction]:
        """Read all transactions from the JSONL file.

        JSONL is used (not JSON) because transactions are immutable — append-only
        writes avoid read-modify-write races and survive partial writes cleanly.
        """
        if not self._transactions_path.exists():
            return []
        entries: list[Transaction] = []
        try:
            with open(self._transactions_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        entries.append(Transaction.from_dict(data))
                    except (json.JSONDecodeError, KeyError, TypeError):
                        logger.warning(
                            "Skipping malformed transaction line %d", line_num
                        )
        except OSError as exc:
            logger.exception("Failed to read transactions: %s", exc)

        return entries

    # ------------------------------------------------------------------
    # Trade Orders (JSON list, read-modify-write)
    # ------------------------------------------------------------------

    def save_trade_order(self, order: TradeOrder) -> None:
        """Create or update a trade order."""
        orders = self._read_json_list(self._trade_orders_path, TradeOrder)
        found = False
        for i, existing in enumerate(orders):
            if existing.id == order.id:
                orders[i] = order
                found = True
                break
        if not found:
            orders.append(order)
        self._write_json_list(self._trade_orders_path, orders)

    def query_trade_orders(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[TradeOrder]:
        """Query trade orders with optional status filter."""
        orders = self._read_json_list(self._trade_orders_path, TradeOrder)
        if status:
            orders = [o for o in orders if o.status == status]
        orders.reverse()
        return orders[:limit]

    def get_trade_order(self, order_id: str) -> TradeOrder | None:
        """Get a single trade order by ID."""
        for order in self._read_json_list(self._trade_orders_path, TradeOrder):
            if order.id == order_id:
                return order
        return None

    # ------------------------------------------------------------------
    # Budgets (JSON list, read-modify-write)
    # ------------------------------------------------------------------

    def save_budget(self, budget: Budget) -> None:
        """Create or update a budget."""
        budgets = self._read_json_list(self._budgets_path, Budget)
        found = False
        for i, existing in enumerate(budgets):
            if existing.id == budget.id:
                budgets[i] = budget
                found = True
                break
        if not found:
            budgets.append(budget)
        self._write_json_list(self._budgets_path, budgets)

    def get_budgets(
        self,
        period_type: str | None = None,
        category: str | None = None,
    ) -> list[Budget]:
        """Query budgets, optionally filtered."""
        budgets = self._read_json_list(self._budgets_path, Budget)
        if period_type:
            budgets = [b for b in budgets if b.period_type == period_type]
        if category:
            budgets = [b for b in budgets if b.category == category]
        return budgets

    def delete_budget(self, budget_id: str) -> bool:
        """Delete a budget by ID. Returns True if found and deleted."""
        budgets = self._read_json_list(self._budgets_path, Budget)
        original_len = len(budgets)
        budgets = [b for b in budgets if b.id != budget_id]
        if len(budgets) < original_len:
            self._write_json_list(self._budgets_path, budgets)
            return True
        return False

    # ------------------------------------------------------------------
    # Trading Sessions (JSON list, read-modify-write)
    # ------------------------------------------------------------------

    def save_session(self, session: TradingSession) -> None:
        """Create or update a trading session."""
        sessions = self._read_json_list(self._sessions_path, TradingSession)
        found = False
        for i, existing in enumerate(sessions):
            if existing.id == session.id:
                sessions[i] = session
                found = True
                break
        if not found:
            sessions.append(session)
        self._write_json_list(self._sessions_path, sessions)

    def get_active_session(self) -> TradingSession | None:
        """Get the currently active trading session (if any)."""
        for session in self._read_json_list(self._sessions_path, TradingSession):
            if session.ended_at is None:
                return session
        return None

    def get_session(self, session_id: str) -> TradingSession | None:
        """Get a single session by ID."""
        for session in self._read_json_list(self._sessions_path, TradingSession):
            if session.id == session_id:
                return session
        return None

    # ------------------------------------------------------------------
    # Account Balance (single JSON object — not a list)
    # ------------------------------------------------------------------

    def get_balance(self) -> AccountBalance:
        """Read the current account balance."""
        if not self._balance_path.exists():
            return AccountBalance()
        try:
            with open(self._balance_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return AccountBalance.from_dict(data)
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.exception("Failed to read balance: %s", exc)
            return AccountBalance()

    def save_balance(self, balance: AccountBalance) -> None:
        """Write the current account balance."""
        try:
            atomic_write_text(
                self._balance_path, json.dumps(balance.to_dict(), indent=2)
            )
        except OSError as exc:
            logger.exception("Failed to write balance: %s", exc)

    # ------------------------------------------------------------------
    # Sync Cursor (tracks position in SC_LogReader ledger)
    # ------------------------------------------------------------------

    def get_sync_cursor(self) -> dict:
        """Return the sync watermark: last imported timestamp and count at that timestamp.

        Format: {"last_ts": "2026-04-12T10:00:00", "count_at_ts": 2}
        "count_at_ts" is how many events at exactly last_ts were already imported —
        used to skip duplicates when multiple events share the same timestamp.
        """
        if not self._sync_cursor_path.exists():
            return {"last_ts": "", "count_at_ts": 0}
        try:
            with open(self._sync_cursor_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Migrate from old line-number format
            if "last_line" in data and "last_ts" not in data:
                return {"last_ts": "", "count_at_ts": 0}
            return {
                "last_ts": data.get("last_ts", ""),
                "count_at_ts": data.get("count_at_ts", 0),
            }
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.exception("Failed to read sync cursor: %s", exc)
            return {"last_ts": "", "count_at_ts": 0}

    def save_sync_cursor(self, last_ts: str, count_at_ts: int) -> None:
        """Save the sync watermark after a successful sync pass."""
        try:
            atomic_write_text(
                self._sync_cursor_path,
                json.dumps({"last_ts": last_ts, "count_at_ts": count_at_ts}),
            )
        except OSError as exc:
            logger.exception("Failed to write sync cursor: %s", exc)

    # ------------------------------------------------------------------
    # Opportunities (JSON list, read-modify-write)
    # ------------------------------------------------------------------

    def save_opportunity(self, opp: Opportunity) -> None:
        """Create or update a single opportunity."""
        opps = self._read_json_list(self._opportunities_path, Opportunity)
        found = False
        for i, existing in enumerate(opps):
            if existing.id == opp.id:
                opps[i] = opp
                found = True
                break
        if not found:
            opps.append(opp)
        self._write_json_list(self._opportunities_path, opps)

    def bulk_save_opportunities(self, new_opps: list[Opportunity]) -> None:
        """Save multiple new opportunities in a single write."""
        opps = self._read_json_list(self._opportunities_path, Opportunity)
        existing_ids = {o.id for o in opps}
        for opp in new_opps:
            if opp.id in existing_ids:
                # Update existing
                for i, existing in enumerate(opps):
                    if existing.id == opp.id:
                        opps[i] = opp
                        break
            else:
                opps.append(opp)
        self._write_json_list(self._opportunities_path, opps)

    def query_opportunities(
        self,
        status: str | None = None,
        commodity_name: str | None = None,
        limit: int = 50,
    ) -> list[Opportunity]:
        """Query opportunities with optional filters."""
        opps = self._read_json_list(self._opportunities_path, Opportunity)
        if status:
            opps = [o for o in opps if o.status == status]
        if commodity_name:
            name_lower = commodity_name.lower()
            opps = [o for o in opps if name_lower in o.commodity_name.lower()]
        # Sort by score descending for available; by created_at descending otherwise
        opps.sort(
            key=lambda o: o.score if o.status == "available" else 0,
            reverse=True,
        )
        return opps[:limit]

    def get_opportunity(self, opp_id: str) -> Opportunity | None:
        """Get a single opportunity by ID."""
        for opp in self._read_json_list(self._opportunities_path, Opportunity):
            if opp.id == opp_id:
                return opp
        return None

    def delete_expired_opportunities(self, before: str) -> int:
        """Remove expired/dismissed opportunities older than a timestamp."""
        opps = self._read_json_list(self._opportunities_path, Opportunity)
        original_len = len(opps)
        opps = [
            o
            for o in opps
            if o.status not in ("expired", "dismissed") or o.created_at >= before
        ]
        removed = original_len - len(opps)
        if removed > 0:
            self._write_json_list(self._opportunities_path, opps)
        return removed

    # ------------------------------------------------------------------
    # Positions (JSON list, read-modify-write)
    # ------------------------------------------------------------------

    def save_position(self, pos: Position) -> None:
        """Create or update a single position."""
        positions = self._read_json_list(self._positions_path, Position)
        found = False
        for i, existing in enumerate(positions):
            if existing.id == pos.id:
                positions[i] = pos
                found = True
                break
        if not found:
            positions.append(pos)
        self._write_json_list(self._positions_path, positions)

    def query_positions(
        self,
        status: str | None = None,
        commodity_name: str | None = None,
        limit: int = 50,
    ) -> list[Position]:
        """Query positions with optional filters."""
        positions = self._read_json_list(self._positions_path, Position)
        if status:
            positions = [p for p in positions if p.status == status]
        if commodity_name:
            name_lower = commodity_name.lower()
            positions = [p for p in positions if name_lower in p.commodity_name.lower()]
        # Open positions sorted by opened_at ASC, closed by closed_at DESC
        positions.sort(
            key=lambda p: p.closed_at or p.opened_at,
            reverse=True,
        )
        return positions[:limit]

    def get_position(self, pos_id: str) -> Position | None:
        """Get a single position by ID."""
        for pos in self._read_json_list(self._positions_path, Position):
            if pos.id == pos_id:
                return pos
        return None

    # ------------------------------------------------------------------
    # Hauls (JSON list, read-modify-write)
    # ------------------------------------------------------------------

    def save_haul(self, haul: Haul) -> None:
        """Create or update a haul record."""
        hauls = self._read_json_list(self._hauls_path, Haul)
        found = False
        for i, existing in enumerate(hauls):
            if existing.id == haul.id:
                hauls[i] = haul
                found = True
                break
        if not found:
            hauls.append(haul)
        self._write_json_list(self._hauls_path, hauls)

    def query_hauls(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Haul]:
        """Query hauls with optional status filter."""
        hauls = self._read_json_list(self._hauls_path, Haul)
        if status:
            hauls = [h for h in hauls if h.status == status]
        # Sort by started_at descending (most recent first)
        hauls.sort(key=lambda h: h.started_at, reverse=True)
        return hauls[:limit]

    def get_haul(self, haul_id: str) -> Haul | None:
        """Get a single haul by ID."""
        for haul in self._read_json_list(self._hauls_path, Haul):
            if haul.id == haul_id:
                return haul
        return None

    # ------------------------------------------------------------------
    # Assets (JSON list, read-modify-write)
    # ------------------------------------------------------------------

    def save_asset(self, asset: Asset) -> None:
        """Create or update an asset."""
        assets = self._read_json_list(self._assets_path, Asset)
        found = False
        for i, existing in enumerate(assets):
            if existing.id == asset.id:
                assets[i] = asset
                found = True
                break
        if not found:
            assets.append(asset)
        self._write_json_list(self._assets_path, assets)

    def query_assets(
        self,
        asset_type: str | None = None,
        status: str | None = None,
        parent_asset_id: str | None = None,
        limit: int = 50,
    ) -> list[Asset]:
        """Query assets with optional filters."""
        assets = self._read_json_list(self._assets_path, Asset)
        if asset_type:
            assets = [a for a in assets if a.asset_type == asset_type]
        if status:
            assets = [a for a in assets if a.status == status]
        if parent_asset_id:
            assets = [a for a in assets if a.parent_asset_id == parent_asset_id]
        # Active assets first, then by created_at descending
        assets.sort(
            key=lambda a: (a.status != "active", a.created_at),
            reverse=True,
        )
        return assets[:limit]

    def get_asset(self, asset_id: str) -> Asset | None:
        """Get a single asset by ID."""
        for asset in self._read_json_list(self._assets_path, Asset):
            if asset.id == asset_id:
                return asset
        return None

    def delete_asset(self, asset_id: str) -> Asset | None:
        """Delete an asset by ID. Returns the deleted asset or None."""
        assets = self._read_json_list(self._assets_path, Asset)
        for i, asset in enumerate(assets):
            if asset.id == asset_id:
                deleted = assets.pop(i)
                self._write_json_list(self._assets_path, assets)
                return deleted
        return None

    # ------------------------------------------------------------------
    # Full reset
    # ------------------------------------------------------------------

    def reset_all_data(self) -> dict[str, bool]:
        """Delete all player-owned accountant data files.

        Used when Star Citizen wipes the player economy (account reset / patch
        wipe) and the user needs to start over. Preserves market cache and
        GUID lookup tables because those are reference data, not user data.

        Returns:
            Dict mapping each data file's stem to whether it existed and was
            deleted (True) or did not exist (False). All entries succeeding
            means the on-disk state is fully cleared.
        """
        targets = [
            self._transactions_path,
            self._trade_orders_path,
            self._budgets_path,
            self._sessions_path,
            self._balance_path,
            self._sync_cursor_path,
            self._opportunities_path,
            self._positions_path,
            self._hauls_path,
            self._assets_path,
        ]
        result: dict[str, bool] = {}
        for path in targets:
            try:
                if path.exists():
                    path.unlink()
                    result[path.stem] = True
                else:
                    result[path.stem] = False
            except OSError as exc:
                logger.exception("Failed to delete %s: %s", path.name, exc)
                result[path.stem] = False
        return result

