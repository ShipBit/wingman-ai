"""The System One decision logic, without a network.

Everything here is about what Core does with an answer, not about how good
the answers are. The cases that matter are the ones where Jev is unsure, silent or broken, because those are
the ones that must come out as "decide the way you did before".
"""

import asyncio
from types import SimpleNamespace

import pytest

from api.interface import CommandActionConfig, CommandConfig, CommandKeyboardConfig
from providers.typesafe_jev import JevClient, JevResult
from services.benchmark import Benchmark
from services.jev_decisions import (
    MULTIPLE_KEY,
    NONE_OPTION,
    command_questions,
    read_command,
    read_triage,
    read_vocabulary,
    triage_questions,
    vocabulary_questions,
)
from services.jev_gate import MAX_COMMAND_OPTIONS, JevGate
from services.turn_metrics import TurnMetrics
from wingmen.facade import SkillSystemOne, SystemOneAnswers


def _command(name, instant=None) -> CommandConfig:
    return CommandConfig(
        name=name,
        instant_activation=instant,
        actions=[CommandActionConfig(keyboard=CommandKeyboardConfig(hotkey="g"))],
    )


def _choice(value, confidence, probabilities=None) -> JevResult:
    return JevResult(
        answers={
            "command": {
                "type": "choice",
                "choice": value,
                "confidence": confidence,
                "probabilities": probabilities or {},
            }
        }
    )


# ── the question we ask ─────────────────────────────────────────────


def test_every_command_is_offered_plus_an_escape_hatch():
    commands = [_command("DeployLandingGear"), _command("ToggleShields")]
    criteria = command_questions(commands)["command"]["criteria"]
    assert set(criteria) == {"DeployLandingGear", "ToggleShields", NONE_OPTION}
    assert criteria[NONE_OPTION]


def test_instant_activation_phrases_become_the_description():
    command = _command("DeployLandingGear", instant=["gear down", "landing gear"])
    criteria = command_questions([command])["command"]["criteria"]
    assert '"gear down"' in criteria["DeployLandingGear"]
    assert '"landing gear"' in criteria["DeployLandingGear"]


def test_a_command_without_phrases_has_no_description():
    criteria = command_questions([_command("ToggleShields")])["command"]["criteria"]
    assert criteria["ToggleShields"] is None


# ── what we do with the answer ──────────────────────────────────────


def test_a_confident_pick_is_executed():
    assert read_command(_choice("ToggleShields", 0.97), 0.9) == "ToggleShields"


def test_an_unsure_pick_falls_through_to_the_main_model():
    assert read_command(_choice("ToggleShields", 0.62), 0.9) is None


def test_the_escape_hatch_never_becomes_a_command():
    assert read_command(_choice(NONE_OPTION, 1.0), 0.9) is None


def test_a_failed_call_changes_nothing():
    assert read_command(JevResult(error="HTTP 503"), 0.0) is None


def test_an_empty_answer_changes_nothing():
    assert read_command(JevResult(answers={}), 0.0) is None


# ── triage ──────────────────────────────────────────────────────────


def test_echo_is_only_asked_about_while_the_wingman_speaks():
    assert "echo" not in triage_questions(["Computer"], during_playback=False)
    assert "echo" in triage_questions(["Computer"], during_playback=True)


def test_the_wingman_names_reach_the_question():
    question = triage_questions(["Computer", "ATC"], during_playback=False)["addressed"]
    assert "Computer" in question["instructions"]
    assert "ATC" in question["instructions"]


def test_triage_hands_back_probabilities_not_a_verdict():
    result = JevResult(answers={"addressed": {"type": "noul", "noul": 0.04}})
    values = read_triage(result)
    assert values["addressed"] == pytest.approx(0.04)
    assert values["stop"] is None
    assert values["echo"] is None


# ── the client, switched off ────────────────────────────────────────


def test_no_subscription_and_no_key_means_no_request():
    client = JevClient(api_key="")
    assert not client.is_ready()
    result = client.system_one({"transcript": "hi"}, {"x": {"type": "noul"}})
    assert not result.ok
    assert "Wingman Pro" in result.error


def test_no_questions_means_no_request():
    result = JevClient(api_key="k").system_one({"transcript": "hi"}, {})
    assert result.error == "no questions"


# ── vocabulary gating ───────────────────────────────────────────────


def _vocab_result(values: list[float | None]) -> JevResult:
    return JevResult(
        answers={
            f"vocab_{i}": {"type": "noul", "noul": v}
            for i, v in enumerate(values)
            if v is not None
        }
    )


CANDIDATES = [("radar", "Yadar"), ("Houston", "Hurston")]


def test_one_question_per_candidate():
    questions = vocabulary_questions(CANDIDATES)
    assert set(questions) == {"vocab_0", "vocab_1"}


def test_both_words_reach_the_question():
    instructions = vocabulary_questions(CANDIDATES)["vocab_0"]["instructions"]
    assert '"radar"' in instructions
    assert '"Yadar"' in instructions


def test_only_the_confirmed_replacements_come_back():
    result = _vocab_result([0.07, 0.81])
    assert read_vocabulary(result, CANDIDATES, 0.5) == {1}


def test_an_unanswered_candidate_is_not_replaced():
    result = _vocab_result([0.9, None])
    assert read_vocabulary(result, CANDIDATES, 0.5) == {0}


def test_a_failed_call_leaves_the_matcher_in_charge():
    assert read_vocabulary(JevResult(error="timeout"), CANDIDATES, 0.5) is None


def test_no_candidates_is_no_replacements():
    assert read_vocabulary(_vocab_result([]), [], 0.5) == set()


# ── the gate, off and on ────────────────────────────────────────────


def _settings(enabled: bool, commands: bool = True):
    return SimpleNamespace(
        system_one=SimpleNamespace(enabled=enabled, commands=commands),
        wingman_pro=SimpleNamespace(base_url="https://example.invalid"),
    )


def test_the_gate_is_off_without_settings():
    gate = JevGate("T")
    assert gate.enabled is False
    assert gate.active is False


def test_the_setting_switches_the_gate():
    gate = JevGate("T", settings=_settings(True))
    assert gate.enabled is True
    gate.update_settings(_settings(False))
    assert gate.enabled is False
    # Off is off even with a credential present.
    gate.client.api_key = "k"
    assert gate.active is False


def test_a_switched_off_gate_reaches_no_model():
    gate = JevGate("T", settings=_settings(False))
    assert asyncio.run(gate.ask({"x": 1}, {"q": {"type": "noul"}})) is None
    assert gate.ask_sync({"x": 1}, {"q": {"type": "noul"}}) is None
    assert gate.triage("hi", ["Computer"], during_playback=False) == {}
    assert gate.confirm_vocabulary("hi", [("a", "B", False)]) is None


# ── what a skill sees ───────────────────────────────────────────────


def test_a_skill_gets_nothing_rather_than_an_error_when_off():
    api = SkillSystemOne(None)
    assert api.available is False
    answers = asyncio.run(api.decide({"x": 1}, {"q": SkillSystemOne.noul("is it?")}))
    assert answers.ok is False
    for reader in (answers.noul, answers.yes_no, answers.choice, answers.score, answers.level):
        assert reader("q") is None
    assert answers.probabilities("q") == {}
    assert answers.levels("q") == []
    assert answers.keys() == []
    assert answers.raw() == {}


def test_the_builders_are_typesafes_own_wire_format():
    """A skill author reading TypeSafe's docs must recognise what we send."""
    assert SkillSystemOne.noul("is it?") == {"type": "noul", "instructions": "is it?"}
    assert SkillSystemOne.score("how bad?", ["low", "high"]) == {
        "type": "score",
        "instructions": "how bad?",
        "criteria": ["low", "high"],
    }
    assert SkillSystemOne.choice("which?", {"a": None, "b": "other"}) == {
        "type": "choice",
        "instructions": "which?",
        "criteria": {"a": None, "b": "other"},
    }
    assert SkillSystemOne.yes_no is SkillSystemOne.noul


def test_not_for_and_examples_become_the_structured_form():
    question = SkillSystemOne.choice(
        "which?",
        {"gear": SkillSystemOne.describe("the gear alone", not_for="landing", examples=["gear down"])},
        not_for="questions about a command",
    )
    assert question["instructions"] == {
        "what": "which?",
        "not_for": "questions about a command",
    }
    assert question["criteria"]["gear"] == {
        "what": "the gear alone",
        "not_for": "landing",
        "examples": ["gear down"],
    }


def test_describe_stays_a_plain_string_when_there_is_nothing_to_add():
    """So a caller can route every description through it without noise."""
    assert SkillSystemOne.describe("the gear alone") == "the gear alone"


def test_a_score_reads_back_as_a_label_a_number_and_named_shares():
    """TypeSafe answers a score with a position and a legend, not a label."""
    answers = SystemOneAnswers(
        JevResult(
            answers={
                "urgency": {
                    "type": "score",
                    "score": 1.99,
                    "confidence": 0.98,
                    "legend": {"0": "can wait", "1": "soon", "2": "right now"},
                    "probabilities": {"0": 0, "1": 0.01, "2": 0.99},
                }
            }
        )
    )
    assert answers.score("urgency") == pytest.approx(1.99)   # TypeSafe's own value
    assert answers.level("urgency") == "right now"           # ours: the lookup
    assert answers.levels("urgency") == ["can wait", "soon", "right now"]
    assert answers.probabilities("urgency")["right now"] == pytest.approx(0.99)
    assert answers.confidence("urgency") == pytest.approx(0.98)


def test_a_noul_is_a_probability_and_yes_no_applies_a_threshold():
    answers = SystemOneAnswers(
        JevResult(answers={"hostile": {"type": "noul", "noul": 0.94}})
    )
    assert answers.noul("hostile") == pytest.approx(0.94)
    assert answers.yes_no("hostile") is True
    assert answers.yes_no("hostile", threshold=0.99) is False


def test_a_skill_cannot_ask_past_the_switch():
    """The one thing the open `decide()` door must not allow."""
    gate = JevGate("T", settings=_settings(False))
    gate.client.api_key = "k"
    api = SkillSystemOne(gate)
    assert api.available is False
    for answers in (
        asyncio.run(api.decide("x", {"q": SkillSystemOne.noul("?")})),
        api.decide_sync("x", {"q": SkillSystemOne.noul("?")}),
    ):
        assert answers.ok is False


# ── the timing row in the turn's benchmark ──────────────────────────


def test_decisions_are_timed_and_drained_per_turn():
    gate = JevGate("T", settings=_settings(True))
    gate._record("Command choice", JevResult(seconds=0.31))
    gate._record("Skill preselection", JevResult(seconds=0.28))

    taken = gate.take_decisions()
    assert [label for label, _ms in taken] == ["Command choice", "Skill preselection"]
    assert [round(ms) for _label, ms in taken] == [310, 280]
    # Drained, so a turn that ends early cannot bill the next one.
    assert gate.take_decisions() == []


def test_the_snapshot_is_one_row_with_the_decisions_under_it():
    benchmark = Benchmark(label="turn")
    metrics = TurnMetrics.__new__(TurnMetrics)
    metrics.add_system_one_snapshot(
        benchmark, [("Command choice", 310.0), ("Skill: 3 question(s)", 280.0)]
    )

    assert len(benchmark.snapshots) == 1
    row = benchmark.snapshots[0]
    assert row.label == "System 1 decision making"
    assert row.execution_time_ms == 590.0
    assert [child.label for child in row.snapshots] == [
        "Command choice",
        "Skill: 3 question(s)",
    ]


def test_a_turn_without_system_one_gets_no_row():
    """An empty row would only make a user ask what it is."""
    benchmark = Benchmark(label="turn")
    TurnMetrics.__new__(TurnMetrics).add_system_one_snapshot(benchmark, [])
    assert benchmark.snapshots == []


# ── one call per turn, and a ceiling on how much it can be asked ────


def _commands(count: int):
    return [
        CommandConfig(
            name=f"Command {i}",
            actions=[CommandActionConfig(keyboard=CommandKeyboardConfig(hotkey="g"))],
        )
        for i in range(count)
    ]


def test_the_turn_asks_about_commands_and_nothing_else():
    """Skill preselection was taken out: it saved 0.26 s expected against
    0.46 s spent on every turn. What is left is the command and the count of
    how many were asked for, which belongs to the same decision."""
    gate = JevGate("T", settings=_settings(True))
    gate.client.api_key = "k"
    sent = []

    def capture(state, questions):
        sent.append(questions)
        return JevResult(answers={})

    gate.client.system_one = capture
    asyncio.run(gate.pick_command("gear down", _commands(3)))


    assert len(sent) == 1
    assert set(sent[0]) == {"command", MULTIPLE_KEY}
    assert not any(key.startswith("group_") for key in sent[0])


def test_the_command_switch_stops_the_question_on_its_own():
    """A roleplayer with no commands turns this off and keeps everything else."""
    gate = JevGate("T", settings=_settings(True, commands=False))
    gate.client.api_key = "k"
    gate.client.system_one = lambda *a: pytest.fail("should not have asked")
    assert asyncio.run(gate.pick_command("gear down", _commands(3))) is None
    # ...and the master switch still governs the rest.
    assert gate.active is True


def test_a_config_too_big_to_ask_about_is_not_asked_about():
    """Over TypeSafe's 255-option limit the model answers 400, so asking
    would cost a rejected request on every turn of the users with the
    biggest configs."""
    gate = JevGate("T", settings=_settings(True))
    assert len(gate._askable_commands(_commands(MAX_COMMAND_OPTIONS))) == MAX_COMMAND_OPTIONS
    assert gate._askable_commands(_commands(MAX_COMMAND_OPTIONS + 1)) == []
    gate.client.api_key = "k"
    gate.client.system_one = lambda *a: pytest.fail("should not have asked")
    assert asyncio.run(gate.pick_command("x", _commands(MAX_COMMAND_OPTIONS + 50))) is None


def test_nothing_to_ask_means_no_call_at_all():
    gate = JevGate("T", settings=_settings(True))
    gate.client.api_key = "k"
    gate.client.system_one = lambda *a: pytest.fail("should not have called out")
    assert asyncio.run(gate.pick_command("x", [])) is None


# ── a request for two things is not half a request ──────────────────


def _answer(multiple: float, command: str = "ToggleShields", confidence: float = 0.99):
    return JevResult(
        answers={
            MULTIPLE_KEY: {"type": "noul", "noul": multiple},
            "command": {
                "type": "choice",
                "choice": command,
                "confidence": confidence,
                "probabilities": {},
            },
        }
    )


def test_the_question_about_more_than_one_rides_along():
    """A Choice names one command, so the count has to be asked separately —
    and in the same call, where it is nearly free."""
    questions = command_questions([_command("ToggleShields")])
    assert set(questions) == {"command", MULTIPLE_KEY}


def test_two_commands_are_handed_over_whole():
    """"Shields up, weapons hot." fired the shields at 0.85 and stopped. The
    weapons never came up, where the main model would have called both."""
    assert read_command(_answer(multiple=0.98), 0.8) is None


def test_one_command_still_fires():
    assert read_command(_answer(multiple=0.05), 0.8) == "ToggleShields"


def test_a_trailing_clause_does_not_count_as_a_second_request():
    """"Fahrwerk ausfahren, wir kommen rein." measured 0.48 — the closest a
    single request came to the gate."""
    assert read_command(_answer(multiple=0.48), 0.8) == "ToggleShields"


def test_an_unanswered_count_does_not_block_a_confident_command():
    """A question the model skipped must not silently disable the feature."""
    result = JevResult(
        answers={"command": {"type": "choice", "choice": "ToggleShields",
                             "confidence": 0.99, "probabilities": {}}}
    )
    assert read_command(result, 0.8) == "ToggleShields"
