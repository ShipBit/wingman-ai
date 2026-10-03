from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError, URLError

from integrations.elite_dangerous.provider import PublicData


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.calls = []
        self.response = {"name": "Sol", "coords": {"x": 0, "y": 0, "z": 0}, "requirePermit": True}

        def opener(request, timeout):
            self.calls.append(request.full_url)
            return BytesIO(json.dumps(self.response).encode())

        self.provider = PublicData(self.directory, opener=opener)

    def test_cache_survives_new_provider_instance(self):
        first = self.provider.lookup("Sol")
        second = PublicData(self.directory, opener=lambda *a, **k: self.fail("cache miss")).lookup("Sol")
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(first["fetched_at"], second["fetched_at"])
        self.assertEqual(1, len(self.calls))
        self.assertIsNone(second["observed_at"])

    def test_reference_csv_and_longer_immutable_cache(self):
        url = "https://raw.githubusercontent.com/EDCD/FDevIDs/" + "a" * 40 + "/material.csv"
        self.provider.opener = lambda *a, **k: BytesIO(b"id,symbol,type,name\n1,TestWake,Encoded,Test Wake Exceptions\n")
        result, _, _, error = self.provider._fetch(url, cache_seconds=86400)
        self.assertIsNone(error)
        self.assertEqual("TestWake", result[0]["symbol"])
        with self.provider._connect() as conn:
            conn.execute("UPDATE cache SET fetched=fetched-1000")
        self.provider.opener = lambda *a, **k: self.fail("Immutable revision should remain cached")
        self.assertTrue(self.provider._fetch(url, cache_seconds=86400)[2])

    def test_github_rate_limit_403_is_persisted(self):
        url = "https://api.github.com/repos/EDCD/coriolis-data/commits/master"
        def throttled(*args, **kwargs):
            raise HTTPError(url, 403, "Rate limited", {"X-RateLimit-Remaining": "0"}, None)
        self.provider.opener = throttled
        self.assertIn("403", self.provider._fetch(url)[3])
        self.assertIn("cooldown", self.provider._fetch(url)[3])

    def test_stations_filtered_bounded_and_timestamped(self):
        self.response = {"stations": [{"name": f"Port{i}", "distanceToArrival": 20-i,
            "otherServices": ["Refuel"], "updateTime": {"information": "2026-01-01 00:00:00"}}
            for i in range(12)]}
        result = self.provider.lookup("Sol", "stations", "refuel")
        self.assertEqual(5, len(result["stations"]))
        self.assertEqual(7, result["omitted"])
        self.assertEqual("Port11", result["stations"][0]["name"])
        self.assertEqual("2026-01-01 00:00:00", result["stations"][0]["updateTime"]["information"])

    def test_outage_labels_stale_fallback(self):
        self.provider.lookup("Sol")
        with self.provider._connect() as conn:
            conn.execute("UPDATE cache SET fetched=fetched-1000")
            conn.execute("DELETE FROM throttle")

        def offline(*args, **kwargs):
            raise URLError("offline")

        result = PublicData(self.directory, opener=offline).lookup("Sol")
        self.assertTrue(result["stale_fallback"])
        self.assertIn("error", result)
        self.assertEqual("Sol", result["system"]["name"])

    def test_rate_limit_persists_and_no_retry(self):
        def throttled(*args, **kwargs):
            raise HTTPError("https://www.edsm.net/", 429, "Rate limited", {"Retry-After": "120"}, None)

        result = PublicData(self.directory, opener=throttled).lookup("Sol")
        self.assertIn("429", result["error"])
        result = self.provider.lookup("Achenar")
        self.assertIn("cooldown", result["error"])
        self.assertEqual([], self.calls)

    def test_provider_cooldowns_are_independent(self):
        with self.provider._connect() as conn:
            import time
            conn.execute("INSERT INTO throttle VALUES (?, ?)", ("https://www.edsm.net", time.time()+120))
        data, fetched, cached, error = self.provider._fetch("https://spansh.co.uk/api/station/1")
        self.assertIsNone(error)
        self.assertIsNotNone(fetched)
        self.assertEqual(1, len(self.calls))
        with self.assertRaises(ValueError):
            self.provider._fetch("https://unknown.example/secret")

    def test_legacy_invalid_input_and_no_results(self):
        self.assertIn("error", self.provider.lookup("Sol", galaxy="legacy"))
        self.assertIn("error", self.provider.lookup(""))
        self.assertEqual([], self.calls)
        self.response = []
        self.assertFalse(self.provider.lookup("Unknown")['found'])

    def test_expired_search_deadline_does_not_make_network_request(self):
        import time
        payload, fetched, cached, error = self.provider._fetch("https://www.edsm.net/api-v1/system?systemName=Sol", deadline=time.monotonic()-1)
        self.assertIsNone(payload)
        self.assertIn("budget", error)
        self.assertEqual([], self.calls)


if __name__ == "__main__":
    unittest.main()
