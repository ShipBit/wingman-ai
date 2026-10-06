"""Resource reconciliation invariants using synthetic journal events."""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import unittest

from skills.elite_dangerous.telemetry import JournalReader


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.reader = JournalReader(Path("unused-synthetic-path"))
        self.now = datetime(2026, 9, 27, 12, 1, tzinfo=timezone.utc)
        self.apply("Materials", Raw=[{"Name": "iron", "Count": 10}, {"Name": "nickel", "Count": 6}],
                   Manufactured=[{"Name": "chemicalprocessors", "Count": 6}],
                   Encoded=[{"Name": "scandatabanks", "Count": 4}])

    def apply(self, kind, second=1, **data):
        self.reader.apply({"event": kind, "timestamp": f"2026-09-27T12:00:{second:02d}Z", **data})

    def inventory(self):
        return self.reader.blocks["materials"]

    def count(self, category, name):
        return next(e["Count"] for e in self.inventory()["data"][category] if e["Name"] == name)

    def planning(self):
        return self.reader.snapshot("planning", now=self.now)["planning"]

    def test_collection_trade_craft_and_synthesis_sequence(self):
        self.apply("MaterialCollected", 2, Category="raw", Name="$Iron_Name;", Count=2)
        self.apply("MaterialTrade", 3,
                   Paid={"Category": "$MICRORESOURCE_CATEGORY_Encoded;", "Material": "scandatabanks", "Quantity": 4},
                   Received={"Category": "Manufactured", "Material": "chemicalprocessors", "Quantity": 2})
        self.apply("EngineerCraft", 4, Ingredients=[{"Name": "iron", "Count": 3}, {"Name": "chemicalprocessors", "Count": 2}])
        self.apply("Synthesis", 5, Materials=[{"Name": "nickel", "Count": 2}])
        self.assertEqual((9, 4, 6, 0), (self.count("Raw", "iron"), self.count("Raw", "nickel"),
                                      self.count("Manufactured", "chemicalprocessors"), self.count("Encoded", "scandatabanks")))
        self.assertNotIn("requires_refresh", self.inventory())
        self.assertEqual("2026-09-27T12:00:01Z", self.inventory()["reconciled_from"])
        self.assertEqual("2026-09-27T12:00:05Z", self.inventory()["observed_at"])

    def test_contribution_uses_this_quantity_and_rewards_also_finish_mission(self):
        self.apply("EngineerContribution", 2, Material="iron", Quantity=2, TotalQuantity=99)
        self.apply("ScientificResearch", 3, Name="iron", Category="Raw", Count=1)
        self.apply("TechnologyBroker", 4, Materials=[{"Name": "iron", "Category": "Raw", "Count": 3}], Commodities=[])
        self.apply("MissionAccepted", 5, MissionID=123, Name="Synthetic")
        self.apply("MissionCompleted", 6, MissionID=123, MaterialsReward=[{"Name": "iron", "Category": "Elements", "Count": 5}])
        self.assertEqual(9, self.count("Raw", "iron"))
        self.assertEqual({}, self.reader.missions)

    def test_new_positive_material_in_known_category_starts_from_zero(self):
        self.apply("MaterialCollected", 2, Name="sulphur", Category="Raw", Count=3)
        self.assertEqual(3, self.count("Raw", "sulphur"))

    def test_trade_is_atomic_if_received_half_invalid(self):
        before = deepcopy(self.inventory()["data"])
        self.apply("MaterialTrade", 2, Paid={"Category": "Raw", "Material": "iron", "Quantity": 5},
                   Received={"Category": "Unknown", "Material": "other", "Quantity": 1})
        self.assertEqual(before, self.inventory()["data"])
        self.assertTrue(self.inventory()["requires_refresh"])
        self.apply("MaterialCollected", 3, Name="iron", Category="Raw", Count=1)
        self.assertEqual(before, self.inventory()["data"])
        self.apply("Materials", 4, Raw=[{"Name": "iron", "Count": 20}])
        self.assertEqual(20, self.count("Raw", "iron"))
        self.assertNotIn("requires_refresh", self.inventory())

    def test_underflow_does_not_clamp_to_zero(self):
        self.apply("MaterialDiscarded", 2, Name="iron", Category="Raw", Count=11)
        self.assertEqual(10, self.count("Raw", "iron"))
        self.assertTrue(self.inventory()["requires_refresh"])

    def test_ambiguous_category_and_legacy_broker_invalidate(self):
        self.apply("Materials", 2, Raw=[{"Name": "ambiguous", "Count": 5}], Encoded=[{"Name": "ambiguous", "Count": 8}])
        self.apply("Synthesis", 3, Materials=[{"Name": "ambiguous", "Count": 2}])
        self.assertTrue(self.inventory()["requires_refresh"])
        self.apply("Materials", 4, Raw=[])
        self.apply("TechnologyBroker", 5, Ingredients=[{"Name": "unknown", "Count": 3}])
        self.assertTrue(self.inventory()["requires_refresh"])

    def test_preview_never_spends_materials(self):
        before = deepcopy(self.inventory())
        self.apply("EngineerLegacyConvert", 2, IsPreview=True, Ingredients=[{"Name": "iron", "Count": 3}])
        self.assertEqual(before, self.inventory())
        self.assertNotIn("ship", self.reader.blocks)

    def test_missing_baseline_category_and_boolean_count_stay_unknown(self):
        self.apply("Materials", 2, Raw=[])
        self.apply("MaterialCollected", 3, Name="other", Category="Encoded", Count=1)
        self.assertTrue(self.inventory()["requires_refresh"])
        self.apply("Materials", 4, Raw=[{"Name": "iron", "Count": True}])
        self.assertTrue(self.inventory()["requires_refresh"])
        self.assertEqual({"Raw": []}, self.inventory()["data"])

    def test_duplicate_snapshot_is_rejected_atomically(self):
        before = deepcopy(self.inventory()["data"])
        self.apply("Materials", 2, Raw=[{"Name": "iron", "Count": 1}, {"Name": "$IRON_NAME;", "Count": 2}])
        self.assertEqual(before, self.inventory()["data"])
        self.assertTrue(self.inventory()["requires_refresh"])

    def test_out_of_order_event_invalidates(self):
        self.apply("MaterialCollected", 5, Name="iron", Category="Raw", Count=1)
        self.apply("MaterialDiscarded", 2, Name="iron", Category="Raw", Count=1)
        self.assertEqual(11, self.count("Raw", "iron"))
        self.assertTrue(self.inventory()["requires_refresh"])

    def test_engineer_update_preserves_other_engineers_and_their_dates(self):
        self.apply("EngineerProgress", 2, Engineers=[{"EngineerID": 1, "Engineer": "One", "Progress": "Unlocked", "Rank": 3},
                                                    {"EngineerID": 2, "Engineer": "Two", "Progress": "Known"}])
        self.apply("EngineerProgress", 5, EngineerID=2, Engineer="Two", Progress="Invited")
        entries = self.reader.blocks["engineerprogress"]["data"]["Engineers"]
        self.assertEqual(2, len(entries))
        self.assertEqual(("Unlocked", 3, "2026-09-27T12:00:02Z"), (entries[0]["Progress"], entries[0]["Rank"], entries[0]["observed_at"]))
        self.assertEqual("Invited", entries[1]["Progress"])
        self.assertNotIn("Rank", entries[1])
        self.assertEqual(1, self.reader.snapshot("progression", query="Two")["engineerprogress"]["data"]["Engineers"]["total"])

    def test_engineer_bad_update_retains_knowledge_but_requires_snapshot(self):
        self.apply("EngineerProgress", 2, Engineers=[{"EngineerID": 1, "Engineer": "One", "Progress": "Known"}])
        self.apply("EngineerProgress", 3, EngineerID=True, Progress="Unlocked")
        self.assertTrue(self.reader.blocks["engineerprogress"]["requires_refresh"])
        self.apply("EngineerProgress", 4, EngineerID=1, Progress="Invited")
        self.assertTrue(self.reader.blocks["engineerprogress"]["requires_refresh"])
        self.apply("EngineerProgress", 5, Engineers=[{"EngineerID": 1, "Engineer": "One", "Progress": "Invited"}])
        self.assertNotIn("requires_refresh", self.reader.blocks["engineerprogress"])

    def test_planning_resource_dates_and_ship_capacity(self):
        self.apply("LoadGame", 2, Credits=15000, Ship="Synthetic", ShipID=1)
        self.apply("Loadout", 3, Ship="Synthetic", ShipID=1, CargoCapacity=20, Rebuy=3000)
        self.apply("Cargo", 4, Vessel="Ship", Count=8, Inventory=[{"Name": "gold", "Count": 8, "Stolen": 0}])
        result = self.planning()
        self.assertEqual(12, result["free_cargo_tonnes"]["value"])
        self.assertEqual(15000, result["credits"]["value"])
        self.assertEqual(58, result["credits"]["age_seconds"])
        self.assertEqual(3000, result["ship_rebuy"]["value"])
        self.assertNotIn("required_pad", result)
        self.apply("ShipyardSwap", 5, ShipID=2)
        self.assertNotIn("free_cargo_tonnes", self.planning())
        self.assertNotIn("ship_rebuy", self.planning())

    def test_new_status_balance_and_main_ship_cargo_only(self):
        self.apply("LoadGame", 2, Credits=15000)
        self.apply("Loadout", 3, CargoCapacity=20, Rebuy=3000)
        self.reader._put("status", {"Balance": 12000, "Cargo": 7.0, "Flags": 1 << 24},
                         {"event": "Status", "timestamp": "2026-09-27T12:00:10Z"})
        self.assertEqual(12000, self.planning()["credits"]["value"])
        self.assertEqual(13, self.planning()["free_cargo_tonnes"]["value"])
        self.reader.blocks["status"]["data"]["Flags"] = 1 << 26
        self.assertNotIn("free_cargo_tonnes", self.planning())

    def test_missing_invalid_and_future_planning_values_remain_unknown(self):
        self.apply("Loadout", 3, CargoCapacity=20, Rebuy=True)
        self.apply("Cargo", 4, Vessel="Ship", Count=25, Inventory=[{"Name": "gold", "Count": 25, "Stolen": 0}])
        self.assertNotIn("free_cargo_tonnes", self.planning())
        self.assertNotIn("ship_rebuy", self.planning())
        self.assertNotIn("credits", self.planning())
        self.reader._put("status", {"Balance": 100}, {"timestamp": "2027-01-01T00:00:00Z"})
        self.assertNotIn("credits", self.planning())

    def test_dashboard_cannot_restore_cargo_before_known_transaction(self):
        self.apply("Loadout", 2, CargoCapacity=20, Rebuy=3000)
        self.apply("Cargo", 3, Vessel="Ship", Count=8, Inventory=[{"Name": "gold", "Count": 8, "Stolen": 0}])
        self.reader._put("status", {"Cargo": 8, "Flags": 1 << 24},
                         {"event": "Status", "timestamp": "2026-09-27T12:00:04Z"})
        self.apply("CargoTransfer", 5, Transfers=[{"Type": "gold", "Count": 1, "Direction": "toship"}])
        self.assertNotIn("free_cargo_tonnes", self.planning())
        self.reader._put("status", {"Cargo": 9, "Flags": 1 << 24},
                         {"event": "Status", "timestamp": "2026-09-27T12:00:06Z"})
        self.assertEqual(11, self.planning()["free_cargo_tonnes"]["value"])

    def test_mission_commodity_reward_invalidates_cargo_without_losing_mission_update(self):
        self.apply("Cargo", 2, Vessel="Ship", Count=8, Inventory=[{"Name": "gold", "Count": 8, "Stolen": 0}])
        self.apply("MissionAccepted", 3, MissionID=123)
        self.apply("MissionCompleted", 4, MissionID=123, CommodityReward=[{"Name": "gold", "Count": 2}])
        self.assertTrue(self.reader.blocks["cargo"]["requires_refresh"])
        self.assertEqual({}, self.reader.missions)


if __name__ == "__main__":
    unittest.main()
