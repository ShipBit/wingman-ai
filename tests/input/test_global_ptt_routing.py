"""Who answers the global push-to-talk key: the wingman named in the first
words, else the one with the star, else the one Jev picks."""

from types import SimpleNamespace

from api.interface import CommandConfig, WingmanConfig
from services.jev_decisions import (
    SPEAKER_INSTRUCTIONS,
    WINGMAN_INSTRUCTIONS,
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
    def __init__(self, pick, active=True):
        self.pick = pick
        self.active = active
        self.asked = []

    def update_settings(self, _settings):
        pass

    def pick_wingman(self, text, configs, recent=None, last_answer_from=None, speakers=None):
        self.asked.append((text, [c.name for c in configs]))
        self.context = (recent, last_answer_from)
        self.speakers = speakers
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
    target, _ = core(jev)._wingman_for_global_ptt("ATC, requesting permission to land.", t)
    assert target.name == "ATC"
    assert jev.asked == []


def test_without_a_name_the_star_answers():
    jev = FakeJev("ATC")
    t = tower(config("Computer", default=True), config("ATC"))
    target, _ = core(jev)._wingman_for_global_ptt("Requesting permission to land.", t)
    assert target.name == "Computer"
    assert jev.asked == []


def test_without_name_and_star_jev_picks():
    jev = FakeJev("ATC")
    t = tower(config("Computer"), config("ATC"))
    target, _ = core(jev)._wingman_for_global_ptt("Requesting permission to land.", t)
    assert target.name == "ATC"
    assert jev.asked == [("Requesting permission to land.", ["Computer", "ATC"])]


def test_when_the_jev_call_fails_the_last_speaker_answers():
    """Someone who held the key wants an answer: nothing happening looks broken."""
    t = tower(config("Computer"), config("ATC"))
    assert core(FakeJev(None))._wingman_for_global_ptt("Hello there.", t)[0].name == "ATC"


def test_without_jev_nobody_answers():
    t = tower(config("Computer"), config("ATC"))
    assert core(FakeJev(None, active=False))._wingman_for_global_ptt("Hello there.", t) == (None, None)


def test_a_single_wingman_answers_without_asking():
    jev = FakeJev(None)
    target, _ = core(jev)._wingman_for_global_ptt("Gear down.", tower(config("Computer")))
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
    target, _ = core(jev)._wingman_for_global_ptt("ATC, requesting permission to land.", t)
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


# --- people a skill voices: an NPC at the user's place is a target too ---------------

def with_speaker(t, host_name, name, description="", taken_over=False):
    """`host_name` hosts a registered speaker, the way the NPC skill registers one."""
    host = next(w for w in t.wingmen if w.name == host_name)
    host.speaker_names = lambda: [name]
    host.speakers = lambda: {name: (description, host_name)}
    host.taken_over = taken_over
    return host


def test_a_speakers_name_reaches_the_wingman_who_hosts_them():
    jev = FakeJev("ATC")
    t = tower(config("Computer"), config("ATC"))
    with_speaker(t, "Computer", "Lena")

    target, speaker = core(jev)._wingman_for_global_ptt("Lena, got any work for me?", t)

    assert target.name == "Computer" and speaker == "Lena"
    assert jev.asked == []


def test_a_running_conversation_gets_the_sentence_that_names_nobody():
    jev = FakeJev("ATC")
    t = tower(config("Computer"), config("ATC", default=True))
    with_speaker(t, "Computer", "Lena", taken_over=True)

    target, speaker = core(jev)._wingman_for_global_ptt("What is in the letter?", t)

    assert target.name == "Computer" and speaker is None  # the takeover on Computer handles it
    assert jev.asked == []


def test_a_wingmans_name_wins_over_a_running_conversation():
    t = tower(config("Computer"), config("ATC"))
    with_speaker(t, "Computer", "Lena", taken_over=True)

    target, speaker = core(FakeJev(None))._wingman_for_global_ptt("ATC, requesting landing.", t)

    assert target.name == "ATC" and speaker is None


def test_jev_is_offered_the_speakers_and_a_pick_names_the_host():
    jev = FakeJev("Lena")
    t = tower(config("Computer"), config("ATC"))
    with_speaker(t, "Computer", "Lena", "Lena Varga, a person at the counter of Tammany and Sons")

    target, speaker = core(jev)._wingman_for_global_ptt("Do you have work for me?", t)

    assert target.name == "Computer" and speaker == "Lena"
    assert jev.speakers == {"Lena": ("Lena Varga, a person at the counter of Tammany and Sons", "Computer")}


def test_the_question_lists_speakers_with_their_own_instructions():
    speakers = {"Lena": ("the trader", "Computer")}
    question = wingman_questions([config("Computer"), config("ATC")], speakers)["wingman"]
    assert set(question["criteria"]) == {"Computer", "ATC", "Lena"}
    assert question["instructions"] == SPEAKER_INSTRUCTIONS

    question = wingman_questions([config("Computer"), config("ATC")])["wingman"]
    assert question["instructions"] == WINGMAN_INSTRUCTIONS


def test_an_unsure_pick_of_a_person_gives_way_to_the_likeliest_wingman():
    def result(pick, confidence, shares):
        return SimpleNamespace(
            ok=True,
            choice=lambda key, min_confidence=0.0: pick if confidence >= min_confidence else None,
            confidence=lambda key: confidence,
            probabilities=lambda key: shares,
        )

    speakers = {"Lena": ("the trader", "Computer")}
    sure = result("Lena", 0.8, {"Lena": 0.8, "Computer": 0.15, "ATC": 0.05})
    assert read_wingman(sure, 0.0, speakers) == "Lena"

    unsure = result("Lena", 0.45, {"Lena": 0.45, "Computer": 0.2, "ATC": 0.35})
    assert read_wingman(unsure, 0.0, speakers) == "ATC"

    assert read_wingman(result("ATC", 0.4, {"ATC": 0.4, "Lena": 0.35}), 0.0, speakers) == "ATC"
