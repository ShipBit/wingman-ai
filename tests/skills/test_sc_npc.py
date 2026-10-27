"""Star Citizen NPCs: content packs, the quest engine, the NPC prompt and how
the skill picks whom the user talks to."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from skills.sc_npc import dialogue
from skills.sc_npc.main import ScNpc
from skills.sc_npc.packs import Packs, load_packs, parse_pack
from skills.sc_npc.quests import ACTIVE, DONE, OFFERED, QuestLog
from tests.support import REPO_ROOT

BUNDLED = Path(REPO_ROOT) / "skills" / "sc_npc" / "packs"


@pytest.fixture(scope="module")
def packs():
    return load_packs([BUNDLED])


# --- packs -----------------------------------------------------------------------

def test_the_starter_pack_loads(packs):
    assert packs.loaded == ["starter"] and packs.problems == []
    tecia = packs.npcs["tecia-varga"]
    assert tecia.at("lorville") and tecia.shop == "Tammany and Sons"
    assert tecia.voices["edge_tts"].startswith("en-GB")
    quest = packs.quests["letter-for-aberdeen"]
    assert quest.giver == "tecia-varga"
    assert [s.type for s in quest.steps] == ["visit", "talk", "reach", "confirm"]
    assert quest.steps[2].target.startswith("Aberdeen ")


def test_npcs_and_quests_are_found_loosely(packs):
    assert packs.find_npc("tecia").id == "tecia-varga"
    assert packs.find_npc("Marek Varga").id == "marek-varga"
    assert packs.find_npc("nobody") is None
    assert packs.find_quest("letter").id == "letter-for-aberdeen"
    assert [n.id for n in packs.npcs_at("HDMS-Anderson")] == ["marek-varga"]
    assert packs.npcs_at("Port Tressler") == []


def test_a_pack_with_problems_is_left_out_and_named(tmp_path):
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "pack.yaml").write_text(
        "npcs:\n  - id: x\n    name: X\n"  # no place, no persona
        "quests:\n  - id: q\n    title: Q\n    giver: ghost\n    steps:\n      - type: fly\n",
        encoding="utf-8",
    )
    (tmp_path / "fine").mkdir()
    (tmp_path / "fine" / "pack.yaml").write_text(
        "npcs:\n  - id: a\n    name: A\n    place: Lorville\n    persona: Someone.\n", encoding="utf-8"
    )

    packs = load_packs([tmp_path])

    assert packs.loaded == ["fine"] and list(packs.npcs) == ["a"]
    (problem,) = packs.problems
    assert problem.startswith("broken: ")
    assert "place is missing" in problem and "persona is missing" in problem
    assert "giver 'ghost'" in problem and "type must be one of" in problem


def test_parse_refuses_what_is_no_mapping():
    npcs, quests, problems = parse_pack(["not", "a", "mapping"], "p")
    assert (npcs, quests) == ([], []) and problems == ["pack.yaml is not a mapping"]


def test_later_folders_win_on_the_same_id(tmp_path):
    for folder, place in (("first", "Lorville"), ("second", "Area 18")):
        (tmp_path / folder / "pack").mkdir(parents=True)
        (tmp_path / folder / "pack" / "pack.yaml").write_text(
            f"npcs:\n  - id: a\n    name: A\n    place: {place}\n    persona: Someone.\n", encoding="utf-8"
        )

    packs = load_packs([tmp_path / "first", tmp_path / "second"])

    assert packs.npcs["a"].place == "Area 18"


# --- the quest engine --------------------------------------------------------------

def _log(packs, tmp_path) -> QuestLog:
    return QuestLog(tmp_path / "quests.json", packs)


def test_a_quest_runs_through_its_steps(packs, tmp_path):
    log = _log(packs, tmp_path)
    quest = packs.quests["letter-for-aberdeen"]

    assert [q.id for q in log.offerable("tecia-varga")] == [quest.id]
    log.offer(quest)
    assert log.state(quest.id).status == OFFERED
    log.accept(quest, now=100.0)
    assert log.state(quest.id).status == ACTIVE
    assert log.offerable("tecia-varga") == []

    assert log.on_place("Port Tressler") == []
    (advance,) = log.on_place("hdms-anderson", now=110.0)
    assert advance.step.type == "visit" and not advance.finished and advance.next_step.type == "talk"

    assert log.on_talk("tecia-varga") == []
    (advance,) = log.on_talk("marek-varga", now=120.0)
    assert advance.step.type == "talk" and advance.next_step.type == "reach"

    assert log.on_confirm(quest) is None  # the current step is reach, not confirm
    advance = log.on_reached(quest, now=130.0)
    assert advance.step.type == "reach" and advance.next_step.type == "confirm"

    advance = log.on_confirm(quest, now=140.0)
    assert advance.finished and advance.next_step is None
    assert log.state(quest.id).status == DONE and log.state(quest.id).finished_at == 140.0
    assert log.active() == [] and log.offerable("tecia-varga") == []


def test_the_quest_log_survives_a_restart(packs, tmp_path):
    log = _log(packs, tmp_path)
    quest = packs.quests["letter-for-aberdeen"]
    log.accept(quest, now=100.0)
    log.on_place("HDMS-Anderson")

    again = _log(packs, tmp_path)

    assert again.state(quest.id).step == 1
    assert "A letter for Aberdeen (step 2 of 4: talk to marek-varga)" in again.summary()


def test_an_abandoned_quest_can_be_offered_again(packs, tmp_path):
    log = _log(packs, tmp_path)
    quest = packs.quests["letter-for-aberdeen"]
    log.accept(quest)

    assert log.abandon(quest) and not log.abandon(quest)
    assert [q.id for q in log.offerable("tecia-varga")] == [quest.id]


# --- the NPC prompt ----------------------------------------------------------------

def test_the_npc_prompt_holds_persona_rules_and_offers(packs):
    tecia = packs.npcs["tecia-varga"]
    quest = packs.quests["letter-for-aberdeen"]

    system = dialogue.npc_system_prompt(
        tecia, language="German", place="Lorville", world="The pilot flies a Cutlass.",
        memory="Talked with Tecia before.", offers=[quest], active_titles=[],
    )

    assert system.startswith("You are Tecia Varga")
    assert "Tammany and Sons" in system and "mine worker" in system
    assert "Answer in German" in system and "IN CHARACTER" in system
    assert "'A letter for Aberdeen'" in system
    assert "Talked with Tecia before." in system and "Cutlass" in system


def test_the_tool_result_tells_the_wingman_not_to_repeat(packs):
    tecia = packs.npcs["tecia-varga"]
    quest = packs.quests["letter-for-aberdeen"]

    text = dialogue.tool_result(tecia, "Not from the company? Good.", offered=[quest], note="Others here: Bob.")

    assert "already spoken aloud" in text and "Do not repeat" in text
    assert "'A letter for Aberdeen'" in text and "Others here: Bob." in text
    assert "in their own words" in text and "quests with accept" in text


def test_only_the_last_turns_reach_the_model():
    history = [("user", str(i)) for i in range(20)]
    assert len(dialogue.history_messages(history)) == dialogue.MAX_HISTORY
    assert dialogue.history_messages(history)[-1] == {"role": "user", "content": "19"}


# --- the skill: whom the user talks to, which voice ----------------------------------

def _skill(packs, here: str = "", provider: str = "edge_tts", voice_setting=None) -> ScNpc:
    skill = object.__new__(ScNpc)
    skill._packs = packs
    skill._here = here
    skill._history = {}
    skill._met = set()
    skill._log = None
    provider_enum = SimpleNamespace(value=provider)
    skill.wingman = SimpleNamespace(
        config=SimpleNamespace(features=SimpleNamespace(tts_provider=provider_enum)),
        sc_gamelog=SimpleNamespace(available=False, state=lambda: None),
    )
    skill.retrieve_custom_property_value = lambda name, errors: voice_setting if name == "npc_voice" else None
    skill._provider_enum = provider_enum
    return skill


def test_the_npc_at_the_place_is_picked_when_none_is_named(packs):
    skill = _skill(packs, here="Lorville")
    npc, note = skill._resolve_npc("")
    assert npc.id == "tecia-varga" and note == ""

    skill = _skill(packs, here="Port Tressler")
    npc, note = skill._resolve_npc("")
    assert npc is None and "no one to talk to at Port Tressler" in note

    npc, note = skill._resolve_npc("marek")
    assert npc.id == "marek-varga"
    npc, note = skill._resolve_npc("ghost")
    assert npc is None and "No NPC called 'ghost'" in note and "Tecia Varga" in note


def test_the_world_says_when_the_pilot_is_elsewhere(packs):
    skill = _skill(packs, here="Port Tressler")
    assert "over comms from Port Tressler" in skill._world(packs.npcs["tecia-varga"])
    skill = _skill(packs, here="Lorville")
    assert skill._world(packs.npcs["tecia-varga"]) == ""


def test_the_voice_comes_from_the_pack_then_the_setting(packs):
    tecia = packs.npcs["tecia-varga"]
    skill = _skill(packs, provider="edge_tts")
    assert skill._voice_for(tecia) == "en-GB-SoniaNeural"

    skill = _skill(packs, provider="elevenlabs")
    assert skill._voice_for(tecia) is None

    skill = _skill(packs, provider="elevenlabs")
    skill.retrieve_custom_property_value = lambda name, errors: SimpleNamespace(provider=skill._provider_enum, voice="Rachel")
    assert skill._voice_for(tecia) == "Rachel"
