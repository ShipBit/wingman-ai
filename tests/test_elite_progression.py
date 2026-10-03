"""Career/engineer updates keep independent dates and never invent promotion."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from skills.elite_dangerous.telemetry import JournalReader, MAX_RESULT, RANK_FIELDS


class ProgressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reader = JournalReader(self.root)
        self.now = datetime(2026, 9, 27, 12, 1, tzinfo=timezone.utc)

    @staticmethod
    def event(kind, second=0, **values):
        return {"event": kind, "timestamp": f"2026-09-27T12:00:{second:02d}Z", **values}

    def apply(self, kind, second=0, **values):
        self.reader.apply(self.event(kind, second, **values))

    def careers(self, query=""):
        values = self.reader.snapshot("progression", query, self.now)["career"]["Ranks"]["items"]
        return {row["category"]: row for row in values}

    def engineers(self):
        return self.reader.blocks["engineerprogress"]["data"]["Engineers"]

    def test_promotion_changes_only_its_rank_and_invalidates_old_percentage(self):
        self.apply("Rank", Combat=3, Trade=5)
        self.apply("Progress", 1, Combat=99, Trade=42)
        original_trade = deepcopy(self.careers()["Trade"])
        self.apply("Promotion", 2, Combat=4)
        combat = self.careers()["Combat"]
        self.assertEqual(4, combat["rank"]["value"])
        self.assertTrue(combat["progress"]["requires_refresh"])
        self.assertEqual(99, combat["progress"]["reported_percent"])
        self.assertEqual(original_trade, self.careers()["Trade"])
        self.apply("Progress", 3, Combat=2)
        combat = self.careers()["Combat"]
        self.assertEqual(4, combat["progress"]["rank_at_observation"])
        self.assertNotIn("requires_refresh", combat["progress"])

    def test_percentages_above_100_do_not_promote_or_invent_unlocks(self):
        self.apply("Rank", Federation=4)
        self.apply("Progress", 1, Federation=135)
        row = self.careers()["Federation"]
        self.assertEqual(4, row["rank"]["value"])
        self.assertEqual(135, row["progress"]["reported_percent"])
        self.assertEqual(100, row["progress"]["display_percent"])
        self.assertNotIn("permits", row)

    def test_unknown_rank_and_future_numeric_levels_are_not_guessed(self):
        self.apply("Progress", Combat=25)
        self.assertNotIn("rank", self.careers()["Combat"])
        self.assertNotIn("rank_at_observation", self.careers()["Combat"]["progress"])
        self.apply("Rank", 1, Combat=40, Exobiologist=13, Soldier=9)
        self.assertEqual(40, self.careers()["Combat"]["rank"]["value"])
        self.assertTrue(self.careers()["Combat"]["progress"]["requires_refresh"])
        self.apply("Promotion", 2, Soldier=10)
        self.assertEqual(10, self.careers()["Soldier"]["rank"]["value"])

    def test_partial_reputation_preserves_other_superpower_dates(self):
        self.apply("Reputation", Empire=-50.5, Federation=25)
        original = deepcopy(self.reader.blocks["reputation"]["data"]["Federation"])
        self.apply("Reputation", 2, Empire=-20)
        data = self.reader.snapshot("progression", now=self.now)["reputation"]["data"]
        self.assertEqual(original, data["Federation"])
        self.assertEqual(-20, data["Empire"]["value"])
        self.assertEqual("2026-09-27T12:00:02Z", data["Empire"]["observed_at"])

    def test_invalid_multi_field_event_is_atomic(self):
        self.apply("Rank", Combat=3, Trade=4)
        self.apply("Promotion", 2, Combat=4, Trade=True)
        rows = self.careers()
        self.assertEqual(3, rows["Combat"]["rank"]["value"])
        self.assertEqual(4, rows["Trade"]["rank"]["value"])
        self.assertTrue(rows["Combat"]["rank"]["requires_refresh"])
        self.apply("Rank", 3, Combat=4)
        self.assertNotIn("requires_refresh", self.careers()["Combat"]["rank"])
        self.assertTrue(self.careers()["Trade"]["rank"]["requires_refresh"])

    def test_bad_percentages_and_future_dates_recover_without_poisoning(self):
        self.apply("Rank", Combat=1)
        self.apply("Progress", 1, Combat=10)
        for invalid in (-1, True, float("nan"), float("inf")):
            self.apply("Progress", 2, Combat=invalid)
            self.assertEqual(10, self.careers()["Combat"]["progress"]["reported_percent"])
        future = self.event("Progress", Combat=50)
        future["timestamp"] = "2099-01-01T00:00:00Z"
        self.reader.apply(future)
        self.apply("Progress", 3, Combat=15)
        self.assertEqual(15, self.careers()["Combat"]["progress"]["reported_percent"])
        self.assertNotIn("requires_refresh", self.careers()["Combat"]["progress"])
        self.apply("Reputation", 4, Empire=101)
        self.assertTrue(self.reader.blocks["reputation"]["data"]["Empire"]["requires_refresh"])

    def test_old_progress_cannot_bind_to_a_new_rank(self):
        self.apply("Rank", 1, Combat=2)
        self.apply("Promotion", 5, Combat=3)
        self.apply("Progress", 4, Combat=99)
        self.assertNotIn("reported_percent", self.careers()["Combat"]["progress"])
        self.assertTrue(self.careers()["Combat"]["progress"]["requires_refresh"])

    def test_gap_requires_each_metric_to_be_reobserved(self):
        path = self.root / "Journal.2026-09-27T120000.01.log"
        events = [self.event("Fileheader", gameversion="4.4.1.1"), self.event("Rank", 1, Combat=3, Trade=4),
                  self.event("Progress", 2, Combat=40, Trade=50)]
        path.write_text("\n".join(json.dumps(e) for e in events) + "\n{bad\n" +
                        json.dumps(self.event("Promotion", 3, Combat=4)) + "\n")
        self.reader.refresh()
        self.assertNotIn("requires_refresh", self.careers()["Combat"]["rank"])
        self.assertTrue(self.careers()["Trade"]["rank"]["requires_refresh"])
        self.assertTrue(self.careers()["Trade"]["progress"]["requires_refresh"])

    def test_engineer_grade_update_without_progress_state_is_accepted(self):
        self.apply("EngineerProgress", Engineers=[{"EngineerID": 1, "Engineer": "One", "Progress": "Unlocked", "Rank": 3},
                                                  {"EngineerID": 2, "Engineer": "Two", "Progress": "Known"}])
        other = deepcopy(self.engineers()[1])
        self.apply("EngineerProgress", 2, EngineerID=1, Rank=3, RankProgress=24.5)
        one = self.engineers()[0]
        self.assertEqual("Unlocked", one["Progress"])
        self.assertEqual(24.5, one["RankProgress"])
        self.assertEqual("2026-09-27T12:00:00Z", one["field_observed_at"]["Progress"])
        self.assertEqual("2026-09-27T12:00:02Z", one["field_observed_at"]["RankProgress"])
        self.assertEqual(other, self.engineers()[1])
        self.assertNotIn("requires_refresh", self.reader.blocks["engineerprogress"])

    def test_engineer_grade_change_clears_old_percent_and_state_change_clears_grade(self):
        self.apply("EngineerProgress", EngineerID=1, Progress="Unlocked", Rank=2, RankProgress=90)
        self.apply("EngineerProgress", 1, EngineerID=1, Rank=3)
        self.assertNotIn("RankProgress", self.engineers()[0])
        self.apply("EngineerProgress", 2, EngineerID=1, Progress="Barred")
        self.assertNotIn("Rank", self.engineers()[0])
        self.assertNotIn("RankProgress", self.engineers()[0])
        self.apply("EngineerProgress", 3, EngineerID=1, Rank=2)
        self.assertNotIn("Progress", self.engineers()[0])

    def test_invalid_engineer_values_preserve_data_until_new_snapshot(self):
        self.apply("EngineerProgress", Engineers=[{"EngineerID": 1, "Progress": "Unlocked", "Rank": 3}])
        before = deepcopy(self.engineers())
        self.apply("EngineerProgress", 1, EngineerID=1, RankProgress=True)
        self.assertEqual(before, self.engineers())
        self.assertTrue(self.reader.blocks["engineerprogress"]["requires_refresh"])
        self.apply("EngineerProgress", 2, Engineers=[{"EngineerID": 1, "Rank": 3, "RankProgress": 20}])
        self.assertNotIn("requires_refresh", self.reader.blocks["engineerprogress"])

    def test_filtered_career_and_large_engineer_summaries_remain_bounded(self):
        self.apply("Rank", **{name: 1 for name in RANK_FIELDS})
        self.apply("Progress", 1, **{name: 50 for name in RANK_FIELDS})
        self.apply("Reputation", 2, Empire=50, Federation=50, Independent=0, Alliance=0)
        self.apply("EngineerProgress", 3, Engineers=[{"EngineerID": i + 1, "Engineer": "A" * 160,
                   "Progress": "Unlocked", "Rank": 5, "RankProgress": 100} for i in range(30)])
        self.assertEqual(["Federation"], list(self.careers("Federation")))
        summary = self.reader.summary("progression", now=self.now)
        self.assertLessEqual(len(summary), MAX_RESULT)
        self.assertIn("career", json.loads(summary))

    def test_commander_reset_clears_all_career_observations(self):
        self.apply("Commander", FID="one")
        self.apply("Rank", Combat=3)
        self.apply("Progress", 1, Combat=30)
        self.apply("Commander", 2, FID="two")
        self.assertNotIn("career", self.reader.snapshot("progression", now=self.now))
