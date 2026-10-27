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


def _run(coro):
    return asyncio.run(coro)


# --- packs -----------------------------------------------------------------------

def test_the_starter_pack_loads(packs):
    assert packs.loaded == ["starter"] and packs.problems == []
    lena = packs.npcs["lena-varga"]
    assert lena.at("lorville") and lena.shop == "Tammany and Sons"
    assert lena.voices["edge_tts"].startswith("en-GB")
    assert lena.aliases == ("Miss Varga",)
    quest = packs.quests["letter-for-aberdeen"]
    assert quest.giver == "lena-varga"
    assert [s.type for s in quest.steps] == ["visit", "talk", "reach", "confirm"]
    assert quest.steps[2].target.startswith("Aberdeen ")


def test_npcs_and_quests_are_found_loosely(packs):
    assert packs.find_npc("lena").id == "lena-varga"
    assert packs.find_npc("Jonas Varga").id == "jonas-varga"
    assert packs.find_npc("nobody") is None
    assert packs.find_quest("letter").id == "letter-for-aberdeen"
    assert [n.id for n in packs.npcs_at("HDMS-Anderson")] == ["jonas-varga"]
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

    assert [q.id for q in log.offerable("lena-varga")] == [quest.id]
    log.offer(quest)
    assert log.state(quest.id).status == OFFERED
    log.accept(quest, now=100.0)
    assert log.state(quest.id).status == ACTIVE
    assert log.offerable("lena-varga") == []

    assert log.on_place("Port Tressler") == []
    (advance,) = log.on_place("hdms-anderson", now=110.0)
    assert advance.step.type == "visit" and not advance.finished and advance.next_step.type == "talk"

    assert log.on_talk("lena-varga") == []
    (advance,) = log.on_talk("jonas-varga", now=120.0)
    assert advance.step.type == "talk" and advance.next_step.type == "reach"

    assert log.on_confirm(quest) is None  # the current step is reach, not confirm
    advance = log.on_reached(quest, now=130.0)
    assert advance.step.type == "reach" and advance.next_step.type == "confirm"

    advance = log.on_confirm(quest, now=140.0)
    assert advance.finished and advance.next_step is None
    assert log.state(quest.id).status == DONE and log.state(quest.id).finished_at == 140.0
    assert log.active() == [] and log.offerable("lena-varga") == []


def test_the_quest_log_survives_a_restart(packs, tmp_path):
    log = _log(packs, tmp_path)
    quest = packs.quests["letter-for-aberdeen"]
    log.accept(quest, now=100.0)
    log.on_place("HDMS-Anderson")

    again = _log(packs, tmp_path)

    assert again.state(quest.id).step == 1
    assert "A letter for Aberdeen (step 2 of 4: talk to jonas-varga)" in again.summary()


def test_an_abandoned_quest_can_be_offered_again(packs, tmp_path):
    log = _log(packs, tmp_path)
    quest = packs.quests["letter-for-aberdeen"]
    log.accept(quest)

    assert log.abandon(quest) and not log.abandon(quest)
    assert [q.id for q in log.offerable("lena-varga")] == [quest.id]


# --- the NPC prompt ----------------------------------------------------------------

def test_the_npc_prompt_holds_persona_rules_and_offers(packs):
    lena = packs.npcs["lena-varga"]
    quest = packs.quests["letter-for-aberdeen"]

    system = dialogue.npc_system_prompt(
        lena, language="German", place="Lorville", world="The pilot flies a Cutlass.",
        memory="Talked with Lena before.", offers=[quest], active_titles=[],
    )

    assert system.startswith("You are Lena Varga")
    assert "Tammany and Sons" in system and "mine worker" in system
    assert "Answer in German" in system and "IN CHARACTER" in system
    assert "'A letter for Aberdeen'" in system
    assert "Talked with Lena before." in system and "Cutlass" in system


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
    assert npc.id == "lena-varga" and note == ""

    skill = _skill(packs, here="Port Tressler")
    npc, note = skill._resolve_npc("")
    assert npc is None and "no one to talk to at Port Tressler" in note

    npc, note = skill._resolve_npc("jonas")
    assert npc.id == "jonas-varga"
    npc, note = skill._resolve_npc("ghost")
    assert npc is None and "No NPC called 'ghost'" in note and "Lena Varga" in note


def test_the_world_says_when_the_pilot_is_elsewhere(packs):
    skill = _skill(packs, here="Port Tressler")
    assert "over comms from Port Tressler" in skill._world(packs.npcs["lena-varga"])
    skill = _skill(packs, here="Lorville")
    assert skill._world(packs.npcs["lena-varga"]) == ""


def test_the_voice_comes_from_the_pack_then_the_setting(packs):
    lena = packs.npcs["lena-varga"]
    skill = _skill(packs, provider="edge_tts")
    assert skill._voice_for(lena) == "en-GB-SoniaNeural"

    skill = _skill(packs, provider="elevenlabs")
    assert skill._voice_for(lena) is None

    skill = _skill(packs, provider="elevenlabs")
    skill.retrieve_custom_property_value = lambda name, errors: SimpleNamespace(provider=skill._provider_enum, voice="Rachel")
    assert skill._voice_for(lena) == "Rachel"


# --- talking directly: the skill takes the conversation ----------------------------

class FakeTakeover:
    def __init__(self, speaker):
        self.speaker = speaker
        self.active = True

    def release(self):
        self.active = False


class FakeConversation:
    def __init__(self):
        self.takeover = None
        self.handler = None
        self.said = []
        self.shown = []
        self.registered = []

    def take_over(self, speaker, handler, *, idle_s=300):
        self.takeover = FakeTakeover(speaker)
        self.handler = handler
        return self.takeover

    def register_speaker(self, name, opener):
        self.registered.append(name)
        return SimpleNamespace(unsubscribe=lambda: None)

    async def said_by(self, speaker, text, *, skill_name=""):
        self.said.append((speaker, text))

    async def show(self, text, *, skill_name=""):
        self.shown.append(text)


class FakeTts:
    def __init__(self):
        self.voice = "wingman-voice"
        self.spoken = []

    async def set_voice(self, voice):
        self.voice = voice
        return "ok"

    async def speak(self, text, **kwargs):
        self.spoken.append((self.voice, text))
        return True


class FakeAnswers:
    def __init__(self, over, accept):
        self._over, self._accept = over, accept

    def yes_no(self, key, threshold=0.5):
        return self._over if key == "over" else None

    def choice(self, key, min_confidence=0.0):
        return ("yes" if self._accept else "no") if key == "accept" else None


class FakeSystemOne:
    def __init__(self, over=False, accept=False, available=True):
        self.available = available
        self.answers = FakeAnswers(over, accept)
        self.asked = []

    def noul(self, question):
        return ("noul", question)

    def choice(self, question, options):
        return ("choice", question, options)

    async def decide(self, state, questions):
        self.asked.append((state, questions))
        return self.answers


def _talking_skill(packs, tmp_path, *, here="Lorville", replies=("Then we can talk.",), **system_one):
    skill = _skill(packs, here=here)
    skill._log = QuestLog(tmp_path / "quests.json", packs)
    skill._talking = None
    skill._speakers, skill._names, skill._tasks, skill._hinted = [], {}, set(), {}
    skill.config = SimpleNamespace(display_name="Star Citizen NPCs")
    quiet = lambda *args, **kwargs: None
    skill.log = SimpleNamespace(warning=quiet, info=quiet, error=quiet)
    pending = list(replies)

    async def generate(prompt=None, *, messages=None):
        return pending.pop(0) if len(pending) > 1 else pending[0]

    skill.wingman.name = "Computer"
    skill.wingman.language = SimpleNamespace(name="English")
    skill.wingman.conversation = FakeConversation()
    skill.wingman.tts = FakeTts()
    skill.wingman.ai = SimpleNamespace(generate=generate)
    skill.wingman.local_ai = SimpleNamespace(available=False)
    skill.wingman.memory = SimpleNamespace(available=False)
    skill.wingman.hud = SimpleNamespace(available=False)
    skill.wingman.system_one = FakeSystemOne(**system_one)
    return skill


def test_addressing_lena_by_name_hands_the_conversation_to_her(packs, tmp_path):
    skill = _talking_skill(packs, tmp_path, replies=("Depends. Who's asking?",))
    skill._register_here()
    assert set(skill._names) == {"Lena", "Lena Varga", "Miss Varga"}  # Jonas is on Aberdeen
    assert skill._names["Miss Varga"] == "lena-varga"
    assert set(skill.wingman.conversation.registered) == set(skill._names)

    keep = _run(skill._addressed("Lena", "Lena, got any work?"))

    conversation, tts = skill.wingman.conversation, skill.wingman.tts
    assert keep and conversation.takeover.speaker == "Lena Varga" and conversation.handler == skill._turn
    assert [who for who, _ in conversation.said] == ["Lena Varga", "Lena Varga"]
    assert "Hurston Dynamics" in conversation.said[0][1]  # her greeting, once per session
    assert conversation.said[1][1] == "Depends. Who's asking?"
    assert [voice for voice, _ in tts.spoken] == ["en-GB-SoniaNeural", "en-GB-SoniaNeural"]
    assert tts.voice == "wingman-voice"  # the Wingman got its voice back
    assert skill._log.state("letter-for-aberdeen").status == OFFERED
    assert skill.wingman.conversation.shown == []  # the Wingman said nothing


def test_a_goodbye_ends_the_conversation_when_system_one_hears_it(packs, tmp_path):
    lena = packs.npcs["lena-varga"]
    skill = _talking_skill(packs, tmp_path, replies=("Safe travels.",), over=True)
    assert _run(skill._start_talk(lena, "Thanks, bye.")) is False
    assert skill._talking is None

    skill = _talking_skill(packs, tmp_path, replies=("Safe travels.",), over=True, available=False)
    assert _run(skill._start_talk(lena, "Thanks, bye.")) is True  # ends by name, leaving or silence


def test_agreeing_to_the_work_accepts_the_quest_and_the_wingman_says_so(packs, tmp_path):
    lena, quest = packs.npcs["lena-varga"], packs.quests["letter-for-aberdeen"]
    skill = _talking_skill(packs, tmp_path, replies=("Good. Don't read it.",), accept=True)
    skill._log.offer(quest)
    skill._talking = lena

    assert _run(skill._turn("Sure, I'll carry it."))

    assert skill._log.state(quest.id).status == ACTIVE
    assert skill.wingman.conversation.shown[0].startswith("Accepted 'A letter for Aberdeen'")
    assert [voice for voice, _ in skill.wingman.tts.spoken] == ["en-GB-SoniaNeural", "wingman-voice"]
    state, questions = skill.wingman.system_one.asked[0]
    assert state["offered_work"] == ["A letter for Aberdeen"] and "accept" in questions


def test_talking_to_jonas_closes_the_talk_step(packs, tmp_path):
    jonas, quest = packs.npcs["jonas-varga"], packs.quests["letter-for-aberdeen"]
    skill = _talking_skill(packs, tmp_path, here="HDMS-Anderson", replies=("A letter? From Lena?",))
    skill._log.accept(quest)
    skill._log.on_place("HDMS-Anderson")
    skill._talking = jonas

    assert _run(skill._turn("Hi Jonas, I have a letter from your sister."))

    assert skill.wingman.conversation.shown[0].startswith("Jonas has the letter.")
    assert skill._log.state(quest.id).step == 2


def test_the_tool_hands_over_and_keeps_the_wingman_silent(packs, tmp_path):
    skill = _talking_skill(packs, tmp_path)

    result, instant = _run(skill.talk_to_npc("Hello", "Lena"))

    assert instant == "." and result.startswith("Lena Varga is talking to the user now")
    assert skill.wingman.conversation.takeover.speaker == "Lena Varga"


def test_leaving_the_place_ends_the_conversation(packs, tmp_path):
    skill = _talking_skill(packs, tmp_path)
    _run(skill._start_talk(packs.npcs["lena-varga"], "Hello"))

    skill._end_talk()

    assert skill._talking is None and skill.wingman.conversation.takeover.active is False


def test_leaving_a_place_drops_its_people_and_the_names_are_hotwords(packs, tmp_path):
    skill = _talking_skill(packs, tmp_path, here="HDMS-Anderson")
    skill._register_here()
    assert set(skill._names) == {"Jonas", "Jonas Varga"}

    skill._here = ""
    skill._register_here()
    assert skill._names == {} and skill._speakers == []

    assert set(skill._hotwords()) == {"Lena Varga", "Lena", "Miss Varga", "Jonas Varga", "Jonas"}


class FakeScreen:
    async def capture(self, display=1):
        from PIL import Image

        return Image.new("RGB", (8, 8), "white")


def _looking_skill(packs, tmp_path, answer):
    skill = _talking_skill(packs, tmp_path, replies=("Hm.",))
    skill.wingman.screen = FakeScreen()
    seen = []

    async def generate(prompt="", *, image=None, messages=None):
        if messages is not None:
            return "Hm."
        seen.append((prompt, image))
        if isinstance(answer, Exception):
            raise answer
        return answer

    skill.wingman.ai = SimpleNamespace(generate=generate)
    return skill, seen


def test_the_screen_tells_who_is_in_front_of_the_user(packs, tmp_path):
    npcs = [packs.npcs["lena-varga"], packs.npcs["jonas-varga"]]

    skill, seen = _looking_skill(packs, tmp_path, "Tammany and Sons")
    assert _run(skill._look_for(npcs)).id == "lena-varga"
    prompt, image = seen[0]
    assert "Lena Varga (at Tammany and Sons)" in prompt and image.startswith("data:image/jpeg;base64,")

    skill, _ = _looking_skill(packs, tmp_path, "none")
    assert _run(skill._look_for(npcs)) is None

    skill, _ = _looking_skill(packs, tmp_path, RuntimeError("the model cannot see"))
    assert _run(skill._look_for(npcs)) is None

    skill, seen = _looking_skill(packs, tmp_path, "Jonas")
    skill.retrieve_custom_property_value = lambda name, errors: False if name == "look_at_screen" else None
    assert _run(skill._look_for(npcs)) is None and seen == []


def test_the_vision_answer_is_matched_by_name_or_shop(packs):
    npcs = [packs.npcs["lena-varga"], packs.npcs["jonas-varga"]]
    assert dialogue.npc_in_answer("The sign says Tammany and Sons.", npcs).id == "lena-varga"
    assert dialogue.npc_in_answer("Jonas Varga", npcs).id == "jonas-varga"
    assert dialogue.npc_in_answer("None of them.", npcs) is None
    assert dialogue.npc_in_answer("", npcs) is None
