"""Bounded service search using EDSM's documented sphere and station endpoints.

Distances rank observed candidates, not reachable jump routes. The returned
coverage prevents a partial catalogue scan from masquerading as an exhaustive
nearest-service search. No account or player journal upload is required.
"""

from datetime import datetime, timezone
import json
import math
import sqlite3
import time
from urllib.parse import urlencode


BASE = "https://www.edsm.net"
MAX_SYSTEMS = 8
MAX_OUTPUT = 9000
SEARCH_SECONDS = 24
SERVICES = {
    "refuel": ("Refuel",), "repair": ("Repair",), "restock": ("Restock",),
    "universal_cartographics": ("Universal Cartographics",),
    "vista_genomics": ("Vista Genomics",),
    "interstellar_factors": ("Interstellar Factors", "Interstellar Factors Contact"),
    "material_trader": ("Material Trader",),
    "technology_broker": ("Technology Broker",),
    "shipyard": (), "outfitting": (), "market": (),
}
SERVICE_FIELDS = {"shipyard": "haveShipyard", "outfitting": "haveOutfitting", "market": "haveMarket"}


def finite(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def short_name(value):
    return isinstance(value, str) and 0 < len(value.strip()) <= 128


def service_present(station, service):
    if service in SERVICE_FIELDS:
        return station.get(SERVICE_FIELDS[service]) is True
    names = station.get("otherServices")
    if not isinstance(names, list):
        return False
    reported = {s.casefold() for s in names if isinstance(s, str)}
    return any(name.casefold() in reported for name in SERVICES[service])


def observation(station, now):
    times = station.get("updateTime")
    value = times.get("information") if isinstance(times, dict) else None
    stamp = None
    if isinstance(value, str):
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            # EDSM documents its API dates in UTC; station dates lack an offset.
            if not stamp.tzinfo:
                stamp = stamp.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    age = round((now - stamp).total_seconds()) if stamp else None
    return {"observed_at": value if isinstance(value, str) and len(value) <= 64 else None,
            "age_seconds": age, "time_basis": "EDSM information update (UTC)",
            "freshness": "unknown" if age is None else "future_timestamp" if age < -60 else
                         "older_than_30_days" if age > 30 * 86400 else "within_30_days"}


class NearbyServices:
    def __init__(self, public_data, clock=lambda: datetime.now(timezone.utc), monotonic=time.monotonic):
        self.public = public_data
        self.clock = clock
        self.monotonic = monotonic

    def _fetch(self, url, deadline):
        meta = {"source": url, "fetched_at": None, "cache_hit": False, "stale_fallback": False}
        try:
            payload, fetched, cached, error = self.public._fetch(url, deadline=deadline)
            meta.update(fetched_at=datetime.fromtimestamp(fetched, timezone.utc).isoformat() if fetched else None,
                        cache_hit=cached, stale_fallback=bool(error and payload is not None))
            if error:
                meta["error"] = error
            return payload, meta
        except (OSError, sqlite3.Error, ValueError, OverflowError):
            return None, {**meta, "error": "Provider/cache unavailable; no search result verified."}

    def search(self, system, service="refuel", radius_ly=20, exclude_permit_systems=False, galaxy="live"):
        if galaxy != "live":
            return {"error": "Nearby service search supports Live only; Legacy/unknown is unsupported."}
        if not short_name(system):
            return {"error": "Supply a system name between 1 and 128 characters."}
        if service not in SERVICES:
            return {"error": "Unsupported service. Choose: " + ", ".join(SERVICES)}
        if isinstance(radius_ly, bool) or not isinstance(radius_ly, int) or not 1 <= radius_ly <= 100:
            return {"error": "Use an integer radius from 1 to 100 light years."}
        if not isinstance(exclude_permit_systems, bool):
            return {"error": "exclude_permit_systems must be true or false."}
        system = system.strip()
        now, started = self.clock(), self.monotonic()
        deadline = started + SEARCH_SECONDS
        url = BASE + "/api-v1/sphere-systems?" + urlencode({"systemName": system,
            "radius": radius_ly, "showId": 1, "showCoordinates": 1, "showPermit": 1, "showInformation": 1})
        payload, sphere_meta = self._fetch(url, deadline)
        result = {"provider": "EDSM", "origin": system, "service": service,
                  "radius_ly": radius_ly, "retrieved_at": now.isoformat(),
                  "galaxy_policy": "Live queries only; community responses do not independently identify galaxy.",
                  "sphere": sphere_meta, "candidates": [],
                  "ordering": "System distance in light years, then arrival distance in light seconds; not a jump route.",
                  "limitations": ["Searches at most eight nearest known populated systems (and the origin if returned).",
                                  "Unpopulated/unknown-population systems and carriers are outside this search.",
                                  "Pad sizes, landing requirements, docking permission and current service availability need verification.",
                                  "No matching observation is not proof that no service exists. Community coverage is incomplete."]}
        if not isinstance(payload, list):
            result["error"] = sphere_meta.get("error", "Nearby catalogue unavailable or invalid; no absence claim can be made.")
            return result
        candidates, seen = [], set()
        rejected = {"invalid": 0, "population_unknown_or_zero": 0, "permit": 0}
        for row in payload:
            if not isinstance(row, dict) or not short_name(row.get("name")) or not finite(row.get("distance")) or row["distance"] > radius_ly:
                rejected["invalid"] += 1
                continue
            name = row["name"].strip()
            key = name.casefold()
            if key in seen:
                rejected["invalid"] += 1
                continue
            seen.add(key)
            information = row.get("information")
            population = information.get("population") if isinstance(information, dict) else None
            if key != system.casefold() and (not finite(population) or population <= 0):
                rejected["population_unknown_or_zero"] += 1
                continue
            # Missing permit metadata is not an assertion of permit-free access.
            if exclude_permit_systems and row.get("requirePermit") is not False:
                rejected["permit"] += 1
                continue
            candidates.append(row)
        candidates.sort(key=lambda row: (row["distance"], row["name"].casefold()))
        selected = candidates[:MAX_SYSTEMS]
        coverage = {"systems_returned": len(payload), "eligible_systems": len(candidates),
                    "selected_systems": len(selected), "checked_systems": 0,
                    "failed_system_queries": 0, "rejected_station_records": 0,
                    "unsearched_eligible_systems": len(candidates), "rejected": rejected,
                    "complete_within_eligible_systems": False, "station_queries": []}
        result["coverage"] = coverage
        found, failed, market_ids = [], bool(sphere_meta.get("error")), set()
        for row in selected:
            if self.monotonic() >= deadline:
                coverage["stopped_reason"] = "Search time budget exhausted"
                break
            station_url = BASE + "/api-system-v1/stations?" + urlencode({"systemName": row["name"]})
            stations_payload, meta = self._fetch(station_url, deadline)
            coverage["station_queries"].append({"system": row["name"], **meta})
            coverage["checked_systems"] += 1
            stations = stations_payload.get("stations") if isinstance(stations_payload, dict) else None
            identity = stations_payload.get("name") if isinstance(stations_payload, dict) else None
            if not short_name(identity) or identity.casefold() != row["name"].strip().casefold() or not isinstance(stations, list):
                meta["error"] = "Station response identity or shape is invalid."
                coverage["station_queries"][-1]["error"] = meta["error"]
                coverage["failed_system_queries"] += 1
                failed = True
                continue
            failed = failed or bool(meta.get("error"))
            if meta.get("error"):
                coverage["failed_system_queries"] += 1
            for station in stations:
                if not isinstance(station, dict) or not short_name(station.get("name")) or not isinstance(station.get("type"), str):
                    failed = True
                    coverage["rejected_station_records"] += 1
                    continue
                if "carrier" in station["type"].casefold() or not service_present(station, service):
                    continue
                market = station.get("marketId")
                if not isinstance(market, int) or isinstance(market, bool) or not 0 < market < 2**64 or market in market_ids:
                    failed = True
                    coverage["rejected_station_records"] += 1
                    if isinstance(market, int) and not isinstance(market, bool) and market in market_ids:
                        found = [candidate for candidate in found if candidate["market_id"] != str(market)]
                    continue
                market_ids.add(market)
                arrival = station.get("distanceToArrival")
                found.append({"station": station["name"], "market_id": str(market), "system": row["name"],
                    "type": station["type"][:80], "system_distance_ly": row["distance"],
                    "arrival_distance_ls": arrival if finite(arrival) else None,
                    "requires_permit": row.get("requirePermit") if isinstance(row.get("requirePermit"), bool) else None,
                    "permit_name": row.get("permitName")[:128] if isinstance(row.get("permitName"), str) else None,
                    "service_reported": service, "pad_access": "unverified", "observation": observation(station, now),
                    "source": station_url, "fetched_at": meta["fetched_at"],
                    "stale_fallback": bool(meta["stale_fallback"] or sphere_meta["stale_fallback"])})
        found.sort(key=lambda row: (row["system_distance_ly"], row["arrival_distance_ls"] if row["arrival_distance_ls"] is not None else float("inf"), row["station"]))
        coverage["unsearched_eligible_systems"] = len(candidates) - coverage["checked_systems"]
        coverage["complete_within_eligible_systems"] = not failed and coverage["unsearched_eligible_systems"] == 0
        result.update(candidates=found[:5], matched_in_checked_systems=len(found), omitted_candidates=max(0, len(found)-5),
                      elapsed_seconds=round(self.monotonic()-started, 2), partial=not coverage["complete_within_eligible_systems"])
        if len(json.dumps(result, ensure_ascii=False)) > MAX_OUTPUT:
            # Source URLs may be long. Retain selected-result provenance and summarize the scan ledger.
            coverage["station_queries"] = [{"system": row["system"], "error": row.get("error"),
                "stale_fallback": row["stale_fallback"]} for row in coverage["station_queries"]]
        if len(json.dumps(result, ensure_ascii=False)) > MAX_OUTPUT:
            return {"provider": "EDSM", "source": url, "error": "Search output exceeds its limit; use a smaller radius.", "partial": True}
        return result
