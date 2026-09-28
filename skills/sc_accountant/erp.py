"""Personal ERP storage and read models. No Wingman or network dependencies."""

from __future__ import annotations

import copy
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

if __package__:
    from .erp_actions import Actions
    from .erp_intake import Intake
    from .erp_values import ZERO, now, money, text
else:
    from erp_actions import Actions
    from erp_intake import Intake
    from erp_values import ZERO, now, money, text


class ERP(Actions, Intake):
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        tables = {
            r[0]
            for r in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if tables and ("settings" not in tables or self._setting("schema") != 1):
            self.db.close()
            raise ValueError("Unsupported ERP database version")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS entities(
                kind TEXT NOT NULL,id TEXT PRIMARY KEY,period TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS entity_kind_period ON entities(kind,period);
            CREATE TABLE IF NOT EXISTS journal(
                sequence INTEGER PRIMARY KEY,id TEXT UNIQUE NOT NULL,period TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evidence(
                id TEXT PRIMARY KEY,sequence INTEGER NOT NULL,source_id TEXT NOT NULL,
                period TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(
                sequence INTEGER PRIMARY KEY,timestamp TEXT NOT NULL,action TEXT NOT NULL,payload TEXT NOT NULL);
        """)
        with self.db:
            for key, value in (
                ("schema", 1),
                ("mode", "simple"),
                ("period", "initial"),
                ("feed", {"source_id": None, "cursor": 0, "status": "not_connected"}),
            ):
                self.db.execute(
                    "INSERT OR IGNORE INTO settings VALUES(?,?)",
                    (key, json.dumps(value)),
                )
        if self._setting("schema") != 1:
            self.db.close()
            raise ValueError("Unsupported ERP database version")
        self._effects = {}
        self._entries = []

    def close(self):
        with self.lock:
            self.db.close()

    def _setting(self, key, default=None):
        row = self.db.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else default

    def _set(self, key, value):
        self.db.execute(
            "INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value))
        )

    @property
    def period(self):
        return self._setting("period")

    @contextmanager
    def _transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            self._effects = {}
            self._entries = []
            try:
                yield
                for entry_id in self._entries:
                    row = self.db.execute(
                        "SELECT payload FROM journal WHERE id=?", (entry_id,)
                    ).fetchone()
                    entry = json.loads(row[0])
                    entry["effects"] = list(self._effects.values())
                    self.db.execute(
                        "UPDATE journal SET payload=? WHERE id=?",
                        (json.dumps(entry), entry_id),
                    )
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise
            finally:
                self._effects = {}
                self._entries = []

    def _rows(self, kind, *, all_periods=False):
        if all_periods:
            rows = self.db.execute(
                "SELECT payload FROM entities WHERE kind=? ORDER BY rowid", (kind,)
            )
        else:
            rows = self.db.execute(
                "SELECT payload FROM entities WHERE kind=? AND period=? ORDER BY rowid",
                (kind, self.period),
            )
        return [json.loads(r[0]) for r in rows]

    def _get(self, kind, identity):
        row = self.db.execute(
            "SELECT payload FROM entities WHERE kind=? AND id=? AND period=?",
            (kind, text(identity), self.period),
        ).fetchone()
        if row is None:
            raise ValueError("Record not found in this accounting period")
        return json.loads(row[0])

    def _put(self, kind, row):
        row = copy.deepcopy(row)
        row.setdefault("id", str(uuid.uuid4()))
        row.setdefault("period", self.period)
        row.setdefault("created_at", now())
        old = self.db.execute(
            "SELECT payload FROM entities WHERE id=?", (row["id"],)
        ).fetchone()
        if row["id"] not in self._effects:
            self._effects[row["id"]] = {
                "kind": kind,
                "id": row["id"],
                "before": json.loads(old[0]) if old else None,
            }
        self._effects[row["id"]]["after"] = copy.deepcopy(row)
        self.db.execute(
            "INSERT OR REPLACE INTO entities VALUES(?,?,?,?)",
            (kind, row["id"], row["period"], json.dumps(row)),
        )
        return row

    def _journal(self, all_periods=False):
        if all_periods:
            rows = self.db.execute("SELECT payload FROM journal ORDER BY sequence")
        else:
            rows = self.db.execute(
                "SELECT payload FROM journal WHERE period=? ORDER BY sequence",
                (self.period,),
            )
        return [json.loads(r[0]) for r in rows]

    def _entry(
        self,
        *,
        cash=ZERO,
        profit=ZERO,
        category,
        notes="",
        operation_id=None,
        source="manual",
        source_id=None,
        unknown_cost=False,
        timestamp=None,
        reverses=None,
    ):
        if operation_id:
            self._get("operations", operation_id)
        row = {
            "id": str(uuid.uuid4()),
            "period": self.period,
            "timestamp": timestamp or now(),
            "category": category,
            "cash": money(cash),
            "profit": money(profit),
            "notes": text(notes),
            "operation_id": operation_id,
            "source": source,
            "source_id": source_id,
            "unknown_cost": bool(unknown_cost),
            "reverses": reverses,
            "effects": [],
        }
        self.db.execute(
            "INSERT INTO journal(id,period,payload) VALUES(?,?,?)",
            (row["id"], self.period, json.dumps(row)),
        )
        self._entries.append(row["id"])
        return row

    def command(self, action, data=None):
        if not isinstance(data, dict):
            raise ValueError("Action details must be an object")
        handler = self.ACTIONS.get(action)
        if not handler:
            raise ValueError("Unknown ERP action; request the help report")
        with self.lock:
            if action == "apply_config_mode" and self._setting(
                "last_config_mode"
            ) == self._mode(data.get("mode")):
                return {"mode": self._setting("mode")}
        with self._transaction():
            result = getattr(self, handler)(copy.deepcopy(data))
            self.db.execute(
                "INSERT INTO audit(timestamp,action,payload) VALUES(?,?,?)",
                (now(), action, json.dumps({"input": data, "result": result})),
            )
            return result

    def set_feed_error(self, message):
        with self.lock, self.db:
            feed = self._setting("feed")
            feed.update(status="unavailable", error=text(str(message), maximum=1000))
            self._set("feed", feed)

    def _summary(self):
        entries = self._journal()
        balance = sum((Decimal(x["cash"]) for x in entries), ZERO)
        profit = sum((Decimal(x["profit"]) for x in entries), ZERO)
        reversals = {x["reverses"] for x in entries if x.get("reverses")}
        resolved = {x.get("resolves_cost") for x in entries if x["id"] not in reversals}
        lots = self._rows("inventory")
        jobs = self._rows("production")
        cost = sum(
            (
                Decimal(x["cost"])
                for x in lots
                if x.get("cost") is not None
                and x.get("owner", "personal") == "personal"
            ),
            ZERO,
        )
        cost += sum(
            (
                Decimal(x["cost"])
                for x in jobs
                if x["status"] != "collected" and x.get("cost") is not None
            ),
            ZERO,
        )
        unknown = sum(
            (
                Decimal(x["quantity"])
                for x in lots
                if x.get("cost") is None and x.get("owner", "personal") == "personal"
            ),
            ZERO,
        )
        plans = self._rows("plans")
        reserve = sum((Decimal(x["reserve"]) for x in plans), ZERO)
        committed = sum((Decimal(x["committed"]) for x in plans), ZERO)
        cash_flow = sum(
            (
                Decimal(x["cash"])
                for x in entries
                if x["category"] not in ("reconciliation", "opening_balance")
                and not (
                    x.get("reverses")
                    and any(
                        y["id"] == x["reverses"]
                        and y["category"] in ("reconciliation", "opening_balance")
                        for y in entries
                    )
                )
            ),
            ZERO,
        )
        return {
            "balance": money(balance),
            "cash_flow": money(cash_flow),
            "realized_profit": money(profit),
            "inventory_cost": money(cost),
            "unknown_cost_quantity": str(unknown),
            "profit_complete": not any(
                x["unknown_cost"]
                and x["id"] not in reversals
                and x["id"] not in resolved
                and not x.get("reverses")
                for x in entries
            ),
            "committed_funds": money(committed),
            "reserve": money(reserve),
            "available_funds": money(balance - reserve - committed),
            "period": self.period,
            "balance_label": "Recorded balance; reconcile against the game wallet",
        }

    def _attention(self):
        evidence = [
            json.loads(r[0])
            for r in self.db.execute(
                "SELECT payload FROM evidence WHERE period=? ORDER BY sequence DESC",
                (self.period,),
            )
        ]
        result = [
            {
                "id": x["id"],
                "type": "event",
                "name": x.get("event_type", "Observation"),
                "status": x.get("erp_status"),
                "reason": x.get("reason", "Review missing evidence"),
                "data": x.get("data", {}),
                "entry_id": x.get("entry_id"),
                "cash_posted": x.get("cash_posted", False),
                "event_type": x.get("event_type"),
            }
            for x in evidence
            if x.get("erp_status") in ("pending", "unresolved", "conflict")
        ]
        for lot in self._rows("inventory"):
            if (
                lot.get("cost") is None
                and Decimal(lot["quantity"]) > 0
                and lot.get("owner", "personal") == "personal"
            ):
                result.append(
                    {
                        "id": lot["id"],
                        "type": "inventory",
                        "name": lot.get("item_name"),
                        "reason": "Cost is unknown; profit on a sale will be incomplete",
                    }
                )
        entries = self._journal()
        reversed_ids = {x["reverses"] for x in entries if x.get("reverses")}
        resolved = {
            x.get("resolves_cost") for x in entries if x["id"] not in reversed_ids
        }
        for entry in entries:
            if (
                entry["unknown_cost"]
                and not entry.get("reverses")
                and entry["id"] not in reversed_ids
                and entry["id"] not in resolved
            ):
                result.append(
                    {
                        "id": entry["id"],
                        "type": "journal",
                        "name": entry["category"],
                        "reason": "Sale or loss has unknown cost; realised profit is incomplete",
                    }
                )
        return result

    def view(self, section="overview", **filters):
        with self.lock:
            limit = max(1, min(int(filters.get("limit", 200)), 200))
            offset = max(0, int(filters.get("offset", 0)))
            if section == "settings":
                data = {
                    "mode": self._setting("mode"),
                    "last_config_mode": self._setting("last_config_mode"),
                    "period": self.period,
                }
            elif section == "help":
                data = self.HELP
            elif section == "feed":
                data = self._setting("feed")
            elif section == "overview":
                data = self._summary()
                data.update(
                    operations=self._operation_rows()[-10:],
                    attention=self._attention()[:10],
                    feed=self._setting("feed"),
                    plans=self._plan_rows()[:10],
                )
            elif section == "reports":
                data = self._reports()
            elif section == "history":
                data = list(reversed(self._journal(True)))
            elif section == "operations":
                data = self._operation_rows()
            elif section == "plans":
                data = self._plan_rows()
            elif section == "attention":
                data = self._attention()
            elif section == "journal":
                data = list(
                    reversed(self._journal(bool(filters.get("all_periods", False))))
                )
            elif section == "evidence":
                data = [
                    json.loads(r[0])
                    for r in self.db.execute(
                        "SELECT payload FROM evidence WHERE period=? ORDER BY sequence DESC",
                        (self.period,),
                    )
                ]
            elif section == "assets":
                data = self._asset_rows()
            elif section in ("inventory", "production"):
                data = self._rows(section)
                if section == "inventory":
                    data = [x for x in data if Decimal(x["quantity"]) > 0]
            else:
                raise ValueError("Unknown ERP report")
            if isinstance(data, list) and filters.get("operation_id"):
                operation = self._get("operations", filters["operation_id"])
                data = [
                    x
                    for x in data
                    if x.get("operation_id") == operation["id"]
                    or (section == "operations" and x["id"] == operation["id"])
                ]
            result = {"mode": self._setting("mode"), "data": data}
            if isinstance(data, list):
                result.update(
                    total=len(data),
                    offset=offset,
                    has_more=offset + limit < len(data),
                    data=data[offset : offset + limit],
                )
            return result

    def _operation_rows(self):
        entries = self._journal()
        rows = self._rows("operations")
        for row in rows:
            linked = [x for x in entries if x.get("operation_id") == row["id"]]
            row["cash_flow"] = money(sum((Decimal(x["cash"]) for x in linked), ZERO))
            row["realized_profit"] = money(
                sum((Decimal(x["profit"]) for x in linked), ZERO)
            )
            row["profit_complete"] = not any(
                x["unknown_cost"]
                and not x.get("reverses")
                and not any(
                    y.get("reverses") == x["id"]
                    or (
                        y.get("resolves_cost") == x["id"]
                        and not any(z.get("reverses") == y["id"] for z in linked)
                    )
                    for y in linked
                )
                for x in linked
            )
            elapsed = (
                datetime.fromisoformat(row.get("ended_at") or now())
                - datetime.fromisoformat(row["started_at"])
            ).total_seconds()
            row["hours"] = round(max(elapsed, 0) / 3600, 3)
            row["profit_per_hour"] = (
                money(
                    Decimal(row["realized_profit"])
                    * Decimal(3600)
                    / Decimal(str(elapsed))
                )
                if elapsed >= 60 and row["profit_complete"]
                else None
            )
            row.setdefault(
                "time_basis",
                "Player-started operation elapsed time, including idle time",
            )
            row["spending"] = money(
                sum(
                    (-Decimal(x["cash"]) for x in linked if Decimal(x["cash"]) < 0),
                    ZERO,
                )
            )
            row["budget_remaining"] = money(
                Decimal(row["budget"]) - Decimal(row["spending"])
            )
        return rows

    def _plan_rows(self):
        summary = self._summary()
        available = Decimal(summary["available_funds"])
        rows = self._rows("plans")
        for row in rows:
            row["shortfall"] = money(max(ZERO, Decimal(row["target"]) - available))
            row["affordable"] = available >= Decimal(row["target"])
            net = Decimal(row.get("income_per_hour", "0")) - Decimal(
                row.get("cost_per_hour", "0")
            )
            row["expected_hours"] = (
                money(Decimal(row["shortfall"]) / net) if net > 0 else None
            )
            hours = Decimal(row.get("hours_per_week", "0"))
            row["estimated_weeks"] = (
                money(Decimal(row["shortfall"]) / net / hours)
                if net > 0 and hours > 0
                else None
            )
            required = Decimal(row.get("required_quantity", "0"))
            row["resource_shortfall"] = str(
                max(ZERO, required - Decimal(row.get("available_quantity", "0")))
            )
            capacity = Decimal(row.get("capacity_per_trip", "0"))
            row["trips_needed"] = (
                int((required / capacity).to_integral_value(rounding=ROUND_CEILING))
                if capacity > 0
                else None
            )
            row["forecast_basis"] = (
                "Player-supplied assumptions; no guarantee of future income or game availability"
            )
        return rows

    def _asset_rows(self):
        rows = self._rows("assets")
        entries = self._journal()
        reversed_ids = {x.get("reverses") for x in entries if x.get("reverses")}
        for asset in rows:
            linked = [x for x in entries if x.get("asset_id") == asset["id"]]
            profit = sum((Decimal(x["profit"]) for x in linked), ZERO)
            asset["realized_profit"] = money(profit)
            asset["profit_complete"] = not any(
                x["unknown_cost"]
                and x["id"] not in reversed_ids
                and not x.get("reverses")
                and not any(
                    y.get("resolves_cost") == x["id"] and y["id"] not in reversed_ids
                    for y in linked
                )
                for x in linked
            )
            asset["remaining_to_break_even"] = (
                money(max(ZERO, Decimal(asset["purchase_price"]) - profit))
                if asset.get("purchase_price") is not None and asset["profit_complete"]
                else None
            )
            asset["attribution"] = "Only explicitly linked transactions are included"
        return rows

    def _reports(self):
        summary = self._summary()
        entries = self._journal()
        cash = [
            x
            for x in entries
            if x["category"] not in ("reconciliation", "opening_balance")
        ]
        # Reversals of opening adjustments retain that classification for cash-flow reporting.
        original = {x["id"]: x for x in entries}
        cash = [
            x
            for x in cash
            if not (
                x.get("reverses")
                and original.get(x["reverses"], {}).get("category")
                in ("reconciliation", "opening_balance")
            )
        ]
        inflows = sum((max(ZERO, Decimal(x["cash"])) for x in cash), ZERO)
        outflows = sum((max(ZERO, -Decimal(x["cash"])) for x in cash), ZERO)
        assets = [
            x for x in self._rows("assets") if x["status"] in ("active", "unavailable")
        ]
        asset_cost = sum(
            (
                Decimal(x["purchase_price"])
                for x in assets
                if x.get("purchase_price") is not None
            ),
            ZERO,
        )
        activities = {}
        for op in self._operation_rows():
            act = activities.setdefault(
                op["activity"],
                {
                    "activity": op["activity"],
                    "cash_flow": ZERO,
                    "realized_profit": ZERO,
                    "profit_complete": True,
                },
            )
            act["cash_flow"] += Decimal(op["cash_flow"])
            act["realized_profit"] += Decimal(op["realized_profit"])
            act["profit_complete"] &= op["profit_complete"]
        for act in activities.values():
            act["cash_flow"] = money(act["cash_flow"])
            act["realized_profit"] = money(act["realized_profit"])
        return {
            "cash_flow": {
                "inflows": money(inflows),
                "outflows": money(outflows),
                "net": money(inflows - outflows),
                "adjustments": money(Decimal(summary["balance"]) - inflows + outflows),
            },
            "income_statement": {
                "realized_profit": summary["realized_profit"],
                "profit_complete": summary["profit_complete"],
            },
            "balance_sheet": {
                "cash": summary["balance"],
                "stock_and_work_in_progress": summary["inventory_cost"],
                "assets_at_recorded_cost": money(asset_cost),
                "total_known_assets": money(
                    Decimal(summary["balance"])
                    + Decimal(summary["inventory_cost"])
                    + asset_cost
                ),
                "unknown_asset_values": sum(
                    x.get("purchase_price") is None for x in assets
                ),
                "liabilities": "0.00",
                "liability_scope": "No shared-credit/banking module",
            },
            "activities": list(activities.values()),
            "scope": "Current accounting period and recorded evidence only; unknown costs/values are excluded, not zero-valued",
        }
