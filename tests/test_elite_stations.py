"""Synthetic Spansh contract fixtures: calculation and freshness invariants."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import unittest

from integrations.elite_dangerous.stations import StationData, MAX_OUTPUT, canonical_id


NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)


def record(market_id, name):
    return {"market_id": market_id, "name": name, "system_name": "Synthetic",
            "has_market": True, "has_large_pad": True, "large_pads": 1,
            "market_updated_at": "2026-09-27T11:00:00Z", "updated_at": "2026-09-27T10:00:00Z",
            "outfitting_updated_at": "2026-09-20T12:00:00Z", "market": [], "modules": [],
            "system_x": 0, "system_y": 0, "system_z": 0}


class FakePublic:
    def __init__(self):
        self.records = {"1": record(1, "Origin"), "2": record(2, "Destination")}
        self.calls = []
        self.error = None

    def _fetch(self, url):
        self.calls.append(url)
        value = self.records.get(url.rsplit("/", 1)[-1])
        return {"record": deepcopy(value)}, NOW.timestamp(), False, self.error


class StationTests(unittest.TestCase):
    def setUp(self):
        self.public = FakePublic()
        self.provider = StationData(self.public, clock=lambda: NOW)
        self.origin = self.public.records["1"]
        self.dest = self.public.records["2"]
        self.origin["market"] = [{"commodity": "Gold", "buy_price": 100, "sell_price": 99, "supply": 90, "demand": 0}]
        self.dest["market"] = [{"commodity": "Gold", "buy_price": 900, "sell_price": 150, "supply": 0, "demand": 70}]

    def trade(self, **overrides):
        params = dict(origin_market_id="1", destination_market_id="2", free_cargo_tonnes=80,
                      credits=5500, rebuy_reserve=500, ship_pad="L")
        params.update(overrides)
        return self.provider.trade(**params)

    def test_price_direction_budget_reserve_supply_demand(self):
        result = self.trade()
        candidate = result["candidates"][0]
        self.assertEqual("conditional_estimates", result["assessment"])
        self.assertEqual(50, candidate["tonnes"])
        self.assertEqual(5000, candidate["purchase_cost"])
        self.assertEqual(500, candidate["remaining_credits_after_purchase"])
        self.assertEqual(2500, candidate["estimated_gross_profit"])
        # The destination BUY quote of 900 must not inflate proceeds.
        self.assertEqual(150, candidate["sell_price"])
        self.assertEqual(70, self.trade(credits=100000)["candidates"][0]["tonnes"])
        self.origin["market"][0]["supply"] = 7
        self.assertEqual(7, self.trade()["candidates"][0]["tonnes"])
        self.assertEqual(3, self.trade(free_cargo_tonnes=3)["candidates"][0]["tonnes"])

    def test_stale_unknown_and_future_observation_blocks_trade(self):
        for value in ("2026-09-20T12:00:00Z", None, "2027-01-01T00:00:00Z", "2026-09-27T11:00:00"):
            with self.subTest(value=value):
                self.dest["market_updated_at"] = value
                result = self.trade()
                self.assertEqual("blocked", result["assessment"])
                self.assertEqual([], result["candidates"])

    def test_outage_blocks_estimate_even_when_cached_timestamp_recent(self):
        self.public.error = "Provider unavailable"
        result = self.trade()
        self.assertEqual("blocked", result["assessment"])
        self.assertTrue(result["destination"]["stale_fallback"])

    def test_pads_incompatible_or_unknown(self):
        self.dest["has_large_pad"] = False
        self.dest["large_pads"] = 0
        self.dest["medium_pads"] = 1
        self.assertEqual("blocked", self.trade()["assessment"])
        self.assertEqual("conditional_estimates", self.trade(ship_pad="M")["assessment"])
        self.dest.pop("medium_pads")
        self.assertEqual("blocked", self.trade(ship_pad="M")["assessment"])

    def test_no_speculative_supply_or_demand(self):
        for value in (None, 0, -1, True, "100", float("nan")):
            with self.subTest(value=value):
                self.dest["market"][0]["demand"] = value
                self.assertEqual([], self.trade()["candidates"])

    def test_duplicate_and_rare_quotes_excluded(self):
        self.origin["market"].append(dict(self.origin["market"][0]))
        self.assertEqual([], self.trade()["candidates"])
        self.origin["market"].pop()
        self.origin["market"][0]["is_rare"] = True
        self.assertEqual([], self.trade()["candidates"])

    def test_known_prohibited_commodity_is_excluded(self):
        self.dest["prohibited_commodities"] = [{"name": "gOLd"}]
        result = self.trade()
        self.assertEqual([], result["candidates"])
        self.assertEqual(1, result["skipped_reported_prohibited"])

    def test_invalid_inputs_never_fetch(self):
        for params in ({"credits": -1}, {"credits": 100, "rebuy_reserve": 200},
                       {"ship_pad": "XL"}, {"free_cargo_tonnes": True},
                       {"origin_market_id": "../../etc"}, {"max_age_hours": float("nan")},
                       {"origin_market_id": "2"}, {"galaxy": "legacy"}, {"credits": 10**400}):
            with self.subTest(params=params):
                self.assertIn("error", self.trade(**params))
        self.assertEqual([], self.public.calls)

    def test_uint64_and_identity_mismatch(self):
        self.assertEqual("18446744073709551615", canonical_id("18446744073709551615"))
        for value in (2**64, -1, 0, True, 1.0, "1.0"):
            with self.assertRaises(ValueError):
                canonical_id(value)
        self.origin["market_id"] = 3
        self.assertIn("identity", self.provider.station("1")["error"])

    def test_module_filter_and_section_specific_age(self):
        self.origin["modules"] = [{"name": "Frame Shift Drive", "class": 5, "rating": "A", "price": 5000},
                                  {"name": "Frame Shift Drive", "class": 4, "rating": "A", "price": 4000}]
        result = self.provider.station("1", "outfitting", "5A frame shift")
        self.assertEqual(1, result["matched"])
        self.assertEqual(5, result["items"][0]["class"])
        self.assertEqual("stale", result["freshness"])
        result = self.provider.station("1", "market", "gold")
        self.assertEqual("within_requested_age", result["freshness"])
        self.assertEqual(100, result["items"][0]["buy_price"])

    def test_station_dataset_missing_is_not_no_stock(self):
        self.origin.pop("modules")
        self.assertIn("unavailable", self.provider.station("1", "outfitting")["error"])

    def test_top_five_order_and_bound(self):
        self.origin["market"] = [{"commodity": f"Commodity {i}", "buy_price": 10, "supply": 20} for i in range(50)]
        self.dest["market"] = [{"commodity": f"Commodity {i}", "sell_price": 100+i, "demand": 20} for i in range(50)]
        result = self.trade()
        self.assertEqual(5, len(result["candidates"]))
        self.assertEqual("Commodity 49", result["candidates"][0]["commodity"])
        self.assertEqual(45, result["omitted"])
        self.assertLessEqual(len(json.dumps(result)), MAX_OUTPUT)
        self.origin["name"] = "x" * 20000
        self.assertLessEqual(len(json.dumps(self.trade())), MAX_OUTPUT)


if __name__ == "__main__":
    unittest.main()
