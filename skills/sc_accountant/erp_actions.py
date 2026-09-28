"""Validated personal operation, stock and accounting commands."""

from __future__ import annotations
import hashlib
import json
import uuid
from decimal import Decimal
from pathlib import Path

if __package__:
    from .erp_values import ZERO, money, now, number, quantity, text
else:
    from erp_values import ZERO, money, now, number, quantity, text


class Actions:
    ACTIONS = {
        name: "_" + name
        for name in (
            "set_mode",
            "apply_config_mode",
            "start_operation",
            "finish_operation",
            "record_cash",
            "buy_stock",
            "sell_stock",
            "reserve_stock",
            "transfer_stock",
            "lose_stock",
            "start_production",
            "complete_production",
            "collect_production",
            "register_asset",
            "update_asset",
            "set_plan",
            "reconcile_wallet",
            "resolve_event",
            "reverse_entry",
            "new_period",
            "import_legacy",
            "set_stock_cost",
            "resolve_cost",
            "allocate_sale",
            "assign_entry",
        )
    }
    HELP = {
        "set_stock_cost": "lot_id; amount total cost of remaining stock; notes optional. No cash movement",
        "resolve_cost": "entry_id of unknown-cost sale/loss; amount actual cost already consumed",
        "allocate_sale": "entry_id of imported commodity sale; inputs list of lot_id/quantity",
        "assign_entry": "entry_id; operation_id; asset_id optional. Explicit allocation without posting cash",
        "set_mode": "mode: simple or advanced",
        "start_operation": "name; activity optional; budget optional aUEC",
        "finish_operation": "operation_id",
        "record_cash": "amount; direction income/expense; category optional; operation_id, asset_id, notes optional",
        "buy_stock": "item_id; item_name; quantity; unit; location; amount optional (unknown if omitted); operation_id, owner optional",
        "sell_stock": "lot_id; quantity; amount; operation_id optional",
        "reserve_stock": "lot_id; quantity (sets reserved quantity, zero releases)",
        "transfer_stock": "lot_id; quantity; destination",
        "lose_stock": "lot_id; quantity; operation_id, notes optional",
        "start_production": "name; inputs list of lot_id/quantity; fee; operation_id optional",
        "complete_production": "production_id (marks ready; does not collect)",
        "collect_production": "production_id; item_id; item_name; quantity; unit; location",
        "register_asset": "name; purchase_price optional; acquired_now boolean default false; operation_id optional",
        "update_asset": "asset_id; status active/unavailable/destroyed/sold; notes; sale_amount optional required for sale",
        "set_plan": "name; target; reserve; committed; id optional; income_per_hour, cost_per_hour, hours_per_week, required_quantity, available_quantity, capacity_per_trip optional scenario assumptions",
        "reconcile_wallet": "amount observed in game; notes optional. Difference is an adjustment, not income",
        "resolve_event": "event_id; decision confirm/dismiss; amount and direction for cash confirmation; notes optional",
        "reverse_entry": "entry_id; reason. Refuses dependent stock changes",
        "new_period": "name. Starts empty books and keeps old history and feed cursor",
        "import_legacy": "path to legacy generated data; confirmed true. One-time non-destructive cash/assets import",
    }

    def _mode(self, value):
        mapping = {
            "simple": "simple",
            "casual": "simple",
            "advanced": "advanced",
            "engaged": "advanced",
            "industrial": "advanced",
        }
        if value not in mapping:
            raise ValueError("Mode must be simple or advanced")
        return mapping[value]

    def _set_mode(self, d):
        mode = self._mode(d.get("mode"))
        self._set("mode", mode)
        return {"mode": mode}

    def _apply_config_mode(self, d):
        mode = self._mode(d.get("mode"))
        if self._setting("last_config_mode") != mode:
            self._set("mode", mode)
            self._set("last_config_mode", mode)
        return {"mode": self._setting("mode")}

    def _start_operation(self, d):
        name = text(d.get("name"))
        if not name:
            raise ValueError("Operation name is required")
        row = self._put(
            "operations",
            {
                "name": name,
                "activity": text(d.get("activity"), "general"),
                "budget": money(number(d.get("budget", 0))),
                "started_at": now(),
                "ended_at": None,
                "status": "active",
            },
        )
        return row

    def _finish_operation(self, d):
        row = self._get("operations", d.get("operation_id"))
        if row["status"] != "active":
            raise ValueError("Operation is already finished")
        row.update(status="completed", ended_at=now())
        return self._put("operations", row)

    def _record_cash(self, d):
        amount = number(d.get("amount"))
        if d.get("direction") not in ("income", "expense"):
            raise ValueError("Direction must be income or expense")
        cash = amount if d["direction"] == "income" else -amount
        category = text(
            d.get("category"), "other_income" if cash >= 0 else "other_expense"
        )
        # Transfers are cash movements whose economic purpose is not necessarily an expense.
        profit = (
            ZERO
            if category
            in (
                "transfer",
                "money_sent",
                "capital",
                "opening_balance",
                "reconciliation",
            )
            else cash
        )
        entry = self._entry(
            cash=cash,
            profit=profit,
            category=category,
            notes=d.get("notes", ""),
            operation_id=d.get("operation_id"),
        )
        if d.get("asset_id"):
            asset = self._get("assets", d["asset_id"])
            entry["asset_id"] = asset["id"]
            self.db.execute(
                "UPDATE journal SET payload=? WHERE id=?",
                (json.dumps(entry), entry["id"]),
            )
            asset["running_cost"] = money(
                Decimal(asset.get("running_cost", "0")) + max(ZERO, -cash)
            )
            self._put("assets", asset)
        return {"id": entry["id"], "entry_id": entry["id"], "cash": entry["cash"]}

    def _new_lot(self, d, cost, *, owner="personal"):
        item_id = text(d.get("item_id"))
        if not item_id:
            raise ValueError("Item identity is required")
        unit = text(d.get("unit"), "units")
        if unit not in ("SCU", "cSCU", "units", "kg"):
            raise ValueError("Unit must be SCU, cSCU, units or kg")
        qty = quantity(d.get("quantity"))
        if unit == "cSCU":
            qty /= 100
            unit = "SCU"
        if owner not in ("personal", "mission", "other"):
            raise ValueError("Owner must be personal, mission or other")
        return self._put(
            "inventory",
            {
                "item_id": item_id,
                "item_name": text(d.get("item_name"), item_id),
                "quantity": str(qty),
                "unit": unit,
                "location": text(d.get("location"), "Unknown"),
                "cost": money(cost) if cost is not None else None,
                "reserved": "0",
                "owner": owner,
                "operation_id": d.get("operation_id"),
                "status": "available",
            },
        )

    def _buy_stock(self, d):
        amount = number(d["amount"]) if d.get("amount") is not None else None
        owner = d.get("owner", "personal")
        lot = self._new_lot(d, amount, owner=owner)
        entry = self._entry(
            cash=-amount if amount is not None and owner == "personal" else ZERO,
            category="stock_purchase" if amount is not None else "stock_observation",
            notes=d.get("notes", ""),
            operation_id=d.get("operation_id"),
        )
        return {**lot, "entry_id": entry["id"]}

    def _take(self, lot_id, value):
        lot = self._get("inventory", lot_id)
        qty = quantity(value)
        total = Decimal(lot["quantity"])
        if qty > total - Decimal(lot["reserved"]):
            raise ValueError(
                "Insufficient unreserved stock; release reservations first"
            )
        cost = (
            None
            if lot["cost"] is None
            else (
                Decimal(lot["cost"])
                if qty == total
                else number(Decimal(lot["cost"]) * qty / total)
            )
        )
        lot["quantity"] = str(total - qty)
        if cost is not None:
            lot["cost"] = money(Decimal(lot["cost"]) - cost)
        self._put("inventory", lot)
        return lot, qty, cost

    def _sell_stock(self, d):
        original = self._get("inventory", d.get("lot_id"))
        if original["owner"] != "personal":
            raise ValueError(
                "Mission or third-party cargo cannot be sold as personal stock"
            )
        amount = number(d.get("amount"))
        lot, qty, cost = self._take(d.get("lot_id"), d.get("quantity"))
        entry = self._entry(
            cash=amount,
            profit=amount - cost if cost is not None else ZERO,
            category="stock_sale",
            unknown_cost=cost is None,
            operation_id=d.get("operation_id"),
            notes=d.get("notes", ""),
        )
        return {
            "id": lot["id"],
            "entry_id": entry["id"],
            "quantity": str(qty),
            "cost": money(cost) if cost is not None else None,
            "profit": entry["profit"],
            "profit_complete": cost is not None,
        }

    def _reserve_stock(self, d):
        lot = self._get("inventory", d.get("lot_id"))
        qty = quantity(d.get("quantity"), positive=False)
        if qty > Decimal(lot["quantity"]):
            raise ValueError("Reservation exceeds stock")
        lot["reserved"] = str(qty)
        return self._put("inventory", lot)

    def _transfer_stock(self, d):
        destination = text(d.get("destination"))
        if not destination:
            raise ValueError("Destination is required")
        lot, qty, cost = self._take(d.get("lot_id"), d.get("quantity"))
        dest = self._new_lot(
            {**lot, "quantity": str(qty), "location": destination},
            cost,
            owner=lot["owner"],
        )
        entry = self._entry(
            category="stock_transfer", notes=f"{lot['location']} to {destination}"
        )
        return {**dest, "entry_id": entry["id"]}

    def _lose_stock(self, d):
        lot, qty, cost = self._take(d.get("lot_id"), d.get("quantity"))
        owned = lot["owner"] == "personal"
        entry = self._entry(
            category="stock_loss",
            profit=-cost if owned and cost is not None else ZERO,
            unknown_cost=owned and cost is None,
            operation_id=d.get("operation_id"),
            notes=d.get("notes", ""),
        )
        return {"id": lot["id"], "entry_id": entry["id"], "quantity": str(qty)}

    def _start_production(self, d):
        name = text(d.get("name"))
        inputs = d.get("inputs")
        if not name or not isinstance(inputs, list) or not 1 <= len(inputs) <= 100:
            raise ValueError("Job name and one to 100 inputs are required")
        fee = number(d.get("fee", 0))
        cost = fee
        captured = []
        for item in inputs:
            if not isinstance(item, dict):
                raise ValueError("Each input needs a lot_id and quantity")
            original = self._get("inventory", item.get("lot_id"))
            if original["owner"] != "personal":
                raise ValueError("Production requires personal stock")
            lot, qty, value = self._take(item.get("lot_id"), item.get("quantity"))
            captured.append(
                {
                    "lot_id": lot["id"],
                    "quantity": str(qty),
                    "cost": money(value) if value is not None else None,
                }
            )
            cost = None if value is None or cost is None else cost + value
        job = self._put(
            "production",
            {
                "name": name,
                "inputs": captured,
                "fee": money(fee),
                "cost": money(cost) if cost is not None else None,
                "status": "in_progress",
                "operation_id": d.get("operation_id"),
            },
        )
        entry = self._entry(
            cash=-fee, category="processing_fee", operation_id=d.get("operation_id")
        )
        return {**job, "entry_id": entry["id"]}

    def _complete_production(self, d):
        job = self._get("production", d.get("production_id"))
        if job["status"] != "in_progress":
            raise ValueError("Only an in-progress job can be marked ready")
        job.update(status="ready", completed_at=now())
        return self._put("production", job)

    def _collect_production(self, d):
        job = self._get("production", d.get("production_id"))
        if job["status"] != "ready":
            raise ValueError("Job must be ready before collection")
        output = self._new_lot(
            {**d, "operation_id": job.get("operation_id")},
            Decimal(job["cost"]) if job["cost"] is not None else None,
        )
        job.update(
            status="collected",
            collected_at=now(),
            output_lot_id=output["id"],
            output_quantity=output["quantity"],
            output_unit=output["unit"],
        )
        self._put("production", job)
        entry = self._entry(
            category="production_collection", operation_id=job.get("operation_id")
        )
        return {**output, "entry_id": entry["id"]}

    def _register_asset(self, d):
        name = text(d.get("name"))
        if not name:
            raise ValueError("Asset name is required")
        price = (
            number(d["purchase_price"]) if d.get("purchase_price") is not None else None
        )
        acquired = d.get("acquired_now", False)
        if type(acquired) is not bool:
            raise ValueError("acquired_now must be true or false")
        if acquired and price is None:
            raise ValueError("A new purchase requires its actual cost")
        asset = self._put(
            "assets",
            {
                "name": name,
                "status": "active",
                "notes": text(d.get("notes")),
                "purchase_price": money(price) if price is not None else None,
                "running_cost": "0.00",
                "location": text(d.get("location"), "Unknown"),
                "acquisition": "purchase" if acquired else "reported",
            },
        )
        entry = self._entry(
            cash=-price if acquired else ZERO,
            category="asset_purchase" if acquired else "asset_registration",
            operation_id=d.get("operation_id"),
        )
        return {**asset, "entry_id": entry["id"]}

    def _update_asset(self, d):
        asset = self._get("assets", d.get("asset_id"))
        status = d.get("status", asset["status"])
        if status not in ("active", "unavailable", "destroyed", "sold"):
            raise ValueError("Invalid asset status")
        if asset["status"] == "sold" and status != "sold":
            raise ValueError("Reverse the sale entry to restore this asset")
        entry = None
        if status == "sold" and asset["status"] != "sold":
            amount = number(d.get("sale_amount"))
            basis = asset.get("purchase_price")
            entry = self._entry(
                cash=amount,
                profit=amount - Decimal(basis) if basis is not None else ZERO,
                category="asset_sale",
                unknown_cost=basis is None,
                operation_id=d.get("operation_id"),
            )
            asset["sale_amount"] = money(amount)
        asset.update(status=status, notes=text(d.get("notes", asset["notes"])))
        if "location" in d:
            asset["location"] = text(d["location"])
        self._put("assets", asset)
        return {**asset, **({"entry_id": entry["id"]} if entry else {})}

    def _set_plan(self, d):
        row = self._get("plans", d["id"]) if d.get("id") else {}
        name = text(d.get("name", row.get("name")))
        if not name:
            raise ValueError("Plan name is required")
        row.update(
            name=name,
            target=money(number(d.get("target", row.get("target", 0)))),
            reserve=money(number(d.get("reserve", row.get("reserve", 0)))),
            committed=money(number(d.get("committed", row.get("committed", 0)))),
        )
        for key in (
            "income_per_hour",
            "cost_per_hour",
            "hours_per_week",
            "required_quantity",
            "available_quantity",
            "capacity_per_trip",
        ):
            if d.get(key) is not None:
                row[key] = str(number(d[key], places=6))
        return self._put("plans", row)

    def _reconcile_wallet(self, d):
        observed = number(d.get("amount"))
        difference = observed - Decimal(self._summary()["balance"])
        entry = self._entry(
            cash=difference,
            category="reconciliation",
            notes=d.get("notes", "Observed wallet balance"),
        )
        return {
            "entry_id": entry["id"],
            "adjustment": money(difference),
            "balance": money(observed),
        }

    def _reverse_entry(self, d):
        identity = text(d.get("entry_id"))
        reason = text(d.get("reason"))
        if not reason:
            raise ValueError("A correction reason is required")
        entries = self._journal()
        entry = next((x for x in entries if x["id"] == identity), None)
        if (
            not entry
            or entry.get("reverses")
            or any(x.get("reverses") == identity for x in entries)
        ):
            raise ValueError("Entry cannot be reversed or was already reversed")
        if any(
            x.get("resolves_cost") == identity
            and not any(y.get("reverses") == x["id"] for y in entries)
            for x in entries
        ):
            raise ValueError("Reverse the cost allocation first")
        if entry.get("source") == "legacy":
            raise ValueError(
                "Legacy history is preserved; record a reconciliation adjustment instead"
            )
        for effect in entry.get("effects", []):
            current = self.db.execute(
                "SELECT payload FROM entities WHERE id=?", (effect["id"],)
            ).fetchone()
            if current is None or json.loads(current[0]) != effect["after"]:
                raise ValueError(
                    "This record has later changes; reverse those changes first"
                )
        for effect in entry.get("effects", []):
            if effect["before"] is None:
                self.db.execute("DELETE FROM entities WHERE id=?", (effect["id"],))
            else:
                self._put(effect["kind"], effect["before"])
        reversal = self._entry(
            cash=-Decimal(entry["cash"]),
            profit=-Decimal(entry["profit"]),
            category="reversal",
            notes=reason,
            operation_id=entry.get("operation_id"),
            reverses=identity,
        )
        if entry.get("asset_id"):
            reversal["asset_id"] = entry["asset_id"]
            self.db.execute(
                "UPDATE journal SET payload=? WHERE id=?",
                (json.dumps(reversal), reversal["id"]),
            )
        return {"id": reversal["id"], "entry_id": reversal["id"], "reverses": identity}

    def _new_period(self, d):
        name = text(d.get("name"))
        if not name:
            raise ValueError("Period name is required")
        identity = str(uuid.uuid4())
        self._set("period", identity)
        self._set("period_name", name)
        self._set("period_started_at", now())
        return {"period": identity, "name": name, "history_preserved": True}

    def _import_legacy(self, d):
        if d.get("confirmed") is not True:
            raise ValueError("Legacy import requires confirmed: true")
        path = Path(text(d.get("path"), maximum=4096)).resolve()
        if not path.is_dir():
            raise ValueError("Legacy data folder not found")
        key = "legacy:" + hashlib.sha256(str(path).casefold().encode()).hexdigest()
        if self._setting(key):
            return {"imported": 0, "already_imported": True}
        if self._journal() or self._rows("assets") or self._rows("inventory"):
            raise ValueError(
                "Import legacy records into empty books to avoid duplication"
            )
        rows = []
        ledger = path / "transactions.jsonl"
        if ledger.exists():
            if ledger.stat().st_size > 100_000_000:
                raise ValueError("Legacy ledger exceeds import limit")
            for line in ledger.read_text(encoding="utf-8-sig").splitlines():
                if line.strip():
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("Invalid legacy ledger row")
                    rows.append(row)
        seen = set()
        for row in rows:
            identity = text(row.get("id"))
            if not identity or identity in seen:
                raise ValueError("Missing or duplicate legacy transaction identity")
            seen.add(identity)
            amount = number(row.get("amount"))
            if row.get("transaction_type") not in ("income", "expense"):
                raise ValueError("Invalid legacy transaction direction")
            cash = amount if row["transaction_type"] == "income" else -amount
            self._entry(
                cash=cash,
                profit=ZERO,
                category="legacy_cash",
                source="legacy",
                source_id=identity,
                notes=text(row.get("description")),
                timestamp=text(row.get("timestamp")) or now(),
                unknown_cost=True,
            )
        balance_file = path / "balance.json"
        if balance_file.exists():
            balance = json.loads(balance_file.read_text(encoding="utf-8-sig"))
            expected = number(balance.get("current_balance"), signed=True)
            delta = expected - Decimal(self._summary()["balance"])
            self._entry(
                cash=delta,
                category="opening_balance",
                source="legacy",
                notes="Legacy opening balance reconciliation",
            )
        assets_file = path / "assets.json"
        if assets_file.exists():
            for asset in json.loads(assets_file.read_text(encoding="utf-8-sig")):
                imported_asset = self._register_asset(
                    {
                        "name": asset.get("name"),
                        "purchase_price": asset.get("purchase_price"),
                        "notes": "Imported legacy asset; ownership reported, not game verified",
                    }
                )
                record = self._get("assets", imported_asset["id"])
                status = asset.get("status", "active")
                if status not in ("active", "unavailable", "sold", "destroyed"):
                    raise ValueError("Invalid legacy asset status")
                record.update(
                    status=status,
                    legacy_id=asset.get("id"),
                    asset_type=asset.get("asset_type", "ship"),
                )
                self._put("assets", record)
        for entry_id in self._entries:
            entry = self._entry_by_id(entry_id)
            entry["source"] = "legacy"
            self.db.execute(
                "UPDATE journal SET payload=? WHERE id=?", (json.dumps(entry), entry_id)
            )
        self._set(key, {"at": now(), "count": len(rows)})
        self._set("legacy_imported", True)
        return {
            "imported": len(rows),
            "inventory_imported": False,
            "note": "Cash history preserved. Historical profit and stock require reconciliation.",
        }

    def _entry_by_id(self, identity):
        entry = next((x for x in self._journal() if x["id"] == identity), None)
        if not entry:
            raise ValueError("Journal entry not found")
        return entry

    def _cost_target(self, identity):
        entries = self._journal()
        target = self._entry_by_id(identity)
        reversed_ids = {x.get("reverses") for x in entries if x.get("reverses")}
        if (
            target["id"] in reversed_ids
            or target.get("reverses")
            or not target["unknown_cost"]
        ):
            raise ValueError(
                "Only an unreversed entry with unknown cost can be resolved"
            )
        if any(
            x.get("resolves_cost") == identity and x["id"] not in reversed_ids
            for x in entries
        ):
            raise ValueError("Cost has already been allocated")
        return target

    def _cost_entry(self, target, cost):
        profit = (
            Decimal(target["cash"]) - cost if Decimal(target["cash"]) > 0 else -cost
        )
        row = self._entry(
            category="cost_allocation",
            profit=profit,
            operation_id=target.get("operation_id"),
            notes="Cost reconciliation for " + target["id"],
        )
        row["resolves_cost"] = target["id"]
        if target.get("asset_id"):
            row["asset_id"] = target["asset_id"]
        self.db.execute(
            "UPDATE journal SET payload=? WHERE id=?", (json.dumps(row), row["id"])
        )
        return {"id": row["id"], "entry_id": row["id"], "profit": row["profit"]}

    def _set_stock_cost(self, d):
        lot = self._get("inventory", d.get("lot_id"))
        if Decimal(lot["quantity"]) <= 0:
            raise ValueError(
                "No remaining stock; resolve the sale or loss cost instead"
            )
        lot["cost"] = money(number(d.get("amount")))
        self._put("inventory", lot)
        entry = self._entry(
            category="stock_cost_adjustment",
            notes=d.get("notes", "Player-reported remaining cost"),
        )
        return {**lot, "entry_id": entry["id"]}

    def _resolve_cost(self, d):
        target = self._cost_target(d.get("entry_id"))
        if target["category"] not in ("stock_sale", "stock_loss", "asset_sale"):
            raise ValueError(
                "Imported commodity sales need stock allocation; historical cash needs reconciliation"
            )
        return self._cost_entry(target, number(d.get("amount")))

    def _allocate_sale(self, d):
        target = self._cost_target(d.get("entry_id"))
        if target["category"] != "commodity_sell":
            raise ValueError("Only an imported commodity sale needs stock allocation")
        inputs = d.get("inputs")
        if not isinstance(inputs, list) or not 1 <= len(inputs) <= 100:
            raise ValueError("One to 100 stock allocations are required")
        total = ZERO
        for item in inputs:
            if not isinstance(item, dict):
                raise ValueError("Each input needs lot_id and quantity")
            lot = self._get("inventory", item.get("lot_id"))
            if lot["owner"] != "personal":
                raise ValueError("Cannot allocate mission or third-party stock")
            _, _, cost = self._take(item.get("lot_id"), item.get("quantity"))
            if cost is None:
                raise ValueError("Set the stock cost before allocating this sale")
            total += cost
        return self._cost_entry(target, total)

    def _assign_entry(self, d):
        target = self._entry_by_id(d.get("entry_id"))
        operation = self._get("operations", d.get("operation_id"))
        if target.get("reverses") or any(
            x.get("reverses") == target["id"] for x in self._journal()
        ):
            raise ValueError("A reversed entry cannot be reassigned")
        target["operation_id"] = operation["id"]
        if d.get("asset_id"):
            self._get("assets", d["asset_id"])
            target["asset_id"] = d["asset_id"]
        self.db.execute(
            "UPDATE journal SET payload=? WHERE id=?",
            (json.dumps(target), target["id"]),
        )
        for dependent in self._journal():
            if dependent.get("resolves_cost") == target["id"]:
                dependent["operation_id"] = operation["id"]
                if target.get("asset_id"):
                    dependent["asset_id"] = target["asset_id"]
                self.db.execute(
                    "UPDATE journal SET payload=? WHERE id=?",
                    (json.dumps(dependent), dependent["id"]),
                )
        return {"id": target["id"], "operation_id": operation["id"]}
