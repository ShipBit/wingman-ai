"""Tests for system jumps on trade routes and for location name matching.

No pytest. Run from the project root:

    python3 -m skills.uexcorp.tests.test_system_jumps_and_name_matching

Exits non-zero on the first failed assertion or crash; prints "ALL OK" on success.

Why this exists
---------------
The game log reported the player at "Stanton-Nyx Jump Point". difflib never offered
"Nyx Gateway (Stanton)" (other word order), so every trade route search started at
"Stanton Gateway (Nyx)", on the other side of the jump. Routes also crossed systems
without saying so, and the only system filter was "stay in one system or not".
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import unittest

from skills.uexcorp.uexcorp.api.llm import Llm
from skills.uexcorp.uexcorp.helper import Helper
from skills.uexcorp.uexcorp.tool.commodity_route import CommodityRoute
from skills.uexcorp.tests.test_commodity_route_auto_load import _FakeConfig, _FakeHelper, _parse_routes

STANTON, NYX, PYRO = 1, 2, 3
# Terminal ids: two in Stanton, one each in Nyx and Pyro
S1, S2, N1, P1 = 11, 12, 13, 14

# Names that push "Nyx Gateway (Stanton)" out of difflib's top ten for "Stanton-Nyx Jump Point"
DECOY_STATIONS = ["Baijini Point"] + [f"Monox Lagrange Point {n}" for n in range(1, 6)] + [
    f"Stanton Lagrange Point {n}" for n in range(1, 6)
]


class _WordEmbedder:
    """Stand-in for Core's embedding model: one dimension per word, so word order does not matter."""

    def __init__(self):
        self.vocabulary: dict[str, int] = {}
        self.calls = 0

    def __vector(self, text: str) -> list[float]:
        vector = [0.0] * 256
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            vector[self.vocabulary.setdefault(word, len(self.vocabulary))] += 1.0
        return vector

    def embed_sync(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [self.__vector(text) for text in texts]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return self.embed_sync(texts)


class _FakeAi:
    """Main model fallback of the name matcher: records the shortlist it was shown, matches nothing."""

    def __init__(self):
        self.prompts: list[str] = []

    async def generate(self, messages: list[dict]) -> str:
        self.prompts.append(messages[0]["content"])
        return "None"


class _FakeAnswers:
    def __init__(self, probabilities: dict[str, float]):
        self._probabilities = probabilities
        self.ok, self.error, self.seconds = True, None, 0.3

    def probabilities(self, key: str) -> dict[str, float]:
        return self._probabilities

    def confidence(self, key: str) -> float:
        return max(self._probabilities.values())

    def choice(self, key: str, min_confidence: float = 0.0) -> str | None:
        best = max(self._probabilities, key=self._probabilities.get)
        return best if self._probabilities[best] >= min_confidence else None


class _FakeSystemOne:
    """Answers with fixed probabilities for the names it is shown."""

    available = True

    def __init__(self, probabilities: dict[str, float]):
        self._probabilities = probabilities

    @staticmethod
    def choice(instructions: str, criteria: dict, **kwargs) -> dict:
        return {"criteria": criteria}

    async def decide(self, state, questions: dict) -> _FakeAnswers:
        shown = questions["match"]["criteria"]
        return _FakeAnswers({name: self._probabilities.get(name, 0.01) for name in shown})


class _FakeWingman:
    def __init__(self, local_ai):
        self.local_ai = local_ai
        self.ai = _FakeAi()
        self.system_one = None


class _MatchingConfig(_FakeConfig):
    def __init__(self, wingman: _FakeWingman):
        super().__init__()
        self._wingman = wingman

    def get_wingman(self) -> _FakeWingman:
        return self._wingman


class _MatchingHelper(_FakeHelper):
    def __init__(self, local_ai):
        super().__init__()
        self.wingman = _FakeWingman(local_ai)
        self._config = _MatchingConfig(self.wingman)
        self._llm = Llm(self)

    def get_llm(self) -> Llm:
        return self._llm

    def add_context(self, context: str) -> None:
        pass


class _DatabaseTest(unittest.TestCase):
    local_ai = None

    def setUp(self) -> None:
        from skills.uexcorp.uexcorp.database.database import Database

        self._original_helper = Helper._instance
        self._tmp_dir = tempfile.mkdtemp(prefix="uexcorp_system_jumps_test_")
        self._helper = _MatchingHelper(self.local_ai)
        Helper._instance = self._helper
        self._db = Database(self._tmp_dir, version="test-system-jumps", helper=self._helper)
        self._helper.set_database(self._db)
        self._seed_systems()
        self._db.commit()

    def tearDown(self) -> None:
        try:
            self._db.destroy()
        except Exception:
            pass
        Helper._instance = self._original_helper
        try:
            for name in os.listdir(self._tmp_dir):
                os.remove(os.path.join(self._tmp_dir, name))
            os.rmdir(self._tmp_dir)
        except OSError:
            pass

    def _seed_systems(self) -> None:
        for system_id, name in ((STANTON, "Stanton"), (NYX, "Nyx"), (PYRO, "Pyro")):
            self._db.execute("INSERT INTO star_system (id, name, is_available) VALUES (?, ?, 1)", (system_id, name))
        # Stanton links to Nyx and Pyro, Nyx and Pyro only through Stanton
        for orbit_id, name, system_id, system in (
            (21, "Nyx Gateway (Stanton system)", STANTON, "Stanton"),
            (22, "Stanton Gateway (Nyx system)", NYX, "Nyx"),
            (23, "Pyro Gateway (Stanton system)", STANTON, "Stanton"),
            (24, "Stanton Gateway (Pyro system)", PYRO, "Pyro"),
        ):
            self._db.execute(
                "INSERT INTO orbit (id, name, id_star_system, star_system_name, is_jump_point) VALUES (?, ?, ?, ?, 1)",
                (orbit_id, name, system_id, system),
            )
        stations = [
            ("Nyx Gateway (Stanton)", STANTON), ("Stanton Gateway (Nyx)", NYX), ("Nyx Gateway (Pyro)", PYRO),
            ("Everus Harbor", STANTON),
        ]
        stations += [(name, STANTON) for name in DECOY_STATIONS]
        for station_id, (name, system_id) in enumerate(stations, start=31):
            self._db.execute(
                "INSERT INTO space_station (id, name, id_star_system, is_available_live, has_trade_terminal) "
                "VALUES (?, ?, ?, 1, 1)",
                (station_id, name, system_id),
            )


class SystemJumpRouteTest(_DatabaseTest):
    def setUp(self) -> None:
        super().setUp()
        for terminal_id, name in ((S1, "Stanton One"), (S2, "Stanton Two"), (N1, "Nyx One"), (P1, "Pyro One")):
            self._db.execute(
                "INSERT INTO terminal (id, name, type, is_available) VALUES (?, ?, 'commodity', 1)", (terminal_id, name)
            )
        systems = {S1: "Stanton", S2: "Stanton", N1: "Nyx", P1: "Pyro"}
        names = {S1: "Stanton One", S2: "Stanton Two", N1: "Nyx One", P1: "Pyro One"}
        for route_id, (origin, destination, sell) in enumerate(
            ((S1, S2, 12), (S1, N1, 30), (P1, N1, 40)), start=101
        ):
            self._db.execute(
                """
                INSERT INTO commodity_route (
                    id, id_terminal_origin, id_terminal_destination, commodity_name,
                    origin_terminal_name, destination_terminal_name,
                    origin_star_system_name, destination_star_system_name,
                    price_origin, price_destination, scu_origin, scu_destination, distance
                ) VALUES (?, ?, ?, 'Laranite', ?, ?, ?, ?, 10, ?, 100, 100, 5)
                """,
                (route_id, origin, destination, names[origin], names[destination], systems[origin], systems[destination], sell),
            )
        self._db.commit()

    def _routes(self, **kwargs) -> dict[tuple[str, ...], int]:
        payload, _instant = CommodityRoute().execute(limit=15, available_cargo_space_scu=10, **kwargs)
        return {tuple(stop["terminal"] for stop in route["stops"]): route["system_jumps"] for route in _parse_routes(payload)}

    def test_every_route_says_its_system_jumps(self) -> None:
        self.assertEqual(self._routes(), {
            ("Stanton One", "Stanton Two"): 0,
            ("Stanton One", "Nyx One"): 1,
            ("Pyro One", "Nyx One"): 2,  # no direct jump: through Stanton
        })

    def test_route_starts_with_a_summary_and_ends_with_the_stops(self) -> None:
        payload, _instant = CommodityRoute().execute(
            limit=15, available_cargo_space_scu=10, filter_start_location="Pyro One"
        )
        route = _parse_routes(payload)[0]
        self.assertEqual(route["path"], "Pyro One -> Nyx One")
        self.assertEqual(route["systems"], "Pyro -> Nyx")
        self.assertEqual(route["main_cargo"], ["Laranite"])
        self.assertEqual(list(route)[-1], "stops")
        # Totals are what the user hears, the price per SCU stays for questions
        self.assertEqual(route["stops"][0]["buy"][0]["total_aUEC"], 100)
        self.assertEqual(route["stops"][1]["sell"][0]["total_aUEC"], 400)

    def test_max_system_jumps_limits_the_whole_route(self) -> None:
        self.assertEqual(set(self._routes(max_system_jumps=0)), {("Stanton One", "Stanton Two")})
        self.assertEqual(set(self._routes(max_system_jumps=1)), {("Stanton One", "Stanton Two"), ("Stanton One", "Nyx One")})

    def test_max_system_jumps_is_a_number_from_zero(self) -> None:
        from skills.uexcorp.uexcorp.tool.validator import Validator

        validator = CommodityRoute().get_optional_fields()["max_system_jumps"]
        self.assertEqual(validator.get_llm_definition()["type"], "number")
        self.assertEqual(asyncio.run(validator.validate(0)), 0)
        self.assertIsNone(asyncio.run(validator.validate(-1)))
        self.assertNotIn("filter_allow_star_system_change", CommodityRoute().get_optional_fields())
        self.assertIsInstance(validator, Validator)


class _LocationTest(_DatabaseTest):
    def _validate(self, name: str) -> str | None:
        from skills.uexcorp.uexcorp.tool.validator import Validator

        return asyncio.run(Validator(Validator.VALIDATE_LOCATION, config={"for_trading": True}).validate(name))

    def _notes(self) -> str:
        return " ".join(self._helper.get_handler_tool().notes)


class GatewayMatchingTest(_LocationTest):
    def test_game_log_jump_point_is_the_gateway_in_the_first_system(self) -> None:
        self.assertEqual(self._validate("Stanton-Nyx Jump Point"), "Nyx Gateway (Stanton)")
        self.assertEqual(self._validate("Stanton Nyx jump point"), "Nyx Gateway (Stanton)")

    def test_gateway_with_its_system_is_matched(self) -> None:
        self.assertEqual(self._validate("Nyx Gateway within the Stanton system"), "Nyx Gateway (Stanton)")
        self.assertEqual(self._validate("Stanton gateway in Nyx"), "Stanton Gateway (Nyx)")
        self.assertEqual(self._validate("Nyx Gateway (Pyro)"), "Nyx Gateway (Pyro)")

    def test_gateway_without_its_system_is_never_guessed(self) -> None:
        self.assertIsNone(self._validate("Nyx Gateway"))
        notes = self._notes()
        self.assertIn("Ask the user which star system", notes)
        self.assertIn("Nyx Gateway (Stanton)", notes)
        self.assertIn("Nyx Gateway (Pyro)", notes)
        self.assertNotIn("Stanton Gateway (Nyx)", notes)
        self.assertEqual(self._helper.wingman.ai.prompts, [])  # no model was asked to guess

    def test_other_names_never_match_a_gateway(self) -> None:
        self._validate("Nyx in Stanton")
        self.assertNotIn("Gateway", self._helper.wingman.ai.prompts[-1])


class EmbeddingMatchingTest(_LocationTest):
    local_ai = _WordEmbedder()

    def test_embeddings_bring_names_in_other_word_order_into_the_shortlist(self) -> None:
        self._validate("harbour of everus")
        self.assertIn("Everus Harbor", self._helper.wingman.ai.prompts[-1])

    def test_names_are_embedded_once(self) -> None:
        self._validate("harbour of everus")
        calls = self.local_ai.calls
        self._validate("everus harbour station")
        self.assertEqual(self.local_ai.calls, calls + 1)  # only the search term


class WithoutEmbeddingsTest(_LocationTest):
    local_ai = None  # no embedding model: matching works as before

    def test_falls_back_to_difflib(self) -> None:
        self.assertIsNone(self._validate("harbour of everus"))
        self.assertNotIn("Everus Harbor", " ".join(self._helper.wingman.ai.prompts))


class SystemOneMatchingTest(_LocationTest):
    local_ai = _WordEmbedder()

    def test_a_sure_answer_is_used(self) -> None:
        self._helper.wingman.system_one = _FakeSystemOne({"Everus Harbor": 0.9})
        self.assertEqual(self._validate("harbour of everus"), "Everus Harbor")

    def test_an_unsure_answer_asks_the_user_instead_of_the_main_model(self) -> None:
        self._helper.wingman.system_one = _FakeSystemOne({"Baijini Point": 0.3, "Everus Harbor": 0.25})
        self.assertIsNone(self._validate("harbour of everus"))
        self.assertEqual(self._helper.wingman.ai.prompts, [])
        notes = self._notes()
        self.assertIn("ask the user", notes)
        self.assertLess(notes.index("Baijini Point"), notes.index("Everus Harbor"))  # best guess first

    def test_one_name_far_ahead_is_used_as_a_guess_with_the_others(self) -> None:
        # Like 'Leske': Levski 0.29, the next names 0.02, none of these 0.66
        self._helper.wingman.system_one = _FakeSystemOne({"Everus Harbor": 0.29, "none_of_these": 0.66})
        self.assertEqual(self._validate("harbour of everus"), "Everus Harbor")
        self.assertEqual(self._helper.wingman.ai.prompts, [])  # no second model asked
        notes = self._notes()
        self.assertIn("'harbour of everus' was taken as 'Everus Harbor' (best guess)", notes)
        self.assertIn("e.g. ", notes)  # the other names, so the user can correct it right away

    def test_a_weak_lead_still_asks_the_user(self) -> None:
        self._helper.wingman.system_one = _FakeSystemOne({"Everus Harbor": 0.12, "none_of_these": 0.85})
        self.assertIsNone(self._validate("harbour of everus"))
        self.assertIn("ask the user", self._notes())

    EVERUS_HARBOR = 34  # its id in _seed_systems

    def _terminal(self, terminal_id: int, name: str, station: str = "Everus Harbor", station_id: int = EVERUS_HARBOR) -> None:
        self._db.execute(
            "INSERT INTO terminal (id, name, type, is_available, id_star_system, star_system_name, "
            "space_station_name, id_space_station) VALUES (?, ?, 'commodity', 1, ?, 'Stanton', ?, ?)",
            (terminal_id, name, STANTON, station, station_id),
        )
        self._db.commit()

    def test_two_names_for_the_same_terminal_are_not_asked_about(self) -> None:
        # Like "ARC-L4": "Admin - ARC-L4" 0.47 against "ARC-L4 Faint Glen Station" 0.42
        self._terminal(501, "Admin - Everus Harbor")
        self._helper.wingman.system_one = _FakeSystemOne({"Admin - Everus Harbor": 0.47, "Everus Harbor": 0.42})
        self.assertEqual(self._validate("everus harbor admin"), "Admin - Everus Harbor")
        self.assertNotIn("ask the user", self._notes())

    def test_the_place_with_all_the_terminals_is_taken(self) -> None:
        # Like "HUR-L2": the station has the Admin terminal and one more, so the station is meant
        self._terminal(501, "Admin - Everus Harbor")
        self._terminal(502, "Market - Everus Harbor")
        self._helper.wingman.system_one = _FakeSystemOne({"Admin - Everus Harbor": 0.47, "Everus Harbor": 0.42})
        self.assertEqual(self._validate("everus harbor admin"), "Everus Harbor")

    def test_a_place_and_the_wider_one_around_it_are_still_asked_about(self) -> None:
        # Like "Lorville" and "Hurston": the system has terminals under other roofs too
        self._terminal(501, "Admin - Everus Harbor")
        self._terminal(503, "Admin - Port Olisar", station="Port Olisar", station_id=99)
        self._helper.wingman.system_one = _FakeSystemOne({"Everus Harbor": 0.47, "Stanton": 0.42})
        self.assertIsNone(self._validate("everus harbor stanton"))
        self.assertIn("ask the user", self._notes())

    def test_different_places_are_still_asked_about(self) -> None:
        self._terminal(501, "Admin - Everus Harbor")  # Baijini Point has no terminal here
        self._helper.wingman.system_one = _FakeSystemOne({"Baijini Point": 0.3, "Everus Harbor": 0.25})
        self.assertIsNone(self._validate("harbour of everus"))
        self.assertIn("ask the user", self._notes())

    def test_an_unknown_name_in_a_list_is_left_out_not_the_whole_list(self) -> None:
        from skills.uexcorp.uexcorp.tool.validator import Validator

        validator = Validator(Validator.VALIDATE_LOCATION, multiple=True, config={"for_trading": True})
        self.assertEqual(asyncio.run(validator.validate(["Everus Harbor", "qqqq xxxx"])), ["Everus Harbor"])
        self.assertIn("Not recognized and left out: qqqq xxxx", self._notes())
        self.assertIsNone(asyncio.run(validator.validate(["qqqq xxxx"])))  # nothing known: still fails


def main() -> None:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(case)
        for case in (
            SystemJumpRouteTest, GatewayMatchingTest, EmbeddingMatchingTest, WithoutEmbeddingsTest,
            SystemOneMatchingTest,
        )
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
