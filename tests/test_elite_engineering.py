"""Synthetic reference data; never assume a full grade climb from one recipe."""

from copy import deepcopy
import json
import time
import unittest

from integrations.elite_dangerous.engineering import EngineeringData, LIMIT


class ReferenceProvider:
    def __init__(self):
        self.calls = []
        self.error = None
        self.unavailable = False
        self.head = {"sha": "a" * 40, "commit": {"committer": {"date": "2025-01-01T00:00:00Z"}}}
        self.blueprints = {"FSD_Test": {"name": "Test range", "modulename": ["Frame shift drive", "FSD"],
            "grades": {"5": {"components": {"Test wake exceptions": 2, "Test iron": 1}}}}}
        self.modules = {"fsd": {"blueprints": {"FSD_Test": {"grades": {"5": {"engineers": ["Test engineer"]}}}}}}
        self.materials = [{"name": "Test wake exceptions", "symbol": "TestWake", "type": "Encoded"},
                          {"name": "Test iron", "symbol": "TestIron", "type": "Raw"}]

    def _fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = self.head if url.endswith("/commits/master") else (
            self.blueprints if url.endswith("blueprints.json") else
            self.modules if url.endswith("modules.json") else self.materials)
        return None if self.unavailable else deepcopy(value), time.time(), bool(self.error), self.error


class EngineeringTests(unittest.TestCase):
    def setUp(self):
        self.provider = ReferenceProvider()
        self.reference = EngineeringData(self.provider)

    def test_exact_recipe_costs_and_real_identifier_mapping(self):
        result = self.reference.lookup("fsd_test", applications=3)
        recipe = result["recipes"][0]
        self.assertEqual("FSD_Test", recipe["id"])
        self.assertEqual(6, recipe["materials"][0]["required_for_requested_applications"])
        self.assertEqual("testwake", recipe["materials"][0]["journal_symbol"])
        self.assertEqual(["Test engineer"], recipe["engineers_in_reference"])
        self.assertIn("not a full grade climb", result["scope"])
        self.assertIn("Unverified", recipe["engineer_access"])
        self.assertEqual(5, len(self.provider.calls))
        self.assertTrue(all("deadline" in options for _, options in self.provider.calls))
        self.assertIn("a" * 40, result["sources"][1]["url"])

    def test_search_words_and_top_five(self):
        for i in range(8):
            self.provider.blueprints[f"FSD_Other{i}"] = deepcopy(self.provider.blueprints["FSD_Test"])
        result = self.reference.lookup("FSD range")
        self.assertEqual(9, result["matching_recipes"])
        self.assertEqual(5, len(result["recipes"]))
        self.assertEqual(4, result["omitted_recipes"])
        self.assertLessEqual(len(json.dumps(result)), LIMIT)
        self.assertEqual(1, self.reference.lookup("FSD_Test")["matching_recipes"])

    def test_missing_grade_or_components_never_means_free(self):
        for grade in ({}, {"components": {}}, {"components": {"Test iron": True}}, {"components": {"Test iron": -1}}):
            self.provider.blueprints["FSD_Test"]["grades"]["5"] = grade
            recipe = self.reference.lookup("FSD_Test")["recipes"][0]
            self.assertIn("unknown", recipe["cost_status"])
            self.assertNotIn("materials", recipe)

    def test_missing_or_ambiguous_identity_does_not_guess(self):
        self.provider.materials.append(dict(self.provider.materials[0]))
        self.provider.materials[1]["symbol"] = "bad symbol"
        recipe = self.reference.lookup("FSD_Test")["recipes"][0]
        self.assertTrue(all("journal_symbol" not in row for row in recipe["materials"]))
        self.assertTrue(all("unknown" in row["inventory_match"] for row in recipe["materials"]))

    def test_cached_outage_remains_explicit(self):
        self.provider.error = "Provider cooldown"
        result = self.reference.lookup("FSD_Test")
        self.assertTrue(result["stale_reference"])
        self.assertTrue(result["recipes"])
        self.assertTrue(all(source["error"] for source in result["sources"]))
        self.provider.unavailable = True
        result = self.reference.lookup("FSD_Test")
        self.assertIn("error", result)
        self.assertFalse(result["recipes"])

    def test_invalid_inputs_never_fetch(self):
        for args in (("",), ("x" * 101,), ("test", True), ("test", 6), ("test", 5, 0),
                     ("test", 5, 101), ("test", 5, 1, "legacy")):
            self.assertIn("error", self.reference.lookup(*args))
        self.assertEqual([], self.provider.calls)

    def test_future_or_invalid_revision_blocks_lookup(self):
        for head in ({"sha": "not a revision"}, {"sha": "a" * 40, "commit": {"committer": {"date": "2999-01-01T00:00:00Z"}}}):
            self.provider.head = head
            result = self.reference.lookup("FSD_Test")
            self.assertIn("error", result)
            self.assertFalse(result["recipes"])

    def test_no_match_is_not_an_in_game_availability_claim(self):
        result = self.reference.lookup("notexisting")
        self.assertFalse(result["recipes"])
        self.assertIn("does not establish", result["note"])
        self.assertEqual(2, len(self.provider.calls))
