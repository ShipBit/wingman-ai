"""Synthetic exploration sequences, including identity, dates and partial coverage."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from skills.elite_dangerous.telemetry import JournalReader, MAX_EXPLORATION_BODIES, MAX_RESULT


class ExplorationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.reader = JournalReader(Path(self.temp.name))
        self.apply("Location", 1, StarSystem="Synthetic", SystemAddress=123)

    def apply(self, event, second=2, **fields):
        self.reader.apply({"event": event, "timestamp": f"2026-09-27T12:00:{second:02d}Z", **fields})

    def data(self):
        return self.reader.blocks["exploration"]["data"]

    def test_body_scans_mapping_and_signals_survive_other_events(self):
        self.apply("Scan", 2, BodyID=1, BodyName="Synthetic 1", PlanetClass="Rocky body", Landable=True, SurfaceGravity=3.5)
        self.apply("SAAScanComplete", 3, BodyID=1, BodyName="Synthetic 1", ProbesUsed=4, EfficiencyTarget=6,
                   Discoverers=["private-pilot"], Mappers=["private-mapper"])
        self.apply("SAASignalsFound", 4, BodyID=1, BodyName="Synthetic 1", Signals=[
            {"Type": "$SAA_SignalType_Biological;", "Type_Localised": "Biological", "Count": 2}])
        self.apply("Scan", 5, BodyID=2, BodyName="Synthetic 2", PlanetClass="Icy body")
        first = self.data()["bodies"][0]
        self.assertEqual("2026-09-27T12:00:02Z", first["scan"]["observed_at"])
        self.assertEqual("2026-09-27T12:00:03Z", first["mapping_completed"]["observed_at"])
        self.assertEqual(2, first["surface_signals"]["Signals"][0]["Count"])
        summary = self.reader.summary("exploration", query="Biological")
        self.assertNotIn("private-pilot", summary)
        self.assertNotIn("private-mapper", summary)
        self.assertEqual(1, json.loads(summary)["exploration"]["data"]["bodies"]["total"])

    def test_organic_body_key_and_analysis_is_not_inferred_from_samples(self):
        for phase, second in (("Log", 2), ("Sample", 3), ("Sample", 4)):
            self.apply("ScanOrganic", second, SystemAddress=123, Body=7, Species="SyntheticSpecies", ScanType=phase)
        organic = self.data()["bodies"][0]["organic_observations"][0]
        self.assertEqual(7, self.data()["bodies"][0]["BodyID"])
        self.assertNotIn("analysis_observed_at", organic)
        self.apply("ScanOrganic", 5, SystemAddress=123, Body=7, Species="SyntheticSpecies", ScanType="Analyse")
        self.apply("ScanOrganic", 6, SystemAddress=123, Body=7, Species="OtherSpecies", ScanType="Log")
        self.apply("SellOrganicData", 7, BioData=[{"Species": "SyntheticSpecies", "Value": 999}])
        self.apply("Died", 8)
        organics = self.data()["bodies"][0]["organic_observations"]
        self.assertEqual("2026-09-27T12:00:05Z", organics[0]["analysis_observed_at"])
        self.assertNotIn("analysis_observed_at", organics[1])
        self.assertIn("not proof of unsold data", self.data()["scope"])
        self.assertNotIn("Value", json.dumps(self.data()))

    def test_current_system_and_arrival_boundaries(self):
        self.apply("Scan", 2, BodyID=1, BodyName="Synthetic 1", SystemAddress=123)
        self.apply("Scan", 3, BodyID=2, BodyName="Foreign 2", SystemAddress=456)
        self.assertEqual(1, len(self.data()["bodies"]))
        self.apply("StartJump", 4, JumpType="Hyperspace")
        self.assertNotIn("exploration", self.reader.blocks)
        self.apply("Scan", 5, BodyID=3, BodyName="Synthetic 3", SystemAddress=123)
        self.assertNotIn("exploration", self.reader.blocks)
        self.apply("FSDJump", 6, StarSystem="Other", SystemAddress=456)
        self.apply("Scan", 7, BodyID=1, BodyName="Other 1", SystemAddress=456)
        self.assertEqual("Other 1", self.data()["bodies"][0]["BodyName"])
        self.assertEqual(456, self.data()["SystemAddress"])

    def test_bad_data_and_older_events_leave_prior_observations_intact(self):
        self.apply("SAASignalsFound", 4, BodyID=1, Signals=[{"Type": "Biological", "Count": 2}])
        before = deepcopy(self.data())
        self.apply("SAASignalsFound", 5, BodyID=1, Signals=[{"Type": "Biological", "Count": True}])
        self.apply("Scan", 3, BodyID=1, BodyName="Out of order")
        self.apply("ScanOrganic", 6, Body=1, Species="Synthetic", ScanType="Unknown")
        self.apply("Scan", 7, BodyID=1, SurfaceGravity=True)
        self.assertEqual(before, self.data())
        self.assertTrue(self.reader.snapshot("exploration")["warnings"])

    def test_supercruise_travel_keeps_current_system_catalogue(self):
        self.apply("Scan", 2, BodyID=1, BodyName="Synthetic 1")
        self.apply("StartJump", 3, JumpType="Supercruise")
        self.apply("SupercruiseEntry", 4, StarSystem="Synthetic", SystemAddress=123)
        self.apply("Scan", 5, BodyID=2, BodyName="Synthetic 2")
        self.apply("SupercruiseExit", 6, StarSystem="Synthetic", SystemAddress=123, Body="Synthetic 2", BodyID=2, BodyType="Planet")
        self.assertEqual(2, len(self.data()["bodies"]))
        self.assertFalse(self.reader.blocks["location"]["data"]["in_transit"])
        self.assertEqual("Synthetic 2", self.reader.blocks["location"]["data"]["Body"])

    def test_system_scan_counts_are_distinct_from_observed_catalogue(self):
        self.apply("FSSDiscoveryScan", 2, BodyCount=12, NonBodyCount=2, Progress=0.5)
        self.apply("Scan", 3, BodyID=1, BodyName="Synthetic 1")
        self.apply("FSSAllBodiesFound", 4, SystemAddress=123, Count=12)
        self.assertEqual(12, self.data()["system_scan"]["data"]["BodyCount"])
        self.assertEqual(12, self.data()["all_bodies_found"]["data"]["Count"])
        self.assertEqual(1, len(self.data()["bodies"]))
        self.assertIn("not a complete catalogue", self.data()["scope"])

    def test_catalogue_and_model_output_are_bounded_and_filterable(self):
        for identity in range(MAX_EXPLORATION_BODIES + 2):
            self.apply("Scan", 2, BodyID=identity, BodyName=f"Synthetic {identity}", PlanetClass="Rocky body")
        self.assertEqual(MAX_EXPLORATION_BODIES, len(self.data()["bodies"]))
        self.assertTrue(self.data()["catalogue_limit_reached"])
        summary = self.reader.summary("exploration", query="Synthetic 511")
        self.assertEqual(1, json.loads(summary)["exploration"]["data"]["bodies"]["total"])
        self.assertLessEqual(len(self.reader.summary("exploration")), MAX_RESULT)

    def test_journal_gap_remains_visible_after_more_scans(self):
        path = Path(self.temp.name) / "Journal.2026-09-27T120000.01.log"
        events = [
            {"event": "Fileheader", "timestamp": "2026-09-27T12:00:00Z", "gameversion": "4.4.1.1"},
            {"event": "Location", "timestamp": "2026-09-27T12:00:01Z", "SystemAddress": 123},
            {"event": "Scan", "timestamp": "2026-09-27T12:00:02Z", "BodyID": 1},
        ]
        path.write_text("\n".join(json.dumps(e) for e in events) + "\n{broken\n" + json.dumps(
            {"event": "Scan", "timestamp": "2026-09-27T12:00:03Z", "BodyID": 2}) + "\n")
        self.reader.refresh()
        self.assertTrue(self.reader.blocks["exploration"]["requires_refresh"])
        self.assertEqual(2, len(self.data()["bodies"]))

    def test_large_result_keeps_list_shape_dates_and_omitted_counts(self):
        for identity in range(5):
            for species in range(8):
                self.apply("ScanOrganic", 2, Body=identity, Species=f"species{species}",
                           Species_Localised="S" * 240, Genus="G" * 160,
                           Genus_Localised="L" * 240, ScanType="Analyse")
        summary = self.reader.summary("exploration")
        self.assertLessEqual(len(summary), MAX_RESULT)
        result = json.loads(summary)
        self.assertIn("truncated", result)
        bodies = result["exploration"]["data"]["bodies"]
        self.assertIsInstance(bodies["items"], list)
        self.assertEqual(4, bodies["omitted"])
        organics = bodies["items"][0]["organic_observations"]
        self.assertEqual(7, organics["omitted"])
        self.assertIn("analysis_observed_at", organics["items"][0])

    def test_unknown_system_and_commander_changes_do_not_leak_catalogue(self):
        self.apply("Commander", FID="synthetic-one")
        self.apply("Scan", BodyID=1, BodyName="Synthetic 1")
        self.apply("Commander", 3, FID="synthetic-two")
        self.assertNotIn("exploration", self.reader.blocks)
        self.apply("Scan", 4, BodyID=2, BodyName="Synthetic 2")
        self.assertNotIn("exploration", self.reader.blocks)
