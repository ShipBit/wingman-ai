"""Odyssey observations use synthetic journals; no game or account required."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from skills.elite_dangerous.telemetry import JournalReader, MAX_RESULT


class OdysseyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reader = JournalReader(self.root)

    def event(self, kind, second=0, **fields):
        return {"event": kind, "timestamp": f"2026-09-27T12:00:{second:02d}Z", **fields}

    def apply(self, kind, second=0, **fields):
        self.reader.apply(self.event(kind, second, **fields))

    def snapshot(self, second=1):
        self.apply("BackpackMaterials", second, Items=[], Components=[], Data=[], Consumables=[
            {"Name": "healthpack", "Count": 3, "OwnerID": 0},
            {"Name": "healthpack", "Count": 2, "OwnerID": 987654321, "MissionID": 42}])

    def test_stack_identity_and_no_double_debit(self):
        self.snapshot()
        self.apply("BackpackChange", 2, Removed=[{"Name": "healthpack", "Type": "Consumable", "Count": 1, "OwnerID": 0}])
        self.apply("UseConsumable", 2, Name="healthpack", Type="Consumable")
        rows = self.reader.blocks["backpack"]["data"]["Consumables"]
        self.assertEqual([2, 2], [row["Count"] for row in rows])
        result = self.reader.summary("odyssey")
        self.assertNotIn("OwnerID", result)
        self.assertNotIn("987654321", result)
        self.assertIn('"MissionID":42', result)

    def test_atomic_underflow_and_snapshot_recovery(self):
        self.snapshot()
        before = deepcopy(self.reader.blocks["backpack"]["data"])
        self.apply("BackpackChange", 2, Removed=[
            {"Name": "healthpack", "Type": "Consumable", "Count": 1, "OwnerID": 0},
            {"Name": "healthpack", "Type": "Consumable", "Count": 9, "OwnerID": 987654321, "MissionID": 42}])
        self.assertEqual(before, self.reader.blocks["backpack"]["data"])
        self.assertTrue(self.reader.blocks["backpack"]["requires_refresh"])
        self.snapshot(3)
        self.assertNotIn("requires_refresh", self.reader.blocks["backpack"])

    def test_unknown_categories_identity_and_bad_quantities(self):
        for change in (
            {"Name": "healthpack", "Type": "Consumable", "Count": True, "OwnerID": 0},
            {"Name": "healthpack", "Type": "Unknown", "Count": 1, "OwnerID": 0},
            {"Name": "healthpack", "Type": "Consumable", "Count": 1},
        ):
            with self.subTest(change=change):
                self.reader = JournalReader(self.root)
                self.snapshot()
                self.apply("BackpackChange", 2, Removed=[change])
                self.assertTrue(self.reader.blocks["backpack"]["requires_refresh"])
        self.apply("ShipLockerMaterials", 3, Items=[{"Name": "sample", "Count": True}])
        self.assertTrue(self.reader.blocks["ship_locker"]["requires_refresh"])

    def test_locker_transactions_require_observation(self):
        self.apply("ShipLockerMaterials", 1, Items=[{"Name": "sample", "Count": 4}])
        self.apply("TradeMicroResources", 2, Received="sample", Count=9)
        block = self.reader.blocks["ship_locker"]
        self.assertEqual(4, block["data"]["Items"][0]["Count"])
        self.assertTrue(block["requires_refresh"])
        self.apply("ShipLockerMaterials", 3, Items=[])
        self.assertEqual([], self.reader.blocks["ship_locker"]["data"]["Items"])
        self.assertNotIn("Components", self.reader.blocks["ship_locker"]["data"])
        self.assertNotIn("requires_refresh", self.reader.blocks["ship_locker"])

    def test_sidecar_order_and_repeated_poll(self):
        self.apply("Fileheader", gameversion="4.4.1.1", odyssey=True)
        self.apply("LoadGame")
        path = self.root / "Backpack.json"
        data = self.event("Backpack", 1, Items=[], Consumables=[{"Name": "healthpack", "OwnerID": 0, "Count": 3}])
        path.write_text(json.dumps(data))
        self.reader._sidecars()
        self.reader._sidecars()
        self.assertTrue(self.reader.odyssey)
        self.apply("BackpackChange", 1, Removed=[{"Name": "healthpack", "OwnerID": 0, "Count": 1, "Type": "Consumable"}])
        self.reader._sidecars()
        self.assertTrue(self.reader.blocks["backpack"]["requires_refresh"])
        data["timestamp"] = self.event("Backpack", 2)["timestamp"]
        data["Consumables"][0]["Count"] = 2
        path.write_text(json.dumps(data))
        self.reader._sidecars()
        self.assertNotIn("requires_refresh", self.reader.blocks["backpack"])
        self.assertEqual(2, self.reader.blocks["backpack"]["data"]["Consumables"][0]["Count"])

    def test_old_sidecar_cannot_repair_death(self):
        self.apply("Fileheader", gameversion="4.4.1.1")
        self.apply("LoadGame")
        self.snapshot()
        self.apply("Died", 5)
        (self.root / "Backpack.json").write_text(json.dumps(self.event("Backpack", 3, Items=[])))
        self.reader._sidecars()
        self.assertTrue(self.reader.blocks["backpack"]["requires_refresh"])

    def test_marker_allows_same_second_authoritative_snapshot(self):
        self.apply("Fileheader", gameversion="4.4.1.1")
        self.apply("LoadGame")
        self.snapshot()
        self.apply("BackpackChange", 2, Removed=[{"Name": "healthpack", "Type": "Consumable", "Count": 1, "OwnerID": 0}])
        self.apply("Backpack", 2)
        (self.root / "Backpack.json").write_text(json.dumps(self.event("Backpack", 2, Consumables=[])))
        self.reader._sidecars()
        self.assertNotIn("requires_refresh", self.reader.blocks["backpack"])
        self.assertEqual([], self.reader.blocks["backpack"]["data"]["Consumables"])

    def test_older_snapshot_and_duplicate_stack_cannot_repair_unknown(self):
        self.snapshot()
        self.apply("Died", 4)
        self.snapshot(2)
        self.assertTrue(self.reader.blocks["backpack"]["requires_refresh"])
        self.apply("BackpackMaterials", 5, Items=[{"Name": "sample", "Count": 1}, {"Name": "sample", "Count": 2}])
        self.assertTrue(self.reader.blocks["backpack"]["requires_refresh"])

    def test_equipped_suit_creation_does_not_equip(self):
        self.apply("SuitLoadout", 1, SuitName="utilitysuit_class2", SuitID=1, SuitMods=["testmod"],
                   Modules=[{"SlotName": "PrimaryWeapon1", "ModuleName": "testgun", "Class": 2, "WeaponMods": []}])
        self.apply("CreateSuitLoadout", 2, SuitName="flightsuit", SuitID=2)
        self.assertEqual(1, self.reader.blocks["suit"]["data"]["SuitID"])
        self.apply("UpgradeSuit", 3, SuitID=1, Class=3)
        self.assertTrue(self.reader.blocks["suit"]["requires_refresh"])
        self.apply("SwitchSuitLoadout", 4, SuitName="flightsuit", SuitID=2)
        self.assertEqual(2, self.reader.blocks["suit"]["data"]["SuitID"])
        self.assertNotIn("Modules", self.reader.blocks["suit"]["data"])

    def test_commander_reset_and_bounded_filtering(self):
        self.apply("Commander", FID="synthetic-one")
        self.apply("ShipLockerMaterials", 1, Items=[{"Name": f"sample{i}", "Count": i, "OwnerID": 123456789} for i in range(100)])
        result = self.reader.snapshot("odyssey", query="sample99")["ship_locker"]["data"]["Items"]
        self.assertEqual(1, result["total"])
        self.assertNotIn("OwnerID", result["items"][0])
        self.assertLessEqual(len(self.reader.summary("odyssey")), MAX_RESULT)
        self.apply("Commander", 2, FID="synthetic-two")
        self.assertNotIn("ship_locker", self.reader.snapshot("odyssey"))
