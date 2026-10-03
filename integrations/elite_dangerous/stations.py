"""Spansh station observations and deterministic, conditional trade comparisons.

Contract: https://docs.spansh.co.uk/ (OpenAPI 3.1.1, checked 2026-09-27).
buy_price is what the player PAYS; sell_price is what the player RECEIVES.
"""

from datetime import datetime, timezone
import json
import math
import re
import sqlite3


SPANSH = "https://spansh.co.uk"
MAX_OUTPUT = 9000
STATION_FIELDS = (
    "market_id", "name", "system_name", "system_id64", "type", "distance_to_arrival",
    "is_planetary", "body_name", "body_gravity", "large_pads", "medium_pads", "small_pads",
    "has_large_pad", "has_market", "has_outfitting", "has_shipyard", "carrier_docking_access",
    "material_trader", "technology_broker",
    "updated_at",
)


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp if stamp.tzinfo else None
    except ValueError:
        return None


def canonical_id(value):
    """IDs are decimal strings in tool schemas to preserve unsigned 64-bit values."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("Supply a decimal market ID from telemetry or a station lookup.")
    text = str(value)
    if not re.fullmatch(r"[0-9]{1,20}", text) or not 0 < int(text) < 2**64:
        raise ValueError("Supply a positive unsigned 64-bit market ID.")
    return str(int(text))


def number(value, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and value >= 0 and (not integer or int(value) == value)
    except OverflowError:
        return False


def bounded(result):
    """Preserve provenance and valid JSON if upstream adds unexpectedly long fields."""
    if len(json.dumps(result, ensure_ascii=False)) <= MAX_OUTPUT:
        return result
    result = {k: v for k, v in result.items() if k not in ("items", "station", "candidates")}
    result["error"] = "Result exceeds output limit; narrow the item filter."
    if len(json.dumps(result, ensure_ascii=False)) > MAX_OUTPUT:
        return {"error": "Provider response exceeds output limit.", "source": "https://docs.spansh.co.uk/"}
    return result


def freshness(value, now, max_age_hours):
    stamp = timestamp(value)
    age = (now - stamp).total_seconds() if stamp else None
    return {"observed_at": value if stamp else None,
            "age_seconds": round(age) if age is not None else None,
            "freshness": "unknown" if age is None else "future_timestamp" if age < -60 else
                         "stale" if age > max_age_hours * 3600 else "within_requested_age"}


def pad_access(record, pad):
    sizes = {"S": ("small_pads", "medium_pads", "large_pads"),
             "M": ("medium_pads", "large_pads"), "L": ("large_pads",)}[pad]
    values = [record.get(key) for key in sizes]
    if any(number(v, integer=True) and v > 0 for v in values) or record.get("has_large_pad") is True:
        return "reported_compatible"
    if all(number(v, integer=True) and v == 0 for v in values):
        return "reported_incompatible"
    if pad == "L" and record.get("has_large_pad") is False:
        return "reported_incompatible"
    return "unknown"


class StationData:
    def __init__(self, public_data, clock=utc_now):
        self.public = public_data
        self.clock = clock

    def _record(self, market_id):
        market_id = canonical_id(market_id)
        url = f"{SPANSH}/api/station/{market_id}"
        now = self.clock()
        meta = {"provider": "Spansh", "source": url, "retrieved_at": now.isoformat(),
                "galaxy_policy": "Live only; community response does not independently identify galaxy."}
        try:
            payload, fetched, cached, error = self.public._fetch(url)
            meta.update(fetched_at=datetime.fromtimestamp(fetched, timezone.utc).isoformat() if fetched else None,
                        cache_hit=cached, stale_fallback=bool(error and payload is not None))
        except (OSError, sqlite3.Error, ValueError):
            return None, {**meta, "error": "Local provider cache unavailable; query not completed."}
        if error:
            meta["error"] = error
        record = payload.get("record") if isinstance(payload, dict) else None
        if not isinstance(record, dict):
            return None, {**meta, "found": False, "error": meta.get("error", "No usable station record returned.")}
        try:
            if canonical_id(record.get("market_id")) != market_id:
                raise ValueError("mismatch")
        except ValueError:
            return None, {**meta, "error": "Provider station identity does not match the requested market ID."}
        return record, {**meta, "found": True}

    def station(self, market_id, section="overview", query="", max_age_hours=24, galaxy="live"):
        if galaxy != "live":
            return {"error": "Station queries support Live only; Legacy/unknown galaxy is unsupported."}
        fields = {
            "market": ("commodity", "category", "buy_price", "sell_price", "supply", "demand", "is_rare"),
            "outfitting": ("name", "class", "rating", "category", "ed_symbol", "ship", "weapon_mode", "price"),
            "shipyard": ("name", "symbol", "price"),
        }
        if section not in ("overview", *fields):
            return {"error": "Choose overview, market, outfitting or shipyard."}
        if not isinstance(query, str) or len(query) > 128:
            return {"error": "Use an item filter of at most 128 characters."}
        if not number(max_age_hours) or not 0 < max_age_hours <= 168:
            return {"error": "Choose a maximum observation age greater than 0 and at most 168 hours."}
        try:
            record, result = self._record(market_id)
        except ValueError as exc:
            return {"error": str(exc)}
        if record is None:
            return result
        result["station"] = {k: record[k] for k in STATION_FIELDS if k in record}
        result["warning"] = "Community observation, not a guarantee of access, prices or availability. Recheck in game."
        dates = {"overview": "updated_at", "market": "market_updated_at",
                 "outfitting": "outfitting_updated_at", "shipyard": "shipyard_updated_at"}
        result.update(freshness(record.get(dates[section]), self.clock(), max_age_hours))
        if section == "overview":
            services = record.get("services")
            if isinstance(services, list):
                result["services"] = [s["name"][:100] for s in services[:40]
                                      if isinstance(s, dict) and isinstance(s.get("name"), str)]
                result["services_omitted"] = max(0, len(services) - 40)
            result["dataset_observed_at"] = {k: record.get(v) for k, v in dates.items()}
        else:
            key = {"market": "market", "outfitting": "modules", "shipyard": "ships"}[section]
            rows = record.get(key)
            if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
                result["error"] = "Requested dataset is unavailable or malformed; absence is not proof of no stock."
                return bounded(result)
            selected = [{k: r[k] for k in fields[section] if k in r} for r in rows]
            # Token-wise filter supports '5A frame shift' as well as item names.
            terms = query.casefold().split()
            def matches(row):
                text = " ".join(str(v) for v in row.values()).casefold()
                text += " " + str(row.get("class", "")) + str(row.get("rating", "")).casefold()
                return all(term in text for term in terms)
            selected = [r for r in selected if matches(r)]
            result.update(section=section, matched=len(selected), omitted=max(0, len(selected)-5), items=selected[:5])
            if section == "market":
                result["price_meaning"] = "buy_price: credits paid by player per tonne; sell_price: credits received by player per tonne."
        return bounded(result)

    def trade(self, origin_market_id, destination_market_id, free_cargo_tonnes,
              credits, rebuy_reserve, ship_pad, commodity="", max_age_hours=24, galaxy="live"):
        """Rank independent single-commodity cargo options for one specified leg."""
        if galaxy != "live":
            return {"error": "Trade comparisons support Live only; Legacy/unknown galaxy is unsupported."}
        if not number(free_cargo_tonnes, integer=True) or not 0 < free_cargo_tonnes <= 25000:
            return {"error": "Supply observed free cargo space, from 1 to 25000 whole tonnes."}
        if not number(credits, integer=True) or not number(rebuy_reserve, integer=True) or rebuy_reserve > credits:
            return {"error": "Supply observed whole credits and a nonnegative reserve no greater than credits."}
        if ship_pad not in ("S", "M", "L"):
            return {"error": "Supply the ship's required pad: S, M or L."}
        if not isinstance(commodity, str) or len(commodity) > 128 or not number(max_age_hours) or not 0 < max_age_hours <= 168:
            return {"error": "Use a commodity filter up to 128 characters and an observation age in (0, 168] hours."}
        try:
            origin_id, destination_id = canonical_id(origin_market_id), canonical_id(destination_market_id)
            if origin_id == destination_id:
                return {"error": "Origin and destination must be different stations."}
            origin, origin_meta = self._record(origin_id)
            destination, destination_meta = self._record(destination_id)
        except ValueError as exc:
            return {"error": str(exc)}
        result = {"origin": origin_meta, "destination": destination_meta, "candidates": [],
                  "inputs": {"free_cargo_tonnes": free_cargo_tonnes, "credits": credits,
                             "rebuy_reserve": rebuy_reserve, "ship_pad": ship_pad},
                  "scope": "One specified leg, independent single-commodity options, ranked by estimated gross profit. Not a galaxy-wide route search or combined shopping list.",
                  "unverified": ["Commander permits and docking access", "Planetary access and approach suitability",
                                 "Commodity legality at both stations", "Actual stock, demand and price on arrival"],
                  "profit_basis": "Gross proceeds minus purchase cost; excludes fuel, repairs, fees and price changes."}
        blockers = []
        now = self.clock()
        for label, record, meta in (("origin", origin, origin_meta), ("destination", destination, destination_meta)):
            if record is None:
                blockers.append(f"{label}: station data unavailable")
                continue
            meta.update({k: record[k] for k in STATION_FIELDS if k in record})
            meta.update(freshness(record.get("market_updated_at"), now, max_age_hours))
            meta["pad_assessment"] = pad_access(record, ship_pad)
            if meta.get("error") or meta.get("stale_fallback"):
                blockers.append(f"{label}: provider unavailable; cached observations are not used for actionable estimates")
            if meta["freshness"] != "within_requested_age":
                blockers.append(f"{label}: market observation is {meta['freshness']}")
            if meta["pad_assessment"] != "reported_compatible":
                blockers.append(f"{label}: pad access is {meta['pad_assessment']}")
            if record.get("has_market") is not True:
                blockers.append(f"{label}: commodity market not confirmed")
            if not isinstance(record.get("market"), list) or not all(isinstance(r, dict) for r in record.get("market", [])):
                blockers.append(f"{label}: market dataset unavailable or malformed")
        if blockers:
            result.update(assessment="blocked", blockers=blockers)
            return bounded(result)
        destination_rows = {}
        duplicates = set()
        for row in destination["market"]:
            name = row.get("commodity")
            if isinstance(name, str):
                key = name.casefold()
                if key in destination_rows:
                    duplicates.add(key)
                destination_rows[key] = row
        seen = set()
        origin_duplicates = set()
        for row in origin["market"]:
            key = str(row.get("commodity", "")).casefold()
            if key in seen:
                origin_duplicates.add(key)
            seen.add(key)
        skipped = 0
        prohibited = set()
        for record in (origin, destination):
            entries = record.get("prohibited_commodities", [])
            if isinstance(entries, list):
                prohibited.update(item["name"].casefold() for item in entries
                                  if isinstance(item, dict) and isinstance(item.get("name"), str))
        skipped_prohibited = 0
        candidates = []
        budget = int(credits) - int(rebuy_reserve)
        for buy in origin["market"]:
            name = buy.get("commodity")
            if not isinstance(name, str) or len(name) > 128 or commodity.casefold() not in name.casefold():
                continue
            key = name.casefold()
            if key in prohibited:
                skipped_prohibited += 1
                continue
            sell = destination_rows.get(key)
            if sell is None:
                continue
            buy_price, sell_price = buy.get("buy_price"), sell.get("sell_price")
            supply, demand = buy.get("supply"), sell.get("demand")
            if (key in duplicates | origin_duplicates or buy.get("is_rare") or sell.get("is_rare") or
                    not all(number(v, integer=True) for v in (buy_price, sell_price, supply, demand))):
                skipped += 1
                continue
            if buy_price <= 0 or sell_price <= buy_price or supply <= 0 or demand <= 0:
                continue
            tonnes = min(int(free_cargo_tonnes), int(supply), int(demand), budget // int(buy_price))
            if tonnes <= 0:
                continue
            purchase = tonnes * int(buy_price)
            candidates.append({"commodity": name[:128], "tonnes": tonnes,
                "buy_price": buy_price, "sell_price": sell_price, "observed_supply": supply, "observed_demand": demand,
                "purchase_cost": purchase, "remaining_credits_after_purchase": int(credits) - purchase,
                "estimated_gross_profit": tonnes * (int(sell_price) - int(buy_price))})
        candidates.sort(key=lambda c: (-c["estimated_gross_profit"], c["commodity"]))
        result.update(assessment="conditional_estimates" if candidates else "no_viable_observed_quotes",
                      candidates=candidates[:5], omitted=max(0, len(candidates)-5),
                      skipped_ambiguous_or_rare=skipped, skipped_reported_prohibited=skipped_prohibited)
        # Straight-line distance is context only, never a computed jump route.
        a = [origin.get("system_" + axis) for axis in ("x", "y", "z")]
        b = [destination.get("system_" + axis) for axis in ("x", "y", "z")]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in a+b):
            result["straight_line_distance_ly"] = round(math.dist(a, b), 2)
        return bounded(result)
