"""Tier 2: fixed interpretation of evidence, independent of log wording."""

from __future__ import annotations

import copy
import json
import math
import re

from .contracts import field_errors
from .reader import Event


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def _identity(value):
    return isinstance(value, str) and any(
        c not in "0-" and not c.isspace() for c in value
    )


def _fresh():
    return {
        "player_name": None,
        "player_geid": None,
        "shard": None,
        "active_missions": {},
        "injuries": {},
        "location_name": None,
        "location_code": None,
        "location_status": None,
        "location_guid": None,
        "last_known_location": None,
        "system": None,
        "ship": None,
        "ship_class": None,
        "ship_owner": None,
        "aboard_ship": None,
        "own_ship": None,
        "armistice": None,
        "restricted": None,
        "monitored": None,
        "jurisdiction": None,
        "incapacitated": None,
        "bleeding": None,
        "generation": None,
        "session_key": None,
        "last_source_timestamp": None,
        "game_build_verified": False,
        "observations": {},
        "mission_reconstruction": {
            "status": "partial",
            "reason": "Logs do not provide a complete mission inventory",
            "orphan_objectives": [],
        },
        "_seen": [],
        "_pending_trades": [],
        "_inventory_candidate": None,
        "_arrival_time": None,
        "_recent_completions": [],
        "_reward_notifications": [],
    }


EVIDENCE_FIELDS = (
    "player_name",
    "player_geid",
    "shard",
    "injuries",
    "location_name",
    "location_code",
    "location_status",
    "location_guid",
    "system",
    "ship",
    "ship_class",
    "ship_owner",
    "aboard_ship",
    "own_ship",
    "armistice",
    "restricted",
    "monitored",
    "jurisdiction",
    "incapacitated",
    "bleeding",
)
WORLD_FIELDS = tuple(
    k for k in EVIDENCE_FIELDS if k not in ("player_name", "player_geid", "shard")
)


class State:
    def __init__(self, lookups, snapshot=None):
        self.lookups = copy.deepcopy(lookups)
        self.data = _fresh()
        if snapshot:
            self.data.update(copy.deepcopy(snapshot))
            for key in EVIDENCE_FIELDS:
                if self.data[key] is not None and key not in self.data["observations"]:
                    self.data["observations"][key] = {
                        "value": copy.deepcopy(self.data[key]),
                        "timestamp": None,
                        "certainty": "unknown_time",
                        "instruction_version": None,
                        "source_occurrence": None,
                    }

    def public(self):
        result = copy.deepcopy(
            {k: v for k, v in self.data.items() if not k.startswith("_")}
        )
        # A one-way notification cannot establish ongoing health or recovery.
        # Preserve its evidence, but never expose it as a current boolean.
        result["bleeding"] = result["incapacitated"] = None
        result["state_semantics"] = (
            "Last logged observations, not continuous telemetry; consult observations and reader_health."
        )
        return result

    def invalidate_world(self, reason, occurrence=None):
        defaults = _fresh()
        for key in WORLD_FIELDS:
            self.data[key] = defaults[key]
            previous = self.data["observations"].get(key)
            if previous:
                previous.update(
                    certainty="invalidated", reason=reason, invalidated_by=occurrence
                )
        self.data["location_status"] = "unknown"
        for key in (
            "_pending_trades",
            "_inventory_candidate",
            "_arrival_time",
            "_recent_completions",
        ):
            self.data[key] = defaults[key]

    def apply(self, event: Event, occurrence: str, generation: str):
        if occurrence in self.data["_seen"]:
            return []
        self._refreshed_fields = set()
        prior_state = self.data
        before = {k: copy.deepcopy(self.data[k]) for k in EVIDENCE_FIELDS}
        rows = self._apply(event, occurrence, generation)
        if event.errors or event.event_type == "diagnostic":
            return rows
        if self.data is not prior_state:
            # A reset is absence of evidence, not an observation of recovery.
            defaults = _fresh()
            before = {k: defaults[k] for k in EVIDENCE_FIELDS}
        repeat_fields = (
            {
                "bleeding": ("bleeding",),
                "incapacitated": ("incapacitated",),
                "injury": ("injuries",),
                "med_bed_heal": ("injuries",),
                "armistice_zone": ("armistice",),
                "restricted_area": ("restricted",),
                "jurisdiction_change": ("jurisdiction",),
                "join_pu": ("shard",),
                "user_login": ("player_name",),
                "session_start": tuple(
                    k for k in ("player_name", "player_geid") if event.fields.get(k)
                ),
                "channel_change": (
                    "ship",
                    "ship_class",
                    "ship_owner",
                    "aboard_ship",
                    "own_ship",
                ),
                "entered_monitored_space": ("monitored",),
                "exited_monitored_space": ("monitored",),
                "monitored_space_down": ("monitored",),
                "monitored_space_restored": ("monitored",),
            }.get(event.event_type, ())
            if rows
            else ()
        )
        if (
            event.event_type == "location_change"
            and self.data["player_name"]
            and event.fields.get("player_name") == self.data["player_name"]
            and event.fields.get("location") == self.data["location_code"]
        ):
            repeat_fields = (
                "location_name",
                "location_code",
                "location_status",
                "system",
            )
        repeat_fields = set(repeat_fields) | self._refreshed_fields
        for key in EVIDENCE_FIELDS:
            old_evidence = self.data["observations"].get(key, {})
            if old_evidence.get("invalidated_by") == occurrence:
                continue
            if self.data[key] != before[key] or key in repeat_fields:
                self.data["observations"][key] = {
                    "value": copy.deepcopy(self.data[key]),
                    "timestamp": event.source_timestamp.isoformat()
                    if event.source_timestamp
                    else None,
                    "certainty": "last_observed"
                    if event.source_timestamp
                    else "unknown_time",
                    "instruction_version": event.instruction_version,
                    "source_occurrence": occurrence,
                }
        return rows

    def _apply(self, event: Event, occurrence: str, generation: str):
        s = self.data
        if occurrence in s["_seen"]:
            return []
        if generation != s["generation"]:
            self.data = s = _fresh()
            s["generation"] = generation
            s["session_key"] = generation
        s["_seen"] = (s["_seen"] + [occurrence])[-2048:]
        event.errors.extend(
            e
            for e in field_errors(event.fields, event.event_type)
            if e not in event.errors
        )
        if event.errors or event.event_type == "diagnostic":
            return []
        f = event.fields
        kind = event.event_type
        text_fields = (
            "mission_id",
            "mission_name",
            "objective",
            "body_part",
            "severity",
            "player_name",
            "player_geid",
            "shard",
            "location",
            "location_guid",
            "loc_from",
            "loc_to",
            "action",
            "channel_raw",
            "entity_class",
            "vehicle",
            "player_id",
            "shop_id",
            "kiosk_id",
            "source_provider",
            "currency",
            "currency_type",
            "result_text",
            "item_name",
            "blueprint_name",
            "recipient",
        )
        if any(k in f and not isinstance(f[k], str) for k in text_fields):
            return []
        if kind == "money_sent" and not _identity(f.get("recipient")):
            return []
        now = event.source_timestamp.timestamp() if event.source_timestamp else None
        timestamp = (
            event.source_timestamp.isoformat() if event.source_timestamp else None
        )
        if timestamp and (
            not s["last_source_timestamp"] or timestamp > s["last_source_timestamp"]
        ):
            s["last_source_timestamp"] = timestamp
        s["game_build_verified"] = event.game_build_verified
        row = {
            "event_type": kind,
            "data": copy.deepcopy(f),
            "timestamp": timestamp,
            "status": "observed",
            "source_occurrences": [occurrence],
            "instruction_version": event.instruction_version,
            "game_build_verified": event.game_build_verified,
            "session_key": s["session_key"],
        }

        def need(*keys):
            return all(f.get(k) not in (None, "", {}, []) for k in keys)

        def own_player():
            return bool(s["player_name"]) and f.get("player_name") == s["player_name"]

        if kind in ("user_login", "session_start", "join_pu"):
            # Login is an explicit fresh session. A character identity alone is
            # not a global dedup key; it may legitimately reappear after relog.
            if kind == "user_login" and need("player_name"):
                self.data = s = _fresh()
                s.update(
                    generation=generation,
                    session_key=occurrence,
                    player_name=f["player_name"],
                )
                s["_seen"] = [occurrence]
            elif kind == "session_start" and need("player_geid"):
                if s["player_geid"] is not None:
                    name = f.get("player_name", s["player_name"])
                    self.data = s = _fresh()
                    s.update(
                        generation=generation, session_key=occurrence, player_name=name
                    )
                    s["_seen"] = [occurrence]
                s["player_geid"] = f["player_geid"]
                if f.get("player_name"):
                    s["player_name"] = f["player_name"]
            elif kind == "join_pu" and need("shard"):
                if s["shard"] and s["shard"] != f["shard"]:
                    self.invalidate_world("shard_changed", occurrence)
                s["shard"] = f["shard"]
            row["session_key"] = s["session_key"]
            if timestamp and (
                not s["last_source_timestamp"] or timestamp > s["last_source_timestamp"]
            ):
                s["last_source_timestamp"] = timestamp
            s["game_build_verified"] = event.game_build_verified
        elif kind.startswith(("contract_", "objective_")):
            mid = f.get("mission_id")
            if not _identity(mid):
                return []
            missions = s["active_missions"]
            if kind == "contract_accepted" and need("mission_name"):
                if mid not in missions:
                    if len(missions) >= 256:
                        return []
                    missions[mid] = {
                        "mission_id": mid,
                        "name": f["mission_name"],
                        "objective": None,
                    }
                row["event_type"] = "mission_accepted"
            elif kind in (
                "contract_complete",
                "contract_failed",
                "contract_withdrawn",
            ) and need("mission_name"):
                missions.pop(mid, None)
                row["event_type"] = (
                    "mission_complete"
                    if kind == "contract_complete"
                    else "mission_withdrawn"
                    if kind == "contract_withdrawn"
                    else "mission_failed"
                )
                if kind == "contract_complete" and now is not None:
                    s["_recent_completions"] = (
                        s["_recent_completions"] + [{"id": mid, "time": now}]
                    )[-32:]
            elif kind.startswith("objective_") and need("objective"):
                if mid not in missions:
                    evidence = {
                        "mission_id": mid,
                        "objective": f["objective"],
                        "event_type": kind,
                        "timestamp": timestamp,
                    }
                    orphan = s["mission_reconstruction"]["orphan_objectives"]
                    s["mission_reconstruction"]["orphan_objectives"] = (
                        orphan + [evidence]
                    )[-100:]
                if mid in missions:
                    if kind == "objective_new":
                        missions[mid]["objective"] = f["objective"]
                        row["event_type"] = "mission_objective_new"
                    elif missions[mid]["objective"] == f["objective"]:
                        missions[mid]["objective"] = None
            elif kind not in ("contract_shared", "contract_available"):
                return []
        elif kind == "injury" and need("body_part", "severity"):
            body = re.sub(r"\s+", "", str(f["body_part"])).lower()
            parts = {
                x.lower(): x
                for x in ("head", "torso", "leftArm", "rightArm", "leftLeg", "rightLeg")
            }
            if body not in parts:
                return []
            s["injuries"][parts[body]] = {
                "severity": f["severity"],
                "tier": f.get("tier"),
            }
        elif kind == "med_bed_heal":
            for name, healed in f.get("healed_parts", {}).items():
                if healed is True:
                    s["injuries"].pop(name, None)
        elif kind in ("bleeding", "incapacitated"):
            s[kind] = True
        elif kind == "location_change":
            if not own_player() or not need("location"):
                return []
            candidate = s["_inventory_candidate"]
            if candidate and (now is None or not 0 <= now - candidate["time"] <= 75):
                s["_inventory_candidate"] = None
            loc = self.lookups["locations"].get(f["location"])
            if not loc:
                s.update(
                    location_name=None,
                    location_code=f["location"],
                    location_status="unknown",
                    location_guid=None,
                    system=None,
                    _arrival_time=None,
                    _inventory_candidate=None,
                )
                row["status"] = "unresolved"
                return [row]
            s["last_known_location"] = {
                "name": loc["name"],
                "code": f["location"],
                "system": loc["system"],
                "timestamp": timestamp,
            }
            if s["location_code"] == f["location"] and s["location_status"] == "at":
                s["_arrival_time"] = now
                if s["_inventory_candidate"] and (
                    now is None
                    or not 0 <= now - s["_inventory_candidate"]["time"] <= 75
                ):
                    s["_inventory_candidate"] = None
                return []
            s.update(
                location_name=loc["name"],
                location_code=f["location"],
                system=loc["system"],
                location_status="at",
                location_guid=None,
            )
            s["_arrival_time"] = now
            row["event_type"] = "location_arrived"
            row["data"]["location_name"] = loc["name"]
            row["attribution"] = "inventory_location_observation"
        elif kind == "personal_inventory_data":
            if not own_player() or not _identity(f.get("location_guid")):
                return []
            if (
                now is not None
                and s["_arrival_time"] is not None
                and 0 <= now - s["_arrival_time"] <= 15
                and s["location_status"] == "at"
            ):
                candidate = s["_inventory_candidate"]
                if candidate is None or (
                    candidate["guid"] == f["location_guid"]
                    and 0 <= now - candidate["time"] <= 75
                ):
                    s["location_guid"] = f["location_guid"]
                    self._refreshed_fields.add("location_guid")
            return []
        elif kind == "inventory_location_update":
            if not own_player() or not need("loc_from", "loc_to"):
                return []
            output = []
            if (
                f["loc_from"] != "0"
                and f["loc_from"] == s["location_guid"]
                and f["loc_to"] != f["loc_from"]
            ):
                s["location_guid"] = None
                s["location_status"] = "departed"
                row["event_type"] = "location_departed"
                row["data"]["location_name"] = s["location_name"]
                output.append(row)
            if now is not None and f["loc_to"] != "0":
                s["_inventory_candidate"] = {"guid": f["loc_to"], "time": now}
            return output
        elif kind == "channel_change":
            if not need("action", "ship_name"):
                return []
            ship_name, owner = f["ship_name"], f.get("owner", "")
            if f["action"] == "joined":
                s.update(
                    # A display label does not establish the internal entity
                    # class used to attribute nearby quantum/collision events.
                    ship_class=f.get("ship_class") or None,
                    ship=ship_name,
                    ship_owner=owner or None,
                    own_ship=(owner == s["player_name"])
                    if owner and s["player_name"]
                    else None,
                    aboard_ship=True,
                )
                row["event_type"] = "ship_entered"
            elif (
                f["action"] == "left"
                and s["aboard_ship"]
                and s["ship"] == ship_name
                and s["ship_owner"] == (owner or None)
            ):
                s.update(
                    ship=None,
                    ship_class=None,
                    ship_owner=None,
                    own_ship=None,
                    aboard_ship=False,
                )
                row["event_type"] = "ship_exited"
            else:
                return []
        elif kind in ("qt_arrived", "fatal_collision"):
            model = f.get("entity_class", f.get("vehicle"))
            if not model or not s["aboard_ship"] or not s["ship_class"]:
                return []
            if (
                model != s["ship_class"]
                or kind == "fatal_collision"
                and f.get("player_pilot") != 1
            ):
                return []
            # Same model is evidence, never an entity-ID ownership proof.
            row["attribution"] = "possible_player_ship"
        elif kind in ("armistice_zone", "restricted_area"):
            if f.get("action") not in ("entered", "exited"):
                return []
            s["armistice" if kind == "armistice_zone" else "restricted"] = (
                f["action"] == "entered"
            )
        elif kind in (
            "entered_monitored_space",
            "exited_monitored_space",
            "monitored_space_down",
            "monitored_space_restored",
        ):
            s["monitored"] = kind in (
                "entered_monitored_space",
                "monitored_space_restored",
            )
        elif kind == "jurisdiction_change" and need("jurisdiction"):
            s["jurisdiction"] = f["jurisdiction"]
        elif kind in ("shop_buy", "shop_sell"):
            row["status"] = "requested"
            price = _number(f.get("price"))
            quantity = _number(f.get("quantity"))
            if (
                now is not None
                and price is not None
                and quantity is not None
                and quantity > 0
                and need("player_id", "source_provider")
                and _identity(f["player_id"])
            ):
                s["_pending_trades"] = [
                    p for p in s["_pending_trades"] if 0 <= now - p["time"] <= 120
                ][-127:]
                s["_pending_trades"].append(
                    {
                        "fields": copy.deepcopy(f),
                        "time": now,
                        "kind": kind,
                        "occurrence": occurrence,
                    }
                )
        elif kind == "shop_transaction_result":
            if (
                now is None
                or not need("player_id", "source_provider", "result")
                or not _identity(f.get("player_id"))
            ):
                row["status"] = "unresolved"
                return [row]
            s["_pending_trades"] = [
                p for p in s["_pending_trades"] if 0 <= now - p["time"] <= 120
            ]
            matches = []
            for p in s["_pending_trades"]:
                q = p["fields"]
                if (
                    q["player_id"] != f["player_id"]
                    or q["source_provider"] != f["source_provider"]
                ):
                    continue
                if any(f.get(k) and f[k] != q.get(k) for k in ("shop_id", "kiosk_id")):
                    continue
                expected = {"Buying": "shop_buy", "Selling": "shop_sell"}.get(
                    f.get("transaction_type")
                )
                if f.get("transaction_type") and (
                    not expected or expected != p["kind"]
                ):
                    continue
                matches.append(p)
            if len(matches) > 1:
                for candidate in matches:
                    candidate["ambiguous"] = True
            if len(matches) != 1 or matches[0].get("ambiguous"):
                row["status"] = "ambiguous" if matches else "unresolved"
                return [row]
            p = matches[0]
            s["_pending_trades"].remove(p)
            q = p["fields"]
            if f["result"] != "Success":
                row["status"] = "failed"
                return [row]
            row.update(
                event_type=p["kind"],
                data=q,
                status="confirmed",
                category="item",
                source_occurrences=[p["occurrence"], occurrence],
            )
            row["confirmation_match"] = (
                "shop_kiosk"
                if f.get("shop_id") and f.get("kiosk_id")
                else "unique_player_request"
            )
            # Missing/novel currency remains an observed transaction, not aUEC.
            if q.get("currency_type") in ("UEC", "aUEC"):
                row["amount_auec"] = _number(q["price"]) * (
                    -1 if p["kind"] == "shop_buy" else 1
                )
                row["status"] = "confirmed"
        elif kind in (
            "commodity_buy",
            "commodity_sell",
            "cargo_transfer",
            "refinery_submitted",
            "insurance_claim",
        ):
            row["status"] = "requested"
            row["category"] = (
                "commodity" if kind.startswith("commodity_") else "movement"
            )
        elif kind in ("reward_earned", "blueprint_received", "fined", "money_sent"):
            if f.get("notification_id") and timestamp:
                fingerprint = json.dumps([kind, timestamp, f], sort_keys=True)
                if fingerprint in s["_reward_notifications"]:
                    return []
                s["_reward_notifications"] = (
                    s["_reward_notifications"] + [fingerprint]
                )[-256:]
            amount = _number(f.get("amount"))
            item = f.get("item_name") or f.get("blueprint_name")
            quantity = _number(f.get("quantity"))
            currency = str(f.get("currency", "")).lower()
            if (
                amount is not None
                and currency in ("auec", "uec")
                and not item
                and "quantity" not in f
            ):
                row["amount_auec"] = amount * (
                    -1 if kind in ("fined", "money_sent") else 1
                )
                row["status"] = "confirmed"
            elif item and "amount" not in f:
                row["item_name"] = item
                if quantity is not None:
                    row["quantity"] = quantity
                row["status"] = "observed"
            else:
                row["status"] = "unresolved"
            row["category"] = (
                "reward" if kind in ("reward_earned", "blueprint_received") else "money"
            )
            mid = f.get("mission_id")
            if _identity(mid):
                row["mission_id"] = mid
                row["mission_association"] = "explicit"
            elif now is not None:
                candidates = {
                    p["id"]
                    for p in s["_recent_completions"]
                    if 0 <= now - p["time"] <= 10
                }
                if len(candidates) == 1:
                    row["possible_mission_id"] = next(iter(candidates))
                    row["mission_association"] = "temporal_only"
        return [row]
