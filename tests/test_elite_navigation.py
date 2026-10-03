"""Nearby service search: truthful coverage, service identity, and provenance."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from integrations.elite_dangerous.navigation import NearbyServices, MAX_OUTPUT


NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)


def system(name, distance, population=100, permit=False):
    return {"name": name, "distance": distance, "information": {"population": population}, "requirePermit": permit}


def station(name, market, arrival=10, services=None):
    return {"name": name, "marketId": market, "type": "Coriolis Starport", "distanceToArrival": arrival,
            "otherServices": ["Refuel"] if services is None else services,
            "updateTime": {"information": "2026-09-26 12:00:00"}}


class FakePublic:
    def __init__(self):
        self.sphere = [system("Further", 10), system("Origin", 0), system("Near", 2)]
        self.stations = {
            "Origin": {"name": "Origin", "stations": [station("Distant Port", 1, 500), station("Close Port", 2, 5)]},
            "Near": {"name": "Near", "stations": [station("Nearby Port", 3)]},
            "Further": {"name": "Further", "stations": [station("Further Port", 4)]}}
        self.calls, self.errors = [], {}
        self.callback = lambda: None

    def _fetch(self, url, deadline=None):
        self.calls.append(url)
        self.callback()
        key = "sphere" if "sphere-systems" in url else parse_qs(urlsplit(url).query)["systemName"][0]
        payload = self.sphere if key == "sphere" else self.stations.get(key)
        return deepcopy(payload), NOW.timestamp(), bool(self.errors.get(key)), self.errors.get(key)


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.public = FakePublic()
        self.navigation = NearbyServices(self.public, clock=lambda: NOW)

    def test_distance_order_and_separate_arrival_units(self):
        result = self.navigation.search("Origin")
        self.assertEqual(["Close Port", "Distant Port", "Nearby Port", "Further Port"], [c["station"] for c in result["candidates"]])
        self.assertEqual(2, result["candidates"][2]["system_distance_ly"])
        self.assertEqual(10, result["candidates"][2]["arrival_distance_ls"])
        self.assertFalse(result["partial"])
        self.assertEqual(86400, result["candidates"][0]["observation"]["age_seconds"])
        self.assertEqual("unverified", result["candidates"][0]["pad_access"])

    def test_filters_service_fields_not_station_name_or_substrings(self):
        self.public.stations["Origin"]["stations"] = [station("Refuel in name only", 1, services=[]),
            station("False positive", 2, services=["No Refuel"]),
            {**station("Shipyard", 5, services=[]), "haveShipyard": True},
            station("Vista", 6, services=["Vista Genomics"])]
        result = self.navigation.search("Origin", "vista_genomics")
        self.assertEqual(["Vista"], [c["station"] for c in result["candidates"]])
        result = self.navigation.search("Origin", "shipyard")
        self.assertEqual(["Shipyard"], [c["station"] for c in result["candidates"]])

    def test_permit_unknowns_and_population_coverage(self):
        self.public.sphere += [system("Uninhabited", 1, 0), system("Unknown Population", 1, None)]
        self.public.sphere[1]["requirePermit"] = True
        self.public.sphere[2].pop("requirePermit")
        result = self.navigation.search("Origin", exclude_permit_systems=True)
        self.assertEqual(["Further Port"], [c["station"] for c in result["candidates"]])
        self.assertEqual(2, result["coverage"]["rejected"]["permit"])
        self.assertEqual(2, result["coverage"]["rejected"]["population_unknown_or_zero"])

    def test_eight_system_budget_never_claims_exhaustive_search(self):
        self.public.sphere = [system(f"System {i}", i) for i in range(12)]
        self.public.stations = {row["name"]: {"name": row["name"], "stations": [station(f"Port {i}", i+1)]}
                                for i, row in enumerate(self.public.sphere)}
        result = self.navigation.search("Origin")
        self.assertEqual(9, len(self.public.calls))
        self.assertEqual(8, result["coverage"]["checked_systems"])
        self.assertEqual(4, result["coverage"]["unsearched_eligible_systems"])
        self.assertTrue(result["partial"])
        self.assertEqual(5, len(result["candidates"]))
        self.assertEqual(3, result["omitted_candidates"])

    def test_deadline_stops_additional_requests(self):
        elapsed = [0]
        self.public.callback = lambda: elapsed.__setitem__(0, elapsed[0]+13)
        navigation = NearbyServices(self.public, clock=lambda: NOW, monotonic=lambda: elapsed[0])
        result = navigation.search("Origin")
        self.assertEqual(2, len(self.public.calls))
        self.assertTrue(result["partial"])
        self.assertIn("time budget", result["coverage"]["stopped_reason"])

    def test_stale_fallback_and_partial_provider_failures_are_visible(self):
        self.public.errors["sphere"] = "Offline; cached catalogue"
        self.public.errors["Origin"] = "Offline; cached stations"
        self.public.stations["Near"] = None
        result = self.navigation.search("Origin")
        self.assertTrue(result["partial"])
        self.assertTrue(all(c["stale_fallback"] for c in result["candidates"]))
        self.assertEqual(2, result["coverage"]["failed_system_queries"])

    def test_identity_mismatch_and_ambiguous_market_ids_excluded(self):
        self.public.stations["Near"]["name"] = "Wrong system"
        self.public.stations["Origin"]["stations"].append(station("Conflicting Port", 1))
        result = self.navigation.search("Origin")
        self.assertTrue(result["partial"])
        self.assertEqual(["2", "4"], [c["market_id"] for c in result["candidates"]])

    def test_carriers_excluded_and_unknown_dates_stay_unknown(self):
        self.public.stations["Origin"]["stations"][0]["type"] = "Fleet Carrier"
        self.public.stations["Origin"]["stations"][1]["updateTime"] = {}
        result = self.navigation.search("Origin")
        self.assertNotIn("1", [c["market_id"] for c in result["candidates"]])
        self.assertEqual("unknown", result["candidates"][0]["observation"]["freshness"])

    def test_invalid_requests_never_fetch(self):
        for params in ({"system": ""}, {"system": "x"*129}, {"radius_ly": True}, {"radius_ly": 101},
                       {"radius_ly": 0}, {"radius_ly": 2.5}, {"service": "unverified"}, {"galaxy": "legacy"},
                       {"exclude_permit_systems": "false"}):
            args = {"system": "Origin", **params}
            self.assertIn("error", self.navigation.search(**args))
        self.assertEqual([], self.public.calls)

    def test_schema_errors_and_empty_results_not_absence_guarantees(self):
        self.public.sphere = {"status": "unavailable"}
        self.assertIn("error", self.navigation.search("Origin"))
        self.public.sphere = []
        result = self.navigation.search("Unknown")
        self.assertEqual([], result["candidates"])
        self.assertIn("not proof", " ".join(result["limitations"]))

    def test_adversarial_fields_and_bounds(self):
        self.public.sphere += [system("Outside", 21), system("Bad distance", float("nan")), system("Huge distance", 10**400)]
        self.public.stations["Origin"]["stations"] += [station("x"*10000, 99)]
        result = self.navigation.search("Origin")
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False)), MAX_OUTPUT)
        self.assertEqual(3, result["coverage"]["rejected"]["invalid"])
        self.assertTrue(result["partial"])


if __name__ == "__main__":
    unittest.main()
