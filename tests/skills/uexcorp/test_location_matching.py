"""Matching a spoken location to a terminal or place.

The game log reported the player at "Stanton-Nyx Jump Point". difflib never offered "Nyx Gateway
(Stanton)" (other word order), so every search started at "Stanton Gateway (Nyx)", on the other side
of the jump. A name that is not sure is never guessed silently: the user is asked."""

import asyncio
import re

import pytest

from skills.uexcorp.uexcorp.tool.validator import Validator
from tests.skills.uexcorp.support import add_terminal

STANTON, NYX, PYRO = 1, 2, 3
EVERUS_HARBOR = 34  # its id in the stations below

# Names that push "Nyx Gateway (Stanton)" out of difflib's top ten for "Stanton-Nyx Jump Point"
DECOY_STATIONS = ["Baijini Point"] + [f"Monox Lagrange Point {n}" for n in range(1, 6)] + [
    f"Stanton Lagrange Point {n}" for n in range(1, 6)
]


class WordEmbedder:
    """Stand-in for Core's embedding model: one dimension per word, so word order does not matter."""

    def __init__(self):
        self.vocabulary: dict[str, int] = {}
        self.calls = 0

    def embed_sync(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        vectors = []
        for text in texts:
            vector = [0.0] * 256
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                vector[self.vocabulary.setdefault(word, len(self.vocabulary))] += 1.0
            vectors.append(vector)
        return vectors

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return self.embed_sync(texts)


class Answers:
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


class SystemOne:
    """Answers with fixed probabilities for the names it is shown."""

    available = True

    def __init__(self, probabilities: dict[str, float]):
        self._probabilities = probabilities

    @staticmethod
    def choice(instructions: str, criteria: dict, **kwargs) -> dict:
        return {"criteria": criteria}

    async def decide(self, state, questions: dict) -> Answers:
        shown = questions["match"]["criteria"]
        return Answers({name: self._probabilities.get(name, 0.01) for name in shown})


@pytest.fixture
def places(helper, db):
    for system_id, name in ((STANTON, "Stanton"), (NYX, "Nyx"), (PYRO, "Pyro")):
        db.execute("INSERT INTO star_system (id, name, is_available) VALUES (?, ?, 1)", (system_id, name))
    stations = [
        ("Nyx Gateway (Stanton)", STANTON), ("Stanton Gateway (Nyx)", NYX), ("Nyx Gateway (Pyro)", PYRO),
        ("Everus Harbor", STANTON),
    ] + [(name, STANTON) for name in DECOY_STATIONS]
    for station_id, (name, system_id) in enumerate(stations, start=31):
        db.execute(
            "INSERT INTO space_station (id, name, id_star_system, is_available_live, has_trade_terminal) VALUES (?, ?, ?, 1, 1)",
            (station_id, name, system_id),
        )
    db.commit()
    return helper


def validate(name: str) -> str | None:
    return asyncio.run(Validator(Validator.VALIDATE_LOCATION, config={"for_trading": True}).validate(name))


def main_model_prompts(helper) -> list[str]:
    return helper.wingman.ai.prompts


def add_station_terminal(db, terminal_id: int, name: str, station: str = "Everus Harbor", station_id: int = EVERUS_HARBOR) -> None:
    add_terminal(
        db, terminal_id, name, id_star_system=STANTON, star_system_name="Stanton",
        space_station_name=station, id_space_station=station_id,
    )
    db.commit()


# ── Gateways ────────────────────────────────────────────────────────


def test_the_jump_point_of_the_game_log_is_the_gateway_in_the_first_system(places):
    assert validate("Stanton-Nyx Jump Point") == "Nyx Gateway (Stanton)"
    assert validate("Stanton Nyx jump point") == "Nyx Gateway (Stanton)"


def test_a_gateway_with_its_system_is_matched(places):
    assert validate("Nyx Gateway within the Stanton system") == "Nyx Gateway (Stanton)"
    assert validate("Stanton gateway in Nyx") == "Stanton Gateway (Nyx)"
    assert validate("Nyx Gateway (Pyro)") == "Nyx Gateway (Pyro)"


def test_a_gateway_without_its_system_is_never_guessed(places):
    assert validate("Nyx Gateway") is None

    notes = " ".join(places.notes)
    assert "Ask the user which star system" in notes
    assert "Nyx Gateway (Stanton)" in notes
    assert "Nyx Gateway (Pyro)" in notes
    assert "Stanton Gateway (Nyx)" not in notes
    assert main_model_prompts(places) == []  # no model was asked to guess


def test_other_names_never_match_a_gateway(places):
    validate("Nyx in Stanton")

    assert "Gateway" not in main_model_prompts(places)[-1]


# ── Embeddings ──────────────────────────────────────────────────────


def test_embeddings_bring_names_in_another_word_order_into_the_shortlist_and_are_made_once(places):
    embedder = places.wingman.local_ai = WordEmbedder()

    validate("harbour of everus")
    calls = embedder.calls
    validate("everus harbour station")

    assert "Everus Harbor" in main_model_prompts(places)[0]
    assert embedder.calls == calls + 1  # the names are embedded once, only the search term again


def test_without_an_embedding_model_matching_falls_back_to_difflib(places):
    assert validate("harbour of everus") is None

    assert "Everus Harbor" not in " ".join(main_model_prompts(places))


# ── System One ──────────────────────────────────────────────────────


@pytest.fixture
def decider(places):
    """Embeddings on and a System One that answers with the given probabilities."""
    places.wingman.local_ai = WordEmbedder()

    def decide(probabilities: dict[str, float]) -> None:
        places.wingman.system_one = SystemOne(probabilities)
    return decide


def test_a_sure_answer_is_used(places, decider):
    decider({"Everus Harbor": 0.9})

    assert validate("harbour of everus") == "Everus Harbor"


def test_an_unsure_answer_asks_the_user_instead_of_the_main_model(places, decider):
    decider({"Baijini Point": 0.3, "Everus Harbor": 0.25})

    assert validate("harbour of everus") is None

    assert main_model_prompts(places) == []
    notes = " ".join(places.notes)
    assert "ask the user" in notes
    assert notes.index("Baijini Point") < notes.index("Everus Harbor")  # best guess first


def test_one_name_far_ahead_is_used_as_a_guess_with_the_others(places, decider):
    # Like 'Leske': Levski 0.29, the next names 0.02, none of these 0.66
    decider({"Everus Harbor": 0.29, "none_of_these": 0.66})

    assert validate("harbour of everus") == "Everus Harbor"

    assert main_model_prompts(places) == []  # no second model asked
    notes = " ".join(places.notes)
    assert "'harbour of everus' was taken as 'Everus Harbor' (best guess)" in notes
    assert "e.g. " in notes  # the other names, so the user can correct it right away


def test_a_weak_lead_still_asks_the_user(places, decider):
    decider({"Everus Harbor": 0.12, "none_of_these": 0.85})

    assert validate("harbour of everus") is None

    assert "ask the user" in " ".join(places.notes)


def test_two_names_for_the_same_terminal_are_not_asked_about(places, db, decider):
    # Like "ARC-L4": "Admin - ARC-L4" 0.47 against "ARC-L4 Faint Glen Station" 0.42
    add_station_terminal(db, 501, "Admin - Everus Harbor")
    decider({"Admin - Everus Harbor": 0.47, "Everus Harbor": 0.42})

    assert validate("everus harbor admin") == "Admin - Everus Harbor"

    assert "ask the user" not in " ".join(places.notes)


def test_the_place_with_all_the_terminals_is_taken(places, db, decider):
    # Like "HUR-L2": the station has the Admin terminal and one more, so the station is meant
    add_station_terminal(db, 501, "Admin - Everus Harbor")
    add_station_terminal(db, 502, "Market - Everus Harbor")
    decider({"Admin - Everus Harbor": 0.47, "Everus Harbor": 0.42})

    assert validate("everus harbor admin") == "Everus Harbor"


def test_a_place_and_the_wider_one_around_it_are_still_asked_about(places, db, decider):
    # Like "Lorville" and "Hurston": the system has terminals under other roofs too
    add_station_terminal(db, 501, "Admin - Everus Harbor")
    add_station_terminal(db, 503, "Admin - Port Olisar", station="Port Olisar", station_id=99)
    decider({"Everus Harbor": 0.47, "Stanton": 0.42})

    assert validate("everus harbor stanton") is None

    assert "ask the user" in " ".join(places.notes)


def test_an_unknown_name_in_a_list_is_left_out_not_the_whole_list(places, decider):
    validator = Validator(Validator.VALIDATE_LOCATION, multiple=True, config={"for_trading": True})

    assert asyncio.run(validator.validate(["Everus Harbor", "qqqq xxxx"])) == ["Everus Harbor"]
    assert "Not recognized and left out: qqqq xxxx" in " ".join(places.notes)
    assert asyncio.run(validator.validate(["qqqq xxxx"])) is None  # nothing known: still fails
