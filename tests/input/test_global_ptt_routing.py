"""Who answers the global push-to-talk key: the wingman named in the first
words, else the one with the star, else the one Jev picks."""

from types import SimpleNamespace

from api.interface import CommandConfig, WingmanConfig
from services.jev_decisions import (
    read_wingman,
    wingman_description,
    wingman_questions,
    wingman_state,
)
from services.tower import Tower
from tests.support import template
from wingman_core import WingmanCore
from services.config_manager import deep_merge_configs


def config(name, default=False, **fields):
    return WingmanConfig(
        **deep_merge_configs(
            template("defaults.yaml"),
            {"name": name, "record_bindings": [], "is_voice_activation_default": default, **fields},
        )
    )


def tower(*configs):
    t = Tower.__new__(Tower)
    t.wingmen = [
        SimpleNamespace(
            name=c.name,
            config=c,
            conversation=SimpleNamespace(last_exchange=lambda c=c: {"user": f"hi {c.name}"}),
        )
        for c in configs
    ]
    return t


class FakeJev:
    def __init__(self, pick):
        self.pick = pick
        self.asked = []

    def update_settings(self, _settings):
        pass

    def pick_wingman(self, text, configs, recent=None, last_answer_from=None):
        self.asked.append((text, [c.name for c in configs]))
        self.context = (recent, last_answer_from)
        return self.pick


def core(jev):
    c = WingmanCore.__new__(WingmanCore)
    c.routing_jev = jev
    c._last_answer_from = "ATC"
    c.settings_service = SimpleNamespace(settings=None)
    c.printr = SimpleNamespace(print=lambda *a, **k: None)
    return c


def test_a_name_in_the_first_words_wins():
    jev = FakeJev("ATC")
    t = tower(config("Computer", default=True), config("ATC"))
    target = core(jev)._wingman_for_global_ptt("ATC, requesting permission to land.", t)
    assert target.name == "ATC"
    assert jev.asked == []


def test_without_a_name_the_star_answers():
    jev = FakeJev("ATC")
    t = tower(config("Computer", default=True), config("ATC"))
    target = core(jev)._wingman_for_global_ptt("Requesting permission to land.", t)
    assert target.name == "Computer"
    assert jev.asked == []


def test_without_name_and_star_jev_picks():
    jev = FakeJev("ATC")
    t = tower(config("Computer"), config("ATC"))
    target = core(jev)._wingman_for_global_ptt("Requesting permission to land.", t)
    assert target.name == "ATC"
    assert jev.asked == [("Requesting permission to land.", ["Computer", "ATC"])]


def test_nobody_answers_when_jev_does_not_pick():
    t = tower(config("Computer"), config("ATC"))
    assert core(FakeJev(None))._wingman_for_global_ptt("Hello there.", t) is None


def test_a_single_wingman_answers_without_asking():
    jev = FakeJev(None)
    target = core(jev)._wingman_for_global_ptt("Gear down.", tower(config("Computer")))
    assert target.name == "Computer"
    assert jev.asked == []


def test_jev_gets_description_tools_and_commands():
    computer = config(
        "Computer",
        description="Your ship's board computer.",
        discoverable_skills=["Timer"],
        discoverable_mcps=["wingman_starhead"],
        commands=[
            CommandConfig(name="Gear Down", actions=[{"wait": 0.1}]),
            CommandConfig(name="Said Only", actions=[{"wait": 0.1}], force_instant_activation=True),
            CommandConfig(name="Empty"),
        ],
    )
    text = wingman_description(computer)
    assert text == "Your ship's board computer. Tools: Timer, wingman_starhead Commands: Gear Down"
    criteria = wingman_questions([computer, config("ATC")])["wingman"]["criteria"]
    assert set(criteria) == {"Computer", "ATC"}


def test_an_unsure_answer_picks_nobody():
    def result(pick, confidence):
        return SimpleNamespace(ok=True, choice=lambda key, min_confidence=0.0: pick if confidence >= min_confidence else None)

    assert read_wingman(result("ATC", 0.9), 0.7) == "ATC"
    assert read_wingman(result("ATC", 0.5), 0.7) is None
    assert read_wingman(SimpleNamespace(ok=False), 0.7) is None


def test_a_switched_off_wingman_is_neither_addressed_nor_offered():
    """Switched off Wingmen live in tower.disabled_wingmen, not in tower.wingmen,
    so their name, their ⭐ and Jev all pass them by."""
    jev = FakeJev("Lore")
    t = tower(config("Computer"), config("Lore"))
    t.disabled_wingmen = [config("ATC", default=True)]
    target = core(jev)._wingman_for_global_ptt("ATC, requesting permission to land.", t)
    assert target.name == "Lore"
    assert jev.asked == [("ATC, requesting permission to land.", ["Computer", "Lore"])]


def test_jev_hears_the_last_exchanges_and_who_answered_last():
    jev = FakeJev("ATC")
    t = tower(config("Computer"), config("ATC"))
    core(jev)._wingman_for_global_ptt("Which pad was it?", t)
    recent, last = jev.context
    assert recent == {"Computer": {"user": "hi Computer"}, "ATC": {"user": "hi ATC"}}
    assert last == "ATC"


def test_the_state_leaves_out_what_is_empty():
    assert wingman_state("Gear down.", {"Computer": {}}, None) == {"transcript": "Gear down."}
    state = wingman_state("Which pad?", {"ATC": {"user": "Land", "assistant": "Pad 4"}}, "ATC")
    assert state == {
        "transcript": "Which pad?",
        "last_answer_from": "ATC",
        "recent": {"ATC": {"user": "Land", "assistant": "Pad 4"}},
    }


def test_the_last_exchange_skips_tool_calls_and_cuts_long_answers():
    from services.conversation_manager import ConversationManager

    manager = ConversationManager.__new__(ConversationManager)
    manager.messages = [
        {"role": "user", "content": "Where do I sell laranite?"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "{}"},
        {"role": "assistant", "content": "Area18 " + "x" * 300},
    ]
    exchange = manager.last_exchange(limit=50)
    assert exchange["user"] == "Where do I sell laranite?"
    assert exchange["assistant"].startswith("Area18 ") and len(exchange["assistant"]) == 50
