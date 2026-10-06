"""Commodity reconciliation must preserve vessel, mission and ownership identity."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from skills.elite_dangerous.telemetry import JournalReader, MAX_CARGO_STACKS, MAX_RESULT


class CargoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reader = JournalReader(self.root)
        self.now = datetime(2026, 9, 27, 12, 1, tzinfo=timezone.utc)

    @staticmethod
    def event(kind, second=0, **data):
        return {"event": kind, "timestamp": f"2026-09-27T12:00:{second:02d}Z", **data}

    def apply(self, kind, second=0, **data):
        self.reader.apply(self.event(kind, second, **data))

    def cargo(self, rows, second=0, **values):
        self.apply("Cargo", second, Vessel="Ship", Inventory=rows, **values)

    def data(self):
        return self.reader.blocks["cargo"]["data"]

    def test_purchases_sales_and_refining_update_hold_and_planning(self):
        self.apply("Loadout", CargoCapacity=20)
        self.cargo([{"Name": "$Gold_Name;", "Count": 4, "Stolen": 0}], 1)
        self.apply("MarketBuy", 2, Type="GOLD", Count=3)
        self.apply("MarketSell", 3, Type="gold", Count=2)
        self.apply("MiningRefined", 4, Type="platinum")
        self.assertEqual(6, self.data()["Count"])
        self.assertEqual(5, self.data()["Inventory"][0]["Count"])
        self.assertEqual(1, self.data()["Inventory"][1]["Count"])
        self.assertEqual("2026-09-27T12:00:01Z", self.reader.blocks["cargo"]["reconciled_from"])
        self.assertEqual(14, self.reader.snapshot("planning", now=self.now)["planning"]["free_cargo_tonnes"]["value"])

    def test_mission_stack_is_not_merged_with_trade_stock(self):
        self.cargo([{"Name": "gold", "Count": 3, "Stolen": 0},
                    {"Name": "gold", "Count": 8, "Stolen": 0, "MissionID": 123}])
        self.apply("MarketSell", 1, Type="gold", Count=3)
        self.assertEqual(8, self.data()["Count"])
        self.assertEqual(123, self.data()["Inventory"][0]["MissionID"])
        self.apply("CollectCargo", 2, Type="gold", MissionID=123, Stolen=False)
        self.apply("EjectCargo", 3, Type="gold", MissionID=123, Count=2)
        self.assertEqual(7, self.data()["Count"])
        self.apply("MarketSell", 4, Type="gold", Count=1)
        self.assertTrue(self.reader.blocks["cargo"]["requires_refresh"])
        self.assertEqual(7, self.data()["Count"])

    def test_stolen_sales_respect_exact_subcounts(self):
        self.cargo([{"Name": "gold", "Count": 10, "Stolen": 4}])
        self.apply("MarketSell", 1, Type="gold", Count=3, StolenGoods=True)
        self.assertEqual({"Name": "gold", "Count": 7, "Stolen": 1}, self.data()["Inventory"][0])
        self.apply("MarketSell", 2, Type="gold", Count=4, StolenGoods=False)
        self.assertEqual({"Name": "gold", "Count": 3, "Stolen": 1}, self.data()["Inventory"][0])
        before = deepcopy(self.data())
        self.apply("MarketSell", 3, Type="gold", Count=2, StolenGoods=True)
        self.assertEqual(before, self.data())
        self.assertTrue(self.reader.blocks["cargo"]["requires_refresh"])

    def test_ambiguous_partial_removal_does_not_guess_ownership(self):
        self.cargo([{"Name": "gold", "Count": 5, "Stolen": 2}])
        before = deepcopy(self.data())
        self.apply("EjectCargo", 1, Type="gold", Count=1, Abandoned=True)
        self.assertEqual(before, self.data())
        self.assertTrue(self.reader.blocks["cargo"]["requires_refresh"])
        self.cargo(before["Inventory"], 2)
        self.apply("EjectCargo", 3, Type="gold", Count=5)
        self.assertEqual(0, self.data()["Count"])
        self.assertEqual([], self.data()["Inventory"])

    def test_missing_stolen_count_remains_unknown(self):
        self.cargo([{"Name": "gold", "Count": 4}])
        self.apply("MarketBuy", 1, Type="gold", Count=2)
        self.assertNotIn("Stolen", self.data()["Inventory"][0])
        self.apply("CollectCargo", 2, Type="gold", Stolen=True)
        self.assertNotIn("Stolen", self.data()["Inventory"][0])
        self.assertEqual(7, self.data()["Count"])

    def test_scooping_and_limpet_transactions(self):
        self.cargo([])
        self.apply("CollectCargo", 1, Type="gold", Stolen=True)
        self.apply("CollectCargo", 2, Type="gold", Stolen=False)
        self.apply("BuyDrones", 3, Type="Drones", Count=4)
        self.apply("SellDrones", 4, Type="Drones", Count=1)
        self.assertEqual(5, self.data()["Count"])
        self.assertEqual(1, self.data()["Inventory"][0]["Stolen"])
        self.apply("LaunchDrone", 5, Type="Collection")
        self.assertTrue(self.reader.blocks["cargo"]["requires_refresh"])

    def test_unknown_baseline_and_bad_snapshot_are_not_empty_hold(self):
        self.apply("MarketBuy", Type="gold", Count=1)
        self.assertTrue(self.reader.blocks["cargo"]["requires_refresh"])
        self.assertNotIn("Count", self.data())
        self.cargo([{"Name": "gold", "Count": 2}], 1, Count=3)
        self.assertNotIn("Count", self.data())
        self.cargo([{"Name": "gold", "Count": 2}], 2, Count=2)
        self.assertNotIn("requires_refresh", self.reader.blocks["cargo"])

    def test_duplicate_invalid_and_oversized_snapshots_are_atomic(self):
        self.cargo([{"Name": "gold", "Count": 2, "Stolen": 0}])
        before = deepcopy(self.data())
        for rows in ([{"Name": "gold", "Count": True}],
                     [{"Name": "gold", "Count": 2, "Stolen": 3}],
                     [{"Name": "gold", "Count": 2, "MissionID": False}],
                     [{"Name": "gold", "Count": 2}, {"Name": "$Gold_Name;", "Count": 1}],
                     [{"Name": f"item{i}", "Count": 1} for i in range(MAX_CARGO_STACKS + 1)]):
            self.cargo(rows, 1)
            self.assertEqual(before, self.data())
            self.assertTrue(self.reader.blocks["cargo"]["requires_refresh"])

    def test_underflow_and_out_of_order_updates_do_not_clamp_or_retime(self):
        self.cargo([{"Name": "gold", "Count": 2, "Stolen": 0}], 2)
        before = deepcopy(self.data())
        self.apply("MarketSell", 3, Type="gold", Count=3)
        self.assertEqual(before, self.data())
        self.cargo(before["Inventory"], 4)
        self.apply("MarketBuy", 3, Type="gold", Count=2)
        self.assertEqual(before, self.data())
        self.assertEqual("2026-09-27T12:00:04Z", self.reader.blocks["cargo"]["observed_at"])

    def test_vessel_changes_block_transactions_until_snapshot(self):
        self.cargo([{"Name": "gold", "Count": 8, "Stolen": 0}])
        self.apply("LaunchSRV", 1)
        self.apply("CollectCargo", 2, Type="gold", Stolen=False)
        self.assertEqual(8, self.data()["Count"])
        self.assertTrue(self.reader.blocks["cargo"]["requires_refresh"])
        self.apply("Cargo", 3, Vessel="SRV", Inventory=[])
        self.apply("CollectCargo", 4, Type="gold", Stolen=False)
        self.assertEqual("SRV", self.data()["Vessel"])
        self.assertEqual(1, self.data()["Count"])
        self.apply("MarketBuy", 5, Type="gold", Count=10)
        self.assertEqual(1, self.data()["Count"])
        self.assertTrue(self.reader.blocks["cargo"]["requires_refresh"])

    def test_completed_mission_invalidates_bound_cargo_and_gap_cannot_be_repaired_by_delta(self):
        self.cargo([{"Name": "gold", "Count": 2, "MissionID": 123, "Stolen": 0}])
        self.apply("MissionCompleted", 1, MissionID=123)
        self.assertTrue(self.reader.blocks["cargo"]["requires_refresh"])
        self.apply("MarketBuy", 2, Type="silver", Count=1)
        self.assertEqual(2, self.data()["Count"])
        self.cargo([], 3)
        self.assertNotIn("requires_refresh", self.reader.blocks["cargo"])

    def test_snapshot_then_same_second_delta_does_not_double_apply(self):
        snapshot = self.event("Cargo", 2, Vessel="Ship", Inventory=[{"Name": "gold", "Count": 4, "Stolen": 0}])
        self.reader._cargo(snapshot, sidecar=True)
        self.apply("MarketBuy", 2, Type="gold", Count=1)
        self.assertTrue(self.reader.blocks["cargo"]["requires_refresh"])
        self.assertEqual(4, self.data()["Count"])
        self.apply("Cargo", 2)
        self.reader._cargo(snapshot, sidecar=True)
        self.assertTrue(self.reader.blocks["cargo"]["requires_refresh"])
        snapshot["Inventory"][0]["Count"] = 5
        self.reader._cargo(snapshot, sidecar=True)
        self.assertEqual(5, self.data()["Count"])
        self.assertNotIn("requires_refresh", self.reader.blocks["cargo"])

    def test_marker_waits_for_file_and_catch_up_does_not_read_ahead(self):
        self.apply("Fileheader", gameversion="4.4.1.1")
        self.apply("LoadGame")
        self.cargo([{"Name": "gold", "Count": 2}], 1)
        self.apply("Cargo", 3)
        path = self.root / "Cargo.json"
        path.write_text(json.dumps(self.event("Cargo", 2, Vessel="Ship", Inventory=[])))
        self.reader._sidecars()
        self.assertTrue(self.reader.blocks["cargo"]["requires_refresh"])
        path.write_text(json.dumps(self.event("Cargo", 3, Vessel="Ship", Inventory=[])))
        self.reader.catch_up = True
        self.reader._sidecars()
        self.assertTrue(self.reader.blocks["cargo"]["requires_refresh"])
        self.reader.catch_up = False
        self.reader._sidecars()
        self.assertEqual(0, self.data()["Count"])
        self.assertNotIn("requires_refresh", self.reader.blocks["cargo"])

    def test_bound_and_filter_operate_after_reconciliation(self):
        self.cargo([{"Name": f"item{i}", "Count": 1, "Stolen": 0} for i in range(100)])
        self.apply("MarketBuy", 1, Type="item99", Count=2)
        result = json.loads(self.reader.summary("cargo", "item99", self.now))
        self.assertEqual(1, result["cargo"]["data"]["Inventory"]["total"])
        self.assertEqual(3, result["cargo"]["data"]["Inventory"]["items"][0]["Count"])
        self.assertEqual(102, result["cargo"]["data"]["Count"])
        self.assertLessEqual(len(self.reader.summary("cargo", now=self.now)), MAX_RESULT)

    def test_future_snapshot_does_not_poison_a_later_valid_refresh(self):
        self.cargo([{"Name": "gold", "Count": 2}], 1)
        future = self.event("Cargo", Vessel="Ship", Inventory=[])
        future["timestamp"] = "2099-01-01T00:00:00Z"
        self.reader._cargo(future, sidecar=True)
        self.assertEqual(2, self.data()["Count"])
        self.assertTrue(self.reader.blocks["cargo"]["requires_refresh"])
        self.cargo([], 2)
        self.assertNotIn("requires_refresh", self.reader.blocks["cargo"])

    def test_partial_file_invalidates_old_snapshot_and_new_file_recovers(self):
        self.apply("Fileheader", gameversion="4.4.1.1")
        self.apply("LoadGame")
        self.cargo([{"Name": "gold", "Count": 2}], 1)
        path = self.root / "Cargo.json"
        path.write_text('{"event":"Cargo",')
        self.reader._sidecars()
        self.assertTrue(self.reader.blocks["cargo"]["requires_refresh"])
        self.assertEqual(2, self.data()["Count"])
        path.write_text(json.dumps(self.event("Cargo", 2, Vessel="Ship", Inventory=[])))
        self.reader._sidecars()
        self.assertEqual(0, self.data()["Count"])
        self.assertNotIn("requires_refresh", self.reader.blocks["cargo"])

    def test_taxi_dashboard_is_not_main_ship_hold_space(self):
        self.apply("Loadout", CargoCapacity=20)
        self.reader._put("status", {"Flags": 1 << 24, "Flags2": 2, "Cargo": 0}, self.event("Status", 1))
        self.assertNotIn("free_cargo_tonnes", self.reader.snapshot("planning", now=self.now)["planning"])
