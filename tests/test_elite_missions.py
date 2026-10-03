"""Mission briefings must preserve journal facts, dates and unknown outcomes."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from skills.elite_dangerous.telemetry import JournalReader, MAX_MISSIONS, MAX_MISSION_OUTCOMES, MAX_RESULT


class MissionTests(unittest.TestCase):
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

    def rows(self, query=""):
        return self.reader.snapshot("missions", query, self.now)["missions"]["data"]["items"]

    def roster(self, second=0, **values):
        self.apply("Missions", second, **{"Active": [], "Complete": [], "Failed": [], **values})

    def test_redirect_replaces_destination_without_retiming_contract(self):
        self.apply("MissionAccepted", 1, MissionID=1, DestinationSystem="Old", DestinationStation="Old Port",
                   DestinationSettlement="Old Settlement", Reward=5000, Count=10, Commodity="gold",
                   Expiry="2026-09-27T13:00:00Z", PassengerWanted=True, PassengerCount=2)
        before = self.rows()[0]
        self.apply("MissionRedirected", 2, MissionID=1, NewDestinationSystem="New", NewDestinationStation="New Port")
        row = self.rows()[0]
        self.assertEqual("New", row["destination"]["DestinationSystem"])
        self.assertNotIn("DestinationSettlement", row["destination"])
        self.assertEqual(before["details"], row["details"])
        self.assertEqual(before["deadline"], row["deadline"])
        self.assertEqual(5000, row["details"]["expected_reward_credits"])
        self.assertNotIn("Reward", row["details"])
        self.assertTrue(row["details"]["PassengerWanted"])

    def test_snapshot_expiry_is_relative_to_observation_and_elapsed_is_not_failure(self):
        self.roster(2, Active=[{"MissionID": 1, "Expires": 30, "Name": "Courier"}, {"MissionID": 2, "Expires": 0}])
        one, two = self.rows()
        self.assertEqual(-28, one["deadline"]["seconds_until_expiry"])
        self.assertEqual("deadline_elapsed_outcome_unconfirmed", one["deadline"]["interpretation"])
        self.assertEqual("active_reported", one["state"])
        self.assertNotIn("expires_at", two["deadline"])
        self.assertNotIn("mission_outcomes", self.reader.blocks)

    def test_complete_snapshot_does_not_report_payment_and_terminal_reward_does_not_change_balance(self):
        self.apply("LoadGame", Credits=100)
        self.roster(1, Complete=[{"MissionID": 1, "Name": "Complete contract"}], Failed=[{"MissionID": 2}])
        self.assertEqual("complete_reported", self.rows()[0]["state"])
        self.assertNotIn("reported_reward_credits", self.rows()[0])
        self.apply("MissionCompleted", 2, MissionID=1, Reward=3000)
        self.assertEqual({}, self.reader.missions)
        self.assertEqual(3000, self.reader.mission_outcomes["1"]["reported_reward_credits"])
        self.assertEqual(100, self.reader.blocks["pilot"]["data"]["Credits"])

    def test_depot_progress_is_not_fraction_delivered_or_current_cargo(self):
        self.apply("MissionAccepted", MissionID=1, Count=3020)
        self.apply("Cargo", 1, Vessel="Ship", Count=8, Inventory=[{"Name": "gold", "Count": 8, "Stolen": 0}])
        self.apply("CargoDepot", 2, MissionID=1, UpdateType="WingUpdate", ItemsCollected=16,
                   ItemsDelivered=16, TotalItemsToDeliver=3020, Progress=0.0)
        row = self.rows()[0]
        self.assertEqual(3004, row["delivery"]["items_remaining_to_deliver"])
        self.assertNotIn("Progress", row["delivery"])
        self.assertNotIn("requires_refresh", self.reader.blocks["cargo"])
        self.apply("CargoDepot", 3, MissionID=1, UpdateType="Deliver", ItemsDelivered=3020, TotalItemsToDeliver=3020)
        self.assertEqual(0, self.rows()[0]["delivery"]["items_remaining_to_deliver"])
        self.assertEqual("accepted", self.rows()[0]["state"])
        self.assertTrue(self.reader.blocks["cargo"]["requires_refresh"])

    def test_partial_depot_observation_never_guesses_zero(self):
        self.apply("CargoDepot", MissionID=1, UpdateType="Collect", Count=8, CargoType="gold")
        row = self.rows()[0]
        self.assertEqual("activity_observed", row["state"])
        self.assertNotIn("items_remaining_to_deliver", row["delivery"])
        self.assertIsNone(self.reader.blocks["missions"]["roster_observed_at"])

    def test_roster_preserves_known_details_but_not_after_a_gap(self):
        self.apply("MissionAccepted", MissionID=1, DestinationSystem="Sol", Reward=1000)
        self.roster(1, Active=[{"MissionID": 1, "Expires": 30}])
        self.assertEqual("Sol", self.rows()[0]["destination"]["DestinationSystem"])
        self.reader._invalidate("missions", self.event("Unknown", 2), "Journal gap")
        self.roster(3, Active=[{"MissionID": 1, "Expires": 20}])
        self.assertNotIn("details", self.rows()[0])
        self.assertNotIn("destination", self.rows()[0])
        self.assertNotIn("requires_refresh", self.reader.blocks["missions"])

    def test_invalid_snapshot_is_atomic_and_no_missing_array_means_empty(self):
        self.apply("MissionAccepted", MissionID=1, DestinationSystem="Sol")
        original = deepcopy(self.reader.missions)
        self.apply("Missions", 1, Active=[])
        self.assertEqual(original, self.reader.missions)
        self.assertTrue(self.reader.blocks["missions"]["requires_refresh"])
        self.roster(2, Active=[{"MissionID": 2}, {"MissionID": True}])
        self.assertEqual(original, self.reader.missions)
        self.roster(3, Active=[{"MissionID": 2}], Complete=[{"MissionID": 2}])
        self.assertEqual(original, self.reader.missions)

    def test_out_of_order_and_future_data_cannot_resurrect_completed_mission(self):
        self.apply("MissionAccepted", 1, MissionID=1)
        self.apply("MissionCompleted", 3, MissionID=1)
        self.apply("MissionAccepted", 2, MissionID=1)
        self.assertEqual({}, self.reader.missions)
        self.apply("MissionRedirected", 4, MissionID=1, NewDestinationSystem="Sol")
        self.assertEqual({}, self.reader.missions)
        self.reader.apply({**self.event("MissionAccepted", MissionID=2), "timestamp": "2099-01-01T00:00:00Z"})
        self.roster(5, Active=[{"MissionID": 2}])
        self.assertEqual(["2"], list(self.reader.missions))
        self.assertNotIn("requires_refresh", self.reader.blocks["missions"])

    def test_rejected_initial_event_still_has_valid_bounded_summary(self):
        self.apply("MissionAccepted", MissionID=False)
        state = json.loads(self.reader.summary("missions", now=self.now))
        self.assertTrue(state["missions"]["requires_refresh"])
        self.assertEqual(0, state["missions"]["data"]["total"])

    def test_bad_quantities_deadlines_and_depot_totals_preserve_previous_state(self):
        self.apply("MissionAccepted", MissionID=1, Count=10)
        original = deepcopy(self.reader.missions)
        for values in ({"Reward": True}, {"Count": -1}, {"PassengerWanted": "yes"}, {"Expiry": "not-a-date"}):
            self.apply("MissionAccepted", 1, MissionID=2, **values)
            self.assertEqual(original, self.reader.missions)
        self.apply("CargoDepot", 2, MissionID=1, UpdateType="Deliver", ItemsDelivered=11, TotalItemsToDeliver=10)
        self.assertEqual(original, self.reader.missions)
        self.roster(3, Active=[{"MissionID": 1, "Expires": 10 ** 30}])
        self.assertEqual(original, self.reader.missions)
        self.roster(4, Active=[{"MissionID": 1, "Expires": 50}])
        self.assertNotIn("requires_refresh", self.reader.blocks["missions"])

    def test_large_mission_descriptions_and_histories_stay_bounded(self):
        for identity in range(1, 31):
            self.apply("MissionCompleted", MissionID=identity, Name="N" * 240, Faction="F" * 240, Reward=1000)
        for identity in range(31, 51):
            self.apply("MissionAccepted", MissionID=identity, Name="N" * 240, LocalisedName="L" * 240,
                       DestinationSystem="S" * 240, DestinationStation="P" * 240, Faction="F" * 240,
                       Commodity_Localised="C" * 240, Expiry="2026-09-28T00:00:00Z")
        summary = self.reader.summary("missions", now=self.now)
        data = json.loads(summary)
        self.assertLessEqual(len(summary), MAX_RESULT)
        self.assertIn("missions", data)
        self.assertEqual(19, data["missions"]["data"]["omitted"])
        self.assertIn("deadline", data["missions"]["data"]["items"][0])

    def test_only_reported_mission_ends_remove_observations(self):
        self.apply("MissionAccepted", MissionID=1)
        self.apply("MissionAccepted", 1, MissionID=2)
        self.apply("Died", 2)
        self.assertEqual(2, len(self.reader.missions))
        self.apply("MissionAbandoned", 3, MissionID=1, Fine=500)
        self.assertEqual(["2"], list(self.reader.missions))
        self.assertEqual(500, self.reader.mission_outcomes["1"]["Fine"])
        self.apply("MissionFailed", 4, MissionID=2)
        self.assertEqual({}, self.reader.missions)

    def test_deadline_order_filter_and_output_bound(self):
        for identity in range(1, 11):
            self.apply("MissionAccepted", MissionID=identity, LocalisedName=f"Task {identity}",
                       Expiry=f"2026-09-27T12:{30-identity:02d}:00Z")
        rows = self.rows()
        self.assertEqual(10, rows[0]["MissionID"])
        self.assertEqual(5, len(rows))
        self.assertEqual(6, self.rows("Task 6")[0]["MissionID"])
        self.assertLessEqual(len(self.reader.summary("missions", now=self.now)), MAX_RESULT)

    def test_roster_and_outcomes_are_bounded_and_commander_reset_clears_both(self):
        self.apply("Commander", FID="first")
        self.roster(1, Active=[{"MissionID": i + 1} for i in range(MAX_MISSIONS + 1)])
        self.assertTrue(self.reader.blocks["missions"]["requires_refresh"])
        self.roster(2)
        for identity in range(MAX_MISSION_OUTCOMES + 5):
            self.apply("MissionFailed", 3, MissionID=identity + 1, Fine=100)
        self.assertEqual(MAX_MISSION_OUTCOMES, len(self.reader.mission_outcomes))
        self.apply("Commander", 4, FID="second")
        self.assertEqual({}, self.reader.mission_outcomes)
        self.assertNotIn("missions", self.reader.blocks)

    def test_gap_then_later_delta_does_not_repair_roster(self):
        path = self.root / "Journal.2026-09-27T120000.01.log"
        events = [self.event("Fileheader", gameversion="4.4.1.1"),
                  self.event("MissionAccepted", 1, MissionID=1, DestinationSystem="Old")]
        path.write_text("\n".join(json.dumps(e) for e in events) + "\n{broken\n" +
                        json.dumps(self.event("MissionRedirected", 3, MissionID=1, NewDestinationSystem="New")) + "\n")
        self.reader.refresh()
        self.assertTrue(self.reader.blocks["missions"]["requires_refresh"])
        self.assertEqual("New", self.rows()[0]["destination"]["DestinationSystem"])
