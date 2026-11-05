"""The decision model logic, without a network.

Everything here is about what Core does with an answer, not about how good
the answers are. The cases that matter are the ones where the model is unsure,
silent or broken, because those are the ones that must come out as "decide
the way you did before".
"""

import asyncio
import time
from types import SimpleNamespace

import pytest
import requests

from api.enums import DecisionModelProvider
from api.interface import CommandActionConfig, CommandConfig, CommandKeyboardConfig
from providers.decision_model import DecisionModelClient, DecisionResult
from services.decision_questions import (
    MULTIPLE_KEY,
    NONE_OPTION,
    command_questions,
    read_command,
    read_vocabulary,
    vocabulary_questions,
)
from services import decision_gate
from services.decision_gate import MAX_COMMAND_OPTIONS, DecisionGate
from tests.support import FakeDecisionSession, decision_model_settings, with_secrets
from wingmen.facade import SkillSystemOne, SystemOneAnswers


def _command(name, instant=None) -> CommandConfig:
    return CommandConfig(
        name=name,
        instant_activation=instant,
        actions=[CommandActionConfig(keyboard=CommandKeyboardConfig(hotkey="g"))],
    )


def _choice(value, confidence, probabilities=None) -> DecisionResult:
    return DecisionResult(
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


# ── what we do with the answer ──────────────────────────────────────


def test_a_confident_pick_is_executed():
    assert read_command(_choice("ToggleShields", 0.97), 0.9) == "ToggleShields"


def test_an_unsure_pick_falls_through_to_the_main_model():
    assert read_command(_choice("ToggleShields", 0.62), 0.9) is None


def test_the_escape_hatch_never_becomes_a_command():
    assert read_command(_choice(NONE_OPTION, 1.0), 0.9) is None


def test_a_failed_call_changes_nothing():
    assert read_command(DecisionResult(error="HTTP 503"), 0.0) is None


# ── the client: where a call goes ───────────────────────────────────


QUESTION = {"q": {"type": "noul", "instructions": "?"}}


def _client(provider, secrets=None, **settings):
    client = DecisionModelClient(settings=decision_model_settings(provider=provider, **settings))
    with_secrets(client, **(secrets or {}))
    client._session = FakeDecisionSession(
        {"model": "m", "answers": {"q": {"type": "noul", "noul": 0.9}},
         "usage": {"input_tokens": 12, "cost": 0.0000147}}
    )
    return client


def test_wingman_pro_lets_the_plan_pick_the_model():
    client = _client(DecisionModelProvider.WINGMAN_PRO, {"wingman_pro": "pro-token"})
    assert client.decide("hi", QUESTION).ok
    url, request = client._session.requests[0]
    assert url == "https://pro.invalid/api/v1/systemone"
    assert request["headers"]["Authorization"] == "Bearer pro-token"
    assert "model" not in request["json"]


def test_openrouter_takes_the_openrouter_key_and_the_chosen_model():
    client = _client(
        DecisionModelProvider.OPENROUTER,
        {"openrouter": "or-key", "wingman_pro": "pro-token"},
        openrouter_model="cloudflare/clef-flash",
    )
    result = client.decide("hi", QUESTION)
    url, request = client._session.requests[0]
    assert url == "https://openrouter.ai/api/v1/systemone"
    assert request["headers"]["Authorization"] == "Bearer or-key"
    assert request["json"]["model"] == "cloudflare/clef-flash"
    assert result.cost == pytest.approx(0.0000147)


@pytest.mark.parametrize("endpoint", [
    "http://127.0.0.1:8000", "http://127.0.0.1:8000/", "http://127.0.0.1:8000/v1",
    "http://127.0.0.1:8000/v1/",
])
def test_a_server_is_reached_however_its_address_was_written(endpoint):
    client = _client(
        DecisionModelProvider.SERVER, {"decision_model_server": "server-key"},
        endpoint=endpoint, model="Qwen3.5-4B-4bit",
    )
    assert client.decide("hi", QUESTION).ok
    url, request = client._session.requests[0]
    assert url == "http://127.0.0.1:8000/v1/systemone"
    assert request["headers"]["Authorization"] == "Bearer server-key"
    assert request["json"]["model"] == "Qwen3.5-4B-4bit"


def test_a_server_without_a_key_gets_no_authorization_header():
    client = _client(DecisionModelProvider.SERVER, endpoint="http://127.0.0.1:8765")
    client.decide("hi", QUESTION)
    assert "Authorization" not in client._session.requests[0][1]["headers"]


@pytest.mark.parametrize("provider,settings,reason", [
    (DecisionModelProvider.WINGMAN_PRO, {}, "Wingman Subscription"),
    (DecisionModelProvider.OPENROUTER, {}, "OpenRouter"),
    (DecisionModelProvider.SERVER, {"endpoint": " "}, "server address"),
])
def test_a_provider_without_what_it_needs_sends_nothing(provider, settings, reason):
    client = _client(provider, {}, **settings)
    assert not client.is_ready()
    result = client.decide("hi", QUESTION)
    assert reason in result.error
    assert client._session.requests == []


def test_a_key_added_while_core_runs_counts_at_once():
    client = _client(DecisionModelProvider.OPENROUTER, {})
    assert not client.is_ready()
    client._secret_keeper.secrets["openrouter"] = "or-key"
    assert client.is_ready()


def test_a_failed_request_starts_the_next_on_a_fresh_connection():
    class DeadSession:
        closed = False

        def post(self, *args, **kwargs):
            raise requests.ReadTimeout("read timeout=4.0")

        def close(self):
            self.closed = True

    client = _client(DecisionModelProvider.WINGMAN_PRO, {"wingman_pro": "k"})
    dead = DeadSession()
    client._session = dead
    result = client.decide({"transcript": "hi"}, QUESTION)
    assert result.error
    assert dead.closed
    assert client._session is not dead


# ── vocabulary gating ───────────────────────────────────────────────


def _vocab_result(values: list[float | None]) -> DecisionResult:
    return DecisionResult(
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
    assert read_vocabulary(DecisionResult(error="timeout"), CANDIDATES, 0.5) is None


def test_no_candidates_is_no_replacements():
    assert read_vocabulary(_vocab_result([]), [], 0.5) == set()


# ── the gate, off and on ────────────────────────────────────────────


def _settings(enabled: bool, commands: bool = True, **switches):
    return decision_model_settings(enabled=enabled, commands=commands, **switches)


def _gate(settings) -> DecisionGate:
    """A gate whose provider could be reached: a Wingman Pro token is there."""
    gate = DecisionGate("T", settings=settings)
    with_secrets(gate.client, wingman_pro="k")
    return gate


def test_a_switched_off_gate_reaches_no_model():
    gate = DecisionGate("T", settings=_settings(False))
    assert asyncio.run(gate.ask({"x": 1}, {"q": {"type": "noul"}})) is None
    assert gate.ask_sync({"x": 1}, {"q": {"type": "noul"}}) is None
    assert gate.confirm_vocabulary("hi", [("a", "B", False)]) is None


# ── the vocabulary check never holds up the transcript ──────────────


def _vocabulary_gate(monkeypatch, answer):
    """An active gate whose model call runs ``answer`` and counts the calls."""
    monkeypatch.setattr(decision_gate, "VOCABULARY_DEADLINE", 0.05)
    gate = _gate(_settings(True))
    calls = []

    def system_one(state, questions):
        calls.append(state)
        return answer()

    gate.client.decide = system_one
    return gate, calls


PROPOSALS = [("radar", "Yadar", True)]


def test_a_slow_answer_is_not_waited_for(monkeypatch):
    def slow():
        time.sleep(0.5)
        return _vocab_result([0.9])

    gate, _ = _vocabulary_gate(monkeypatch, slow)
    started = time.monotonic()
    assert gate.confirm_vocabulary("radar on", PROPOSALS) is None
    assert time.monotonic() - started < 0.3


def test_after_a_failure_the_check_pauses(monkeypatch):
    gate, calls = _vocabulary_gate(monkeypatch, lambda: DecisionResult(error="HTTP 502"))
    assert gate.confirm_vocabulary("radar on", PROPOSALS) is None
    assert gate.confirm_vocabulary("radar on", PROPOSALS) is None
    assert len(calls) == 1


def test_after_the_pause_the_check_asks_again(monkeypatch):
    answers = [DecisionResult(error="HTTP 502"), _vocab_result([0.9])]
    gate, calls = _vocabulary_gate(monkeypatch, lambda: answers.pop(0))
    assert gate.confirm_vocabulary("radar on", PROPOSALS) is None
    gate._vocabulary_paused_until = 0.0
    assert gate.confirm_vocabulary("radar on", PROPOSALS) == {0}
    assert len(calls) == 2


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


def test_a_score_reads_back_as_a_label_a_number_and_named_shares():
    """TypeSafe answers a score with a position and a legend, not a label."""
    answers = SystemOneAnswers(
        DecisionResult(
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
        DecisionResult(answers={"hostile": {"type": "noul", "noul": 0.94}})
    )
    assert answers.noul("hostile") == pytest.approx(0.94)
    assert answers.yes_no("hostile") is True
    assert answers.yes_no("hostile", threshold=0.99) is False


def test_a_skill_cannot_ask_past_the_switch():
    """The one thing the open `decide()` door must not allow."""
    gate = _gate(_settings(False))
    api = SkillSystemOne(gate)
    assert api.available is False
    for answers in (
        asyncio.run(api.decide("x", {"q": SkillSystemOne.noul("?")})),
        api.decide_sync("x", {"q": SkillSystemOne.noul("?")}),
    ):
        assert answers.ok is False


# ── the timing row in the turn's benchmark ──────────────────────────


def test_decisions_are_timed_and_drained_per_turn():
    gate = DecisionGate("T", settings=_settings(True))
    gate._record("Command choice", DecisionResult(seconds=0.31))
    gate._record("Skill preselection", DecisionResult(seconds=0.28))

    taken = gate.take_decisions()
    assert [label for label, _ms in taken] == ["Command choice", "Skill preselection"]
    assert [round(ms) for _label, ms in taken] == [310, 280]
    # Drained, so a turn that ends early cannot bill the next one.
    assert gate.take_decisions() == []


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
    gate = _gate(_settings(True))
    sent = []

    def capture(state, questions):
        sent.append(questions)
        return DecisionResult(answers={})

    gate.client.decide = capture
    asyncio.run(gate.pick_command("gear down", _commands(3)))


    assert len(sent) == 1
    assert set(sent[0]) == {"command", MULTIPLE_KEY}
    assert not any(key.startswith("group_") for key in sent[0])


def test_the_command_switch_stops_the_question_on_its_own():
    """A roleplayer with no commands turns this off and keeps everything else."""
    gate = _gate(_settings(True, commands=False))
    gate.client.decide = lambda *a: pytest.fail("should not have asked")
    assert asyncio.run(gate.pick_command("gear down", _commands(3))) is None
    # ...and the master switch still governs the rest.
    assert gate.active is True


def test_a_config_too_big_to_ask_about_is_not_asked_about():
    """Over TypeSafe's 255-option limit the model answers 400, so asking
    would cost a rejected request on every turn of the users with the
    biggest configs."""
    gate = DecisionGate("T", settings=_settings(True))
    assert len(gate._askable_commands(_commands(MAX_COMMAND_OPTIONS))) == MAX_COMMAND_OPTIONS
    assert gate._askable_commands(_commands(MAX_COMMAND_OPTIONS + 1)) == []
    with_secrets(gate.client, wingman_pro="k")
    gate.client.decide = lambda *a: pytest.fail("should not have asked")
    assert asyncio.run(gate.pick_command("x", _commands(MAX_COMMAND_OPTIONS + 50))) is None


def test_nothing_to_ask_means_no_call_at_all():
    gate = _gate(_settings(True))
    gate.client.decide = lambda *a: pytest.fail("should not have called out")
    assert asyncio.run(gate.pick_command("x", [])) is None


# ── a request for two things is not half a request ──────────────────


def _answer(multiple: float, command: str = "ToggleShields", confidence: float = 0.99):
    return DecisionResult(
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


def test_two_commands_are_handed_over_whole():
    """"Shields up, weapons hot." fired the shields at 0.85 and stopped. The
    weapons never came up, where the main model would have called both."""
    assert read_command(_answer(multiple=0.98), 0.8) is None


def test_a_trailing_clause_does_not_count_as_a_second_request():
    """"Fahrwerk ausfahren, wir kommen rein." measured 0.48 — the closest a
    single request came to the gate."""
    assert read_command(_answer(multiple=0.48), 0.8) == "ToggleShields"


def test_an_unanswered_count_does_not_block_a_confident_command():
    """A question the model skipped must not silently disable the feature."""
    result = DecisionResult(
        answers={"command": {"type": "choice", "choice": "ToggleShields",
                             "confidence": 0.99, "probabilities": {}}}
    )
    assert read_command(result, 0.8) == "ToggleShields"


# ── a switch per place, under the master switch ─────────────────────


def _gate_that_must_not_ask(**switches) -> DecisionGate:
    gate = _gate(_settings(True, **switches))
    gate.client.decide = lambda *a: pytest.fail("should not have asked")
    return gate


def test_the_skills_switch_closes_the_door_for_skills_only():
    gate = _gate_that_must_not_ask(skills=False)
    api = SkillSystemOne(gate)
    assert api.available is False
    assert asyncio.run(api.decide("x", {"q": SkillSystemOne.noul("?")})).ok is False
    assert api.decide_sync("x", {"q": SkillSystemOne.noul("?")}).ok is False
    assert gate.active is True


def test_the_wingman_choice_switch_stops_picking_a_wingman():
    gate = _gate_that_must_not_ask(wingman_choice=False)
    configs = [SimpleNamespace(name="A"), SimpleNamespace(name="B")]
    assert gate.pick_wingman("hello", configs) is None
    assert gate.wingman_choice_active is False


def test_the_vocabulary_switch_leaves_the_matcher_alone():
    gate = _gate_that_must_not_ask(vocabulary=False)
    assert gate.confirm_vocabulary("radar on", PROPOSALS) is None


def test_the_master_switch_wins_over_every_place():
    gate = _gate(_settings(False))
    assert gate.skills_active is False
    assert gate.wingman_choice_active is False
