"""Route progress and fuel provenance through real journal/sidecar ingestion."""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from skills.elite_dangerous.telemetry import JournalReader, MAX_RESULT, MAX_ROUTE_SYSTEMS


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.journal = self.root / "Journal.2026-09-27T120000.01.log"
        self.reader = JournalReader(self.root)
        self.now = datetime(2026, 9, 27, 12, 0, 50, tzinfo=timezone.utc)
        self.append("Fileheader", 0, gameversion="4.4.1.1")
        self.append("LoadGame", 1, FID="synthetic")
        self.append("Location", 2, StarSystem="System 1", SystemAddress=1)

    @staticmethod
    def event(kind, second, **values):
        return {"event": kind, "timestamp": f"2026-09-27T12:00:{second:02d}Z", **values}

    def append(self, kind, second, **values):
        with self.journal.open("a") as handle:
            handle.write(json.dumps(self.event(kind, second, **values)) + "\n")

    def sidecar(self, kind="NavRoute", second=3, **values):
        filename = "Status.json" if kind == "Status" else "NavRoute.json"
        (self.root / filename).write_text(json.dumps(self.event(kind, second, **values)))

    @staticmethod
    def rows(count=9):
        return [{"StarSystem": f"System {i}", "SystemAddress": i,
                 "StarPos": [i * 3, i * 4, 0], "StarClass": "G" if i == 8 else "L"}
                for i in range(1, count + 1)]

    def state(self, query=""):
        self.reader.refresh()
        return self.reader.snapshot("navigation", query, self.now)

    def test_progress_uses_current_system_before_output_cap(self):
        self.sidecar(Route=self.rows())
        self.append("FSDJump", 4, SystemAddress=6, StarSystem="System 6")
        data = self.state()["route"]["data"]
        self.assertEqual(3, data["remaining_jumps"])
        self.assertEqual(15, data["remaining_distance_ly"])
        self.assertEqual("System 7", data["Route"]["items"][0]["StarSystem"])
        self.assertEqual(2, data["next_standard_scoop_star"]["jumps_ahead"])
        self.assertEqual(3, data["Route"]["total"])
        self.assertEqual(1, self.state("System 9")["route"]["data"]["Route"]["total"])
        self.assertEqual(3, self.state("System 9")["route"]["data"]["remaining_jumps"])

    def test_arrival_and_interleaved_target(self):
        self.sidecar(Route=self.rows(3))
        self.append("FSDTarget", 3, Name="System 2", SystemAddress=2)
        self.append("StartJump", 4, JumpType="Hyperspace", SystemAddress=2)
        self.append("FSDTarget", 5, Name="System 3", SystemAddress=3)
        self.assertEqual("location_unconfirmed_or_in_transit", self.state()["route"]["data"]["progress"])
        self.append("FSDJump", 6, SystemAddress=2, StarSystem="System 2")
        self.assertEqual(3, self.state()["navigation"]["data"]["SystemAddress"])
        self.append("FSDJump", 7, SystemAddress=3, StarSystem="System 3")
        state = self.state()
        self.assertNotIn("navigation", state)
        self.assertEqual("at_plotted_destination", state["route"]["data"]["progress"])
        self.assertEqual(0, state["route"]["data"]["remaining_jumps"])

    def test_clear_sidecar_and_same_second_old_route_cannot_resurrect(self):
        self.sidecar(Route=self.rows())
        self.state()
        self.sidecar("NavRouteClear", 4)
        self.assertEqual("no_plotted_route", self.state()["route"]["data"]["progress"])
        self.sidecar(second=4, Route=self.rows())
        self.assertEqual(0, self.state()["route"]["data"]["Route"]["total"])

    def test_clear_file_preserves_newer_independently_selected_target(self):
        self.sidecar("NavRouteClear", 3)
        self.append("FSDTarget", 4, Name="System 2", SystemAddress=2)
        self.assertEqual(2, self.state()["navigation"]["data"]["SystemAddress"])

    def test_target_off_route_is_exposed_without_rewriting_plotted_route(self):
        self.sidecar(Route=self.rows())
        self.append("FSDTarget", 4, Name="Elsewhere", SystemAddress=999)
        self.assertFalse(self.state()["route"]["data"]["selected_target_matches_next_stop"])
        self.append("StartJump", 5, JumpType="Supercruise")
        self.assertEqual(8, self.state()["route"]["data"]["remaining_jumps"])

    def test_replot_waits_for_new_snapshot_and_same_second_file_is_accepted(self):
        self.sidecar(Route=self.rows())
        self.state()
        self.append("NavRoute", 5)
        state = self.state()["route"]
        self.assertTrue(state["requires_refresh"])
        self.assertNotIn("remaining_jumps", state["data"])
        self.sidecar(second=5, Route=self.rows(4))
        self.assertEqual(3, self.state()["route"]["data"]["remaining_jumps"])

    def test_ambiguous_absent_and_invalid_routes_do_not_guess_progress(self):
        for second, rows in enumerate((self.rows()[1:], self.rows() + self.rows()[:1]), 3):
            self.sidecar(second=second, Route=rows)
            data = self.state()["route"]["data"]
            self.assertNotIn("remaining_jumps", data)
        for bad in (True, float("nan"), float("inf"), 10 ** 400):
            rows = self.rows()
            rows[0]["StarPos"][0] = bad
            self.sidecar(second=6, Route=rows)
            self.assertTrue(self.state()["route"]["requires_refresh"])
        self.sidecar(second=7, Route=self.rows())
        self.assertEqual(8, self.state()["route"]["data"]["remaining_jumps"])

    def test_future_route_does_not_poison_later_valid_snapshot(self):
        self.sidecar(Route=self.rows())
        self.state()
        future = self.event("NavRoute", 6, Route=self.rows())
        future["timestamp"] = "2099-01-01T00:00:00Z"
        (self.root / "NavRoute.json").write_text(json.dumps(future))
        self.assertTrue(self.state()["route"]["requires_refresh"])
        self.sidecar(second=7, Route=self.rows())
        self.assertEqual(8, self.state()["route"]["data"]["remaining_jumps"])

    def test_same_second_replot_cannot_reuse_unchanged_old_file(self):
        self.sidecar(Route=self.rows())
        self.state()
        self.append("NavRoute", 3)
        self.assertTrue(self.state()["route"]["requires_refresh"])
        self.sidecar(Route=self.rows(5))
        self.assertEqual(4, self.state()["route"]["data"]["remaining_jumps"])

    def test_partial_route_file_invalidates_previous_progress(self):
        self.sidecar(Route=self.rows())
        self.state()
        (self.root / "NavRoute.json").write_text('{"event":"NavRoute",')
        self.assertTrue(self.state()["route"]["requires_refresh"])
        self.sidecar(second=6, Route=self.rows(5))
        self.assertEqual(4, self.state()["route"]["data"]["remaining_jumps"])

    def test_route_limit_rejects_entire_route_without_truncating_destination(self):
        self.sidecar(Route=self.rows(MAX_ROUTE_SYSTEMS + 1))
        data = self.state()["route"]
        self.assertTrue(data["requires_refresh"])
        self.assertNotIn("destination", data["data"])

    def test_large_route_summary_finds_later_scoop_star_and_remains_bounded(self):
        self.sidecar(Route=self.rows(1000))
        data = self.state()["route"]["data"]
        self.assertEqual(994, data["Route"]["omitted"])
        self.assertEqual(7, data["next_standard_scoop_star"]["jumps_ahead"])
        self.assertLessEqual(len(self.reader.summary("navigation", now=self.now)), MAX_RESULT)

    def test_fuel_and_range_keep_independent_dates_and_vessel_context(self):
        self.append("Loadout", 3, ShipID=1, MaxJumpRange=32.5, FuelCapacity={"Main": 16, "Reserve": 0.5})
        self.sidecar("Status", 4, Flags=(1 << 24) | (1 << 19), Fuel={"FuelMain": 2.5, "FuelReservoir": 0.3})
        travel = self.state()["travel"]
        self.assertEqual(32.5, travel["ship"]["unladen_max_jump_range_ly"])
        self.assertTrue(travel["status"]["low_fuel_flag"])
        self.assertNotEqual(travel["ship"]["observed_at"], travel["status"]["observed_at"])
        for extra in (1 << 25, 1 << 26):
            self.sidecar("Status", 5, Flags=(1 << 24) | extra, Fuel={"FuelMain": 2.5})
            self.assertNotIn("status", self.state()["travel"])
        self.sidecar("Status", 6, Flags=1 << 24, Flags2=2, Fuel={"FuelMain": 2.5})
        self.assertNotIn("status", self.state()["travel"])

    def test_changed_ship_rejects_old_fuel_and_unladen_range(self):
        self.append("Loadout", 3, ShipID=1, MaxJumpRange=32.5)
        self.sidecar("Status", 4, Flags=1 << 24, Fuel={"FuelMain": 2.5})
        self.state()
        self.append("ShipyardSwap", 5, ShipID=2)
        travel = self.state()["travel"]
        self.assertNotIn("ship", travel)
        self.assertNotIn("status", travel)

    def test_journal_gap_blocks_route_until_new_snapshot(self):
        self.sidecar(Route=self.rows())
        self.state()
        with self.journal.open("a") as handle:
            handle.write("{malformed\n")
        self.assertTrue(self.state()["route"]["requires_refresh"])
        self.sidecar(second=6, Route=self.rows())
        self.assertNotIn("remaining_jumps", self.state()["route"]["data"])
        self.append("Location", 7, StarSystem="System 1", SystemAddress=1)
        self.assertEqual(8, self.state()["route"]["data"]["remaining_jumps"])
