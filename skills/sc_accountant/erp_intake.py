"""Durable evidence intake. Requests and observations never imply cash."""

from __future__ import annotations
import copy
import json

if __package__:
    from .erp_values import ZERO, money, now, number, text
else:
    from erp_values import ZERO, money, now, number, text

ECONOMIC = {
    "shop_buy",
    "shop_sell",
    "commodity_buy",
    "commodity_sell",
    "reward_earned",
    "fined",
    "money_sent",
}
REQUESTS = {
    "shop_buy",
    "shop_sell",
    "commodity_buy",
    "commodity_sell",
    "cargo_transfer",
    "refinery_submitted",
    "insurance_claim",
}
CONTEXT_ATTENTION = {
    "refinery_complete",
    "insurance_claim_complete",
    "vehicle_impounded",
}


class Intake:
    def _save_evidence(self, row, source):
        self.db.execute(
            "INSERT OR REPLACE INTO evidence VALUES(?,?,?,?,?)",
            (
                row["id"],
                row["sequence"],
                source,
                row.get("period", self.period),
                json.dumps(row),
            ),
        )

    def _finalize_effects(self):
        for entry_id in self._entries:
            row = self.db.execute(
                "SELECT payload FROM journal WHERE id=?", (entry_id,)
            ).fetchone()
            entry = json.loads(row[0])
            entry["effects"] = list(self._effects.values())
            self.db.execute(
                "UPDATE journal SET payload=? WHERE id=?", (json.dumps(entry), entry_id)
            )
        self._entries = []
        self._effects = {}

    def ingest_page(self, page):
        if not isinstance(page, dict) or page.get("contract_version") != 1:
            raise ValueError("Unsupported reader feed contract")
        source = text(page.get("source_id"), maximum=200)
        after = page.get("after")
        cursor = page.get("next_cursor")
        events = page.get("events")
        if (
            not source
            or type(after) is not int
            or type(cursor) is not int
            or after < 0
            or cursor < after
        ):
            raise ValueError("Invalid reader cursor")
        if not isinstance(events, list) or len(events) > 1000:
            raise ValueError("Invalid reader event page")
        if (
            events
            and (
                not isinstance(events[-1], dict) or events[-1].get("sequence") != cursor
            )
        ) or (not events and cursor != after):
            raise ValueError("Reader cursor must identify the last delivered event")
        with self._transaction():
            feed = self._setting("feed")
            if feed.get("source_id") not in (None, source):
                raise ValueError(
                    "Reader database identity changed; keep history and reconcile before rebinding"
                )
            if after > feed["cursor"]:
                raise ValueError("Reader page would skip events")
            imported = 0
            previous = after
            for raw in events:
                if not isinstance(raw, dict):
                    raise ValueError("Invalid reader event")
                event = copy.deepcopy(raw)
                sequence = event.get("sequence")
                if (
                    type(sequence) is not int
                    or sequence <= previous
                    or sequence > cursor
                ):
                    raise ValueError("Reader events are out of order")
                previous = sequence
                identity = text(event.get("id"), maximum=300)
                if not identity or not identity.startswith(source + ":"):
                    raise ValueError("Reader event identity does not match source")
                exists = self.db.execute(
                    "SELECT payload FROM evidence WHERE id=?", (identity,)
                ).fetchone()
                if exists:
                    continue
                if sequence <= feed["cursor"]:
                    raise ValueError("Reader history changed behind the saved cursor")
                if not isinstance(event.get("data", {}), dict):
                    raise ValueError("Invalid event fields")
                event.update(period=self.period, erp_status="observed")
                # Account/economy and wipe boundaries remain explicit.
                if event.get("environment") not in ("LIVE", "HOTFIX"):
                    event.update(erp_status="excluded", reason="Test economy")
                elif (
                    self._setting("period_started_at")
                    and event.get("timestamp")
                    and event["timestamp"] < self._setting("period_started_at")
                ):
                    event.update(
                        erp_status="excluded",
                        reason="Historical observation predates current accounting period",
                    )
                elif (
                    self._setting("period_started_at")
                    and not event.get("timestamp")
                    and event.get("event_type") in ECONOMIC
                ):
                    event.update(
                        erp_status="unresolved",
                        reason="Unknown observation date; confirm which accounting period it belongs to",
                    )
                else:
                    self._consume_event(event, source)
                self._save_evidence(event, source)
                self._finalize_effects()
                imported += 1
            feed.update(
                source_id=source,
                cursor=max(cursor, feed["cursor"]),
                status="catching_up" if page.get("has_more") else "connected",
                health=page.get("health", {}),
                last_import=now(),
                error=None,
            )
            self._set("feed", feed)
            return {"imported": imported, "cursor": feed["cursor"]}

    def _related(self, event):
        occurrences = set(event.get("source_occurrences") or [])
        if not occurrences:
            return []
        rows = [
            json.loads(r[0])
            for r in self.db.execute(
                "SELECT payload FROM evidence WHERE source_id=? AND period=?",
                (event["id"].rsplit(":", 1)[0], self.period),
            )
        ]
        return [
            x
            for x in rows
            if x["event_type"] == event["event_type"]
            and occurrences.intersection(x.get("source_occurrences") or [])
        ]

    def _consume_event(self, event, source):
        kind = event.get("event_type", "")
        status = event.get("status")
        if kind == "user_login" and event.get("data", {}).get("player_name"):
            player = text(event["data"]["player_name"])
            bound = self._setting("player_name")
            if bound and bound != player:
                raise ValueError(
                    "Different player detected; use a separate ERP data folder for that account"
                )
            self._set("player_name", player)
        if "amount_auec" in event and event["amount_auec"] is not None:
            number(
                event["amount_auec"], signed=True
            )  # Bad money aborts the complete page.
        if (
            kind in ECONOMIC
            and status == "confirmed"
            and event.get("amount_auec") is not None
        ):
            related = self._related(event)
            prior = next(
                (
                    x
                    for x in related
                    if (
                        x.get("entry_id")
                        or x.get("erp_status") in ("posted", "manual_confirmed")
                    )
                ),
                None,
            )
            if prior:
                old = prior.get("posted_amount")
                if old is not None and number(old, signed=True) == number(
                    event["amount_auec"], signed=True
                ):
                    event.update(
                        erp_status="matched",
                        matched_event_id=prior["id"],
                        entry_id=prior.get("entry_id"),
                    )
                else:
                    event.update(
                        erp_status="conflict",
                        entry_id=prior.get("entry_id"),
                        matched_event_id=prior["id"],
                        cash_posted=True,
                        reason="Reader confirmation differs; reverse/correct the existing entry, then dismiss this notice",
                    )
                return
            self._post_event(event)
            for old in related:
                if old.get("erp_status") in ("pending", "unresolved"):
                    old.update(erp_status="resolved", resolved_by=event["id"])
                    self._save_evidence(old, source)
        elif kind in REQUESTS and status == "requested":
            event.update(
                erp_status="pending",
                reason="Request observed; outcome requires confirmation",
            )
        elif kind in ECONOMIC and status != "failed":
            event.update(
                erp_status="unresolved",
                reason="Amount, currency, outcome or physical reward details need review",
            )
        elif kind in CONTEXT_ATTENTION:
            event.update(
                erp_status="pending",
                reason="Match this observation to the appropriate job or asset; cost/output is not known",
            )
        elif kind == "blueprint_received":
            fields = event.get("data", {})
            name = fields.get("blueprint_name") or fields.get("item_name")
            if name and not any(
                a["name"] == name and a.get("asset_type") == "blueprint"
                for a in self._rows("assets")
            ):
                self._put(
                    "assets",
                    {
                        "name": name,
                        "asset_type": "blueprint",
                        "status": "active",
                        "purchase_price": None,
                        "running_cost": "0.00",
                        "notes": "Observed unlock; no cash valuation",
                        "location": "Knowledge",
                        "source_event": event["id"],
                    },
                )
        elif kind == "mission_accepted":
            fields = event.get("data", {})
            mid = fields.get("mission_id")
            if mid and not any(
                x.get("mission_id") == mid for x in self._rows("operations")
            ):
                self._put(
                    "operations",
                    {
                        "name": fields.get("mission_name") or "Observed mission",
                        "mission_id": mid,
                        "activity": "missions",
                        "budget": "0.00",
                        "started_at": event.get("timestamp") or now(),
                        "ended_at": None,
                        "status": "active",
                        "time_basis": "Elapsed since observed mission acceptance; reconstruction may be incomplete",
                    },
                )
        elif kind in ("mission_complete", "mission_failed", "mission_withdrawn"):
            mid = event.get("data", {}).get("mission_id")
            for op in self._rows("operations"):
                if mid and op.get("mission_id") == mid:
                    op.update(
                        status=kind.removeprefix("mission_"),
                        ended_at=event.get("timestamp") or now(),
                    )
                    self._put("operations", op)
        # Context stays dated evidence and is never turned into invented inventory.

    def _post_event(self, event):
        cash = number(event["amount_auec"], signed=True)
        kind = event["event_type"]
        fields = event.get("data", {})
        operation_id = event.get("operation_id")
        explicit_mid = (
            event.get("mission_id")
            if event.get("mission_association") == "explicit"
            else None
        )
        if explicit_mid:
            op = next(
                (
                    x
                    for x in self._rows("operations")
                    if x.get("mission_id") == explicit_mid
                ),
                None,
            )
            operation_id = op["id"] if op else operation_id
        if (
            kind in ("shop_buy", "commodity_buy")
            and cash > 0
            or kind in ("shop_sell", "commodity_sell", "reward_earned")
            and cash < 0
        ):
            raise ValueError("Reader amount direction conflicts with transaction")
        if kind in ("fined", "money_sent") and cash > 0:
            raise ValueError("Outgoing money has an invalid sign")
        unknown = False
        profit = cash
        if kind == "commodity_buy":
            item = fields.get("resource_guid") or fields.get("item_guid")
            qty = fields.get("quantity_cscu")
            unit = "cSCU"
            if qty is None:
                qty = fields.get("quantity")
                unit = fields.get("quantity_unit", "SCU")
            if item and qty is not None and number(qty, places=6) > 0:
                self._new_lot(
                    {
                        "item_id": item,
                        "item_name": fields.get("item_name") or item,
                        "quantity": qty,
                        "unit": unit,
                        "location": fields.get("shop_name") or "Unknown",
                        "operation_id": operation_id,
                    },
                    -cash,
                )
            else:
                unknown = True
            profit = ZERO
        elif kind == "commodity_sell":
            # Sale amount is supported, but exact cost/lot allocation still requires the player.
            profit = ZERO
            unknown = True
        elif kind == "money_sent":
            profit = ZERO
        entry = self._entry(
            cash=cash,
            profit=profit,
            category=kind,
            operation_id=operation_id,
            source="reader",
            source_id=event["id"],
            timestamp=event.get("timestamp"),
            unknown_cost=unknown,
            notes="Confirmed reader evidence",
        )
        event.update(
            erp_status="posted", posted_amount=money(cash), entry_id=entry["id"]
        )
        if unknown:
            event.update(
                erp_status="unresolved",
                reason="Cash recorded; inventory allocation/cost needs review",
                cash_posted=True,
            )
        return entry

    def _resolve_event(self, d):
        identity = text(d.get("event_id"), maximum=300)
        raw = self.db.execute(
            "SELECT payload,source_id FROM evidence WHERE id=? AND period=?",
            (identity, self.period),
        ).fetchone()
        if not raw:
            raise ValueError("Event not found")
        event = json.loads(raw[0])
        if event.get("erp_status") not in ("pending", "unresolved", "conflict"):
            raise ValueError("Event is already resolved")
        decision = d.get("decision")
        if decision == "dismiss":
            event.update(erp_status="dismissed", resolution_note=text(d.get("notes")))
        elif decision == "confirm":
            if event.get("cash_posted") or event.get("entry_id"):
                raise ValueError(
                    "Cash already recorded; correct its journal entry rather than recording it again"
                )
            if event.get("event_type") not in ECONOMIC:
                raise ValueError(
                    "Update the matching job or asset explicitly, then dismiss this observation"
                )
            amount = number(d.get("amount"))
            direction = d.get("direction")
            if direction not in ("income", "expense"):
                raise ValueError("Confirmation needs income or expense direction")
            event["amount_auec"] = money(amount if direction == "income" else -amount)
            event["operation_id"] = d.get("operation_id")
            self._post_event(event)
            event.update(
                erp_status="manual_confirmed", resolution_note=text(d.get("notes"))
            )
        else:
            raise ValueError("Decision must be confirm or dismiss")
        self._save_evidence(event, raw[1])
        return {
            "id": event["id"],
            "status": event["erp_status"],
            "entry_id": event.get("entry_id"),
        }
