"""The filler line: what is spoken, when it starts, and when it is dropped."""

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api.enums import SpokenLanguage
from services import filler_response
from services.filler_response import (
    FillerResponder,
    build_system_prompt,
    clean_filler,
    language_rule,
)


# ── clean_filler ─────────────────────────────────────────────────────


def test_a_short_line_is_kept_and_unquoted():
    assert clean_filler('"Moment, ich schau nach."', "Wie viel kostet Eisen?") == "Moment, ich schau nach."


def test_only_the_first_line_is_spoken():
    assert clean_filler("Einen Moment.\nDas dauert kurz.", "x") == "Einen Moment."


@pytest.mark.parametrize("text", [None, "", "   \n ", "Soll ich nachsehen?", "¿Busco el precio?"])
def test_empty_answers_and_questions_are_dropped(text):
    assert clean_filler(text, "Wie viel kostet Eisen") is None


def test_a_made_up_number_is_dropped():
    assert clean_filler("Eisen kostet 3900 UEC.", "Wie viel kostet Eisen") is None


def test_a_number_the_user_said_is_fine():
    assert clean_filler("Ich suche 50 SCU für dich.", "Wo kaufe ich 50 SCU Eisen") == "Ich suche 50 SCU für dich."


def test_a_long_answer_is_dropped():
    assert clean_filler(" ".join(["wort"] * 20), "x") is None


# ── prompt ───────────────────────────────────────────────────────────


def test_the_language_is_named():
    assert language_rule(SpokenLanguage.DE) == "Write in German."


def test_the_prompt_is_filled():
    prompt = build_system_prompt("Emily", "A trader.", ["uex_get_commodity_information"], SpokenLanguage.ES)
    assert "You are Emily." in prompt
    assert "uex get commodity information" in prompt
    assert "Write in Spanish." in prompt
    assert "{" not in prompt


# ── FillerResponder ──────────────────────────────────────────────────


def _responder(text="Moment, ich schau nach.", enabled=True, ready=True, delay=0.0, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setattr(filler_response, "FILLER_DELAY_S", delay)
    local_ai = MagicMock()
    local_ai.is_ready.return_value = ready
    local_ai.support.return_value = SimpleNamespace(text=text)
    spoken: list[str] = []
    settings = SimpleNamespace(
        filler_responses=enabled, spoken_language=SpokenLanguage.DE, other_language=None
    )
    return FillerResponder(settings, lambda: local_ai, spoken.append), local_ai, spoken


def _start(responder, immediate=True):
    return responder.start(
        request="Wie viel kostet Eisen?",
        tool_names=["uex_get_commodity_information"],
        immediate=immediate,
        name="Emily",
        backstory="A trader.",
    )


def _wait_until(predicate, timeout=2.0):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        time.sleep(0.005)


def test_switched_off_starts_nothing():
    responder, local_ai, _ = _responder(enabled=False)
    assert _start(responder) is None
    local_ai.support.assert_not_called()


def test_no_support_model_starts_nothing():
    responder, _, _ = _responder(ready=False)
    assert _start(responder) is None


def test_the_line_is_spoken_while_the_turn_runs():
    responder, _, spoken = _responder()
    line = _start(responder)
    _wait_until(lambda: line.finished)  # the turn is still running
    assert responder.stop(line) is True
    assert spoken == ["Moment, ich schau nach."]


def test_it_does_not_need_the_turns_event_loop():
    """The bug from the first boot test: the main model's provider blocks the
    turn's loop with requests.post, so a task on it never ran. The line has to
    come out while that loop is stuck."""
    responder, _, spoken = _responder()
    line = _start(responder)
    # This thread stands in for the turn's loop, blocked by a synchronous call.
    _wait_until(lambda: spoken)
    assert spoken == ["Moment, ich schau nach."]
    assert responder.stop(line) is True


def test_a_fast_turn_drops_the_line_and_costs_no_call(monkeypatch):
    responder, local_ai, spoken = _responder(delay=1.0, monkeypatch=monkeypatch)
    line = _start(responder, immediate=False)
    assert responder.stop(line) is False  # the answer is ready at once
    time.sleep(0.05)
    assert spoken == []
    local_ai.support.assert_not_called()


def test_a_line_that_comes_after_the_answer_is_not_spoken():
    responder, local_ai, spoken = _responder()
    gate = threading.Event()
    local_ai.support.side_effect = lambda *a, **k: (gate.wait(), SimpleNamespace(text="Bin dran."))[1]
    line = _start(responder)
    assert responder.stop(line) is False
    gate.set()
    _wait_until(lambda: line.finished)
    assert spoken == []


def test_a_dropped_answer_is_not_spoken():
    responder, _, spoken = _responder(text="Soll ich nachsehen?")
    line = _start(responder)
    _wait_until(lambda: line.finished)
    assert responder.stop(line) is False
    assert spoken == []


def test_a_failing_support_call_is_silent():
    responder, local_ai, spoken = _responder()
    local_ai.support.side_effect = RuntimeError("support model down")
    line = _start(responder)
    _wait_until(lambda: line.finished)
    assert responder.stop(line) is False
    assert spoken == []


def test_stop_without_a_line():
    assert _responder()[0].stop(None) is False


def test_stop_waits_for_a_line_being_handed_out():
    """The answer is printed right after stop(); the filler must be out first."""
    responder, _, _ = _responder()
    spoken: list[str] = []
    entered, release = threading.Event(), threading.Event()

    def slow_speak(text):
        entered.set()
        release.wait()
        spoken.append(text)

    responder._speak = slow_speak
    line = _start(responder)
    assert entered.wait(1)
    result = {}
    stopper = threading.Thread(target=lambda: result.update(spoken=responder.stop(line)))
    stopper.start()
    time.sleep(0.05)
    assert stopper.is_alive()
    release.set()
    stopper.join(1)
    assert result["spoken"] is True
    assert spoken == ["Moment, ich schau nach."]



def test_semicolon_cuts_off_the_second_clause():
    assert clean_filler("Updating panels; Yadar spec only.", "x") == "Updating panels"


def _turn(responder, rest_s, tool="execute_command"):
    """One turn with this tool whose answer is ready after rest_s."""
    line = responder.start(
        request="Turn off engines", tool_names=[tool], immediate=False, name="KAT", backstory=""
    )
    time.sleep(rest_s)
    responder.stop(line)
    if line and not line.skipped:
        _wait_until(lambda: line.finished)
    return line


def test_a_tool_whose_answer_always_beats_the_line_gets_none(monkeypatch):
    """A keypress is followed by one short model call; the line was ready after
    the answer in 8 of 9 such turns of a real session."""
    responder, local_ai, _ = _responder(delay=0.0, monkeypatch=monkeypatch)
    monkeypatch.setattr(filler_response, "SPEAK_MARGIN_S", 0.0)
    slow = lambda *a, **k: (time.sleep(0.2), SimpleNamespace(text="Bin dran."))[1]
    local_ai.support.side_effect = slow
    for _ in range(2):
        assert not _turn(responder, 0.01).skipped
    calls = local_ai.support.call_count
    assert _turn(responder, 0.01).skipped
    assert local_ai.support.call_count == calls
    # Another tool is not known yet and still gets its line.
    assert not _turn(responder, 0.01, tool="uex_get_vehicle_information").skipped


def test_a_slow_tool_keeps_its_line(monkeypatch):
    responder, local_ai, _ = _responder(delay=0.0, monkeypatch=monkeypatch)
    monkeypatch.setattr(filler_response, "SPEAK_MARGIN_S", 0.0)
    for _ in range(3):
        assert not _turn(responder, 0.1).skipped
