"""Read-only Elite journal projection. No Wingman or third-party dependencies.

Only observed fields are returned. Absence never means zero, false or unlocked.
Companion snapshots belong to a session only if their timestamps are recent enough.
"""

from datetime import datetime, timedelta, timezone
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import platform
import re
from threading import RLock


MAX_LINE = 2 * 1024 * 1024
MAX_BATCH = 4 * 1024 * 1024
MAX_RESULT = 6000
MAX_EXPLORATION_BODIES = 512
MAX_ROUTE_SYSTEMS = 4096
MAX_MISSIONS = 128
MAX_MISSION_OUTCOMES = 32
MAX_CARGO_STACKS = 512
RANK_FIELDS = ("Combat", "Trade", "Explore", "Soldier", "Exobiologist", "Empire", "Federation", "CQC")
REPUTATION_FIELDS = ("Empire", "Federation", "Independent", "Alliance")
MICRO_CATEGORIES = ("Items", "Components", "Consumables", "Data")
STATUS_FLAGS = {
    0: "docked", 1: "landed", 2: "landing_gear_down", 3: "shields_up",
    4: "supercruise", 5: "flight_assist_off", 6: "hardpoints_deployed",
    8: "lights_on", 9: "cargo_scoop_deployed", 10: "silent_running",
    11: "scooping_fuel", 12: "srv_handbrake", 13: "srv_turret",
    14: "srv_under_ship", 15: "srv_drive_assist", 16: "fsd_mass_locked",
    17: "fsd_charging", 18: "fsd_cooldown", 19: "low_fuel",
    20: "overheating", 22: "in_danger", 23: "being_interdicted",
    24: "in_main_ship", 25: "in_fighter",
    26: "in_srv", 27: "analysis_mode", 28: "night_vision", 30: "fsd_jump",
}
STATUS_FLAGS2 = {
    0: "on_foot", 1: "in_taxi", 2: "in_multicrew", 3: "on_foot_in_station",
    4: "on_foot_on_planet", 5: "aim_down_sight", 6: "low_oxygen",
    7: "low_health", 8: "cold", 9: "hot", 10: "very_cold", 11: "very_hot",
    12: "glide_mode", 13: "on_foot_in_hangar", 14: "on_foot_social_space",
    15: "on_foot_exterior", 16: "breathable_atmosphere",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parsed_time(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp if stamp.tzinfo else None
    except (ValueError, TypeError):
        return None


def age_seconds(value, now):
    stamp = parsed_time(value)
    return round((now - stamp).total_seconds()) if stamp else None


ELITE_STEAM_APP_ID = "359320"
PROTON_SAVED_GAMES = ("steamapps/compatdata/" + ELITE_STEAM_APP_ID +
                      "/pfx/drive_c/users/steamuser/Saved Games")
STEAM_ROOTS = (".local/share/Steam", ".steam/steam",
               ".var/app/com.valvesoftware.Steam/.local/share/Steam")


def default_journal_dir() -> Path:
    """Respect Windows' redirected Saved Games folder and Steam Proton on Linux."""
    saved = Path.home() / "Saved Games"
    if platform.system() == "Linux":
        for root in STEAM_ROOTS:
            candidate = Path.home() / root / PROTON_SAVED_GAMES
            if candidate.is_dir():
                saved = candidate
                break
    if platform.system() == "Windows":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                value, _ = winreg.QueryValueEx(key, "{4C5C32FF-BB9D-43B0-BF64-44433C3AC3D8}")
                saved = Path(os.path.expandvars(value))
        except OSError:
            pass
    return saved / "Frontier Developments" / "Elite Dangerous"


def select(event, fields):
    return {key: event[key] for key in fields.split() if key in event}


def nonnegative_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def finite_number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def material_name(value):
    if not isinstance(value, str) or not value or len(value) > 160:
        raise ValueError("Invalid material name")
    name = value.casefold()
    if name.startswith("$") and name.endswith("_name;"):
        name = name[1:-6]
    if not re.fullmatch(r"[a-z0-9_]+", name):
        raise ValueError("Invalid material symbol")
    return name


def material_category(value):
    if not isinstance(value, str):
        raise ValueError("Missing material category")
    category = value.casefold()
    if category.startswith("$microresource_category_") and category.endswith(";"):
        category = category[len("$microresource_category_"):-1]
    names = {"raw": "Raw", "elements": "Raw", "manufactured": "Manufactured", "encoded": "Encoded"}
    if category not in names:
        raise ValueError("Unknown material category")
    return names[category]


def journal_order(path):
    """Old Horizons uses YYMMDDHHMMSS; Odyssey uses YYYY-MM-DDTHHMMSS.

    Alphabetical sorting incorrectly places Journal.22... above Journal.2026-...
    Parse both formats. Alpha/Beta journals are deliberately outside this reader.
    """
    match = re.fullmatch(r"Journal\.(\d{4}-\d{2}-\d{2}T\d{6}|\d{12})\.(\d+)\.log", path.name)
    if not match:
        return None
    date, part = match.groups()
    try:
        return datetime.strptime(date, "%Y-%m-%dT%H%M%S" if "T" in date else "%y%m%d%H%M%S"), int(part)
    except ValueError:
        return None


def micro_entry(entry):
    """Keep stack identity internally; owner identifiers never enter summaries."""
    row = {"Name": material_name(entry.get("Name")), "Count": entry.get("Count")}
    if not nonnegative_int(row["Count"]):
        raise ValueError("Invalid microresource quantity")
    for field in ("OwnerID", "MissionID"):
        if field in entry:
            value = entry[field]
            if not nonnegative_int(value):
                raise ValueError("Invalid microresource stack identity")
            if field == "MissionID" and value in (0, 18446744073709551615):
                continue
            row[field] = value
    if isinstance(entry.get("Name_Localised"), str):
        row["Name_Localised"] = entry["Name_Localised"][:240]
    return row


def micro_key(row):
    return row["Name"], row.get("OwnerID"), row.get("MissionID")


def public_inventory(data):
    return {category: [{k: v for k, v in row.items() if k != "OwnerID"} for row in rows]
            for category, rows in data.items()}


def compact(value, limit=5):
    """Bound arbitrary journal structures before they can reach model context."""
    if isinstance(value, dict):
        result = {str(k)[:80]: compact(v, limit) for k, v in list(value.items())[:40]}
        if len(value) > 40:
            result["omitted_fields"] = len(value) - 40
        return result
    if isinstance(value, list):
        items = [compact(item, limit) for item in value[:limit]]
        return {"items": items, "total": len(value), "omitted": max(0, len(value) - limit)}
    if isinstance(value, str):
        return value[:240]
    return value


def shrink_summary(value):
    """Reduce already-compacted lists without wrapping them a second time."""
    if isinstance(value, dict):
        if (isinstance(value.get("items"), list) and nonnegative_int(value.get("total")) and
                "omitted" in value):
            kept = value["items"][:1]
            return {**value, "items": [shrink_summary(item) for item in kept],
                    "omitted": max(0, value["total"] - len(kept))}
        return {key: shrink_summary(item) for key, item in value.items()}
    if isinstance(value, list):
        return [shrink_summary(item) for item in value]
    return value


class JournalReader:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.lock = RLock()
        self.session = ""
        self.offsets = {}
        self._reset()

    def _reset(self):
        self.blocks = {}
        self.commander_id = ""
        self.commander_name = ""
        self.session_started = ""
        self.last_event = ""
        self.last_timestamp = ""
        self.game_version = ""
        self.galaxy = "unknown"
        self.odyssey = None
        self.running = False
        self.missions = {}
        self.mission_outcomes = {}
        self.mission_roster_at = None
        self.errors = set()
        self.data_warnings = set()
        self.catch_up = False

    def _put(self, name, data, event):
        self.blocks[name] = {
            "observed_at": event.get("timestamp"),
            "event": event.get("event"),
            "data": data,
        }

    def _invalidate(self, name, event, reason):
        block = self.blocks.setdefault(name, {"observed_at": None, "data": {}})
        block.pop("awaiting_snapshot", None)
        stamp = event.get("timestamp")
        old, new = parsed_time(block.get("invalidated_at")), parsed_time(stamp)
        if old and (not new or old > new):
            stamp = block["invalidated_at"]
        block.update(requires_refresh=True, invalidated_at=stamp, reason=reason)
        if name in ("rank", "progress", "reputation"):
            for row in block["data"].values():
                row.update(requires_refresh=True, invalidated_at=stamp, reason=reason)

    def _career(self, event):
        """Merge only reported career metrics; never infer a promotion from percent."""
        kind = event["event"]
        name = "rank" if kind == "Promotion" else kind.lower()
        previous = self.blocks.get(name, {})
        data = deepcopy(previous.get("data", {}))
        fields = REPUTATION_FIELDS if name == "reputation" else RANK_FIELDS
        keys = [key for key in fields if key in event]
        if not keys:
            return
        stamp = parsed_time(event.get("timestamp"))
        try:
            if not stamp or stamp > utc_now():
                raise ValueError("Missing or future career timestamp")
            for key in keys:
                row = data.get(key, {})
                times = [parsed_time(row.get(field)) for field in ("observed_at", "invalidated_at")]
                if any(prior and stamp < prior for prior in times):
                    raise ValueError("Out-of-order career observation")
                value = event[key]
                if name == "rank":
                    if not nonnegative_int(value) or value >= 2 ** 31:
                        raise ValueError("Invalid career rank")
                elif not finite_number(value) or (name == "progress" and value < 0) or (name == "reputation" and not -100 <= value <= 100):
                    raise ValueError("Invalid career percentage")
                if name == "progress":
                    rank = self.blocks.get("rank", {}).get("data", {}).get(key, {})
                    rank_time = parsed_time(rank.get("observed_at"))
                    if rank_time and stamp < rank_time:
                        raise ValueError("Percentage predates the observed rank")
            for key in keys:
                old_rank = data.get(key, {}).get("value")
                data[key] = {"value": event[key], "observed_at": event["timestamp"], "event": kind}
                if name == "progress":
                    rank = self.blocks.get("rank", {}).get("data", {}).get(key, {})
                    if "value" in rank and not rank.get("requires_refresh"):
                        data[key]["rank_at_observation"] = rank["value"]
                    else:
                        data[key]["rank_context"] = "Rank not confirmed when this percentage was observed."
                elif name == "rank" and (old_rank != event[key] or kind == "Promotion"):
                    progress = self.blocks.get("progress", {}).get("data", {}).get(key)
                    if progress is not None:
                        progress.update(requires_refresh=True, invalidated_at=event["timestamp"],
                                        reason="Rank changed or was first observed; awaiting its new percentage")
            # The block time is its newest metric; each field keeps its own time.
            old_time = parsed_time(previous.get("observed_at"))
            metadata = previous if old_time and old_time > stamp else event
            self._put(name, data, {"timestamp": metadata.get("observed_at", metadata.get("timestamp")),
                                   "event": metadata.get("event")})
        except (ValueError, TypeError, OverflowError):
            for key in keys:
                row = data.setdefault(key, {})
                safe_stamp = event.get("timestamp") if stamp and stamp <= utc_now() else row.get("observed_at")
                old_invalidated = parsed_time(row.get("invalidated_at"))
                if old_invalidated and (not parsed_time(safe_stamp) or old_invalidated > parsed_time(safe_stamp)):
                    safe_stamp = row["invalidated_at"]
                row.update(requires_refresh=True, invalidated_at=safe_stamp,
                           reason="Invalid or older career observation; awaiting this metric again")
            self.blocks[name] = {**previous, "data": data}

    def _career_view(self, now):
        rows = []
        ranks = self.blocks.get("rank", {}).get("data", {})
        progress = self.blocks.get("progress", {}).get("data", {})
        for field in RANK_FIELDS:
            row = {"category": field}
            for label, source in (("rank", ranks), ("progress", progress)):
                if field not in source:
                    continue
                value = deepcopy(source[field])
                value["age_seconds"] = age_seconds(value.get("observed_at"), now)
                if label == "progress" and "value" in value:
                    # Military rank progress may exceed 100 while awaiting promotion.
                    value["reported_percent"] = value.pop("value")
                    value["display_percent"] = min(100, value["reported_percent"])
                row[label] = value
            if len(row) > 1:
                rows.append(row)
        return {"Ranks": rows,
                "scope": "Each rank and percentage has its own date. Percentages do not establish promotion, permits, ship access or unlock completion."}

    @staticmethod
    def _mission_fields(event):
        """Allowlisted mission data only; reject ambiguous numeric/boolean fields."""
        result = {}
        for key in ("Name LocalisedName Faction Influence Reputation Commodity Commodity_Localised "
                    "TargetType TargetFaction PassengerType DestinationSystem DestinationStation "
                    "DestinationSettlement NewDestinationSystem NewDestinationStation NewDestinationSettlement").split():
            if key in event:
                if not isinstance(event[key], str):
                    raise ValueError("Invalid mission text")
                result[key] = event[key][:240]
        for key in "MissionID Reward Count KillCount PassengerCount Fine".split():
            if key in event:
                value = event[key]
                if not nonnegative_int(value) or value >= 2 ** 64 or (key == "MissionID" and value == 0):
                    raise ValueError("Invalid mission quantity or ID")
                result[key] = value
        if "MissionID" not in result:
            raise ValueError("Missing mission ID")
        for key in "Wing PassengerMission PassengerVIPs PassengerWanted".split():
            if key in event:
                if not isinstance(event[key], bool):
                    raise ValueError("Invalid mission flag")
                result[key] = event[key]
        return result

    @staticmethod
    def _mission_deadline(event, stamp):
        if "Expiry" in event:
            expiry = parsed_time(event["Expiry"])
            if not expiry:
                raise ValueError("Invalid mission expiry")
            return {"expires_at": expiry.isoformat(), "basis": "MissionAccepted.Expiry",
                    "observed_at": event["timestamp"]}
        if "Expires" in event:
            seconds = event["Expires"]
            if not isinstance(seconds, int) or isinstance(seconds, bool):
                raise ValueError("Invalid mission time remaining")
            result = {"reported_seconds": seconds, "basis": "Missions.Expires",
                      "observed_at": event["timestamp"]}
            # Zero/negative snapshot values do not establish a future deadline.
            if seconds > 0:
                result["expires_at"] = (stamp + timedelta(seconds=seconds)).isoformat()
            return result
        return None

    @staticmethod
    def _mission_destination(fields, event):
        redirected = any(key.startswith("NewDestination") for key in fields)
        prefix = "NewDestination" if redirected else "Destination"
        data = {"Destination" + suffix: fields[prefix + suffix]
                for suffix in ("System", "Station", "Settlement") if fields.get(prefix + suffix)}
        return {**data, "observed_at": event["timestamp"], "event": event["event"]} if data else None

    def _missions(self, event):
        """Merge dated mission observations atomically, without inventing outcomes."""
        previous = self.blocks.get("missions", {})
        stamp = parsed_time(event.get("timestamp"))
        prior_stamp = parsed_time(previous.get("observed_at"))
        kind = event["event"]
        try:
            invalidated = parsed_time(previous.get("invalidated_at"))
            if (not stamp or stamp > utc_now() or (prior_stamp and stamp < prior_stamp) or
                    (invalidated and stamp < invalidated)):
                raise ValueError("Missing, future or out-of-order mission observation")
            missions, outcomes = deepcopy(self.missions), deepcopy(self.mission_outcomes)
            roster_at = self.mission_roster_at
            if kind == "Missions":
                replacement, seen = {}, set()
                for group, state in (("Active", "active_reported"), ("Complete", "complete_reported"), ("Failed", "failed_reported")):
                    rows = event.get(group)
                    if not isinstance(rows, list) or len(rows) > MAX_MISSIONS:
                        raise ValueError("Missing or oversized mission roster")
                    for item in rows:
                        fields = self._mission_fields(item)
                        key = str(fields["MissionID"])
                        if key in seen:
                            raise ValueError("Mission appears more than once in roster")
                        seen.add(key)
                        old = missions.get(key, {}) if not previous.get("requires_refresh") else {}
                        row = {**old, "MissionID": fields["MissionID"], "state": state,
                               "state_observed_at": event["timestamp"],
                               "roster_details": {**fields, "observed_at": event["timestamp"]}}
                        deadline = self._mission_deadline({**item, "timestamp": event["timestamp"]}, stamp)
                        if deadline:
                            row["deadline"] = deadline
                        if group == "Failed":
                            outcomes[key] = row
                        else:
                            replacement[key] = row
                            outcomes.pop(key, None)
                if len(replacement) > MAX_MISSIONS:
                    raise ValueError("Too many missions")
                missions, roster_at = replacement, event["timestamp"]
            else:
                fields = self._mission_fields(event)
                key = str(fields["MissionID"])
                if key in outcomes and kind not in ("MissionCompleted", "MissionFailed", "MissionAbandoned"):
                    raise ValueError("Update for a terminal mission requires a fresh roster")
                row = deepcopy(missions.get(key, {"MissionID": fields["MissionID"], "state": "activity_observed"}))
                if kind == "MissionAccepted":
                    detail = {k: v for k, v in fields.items() if not k.startswith(("Destination", "NewDestination"))}
                    if "Reward" in detail:
                        detail["expected_reward_credits"] = detail.pop("Reward")
                    row = {"MissionID": fields["MissionID"], "state": "accepted",
                           "state_observed_at": event["timestamp"],
                           "details": {**detail, "observed_at": event["timestamp"]}}
                    deadline = self._mission_deadline(event, stamp)
                    if deadline:
                        row["deadline"] = deadline
                if kind in ("MissionAccepted", "MissionRedirected"):
                    destination = self._mission_destination(fields, event)
                    if kind == "MissionRedirected" and (not destination or not any(k.startswith("NewDestination") for k in fields)):
                        raise ValueError("Redirect lacks a new destination")
                    if destination:
                        row["destination"] = destination
                elif kind == "CargoDepot":
                    data = select(event, "UpdateType CargoType StartMarketID EndMarketID ItemsCollected ItemsDelivered TotalItemsToDeliver")
                    if data.get("UpdateType") not in ("Collect", "Deliver", "WingUpdate"):
                        raise ValueError("Unknown depot update")
                    for name in ("StartMarketID", "EndMarketID", "ItemsCollected", "ItemsDelivered", "TotalItemsToDeliver"):
                        if name in data and (not nonnegative_int(data[name]) or data[name] >= 2 ** 64):
                            raise ValueError("Invalid depot count or ID")
                    if "CargoType" in data:
                        if not isinstance(data["CargoType"], str):
                            raise ValueError("Invalid depot commodity")
                        data["CargoType"] = data["CargoType"][:240]
                    delivered, total = data.get("ItemsDelivered"), data.get("TotalItemsToDeliver")
                    if delivered is not None and total is not None:
                        if delivered > total:
                            raise ValueError("Delivered count exceeds contract total")
                        data["items_remaining_to_deliver"] = total - delivered
                    row["delivery"] = {**data, "observed_at": event["timestamp"],
                        "scope": "Depot totals may include wing contributions; not ship cargo or proof of mission completion."}
                elif kind in ("MissionCompleted", "MissionFailed", "MissionAbandoned"):
                    row = {"MissionID": fields["MissionID"], "state": kind,
                           "state_observed_at": event["timestamp"],
                           **select(fields, "Name LocalisedName Faction Fine")}
                    if kind == "MissionCompleted" and "Reward" in fields:
                        row["reported_reward_credits"] = fields["Reward"]
                    missions.pop(key, None)
                    outcomes[key] = row
                if kind not in ("MissionCompleted", "MissionFailed", "MissionAbandoned"):
                    row["last_update_at"] = event["timestamp"]
                    missions[key] = row
                    if len(missions) > MAX_MISSIONS:
                        raise ValueError("Too many mission observations")
            outcomes = dict(sorted(outcomes.items(), key=lambda pair: pair[1].get("state_observed_at", ""))[-MAX_MISSION_OUTCOMES:])
            self.missions, self.mission_outcomes, self.mission_roster_at = missions, outcomes, roster_at
            self._put("missions", list(missions.values()), event)
            self.blocks["missions"].update(roster_observed_at=roster_at,
                scope="Observed missions; complete_reported is a roster state, not proof of reward payment. Expected rewards are not credits on hand.")
            if outcomes:
                self._put("mission_outcomes", list(reversed(list(outcomes.values()))), event)
                self.blocks["mission_outcomes"]["scope"] = "Last 32 observed outcomes; not a complete earnings ledger."
            else:
                self.blocks.pop("mission_outcomes", None)
            if previous.get("requires_refresh") and kind != "Missions":
                self._invalidate("missions", event, "Mission history incomplete; awaiting a full roster")
        except (ValueError, TypeError, AttributeError, OverflowError):
            safe = event if stamp and stamp <= utc_now() else {"timestamp": previous.get("observed_at")}
            self._invalidate("missions", safe, "Malformed or out-of-order mission observation; awaiting a full roster")

    def _mission_view(self, now):
        data = self.blocks["missions"]["data"]
        rows = deepcopy(data) if isinstance(data, list) else []
        for row in rows:
            deadline = row.get("deadline", {})
            expiry = parsed_time(deadline.get("expires_at"))
            if expiry:
                remaining = int((expiry - now).total_seconds())
                deadline.update(seconds_until_expiry=remaining,
                                interpretation="deadline_elapsed_outcome_unconfirmed" if remaining <= 0 else "time_remaining_from_observation")
        # Soonest known deadline first; unknown deadlines remain explicitly unknown.
        return sorted(rows, key=lambda row: (parsed_time(row.get("deadline", {}).get("expires_at")) or
                                             datetime.max.replace(tzinfo=timezone.utc), row["MissionID"]))

    def _materials(self, event):
        """Apply verified journal quantities atomically, retaining the snapshot baseline."""
        kind = event["event"]
        previous = self.blocks.get("materials", {})
        try:
            stamp = parsed_time(event.get("timestamp"))
            prior_stamp = parsed_time(previous.get("observed_at"))
            if not stamp or (prior_stamp and stamp < prior_stamp):
                raise ValueError("Missing or out-of-order material timestamp")
            if kind == "Materials":
                data = {}
                for category in ("Raw", "Manufactured", "Encoded"):
                    if category not in event:
                        continue  # Unreported categories stay unknown, not empty.
                    entries = event[category]
                    if not isinstance(entries, list):
                        raise ValueError("Invalid material snapshot")
                    seen, rows = set(), []
                    for entry in entries:
                        name = material_name(entry.get("Name"))
                        if name in seen or not nonnegative_int(entry.get("Count")):
                            raise ValueError("Duplicate or invalid material quantity")
                        seen.add(name)
                        rows.append({**select(entry, "Name_Localised Count"), "Name": name})
                    data[category] = rows
                if not data:
                    raise ValueError("Missing material snapshot categories")
                invalidated = parsed_time(previous.get("invalidated_at"))
                if invalidated and stamp < invalidated:
                    raise ValueError("Material snapshot predates invalidation")
                self._put("materials", data, event)
                return
            if event.get("IsPreview") is True:
                return
            if not previous or previous.get("requires_refresh"):
                raise ValueError("A complete material observation is needed before reconciliation")
            data = deepcopy(previous["data"])
            inventory = {c: {e["Name"]: e for e in entries} for c, entries in data.items()}
            changes = []

            def change(row, sign, name_field="Name", count_field="Count"):
                name, count = material_name(row.get(name_field)), row.get(count_field)
                if not nonnegative_int(count) or count == 0:
                    raise ValueError("Invalid material transaction quantity")
                if "Category" in row:
                    category = material_category(row["Category"])
                else:
                    matches = [c for c, entries in inventory.items() if name in entries]
                    if len(matches) != 1:
                        raise ValueError("Material category cannot be resolved from the observed inventory")
                    category = matches[0]
                if category not in inventory:
                    raise ValueError("Material category has no baseline observation")
                changes.append((category, name, sign * count))

            def batch(rows, sign):
                if not isinstance(rows, list):
                    raise ValueError("Missing material transaction list")
                for row in rows:
                    change(row, sign)

            if kind in ("MaterialCollected", "MaterialDiscarded", "ScientificResearch"):
                change(event, 1 if kind == "MaterialCollected" else -1)
            elif kind == "MaterialTrade":
                change(event["Paid"], -1, "Material", "Quantity")
                change(event["Received"], 1, "Material", "Quantity")
            elif kind in ("EngineerCraft", "EngineerLegacyConvert"):
                batch(event.get("Ingredients"), -1)
            elif kind == "Synthesis":
                batch(event.get("Materials"), -1)
            elif kind == "EngineerContribution":
                change(event, -1, "Material", "Quantity")
            elif kind == "MissionCompleted":
                batch(event["MaterialsReward"], 1)
            elif kind == "TechnologyBroker":
                if "Ingredients" in event:
                    raise ValueError("Legacy broker ingredients may mix cargo and materials")
                batch(event.get("Materials"), -1)
            for category, name, delta in changes:
                entry = inventory[category].get(name)
                count = (entry["Count"] if entry else 0) + delta
                if count < 0:
                    raise ValueError("Material transaction exceeds the observed inventory")
                if entry is None:
                    entry = {"Name": name}
                    inventory[category][name] = entry
                    data[category].append(entry)
                entry["Count"] = count
            self._put("materials", data, event)
            self.blocks["materials"]["reconciled_from"] = previous.get("reconciled_from", previous.get("observed_at"))
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            self._invalidate("materials", event, str(exc))

    def _engineers(self, event):
        previous = self.blocks.get("engineerprogress", {})
        try:
            stamp, prior = parsed_time(event.get("timestamp")), parsed_time(previous.get("observed_at"))
            invalidated = parsed_time(previous.get("invalidated_at"))
            if not stamp or stamp > utc_now() or (prior and stamp < prior) or (invalidated and stamp < invalidated):
                raise ValueError("Missing or out-of-order engineer timestamp")
            snapshot = "Engineers" in event
            rows = event["Engineers"] if snapshot else [event]
            if not isinstance(rows, list):
                raise ValueError("Invalid engineer snapshot")
            engineers = {} if snapshot else {
                str(row["EngineerID"]): dict(row) for row in previous.get("data", {}).get("Engineers", [])}
            seen = set()
            for row in rows:
                identity = row.get("EngineerID")
                if not nonnegative_int(identity) or identity == 0 or identity in seen:
                    raise ValueError("Invalid or duplicate engineer entry")
                seen.add(identity)
                fields = select(row, "Engineer Progress Rank RankProgress")
                if not fields:
                    raise ValueError("Engineer update has no observations")
                for key in ("Engineer", "Progress"):
                    if key in fields and (not isinstance(fields[key], str) or not 0 < len(fields[key]) <= 160):
                        raise ValueError("Invalid engineer name or state")
                if "Rank" in fields and (not nonnegative_int(fields["Rank"]) or fields["Rank"] > 5):
                    raise ValueError("Invalid engineer grade")
                if "RankProgress" in fields and (not finite_number(fields["RankProgress"]) or not 0 <= fields["RankProgress"] <= 100):
                    raise ValueError("Invalid engineer rank progress")
                entry = deepcopy(engineers.get(str(identity), {"EngineerID": identity}))
                if fields.get("Rank", 0) > 0 and "Progress" not in fields and entry.get("Progress") != "Unlocked":
                    entry.pop("Progress", None)
                    entry.get("field_observed_at", {}).pop("Progress", None)
                # A named state transition can make earlier grades meaningless.
                if "Progress" in fields and fields["Progress"] != "Unlocked":
                    for key in ("Rank", "RankProgress"):
                        entry.pop(key, None)
                        entry.get("field_observed_at", {}).pop(key, None)
                if "Rank" in fields and fields["Rank"] != entry.get("Rank") and "RankProgress" not in fields:
                    entry.pop("RankProgress", None)
                    entry.get("field_observed_at", {}).pop("RankProgress", None)
                entry.update(fields)
                dates = entry.setdefault("field_observed_at", {})
                dates.update({key: event.get("timestamp") for key in fields})
                # Each entry carries its own time; one update does not refresh others.
                entry["observed_at"] = event.get("timestamp")
                engineers[str(identity)] = entry
            self._put("engineerprogress", {"Engineers": list(engineers.values())}, event)
            if previous.get("requires_refresh") and not snapshot:
                self._invalidate("engineerprogress", event, "Full engineer snapshot needed after an earlier invalid record")
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            safe = event if stamp and stamp <= utc_now() else {"timestamp": previous.get("observed_at")}
            self._invalidate("engineerprogress", safe, str(exc))

    def _microresources(self, block, event, sidecar=False):
        previous = self.blocks.get(block, {})
        delta = event.get("event") == "BackpackChange"
        try:
            stamp = parsed_time(event.get("timestamp"))
            prior = parsed_time(previous.get("observed_at"))
            invalidated = parsed_time(previous.get("invalidated_at"))
            if not stamp or (prior and stamp < prior) or (invalidated and stamp < invalidated):
                raise ValueError("Missing or out-of-order inventory timestamp")
            if delta:
                if not previous or previous.get("requires_refresh"):
                    raise ValueError("Full backpack observation needed before applying changes")
                if previous.get("source_file") and prior == stamp:
                    raise ValueError("Snapshot and change order ambiguous; awaiting newer backpack snapshot")
                data = deepcopy(previous["data"])
                if not any(key in event for key in ("Added", "Removed")):
                    raise ValueError("Missing backpack changes")
                for field, direction in (("Removed", -1), ("Added", 1)):
                    changes = event.get(field, [])
                    if not isinstance(changes, list):
                        raise ValueError("Invalid backpack changes")
                    for change in changes:
                        row = micro_entry(change)
                        category = {"item": "Items", "component": "Components",
                                    "consumable": "Consumables", "data": "Data"}.get(str(change.get("Type")).casefold())
                        if category not in data:
                            raise ValueError("Unknown backpack category or missing baseline")
                        rows = data[category]
                        match = next((r for r in rows if micro_key(r) == micro_key(row)), None)
                        if match is None:
                            if direction < 0:
                                raise ValueError("Removed backpack stack was not observed")
                            rows.append(row)
                        else:
                            match["Count"] += direction * row["Count"]
                            if match["Count"] < 0:
                                raise ValueError("Backpack quantity would become negative")
                            if match["Count"] == 0:
                                rows.remove(match)
            else:
                data = {}
                for category in MICRO_CATEGORIES:
                    if category not in event:
                        continue
                    if not isinstance(event[category], list):
                        raise ValueError("Invalid inventory snapshot")
                    rows = [micro_entry(row) for row in event[category]]
                    if len({micro_key(row) for row in rows}) != len(rows):
                        raise ValueError("Duplicate inventory stack")
                    data[category] = rows
                if not data:
                    raise ValueError("Inventory snapshot has no reported categories")
            self._put(block, data, event)
            if sidecar:
                self.blocks[block]["source_file"] = True
            if delta:
                self.blocks[block]["reconciled_from"] = previous.get("reconciled_from", previous.get("observed_at"))
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            self._invalidate(block, event, str(exc))

    @staticmethod
    def _cargo_key(row):
        mission = row.get("MissionID")
        if mission is not None and (not nonnegative_int(mission) or not 0 < mission < 2 ** 64):
            raise ValueError("Invalid cargo mission identity")
        return material_name(row.get("Name", row.get("Type"))), mission

    def _cargo(self, event, sidecar=False):
        """Reconcile exact commodity/mission stacks; uncertain ownership stays unknown."""
        previous = self.blocks.get("cargo", {})
        stamp = parsed_time(event.get("timestamp"))
        prior = parsed_time(previous.get("observed_at"))
        invalidated = parsed_time(previous.get("invalidated_at"))
        kind = event.get("event")
        try:
            if (not stamp or stamp > utc_now() or (prior and stamp < prior) or
                    (invalidated and stamp < invalidated)):
                raise ValueError("Missing, future or out-of-order cargo timestamp")
            if kind == "Cargo":
                if "Inventory" not in event:
                    if sidecar:
                        raise ValueError("Cargo file lacks its inventory")
                    self._invalidate("cargo", event, "Cargo changed; awaiting its snapshot file")
                    self.blocks["cargo"]["awaiting_snapshot"] = True
                    return
                vessel, inventory = event.get("Vessel"), event["Inventory"]
                if vessel not in ("Ship", "SRV") or not isinstance(inventory, list) or len(inventory) > MAX_CARGO_STACKS:
                    raise ValueError("Unknown vessel or invalid cargo inventory")
                rows, seen = [], set()
                for item in inventory:
                    key = self._cargo_key(item)
                    count, stolen = item.get("Count"), item.get("Stolen")
                    if key in seen or not nonnegative_int(count) or count >= 2 ** 64:
                        raise ValueError("Duplicate cargo stack or invalid count")
                    if "Stolen" in item and (not nonnegative_int(stolen) or stolen > count):
                        raise ValueError("Invalid stolen cargo count")
                    row = {"Name": key[0], "Count": count}
                    if key[1] is not None:
                        row["MissionID"] = key[1]
                    if stolen is not None:
                        row["Stolen"] = stolen
                    if isinstance(item.get("Name_Localised"), str):
                        row["Name_Localised"] = item["Name_Localised"][:240]
                    rows.append(row)
                    seen.add(key)
                total = sum(row["Count"] for row in rows)
                if "Count" in event and (not nonnegative_int(event["Count"]) or event["Count"] != total):
                    raise ValueError("Cargo total differs from its inventory")
                data = {"Vessel": vessel, "Count": total, "Inventory": rows}
                if (sidecar and previous.get("source_file") and prior == stamp and
                        previous.get("requires_refresh") and data == previous.get("data")):
                    return  # Unchanged same-second bytes cannot prove the snapshot has caught up.
            else:
                if not previous or previous.get("requires_refresh") or previous.get("awaiting_snapshot"):
                    raise ValueError("Full cargo snapshot needed before applying a transaction")
                if previous.get("source_file") and prior == stamp:
                    raise ValueError("Snapshot and cargo transaction order is ambiguous")
                data = deepcopy(previous["data"])
                if kind not in ("CollectCargo", "EjectCargo") and data.get("Vessel") != "Ship":
                    raise ValueError("Ship transaction cannot update another vessel's cargo")
                key = self._cargo_key(event)
                count = event.get("Count", 1 if kind in ("CollectCargo", "MiningRefined") else None)
                if not nonnegative_int(count) or not 0 < count < 2 ** 64:
                    raise ValueError("Invalid cargo transaction count")
                rows = data["Inventory"]
                row = next((r for r in rows if self._cargo_key(r) == key), None)
                adding = kind in ("MarketBuy", "BuyDrones", "CollectCargo", "MiningRefined")
                if adding:
                    stolen = event.get("Stolen") if kind == "CollectCargo" else False
                    if not isinstance(stolen, bool):
                        raise ValueError("Scooped cargo ownership is unknown")
                    if row is None:
                        row = {"Name": key[0], "Count": 0, "Stolen": 0}
                        if key[1] is not None:
                            row["MissionID"] = key[1]
                        rows.append(row)
                    row["Count"] += count
                    if "Stolen" in row:
                        row["Stolen"] += count if stolen else 0
                else:
                    if row is None or count > row["Count"]:
                        raise ValueError("Removed cargo exceeds the matching observed stack")
                    stolen = row.get("Stolen")
                    flag = event.get("StolenGoods") if kind == "MarketSell" else None
                    if flag is not None and not isinstance(flag, bool):
                        raise ValueError("Invalid sale ownership flag")
                    if count == row["Count"]:
                        if flag is not None and stolen is not None and (stolen != (count if flag else 0)):
                            raise ValueError("Sale ownership contradicts the observed stack")
                        rows.remove(row)
                    else:
                        if stolen is not None:
                            if flag is True:
                                if count > stolen:
                                    raise ValueError("Sold stolen quantity exceeds observation")
                                row["Stolen"] -= count
                            elif flag is False:
                                if count > row["Count"] - stolen:
                                    raise ValueError("Sold clean quantity exceeds observation")
                            elif stolen == row["Count"]:
                                row["Stolen"] -= count
                            elif stolen != 0:
                                raise ValueError("Mixed-ownership removal needs a fresh snapshot")
                        row["Count"] -= count
                if len(rows) > MAX_CARGO_STACKS or any(row["Count"] >= 2 ** 64 for row in rows):
                    raise ValueError("Cargo inventory bound exceeded")
                data["Count"] = sum(row["Count"] for row in rows)
            self._put("cargo", data, event)
            if sidecar:
                self.blocks["cargo"]["source_file"] = True
            if kind != "Cargo":
                self.blocks["cargo"]["reconciled_from"] = previous.get("reconciled_from", previous.get("observed_at"))
            self.blocks["cargo"]["scope"] = "Observed vessel inventory; mission/stolen quantities do not establish current local legality."
        except (ValueError, TypeError, AttributeError, KeyError):
            safe = event if stamp and stamp <= utc_now() else {"timestamp": previous.get("observed_at")}
            self._invalidate("cargo", safe, "Cargo quantity, identity or event order uncertain; awaiting a full snapshot")

    def _exploration(self, event):
        """Retain independently dated observations for this system visit only."""
        previous = self.blocks.get("exploration", {})
        try:
            location = self.blocks.get("location", {})
            address = location.get("data", {}).get("SystemAddress")
            when = parsed_time(event.get("timestamp"))
            arrived = parsed_time(location.get("observed_at"))
            prior = parsed_time(previous.get("observed_at"))
            if (not nonnegative_int(address) or address == 0 or
                    not when or when > utc_now() or (arrived and when < arrived) or (prior and when < prior) or
                    location.get("data", {}).get("in_transit")):
                raise ValueError("Unknown exploration context")
            if "SystemAddress" in event and (not nonnegative_int(event["SystemAddress"]) or event["SystemAddress"] != address):
                raise ValueError("Exploration system mismatch")

            def observation(fields):
                data = select(event, fields)
                for key, value in data.items():
                    if isinstance(value, str):
                        data[key] = value[:240]
                    elif type(value) not in (bool, int, float) or (isinstance(value, float) and not math.isfinite(value)):
                        raise ValueError("Invalid exploration field")
                return {"observed_at": event["timestamp"], "event": event["event"], "data": data}

            data = dict(previous.get("data", {}))
            data.update(SystemAddress=address,
                        scope="Observed bodies since this system arrival, not a complete catalogue. Organic analyses are historical events, not proof of unsold data, retained partial samples, payout or first-footfall status.",
                        units="DistanceFromArrivalLS: light seconds; SurfaceGravity: m/s^2; SurfaceTemperature: K; SurfacePressure: Pa.")
            kind = event["event"]
            if kind in ("FSSDiscoveryScan", "FSSAllBodiesFound"):
                for field in ("BodyCount", "NonBodyCount", "Count"):
                    if field in event and not nonnegative_int(event[field]):
                        raise ValueError("Invalid system body count")
                if "Progress" in event and (type(event["Progress"]) not in (int, float) or not 0 <= event["Progress"] <= 1):
                    raise ValueError("Invalid scan progress")
                data["system_scan" if kind == "FSSDiscoveryScan" else "all_bodies_found"] = observation("Progress BodyCount NonBodyCount Count")
            else:
                identity = event.get("Body" if kind == "ScanOrganic" else "BodyID")
                if not nonnegative_int(identity):
                    raise ValueError("Missing body identity")
                bodies = list(data.get("bodies", []))
                index = next((i for i, body in enumerate(bodies) if body["BodyID"] == identity), None)
                if index is None and len(bodies) >= MAX_EXPLORATION_BODIES:
                    data["catalogue_limit_reached"] = True
                else:
                    body = deepcopy(bodies[index]) if index is not None else {"BodyID": identity}
                    if "BodyName" in event:
                        name = event["BodyName"]
                        if not isinstance(name, str) or not name or len(name) > 240:
                            raise ValueError("Invalid body name")
                        if body.get("BodyName", name) != name:
                            raise ValueError("Conflicting body identity")
                        body["BodyName"] = name
                    if kind == "Scan":
                        for field in ("SurfaceGravity", "SurfaceTemperature", "SurfacePressure", "DistanceFromArrivalLS"):
                            if field in event and (type(event[field]) not in (int, float) or not math.isfinite(event[field]) or event[field] < 0):
                                raise ValueError("Invalid body measurement")
                        for field in ("Landable", "WasDiscovered", "WasMapped", "WasFootfalled"):
                            if field in event and type(event[field]) is not bool:
                                raise ValueError("Invalid body flag")
                        body["scan"] = observation("ScanType PlanetClass StarType TerraformState Landable Atmosphere AtmosphereType Volcanism SurfaceGravity SurfaceTemperature SurfacePressure DistanceFromArrivalLS WasDiscovered WasMapped WasFootfalled")
                    elif kind == "SAAScanComplete":
                        for field in ("ProbesUsed", "EfficiencyTarget"):
                            if field in event and not nonnegative_int(event[field]):
                                raise ValueError("Invalid mapping observation")
                        body["mapping_completed"] = observation("ProbesUsed EfficiencyTarget")
                    elif kind == "SAASignalsFound":
                        signals = event.get("Signals")
                        if not isinstance(signals, list) or len(signals) > 64:
                            raise ValueError("Invalid surface signals")
                        rows, seen = [], set()
                        for signal in signals:
                            name, count = signal.get("Type"), signal.get("Count")
                            if not isinstance(name, str) or not name or len(name) > 160 or name in seen or not nonnegative_int(count):
                                raise ValueError("Invalid surface signal count or identity")
                            seen.add(name)
                            row = {"Type": name, "Count": count}
                            if isinstance(signal.get("Type_Localised"), str):
                                row["Type_Localised"] = signal["Type_Localised"][:160]
                            rows.append(row)
                        body["surface_signals"] = {"observed_at": event["timestamp"], "Signals": rows}
                    elif kind == "ScanOrganic":
                        species, variant = event.get("Species"), event.get("Variant")
                        if not isinstance(species, str) or not species or len(species) > 160 or (variant is not None and (not isinstance(variant, str) or len(variant) > 160)):
                            raise ValueError("Invalid organic identity")
                        phase = str(event.get("ScanType")).casefold()
                        if phase not in ("log", "sample", "analyse"):
                            raise ValueError("Unknown organic scan phase")
                        organics = body.setdefault("organic_observations", [])
                        organic_index = next((i for i, row in enumerate(organics) if row["data"]["Species"] == species and row["data"].get("Variant") == variant), None)
                        if organic_index is None and len(organics) >= 32:
                            body["organic_limit_reached"] = True
                        else:
                            organic = observation("Genus Genus_Localised Species Species_Localised Variant Variant_Localised ScanType")
                            if phase == "analyse":
                                organic["analysis_observed_at"] = event["timestamp"]
                            elif organic_index is not None and "analysis_observed_at" in organics[organic_index]:
                                organic["analysis_observed_at"] = organics[organic_index]["analysis_observed_at"]
                            if organic_index is None:
                                organics.append(organic)
                            else:
                                organics[organic_index] = organic
                    if index is None:
                        bodies.append(body)
                    else:
                        bodies[index] = body
                    data["bodies"] = bodies
            self._put("exploration", data, event)
            if previous.get("requires_refresh"):
                self._invalidate("exploration", event, "Journal gap; observations since this arrival may be incomplete")
        except (ValueError, TypeError, AttributeError, KeyError):
            self.data_warnings.add("Unmatched or malformed exploration event ignored; system observations may be incomplete.")

    def apply(self, event):
        """Project a journal event without exposing text chat or Frontier identifiers."""
        kind = event.get("event", "")
        if kind in ("Commander", "LoadGame"):
            identity = event.get("FID")
            name = event.get("Commander") or event.get("Name")
            changed = (identity and self.commander_id and identity != self.commander_id) or (
                not identity and name and self.commander_name and name != self.commander_name)
            if changed:
                version, galaxy, odyssey, started = (
                    self.game_version, self.galaxy, self.odyssey, event.get("timestamp", self.session_started))
                self._reset()
                self.game_version, self.galaxy, self.odyssey, self.session_started = (
                    version, galaxy, odyssey, started)
            if identity:
                self.commander_id = identity
            if name:
                self.commander_name = name
        self.last_event = kind
        self.last_timestamp = event.get("timestamp", self.last_timestamp)
        if kind in ("Backpack", "BackpackMaterials", "BackpackChange", "ShipLocker", "ShipLockerMaterials"):
            block = "backpack" if kind.startswith("Backpack") else "ship_locker"
            if kind == "BackpackChange" or any(key in event for key in MICRO_CATEGORIES):
                self._microresources(block, event)
            else:
                self._invalidate(block, event, "Inventory changed; awaiting its snapshot file")
                self.blocks[block]["awaiting_snapshot"] = True
        if kind in ("TransferMicroResources", "BuyMicroResources", "SellMicroResources", "TradeMicroResources",
                    "UpgradeSuit", "UpgradeWeapon", "EngineerSuit", "EngineerWeapon", "Died", "Resurrect"):
            self._invalidate("ship_locker", event, "Inventory may have changed; awaiting full locker observation")
        if kind in ("Died", "Resurrect"):
            self._invalidate("backpack", event, "Awaiting backpack observation after death or resurrection")
        if kind == "MissionCompleted" and "MicroResourceReward" in event:
            self._invalidate("ship_locker", event, "Mission reward; awaiting full locker observation")
        if kind in ("SuitLoadout", "SwitchSuitLoadout"):
            data = select(event, "SuitID SuitName SuitName_Localised SuitMods LoadoutID LoadoutName")
            if "Modules" in event:
                data["Modules"] = [select(m, "SlotName SuitModuleID ModuleName ModuleName_Localised Class WeaponMods")
                                   for m in event["Modules"] if isinstance(m, dict)]
            self._put("suit", data, event)
        elif kind in ("DeleteSuitLoadout", "RenameSuitLoadout", "LoadoutEquipModule", "LoadoutRemoveModule",
                      "SellSuit", "SellWeapon", "UpgradeSuit", "UpgradeWeapon", "EngineerSuit", "EngineerWeapon"):
            self._invalidate("suit", event, "Equipment changed; awaiting current suit loadout")
        # Transactions also affect other blocks (missions, ship, market). Do not
        # put reconciliation in the mutually exclusive event projection below.
        if (kind in ("Materials", "MaterialCollected", "MaterialDiscarded", "ScientificResearch",
                     "MaterialTrade", "EngineerCraft", "EngineerLegacyConvert", "Synthesis") or
                (kind == "EngineerContribution" and "Material" in event) or
                (kind == "MissionCompleted" and "MaterialsReward" in event) or
                (kind == "TechnologyBroker" and ("Materials" in event or "Ingredients" in event))):
            self._materials(event)
        if kind in ("ShipyardSwap", "ShipyardNew", "ShipyardBuy", "Resurrect", "Died"):
            self._invalidate("ship", event, "Ship changed; awaiting its loadout")
            self._invalidate("cargo", event, "Ship changed; awaiting its cargo observation")
        elif (kind in ("ModuleBuy", "ModuleSell", "ModuleStore", "ModuleRetrieve", "ModuleSwap", "MassModuleStore") or
              (kind in ("EngineerCraft", "EngineerLegacyConvert") and event.get("IsPreview") is not True)):
            self._invalidate("ship", event, "Loadout changed; awaiting updated capacity, rebuy and module observations")
        if (kind in ("SearchAndRescue", "PowerplayCollect", "PowerplayDeliver") or
                (kind == "CargoDepot" and event.get("UpdateType") != "WingUpdate") or
                (kind == "MissionCompleted" and "CommodityReward" in event) or
                (kind == "EngineerContribution" and "Commodity" in event) or
                (kind == "TechnologyBroker" and ("Commodities" in event or "Ingredients" in event))):
            self._invalidate("cargo", event, "Cargo transaction; awaiting a full cargo observation")
        if kind in ("LaunchSRV", "DockSRV", "VehicleSwitch", "LaunchDrone", "Synthesis", "CargoTransfer"):
            self._invalidate("cargo", event, "Cargo or vessel context changed; awaiting its snapshot")
        if (kind in ("MissionCompleted", "MissionFailed", "MissionAbandoned") and
                any(row.get("MissionID") == event.get("MissionID") for row in
                    self.blocks.get("cargo", {}).get("data", {}).get("Inventory", []))):
            self._invalidate("cargo", event, "Mission cargo disposition changed; awaiting its snapshot")
        if kind.lower() == "fileheader":
            if not self.session_started:
                self.session_started = event.get("timestamp", "")
            self.game_version = str(event.get("gameversion", ""))
            self.galaxy = ("live" if self.game_version.startswith("4.") else
                           "legacy" if self.game_version.startswith(("3.", "2.")) else "unknown")
            self.odyssey = event.get("Odyssey", event.get("odyssey"))
        elif kind == "LoadGame":
            self.running = True
            self._put("pilot", select(event, "GameMode Ship ShipID Credits Loan"), event)
        elif kind == "Shutdown":
            self.running = False
        elif kind in ("Location", "FSDJump", "CarrierJump"):
            self._put("location", select(event,
                "StarSystem SystemAddress StarPos Body BodyType Docked StationName StationType MarketID"), event)
            # Destination-specific observations must not survive a system change.
            for block in ("market", "outfitting", "shipyard", "exploration"):
                self.blocks.pop(block, None)
            target = self.blocks.get("navigation", {})
            if (event.get("SystemAddress") is not None and
                    target.get("data", {}).get("SystemAddress") == event["SystemAddress"]):
                self.blocks.pop("navigation", None)
        elif kind == "Docked":
            data = dict(self.blocks.get("location", {}).get("data", {}))
            data.update(select(event, "StarSystem SystemAddress StationName StationType MarketID StationServices LandingPads"))
            data["Docked"] = True
            self._put("location", data, event)
        elif kind in ("Undocked", "StartJump"):
            data = dict(self.blocks.get("location", {}).get("data", {}))
            for key in ("StationName", "StationType", "MarketID", "StationServices", "LandingPads"):
                data.pop(key, None)
            data["Docked"] = False
            if kind == "StartJump" and event.get("JumpType") != "Supercruise":
                data["in_transit"] = True
                self.blocks.pop("exploration", None)
            self._put("location", data, event)
            for block in ("market", "outfitting", "shipyard"):
                self.blocks.pop(block, None)
        elif kind in ("SupercruiseEntry", "SupercruiseExit"):
            data = dict(self.blocks.get("location", {}).get("data", {}))
            address = event.get("SystemAddress", data.get("SystemAddress"))
            if nonnegative_int(address) and address != data.get("SystemAddress"):
                self.blocks.pop("exploration", None)
                data = {}
            if kind == "SupercruiseEntry":
                for field in ("Body", "BodyID", "BodyType"):
                    data.pop(field, None)
            data.update(select(event, "StarSystem SystemAddress Body BodyID BodyType"))
            data["in_transit"] = False
            self._put("location", data, event)
        elif kind == "Loadout":
            old_id = self.blocks.get("ship", {}).get("data", {}).get("ShipID")
            if old_id is not None and event.get("ShipID") is not None and old_id != event["ShipID"]:
                self._invalidate("cargo", event, "Ship changed; awaiting its cargo observation")
            data = select(event, "Ship ShipID ShipName HullHealth UnladenMass CargoCapacity MaxJumpRange FuelCapacity Rebuy")
            data["Modules"] = [select(m, "Slot Item Health Engineering") for m in event.get("Modules", []) if isinstance(m, dict)]
            self._put("ship", data, event)
        elif kind == "EngineerProgress":
            self._engineers(event)
        elif kind in ("Rank", "Promotion", "Progress", "Reputation"):
            self._career(event)
        elif kind == "Powerplay":
            self._put("powerplay", select(event, "Power Rank Merits Votes TimePledged"), event)
        elif kind in ("Cargo", "MarketBuy", "MarketSell", "BuyDrones", "SellDrones", "CollectCargo", "EjectCargo", "MiningRefined"):
            self._cargo(event)
            if kind in ("MarketBuy", "MarketSell") and "market" in self.blocks:
                self.blocks["market"]["requires_refresh"] = True
                self.blocks["market"]["invalidated_at"] = event.get("timestamp")
        elif kind in ("Missions", "MissionAccepted", "MissionRedirected", "CargoDepot", "MissionCompleted", "MissionAbandoned", "MissionFailed"):
            self._missions(event)
        elif kind == "NavRoute":
            if "Route" in event:
                self._route_snapshot(event)
            else:
                self._invalidate("route", event, "Route changed; awaiting its snapshot file")
                self.blocks["route"]["awaiting_snapshot"] = True
        elif kind in ("FSDTarget", "NavRouteClear"):
            self._put("navigation", select(event, "Name SystemAddress StarClass RemainingJumpsInRoute"), event)
            if kind == "NavRouteClear":
                self._put("route", {"Route": []}, event)
        elif kind in ("Scan", "SAASignalsFound", "SAAScanComplete", "ScanOrganic", "FSSDiscoveryScan", "FSSAllBodiesFound"):
            self._exploration(event)

    def refresh(self):
        """Tail complete lines only. Return fresh events, never initial replay events."""
        with self.lock:
            self.errors.clear()
            try:
                keyed = [(journal_order(p), p) for p in self.directory.glob("Journal.*.log")]
                paths = [p for key, p in sorted((key, p) for key, p in keyed if key is not None)]
                if not paths:
                    self.errors.add("No journal files found; configure the journal directory.")
                    return []
                session = paths[-1].name.rsplit(".", 2)[0]
                initial = session != self.session
                if initial:
                    self.session = session
                    self.offsets.clear()
                    self._reset()
                parts = [p for p in paths if p.name.rsplit(".", 2)[0] == session]
                # Detect truncation before replaying any part of the session.
                if any(p.stat().st_size < self.offsets.get(p.name, 0) for p in parts):
                    self.offsets.clear()
                    self._reset()
                    initial = True
                events = []
                consumed = 0
                was_catching_up = self.catch_up
                self.catch_up = False
                for path in parts:
                    with path.open("rb") as handle:
                        handle.seek(self.offsets.get(path.name, 0))
                        while consumed < MAX_BATCH:
                            start = handle.tell()
                            line = handle.readline(MAX_LINE + 1)
                            if not line:
                                break
                            if len(line) > MAX_LINE:
                                self.errors.add("Oversized journal record; ingestion paused.")
                                self.catch_up = True
                                break
                            if not line.endswith(b"\n"):
                                break  # Retry this byte offset after the writer finishes.
                            consumed += len(line)
                            self.offsets[path.name] = start + len(line)
                            try:
                                event = json.loads(line)
                                if not isinstance(event, dict) or not isinstance(event.get("event"), str):
                                    raise ValueError("Expected journal event object")
                                self.apply(event)
                                if not initial and not was_catching_up:
                                    events.append(event)
                            except (ValueError, TypeError, KeyError, AttributeError):
                                self.data_warnings.add("Malformed journal record skipped; state may be incomplete.")
                                for block in ("materials", "cargo", "ship", "engineerprogress", "backpack", "ship_locker", "suit", "exploration", "route", "navigation", "location", "missions", "rank", "progress", "reputation"):
                                    if block in self.blocks:
                                        self._invalidate(block, {"timestamp": self.last_timestamp},
                                                         "Journal gap; a full observation is needed")
                    if consumed >= MAX_BATCH or self.catch_up:
                        self.catch_up = True
                        break
                self._sidecars()
                return events if not self.catch_up else []
            except OSError:
                self.errors.add("Journal files unavailable; last observations may be stale.")
                return []

    def _sidecars(self):
        # Reading historical sidecars after shutdown/commander changes risks mixing
        # sessions. Historical journal observations remain available separately.
        self.blocks.pop("status", None)
        if not self.running or not parsed_time(self.session_started):
            return
        for filename, block, fields in (
            ("Status.json", "status", "Flags Flags2 Pips FireGroup GuiFocus Fuel Cargo LegalState Balance Latitude Longitude Altitude BodyName PlanetRadius Oxygen Health Temperature SelectedWeapon"),
            ("Cargo.json", "cargo", "Vessel Count Inventory"),
            ("NavRoute.json", "route", "Route"),
            ("ShipLocker.json", "ship_locker", "Items Components Consumables Data"),
            ("Backpack.json", "backpack", "Items Components Consumables Data"),
            ("Market.json", "market", "MarketID StationName StarSystem Items"),
        ):
            if block == "cargo" and self.catch_up:
                continue  # A current snapshot can be ahead of the journal batch being replayed.
            try:
                with (self.directory / filename).open("rb") as handle:
                    raw = handle.read(MAX_LINE + 1)
                if len(raw) > MAX_LINE:
                    raise ValueError("Oversized snapshot")
                data = json.loads(raw)
                stamp = parsed_time(data.get("timestamp"))
                if not stamp or stamp < parsed_time(self.session_started):
                    continue
                if block == "market":
                    location = self.blocks.get("location", {}).get("data", {})
                    location_time = parsed_time(self.blocks.get("location", {}).get("observed_at"))
                    if (location.get("Docked") is not True or not location.get("MarketID") or
                            data.get("MarketID") != location["MarketID"] or
                            data.get("StarSystem") != location.get("StarSystem") or
                            (location_time and stamp < location_time)):
                        continue
                prior = self.blocks.get(block, {})
                prior_stamp = parsed_time(prior.get("observed_at"))
                if prior_stamp and (stamp < prior_stamp or (stamp == prior_stamp and not prior.get("awaiting_snapshot"))):
                    continue
                invalidated = parsed_time(prior.get("invalidated_at"))
                if invalidated and stamp < invalidated:
                    continue
                if block == "cargo":
                    if data.get("event") != "Cargo":
                        raise ValueError("Cargo snapshot event does not match its file")
                    self._cargo(data, sidecar=True)
                elif block == "route":
                    self._route_snapshot(data)
                elif block in ("backpack", "ship_locker"):
                    if data.get("event") != ("Backpack" if block == "backpack" else "ShipLocker"):
                        raise ValueError("Inventory snapshot event does not match its file")
                    self._microresources(block, data, sidecar=True)
                else:
                    self._put(block, select(data, fields), data)
            except FileNotFoundError:
                continue
            except (OSError, ValueError, AttributeError, TypeError):
                self.errors.add(f"{filename} unavailable or incomplete.")
                if block == "cargo":
                    prior = self.blocks.get("cargo", {})
                    self._invalidate("cargo", {"timestamp": prior.get("observed_at")},
                                     "Cargo file unavailable or incomplete; awaiting a full snapshot")
                if block == "route":
                    prior = self.blocks.get("route", {})
                    self._invalidate("route", {"timestamp": prior.get("observed_at")},
                                     "Route file unavailable or incomplete; awaiting its snapshot")
                    self.blocks["route"]["awaiting_snapshot"] = True

    def _route_snapshot(self, event):
        """Accept a complete bounded route atomically, including sidecar clear events."""
        previous = self.blocks.get("route", {})
        stamp = parsed_time(event.get("timestamp"))
        prior = parsed_time(previous.get("observed_at"))
        invalidated = parsed_time(previous.get("invalidated_at"))
        if stamp and ((prior and stamp < prior) or (invalidated and stamp < invalidated)):
            return
        try:
            if not stamp or stamp > utc_now():
                raise ValueError("Invalid route timestamp")
            if event.get("event") == "NavRouteClear":
                self._put("route", {"Route": []}, event)
                target_time = parsed_time(self.blocks.get("navigation", {}).get("observed_at"))
                if not target_time or target_time <= stamp:
                    self._put("navigation", {}, event)
                return
            if event.get("event") != "NavRoute":
                raise ValueError("Unexpected route event")
            rows = event.get("Route")
            if not isinstance(rows, list) or len(rows) > MAX_ROUTE_SYSTEMS:
                raise ValueError("Missing or oversized route")
            clean = []
            for row in rows:
                name, address, pos = row.get("StarSystem"), row.get("SystemAddress"), row.get("StarPos")
                if (not isinstance(name, str) or not 0 < len(name) <= 128 or
                        not nonnegative_int(address) or not 0 < address < 2 ** 64 or
                        not isinstance(pos, list) or len(pos) != 3 or
                        not all(finite_number(v) and abs(v) <= 1_000_000 for v in pos)):
                    raise ValueError("Invalid route system")
                item = {"StarSystem": name, "SystemAddress": address, "StarPos": pos}
                star = row.get("StarClass")
                if isinstance(star, str) and 0 < len(star) <= 64:
                    item["StarClass"] = star
                clean.append(item)
            if (previous.get("awaiting_snapshot") and stamp == prior and
                    clean == previous.get("data", {}).get("Route")):
                return  # Same-second unchanged file cannot establish the newly plotted route.
            self._put("route", {"Route": clean}, event)
        except (ValueError, TypeError, AttributeError):
            safe_event = event if stamp and stamp <= utc_now() else {"timestamp": previous.get("observed_at")}
            self._invalidate("route", safe_event, "Route snapshot malformed; awaiting a complete route")
            self.blocks["route"]["awaiting_snapshot"] = True

    def _route_view(self, now):
        block = self.blocks["route"]
        rows = block.get("data", {}).get("Route", [])
        location = self.blocks.get("location", {})
        current = location.get("data", {})
        output = {"plotted_systems": len(rows), "Route": [],
                  "scope": "Remaining plotted stops, not verified reachable jumps. Distances are geometric light years."}
        age = age_seconds(block.get("observed_at"), now)
        loc_age = age_seconds(location.get("observed_at"), now)
        if block.get("requires_refresh") or age is None or age < 0:
            output["progress"] = "awaiting_route_snapshot"
        elif not rows:
            output["progress"] = "no_plotted_route"
        elif (location.get("requires_refresh") or loc_age is None or loc_age < 0 or current.get("in_transit")):
            output["progress"] = "location_unconfirmed_or_in_transit"
        else:
            address = current.get("SystemAddress")
            matches = [i for i, row in enumerate(rows) if nonnegative_int(address) and row["SystemAddress"] == address]
            if len(matches) != 1:
                output["progress"] = "current_system_absent_or_ambiguous"
            else:
                index = matches[0]
                remaining = rows[index + 1:]
                output.update(progress="at_plotted_destination" if not remaining else "on_plotted_route",
                              remaining_jumps=len(remaining), destination=select(rows[-1], "StarSystem SystemAddress"),
                              location_observed_at=location.get("observed_at"))
                distances = [math.dist(a["StarPos"], b["StarPos"]) for a, b in zip(rows[index:], rows[index + 1:])]
                output["remaining_distance_ly"] = round(sum(distances), 3)
                target = self.blocks.get("navigation", {})
                target_age = age_seconds(target.get("observed_at"), now)
                target_address = target.get("data", {}).get("SystemAddress")
                if (remaining and not target.get("requires_refresh") and nonnegative_int(target_address) and
                        target_age is not None and 0 <= target_age <= age):
                    output["selected_target_matches_next_stop"] = target_address == remaining[0]["SystemAddress"]
                output["Route"] = [{**select(row, "StarSystem SystemAddress StarClass"),
                                    "leg_distance_ly": round(distance, 3)} for row, distance in zip(remaining, distances)]
                # Exact standard classes only; no conclusion about other stars in the system.
                for jumps, row in enumerate(remaining, 1):
                    if row.get("StarClass") in ("O", "B", "A", "F", "G", "K", "M"):
                        output["next_standard_scoop_star"] = {
                            **select(row, "StarSystem StarClass"), "jumps_ahead": jumps,
                            "scope": "Primary star class only; fuel scoop equipment and ability to reach it are unverified."}
                        break
        return {**block, "data": output}

    def _travel(self, now):
        output = {"scope": "Dated fuel and unladen range; current jump feasibility and fuel endurance are unknown."}
        for name in ("ship", "status"):
            block = self.blocks.get(name, {})
            age = age_seconds(block.get("observed_at"), now)
            if block.get("requires_refresh") or age is None or age < 0:
                continue
            data = block.get("data", {})
            values = {}
            if name == "ship":
                value = data.get("MaxJumpRange")
                if finite_number(value) and value >= 0:
                    values["unladen_max_jump_range_ly"] = value
                capacity = data.get("FuelCapacity")
                if isinstance(capacity, dict):
                    values["fuel_capacity_tonnes"] = {k: v for k, v in capacity.items()
                        if k in ("Main", "Reserve") and finite_number(v) and v >= 0}
            else:
                flags, flags2 = data.get("Flags"), data.get("Flags2", 0)
                ship = self.blocks.get("ship", {})
                changed = parsed_time(ship.get("invalidated_at"))
                loaded = parsed_time(ship.get("observed_at"))
                status_time = parsed_time(block.get("observed_at"))
                if (changed and status_time <= changed) or (loaded and status_time < loaded):
                    continue
                if (not nonnegative_int(flags) or not flags & (1 << 24) or flags & ((1 << 25) | (1 << 26)) or
                        not nonnegative_int(flags2) or flags2 & 7):
                    continue  # Do not label taxi/fighter/SRV readings as the pilot's main ship.
                fuel = data.get("Fuel")
                if isinstance(fuel, dict):
                    values["fuel_tonnes"] = {k: v for k, v in fuel.items()
                        if k in ("FuelMain", "FuelReservoir") and finite_number(v) and v >= 0}
                values["low_fuel_flag"] = bool(flags & (1 << 19))
                values["scooping_flag"] = bool(flags & (1 << 11))
            if values:
                output[name] = {"observed_at": block.get("observed_at"), "age_seconds": age, **values}
        return output

    def snapshot(self, topic="overview", query="", now=None):
        with self.lock:
            now = now or utc_now()
            age = age_seconds(self.last_timestamp, now)
            session_state = ("offline" if not self.running else
                             "recent_observation" if age is not None and 0 <= age <= 300 else
                             "unconfirmed")
            result = {
                "source": "Elite Dangerous local Player Journal",
                "retrieved_at": now.isoformat(), "observed_at": self.last_timestamp or None,
                "age_seconds": age, "session": session_state,
                "galaxy": self.galaxy, "game_version": self.game_version,
                "odyssey": self.odyssey, "catching_up": self.catch_up,
                "scope": "Latest journal session only; missing fields are unknown. Values are observations, not live guarantees.",
            }
            topics = {
                "overview": ("location", "ship", "status"),
                "ship": ("ship", "status"), "cargo": ("cargo",),
                "materials": ("materials", "ship_locker"),
                "progression": ("pilot", "reputation", "engineerprogress", "powerplay"),
                "missions": ("missions", "mission_outcomes"), "navigation": ("location", "navigation", "route"),
                "exploration": ("location", "exploration"),
                "market": ("location", "market"),
                "planning": (),
                "odyssey": ("suit", "backpack", "ship_locker", "status"),
            }
            if topic not in topics:
                result["error"] = "Unknown topic. Choose: " + ", ".join(topics)
                return result
            if self.errors or self.data_warnings:
                result["warnings"] = sorted(self.errors | self.data_warnings)
            if topic == "planning":
                result["planning"] = self._planning(now)
            elif topic == "navigation":
                result["travel"] = self._travel(now)
            elif topic == "progression" and ("rank" in self.blocks or "progress" in self.blocks):
                data = self._career_view(now)
                if query:
                    data = self._filter(data, query.casefold())
                result["career"] = compact(data)
            for name in topics[topic]:
                if name not in self.blocks:
                    continue
                block = self.blocks[name]
                if name == "route":
                    block = self._route_view(now)
                data = block["data"]
                if name == "missions":
                    data = self._mission_view(now)
                if name in ("backpack", "ship_locker"):
                    data = public_inventory(data)
                if topic == "overview" and name == "ship":
                    data = {k: v for k, v in data.items() if k != "Modules"}
                if query:
                    data = self._filter(data, query.casefold())
                result[name] = {**block, "data": compact(data), "age_seconds": age_seconds(block.get("observed_at"), now)}
                if name == "status":
                    flags = block["data"].get("Flags")
                    flags2 = block["data"].get("Flags2")
                    result[name]["set_flags"] = [label for bit, label in STATUS_FLAGS.items()
                                                  if isinstance(flags, int) and flags & (1 << bit)]
                    result[name]["set_flags"] += [label for bit, label in STATUS_FLAGS2.items()
                                                   if isinstance(flags2, int) and flags2 & (1 << bit)]
                    result[name]["age_seconds"] = age_seconds(block["observed_at"], now)
                elif name == "market":
                    result[name]["age_seconds"] = age_seconds(block["observed_at"], now)
                    result[name]["price_meaning"] = "BuyPrice: player pays per tonne; SellPrice: player receives per tonne. Stock/Demand are dated observations."
            return result

    def _planning(self, now):
        """Combine independently dated resource observations, without a credit ledger guess."""
        output = {"unverified": ["required landing pad", "user's desired cash reserve", "permits and docking access"]}

        def observation(block, field):
            value = block.get("data", {}).get(field)
            if field == "Cargo" and isinstance(value, float) and value.is_integer():
                value = int(value)
            age = age_seconds(block.get("observed_at"), now)
            if block.get("requires_refresh") or not nonnegative_int(value) or age is None or age < 0:
                return None
            return {"value": value, "observed_at": block.get("observed_at"), "age_seconds": age,
                    "event": block.get("event")}

        pilot, status, ship, cargo = (self.blocks.get(n, {}) for n in ("pilot", "status", "ship", "cargo"))
        balances = [b for b in (observation(pilot, "Credits"), observation(status, "Balance")) if b]
        if balances:
            output["credits"] = min(balances, key=lambda b: b["age_seconds"])
            output["credits"]["scope"] = "Dated balance observation; later transactions may change it."
        rebuy, capacity = observation(ship, "Rebuy"), observation(ship, "CargoCapacity")
        if rebuy:
            output["ship_rebuy"] = rebuy
        if capacity:
            output["ship_cargo_capacity"] = capacity
        carried = observation(cargo, "Count") if cargo.get("data", {}).get("Vessel") == "Ship" else None
        flags = status.get("data", {}).get("Flags")
        flags2 = status.get("data", {}).get("Flags2", 0)
        if (nonnegative_int(flags) and flags & (1 << 24) and not flags & ((1 << 25) | (1 << 26)) and
                nonnegative_int(flags2) and not flags2 & 7):
            current = observation(status, "Cargo")
            invalidated = parsed_time(cargo.get("invalidated_at"))
            if current and invalidated and parsed_time(current["observed_at"]) <= invalidated:
                current = None  # Older dashboard cargo cannot repair a known inventory change.
            if current and (not carried or current["age_seconds"] < carried["age_seconds"]):
                carried = current
        if carried:
            output["ship_cargo_carried"] = carried
        if carried and capacity and carried["value"] <= capacity["value"]:
            output["free_cargo_tonnes"] = {
                "value": capacity["value"] - carried["value"],
                "derived_from": {"capacity_observed_at": capacity["observed_at"], "cargo_observed_at": carried["observed_at"]},
                "scope": "Derived from separate observations; verify freshness and current ship before use."}
        return output

    @staticmethod
    def _filter(value, query):
        if isinstance(value, list):
            return [v for v in value if query in json.dumps(v, ensure_ascii=False).casefold()]
        if isinstance(value, dict):
            return {k: JournalReader._filter(v, query) if isinstance(v, (dict, list)) else v
                    for k, v in value.items()}
        return value

    def summary(self, topic="overview", query="", now=None):
        result = self.snapshot(topic, query, now)
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > MAX_RESULT:
            result = shrink_summary(result)
            result["truncated"] = "Narrow the topic/query for additional observations."
            encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > MAX_RESULT:
            # Preserve valid JSON and provenance rather than slicing a JSON string.
            return json.dumps({k: result[k] for k in ("source", "observed_at", "session", "galaxy", "truncated")})
        return encoded
