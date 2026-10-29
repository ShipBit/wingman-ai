"""Content packs: the NPCs and quests a player has switched on.

A pack is one YAML file, `pack.yaml`, in a folder of its own: a few NPCs
anchored to places the Game.log names, and quests those NPCs hand out. The
bundled packs live in this skill's `packs/` folder, the player's own in the
skill's files folder under `packs/`. Authors write who an NPC is, what they
know and what they want; the lines are made from that at play time.

Pure: reading files aside, nothing here touches Wingman. Validation returns
problems as text so the skill can show them; a pack with problems is left
out, the others still load.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

PACK_FILE = "pack.yaml"
STEP_TYPES = ("visit", "talk", "reach", "confirm")
MAX_TEXT = 2000


@dataclass(frozen=True)
class Npc:
    id: str
    name: str
    place: str
    """The place as the Game.log names it, e.g. "Lorville"."""
    persona: str
    shop: str = ""
    knows: tuple = ()
    wants: str = ""
    greeting: str = ""
    """Said when the player first talks to them; empty = improvised."""
    voices: dict = field(default_factory=dict)
    """TTS provider id to voice, e.g. {"edge_tts": "en-GB-SoniaNeural"}."""
    aliases: tuple = ()
    """Other names the user may address them by: a nickname, a spelling the
    speech recognition tends to produce."""
    pack: str = ""

    def at(self, place_name: str) -> bool:
        return _same(self.place, place_name)


@dataclass(frozen=True)
class Step:
    type: str
    hint: str = ""
    """What the player is told when the step becomes current."""
    place: str = ""
    """visit: the place as the Game.log names it."""
    npc: str = ""
    """talk: the NPC's id."""
    target: str = ""
    """reach: a target the position skill understands, e.g. "Aberdeen 12.4 -88.1 120 800"."""
    done: str = ""
    """What the player is told when the step is done."""


@dataclass(frozen=True)
class Quest:
    id: str
    title: str
    giver: str
    """The NPC's id."""
    offer: str
    """How the giver brings it up."""
    steps: tuple
    reward: str = ""
    pack: str = ""

    def involves(self, npc_id: str) -> bool:
        """The NPC gives this quest or is talked to in it."""
        return self.giver == npc_id or any(s.type == "talk" and s.npc == npc_id for s in self.steps)


@dataclass
class Packs:
    npcs: dict = field(default_factory=dict)
    quests: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)
    """"<pack>: <what is wrong>" per pack that was left out."""
    loaded: list = field(default_factory=list)

    def npcs_at(self, place_name: str) -> list:
        return [n for n in self.npcs.values() if n.at(place_name)]

    def find_npc(self, name: str) -> Optional[Npc]:
        """By id or name: the same first, then starts with, then contains."""
        wanted = (name or "").strip().lower()
        if not wanted:
            return None
        for match in (lambda s: s == wanted, lambda s: s.startswith(wanted), lambda s: wanted in s):
            for npc in self.npcs.values():
                if match(npc.id.lower()) or match(npc.name.lower()):
                    return npc
        return None

    def find_quest(self, name: str) -> Optional[Quest]:
        wanted = (name or "").strip().lower()
        if not wanted:
            return None
        for match in (lambda s: s == wanted, lambda s: s.startswith(wanted), lambda s: wanted in s):
            for quest in self.quests.values():
                if match(quest.id.lower()) or match(quest.title.lower()):
                    return quest
        return None

    def quests_of(self, npc_id: str) -> list:
        return [q for q in self.quests.values() if q.giver == npc_id]


def _same(a: str, b: str) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def _text(value, what: str, required: bool = False, problems: list = None) -> str:
    if value is None or value == "":
        if required:
            problems.append(f"{what} is missing")
        return ""
    if not isinstance(value, str):
        problems.append(f"{what} must be text")
        return ""
    if len(value) > MAX_TEXT:
        problems.append(f"{what} is longer than {MAX_TEXT} characters")
        return value[:MAX_TEXT]
    return value.strip()


def parse_pack(data, pack_name: str) -> tuple[list, list, list]:
    """NPCs, quests and problems from one pack's parsed YAML."""
    problems: list = []
    if not isinstance(data, dict):
        return [], [], ["pack.yaml is not a mapping"]
    npcs, quests = [], []
    for index, item in enumerate(data.get("npcs") or []):
        if not isinstance(item, dict):
            problems.append(f"npcs[{index}] is not a mapping")
            continue
        what = f"npc '{item.get('id') or index}'"
        npc_id = _text(item.get("id"), f"{what}.id", True, problems)
        voices = item.get("voices") or {}
        if not isinstance(voices, dict) or not all(isinstance(v, str) for v in voices.values()):
            problems.append(f"{what}.voices must map provider ids to voice names")
            voices = {}
        knows = item.get("knows") or []
        if isinstance(knows, str):
            knows = [knows]
        aliases = item.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        npcs.append(
            Npc(
                id=npc_id,
                name=_text(item.get("name"), f"{what}.name", True, problems),
                place=_text(item.get("place"), f"{what}.place", True, problems),
                persona=_text(item.get("persona"), f"{what}.persona", True, problems),
                shop=_text(item.get("shop"), f"{what}.shop", False, problems),
                knows=tuple(_text(k, f"{what}.knows", False, problems) for k in knows),
                wants=_text(item.get("wants"), f"{what}.wants", False, problems),
                greeting=_text(item.get("greeting"), f"{what}.greeting", False, problems),
                voices={str(k): v for k, v in voices.items()},
                aliases=tuple(_text(a, f"{what}.aliases", False, problems) for a in aliases),
                pack=pack_name,
            )
        )
    npc_ids = {n.id for n in npcs}
    for index, item in enumerate(data.get("quests") or []):
        if not isinstance(item, dict):
            problems.append(f"quests[{index}] is not a mapping")
            continue
        what = f"quest '{item.get('id') or index}'"
        giver = _text(item.get("giver"), f"{what}.giver", True, problems)
        if giver and giver not in npc_ids:
            problems.append(f"{what}.giver '{giver}' is no NPC of this pack")
        steps = []
        for s_index, step in enumerate(item.get("steps") or []):
            s_what = f"{what}.steps[{s_index}]"
            if not isinstance(step, dict):
                problems.append(f"{s_what} is not a mapping")
                continue
            s_type = _text(step.get("type"), f"{s_what}.type", True, problems)
            if s_type not in STEP_TYPES:
                problems.append(f"{s_what}.type must be one of {', '.join(STEP_TYPES)}")
                continue
            parsed = Step(
                type=s_type,
                hint=_text(step.get("hint"), f"{s_what}.hint", False, problems),
                place=_text(step.get("place"), f"{s_what}.place", s_type == "visit", problems),
                npc=_text(step.get("npc"), f"{s_what}.npc", s_type == "talk", problems),
                target=_text(step.get("target"), f"{s_what}.target", s_type == "reach", problems),
                done=_text(step.get("done"), f"{s_what}.done", False, problems),
            )
            if parsed.npc and parsed.npc not in npc_ids:
                problems.append(f"{s_what}.npc '{parsed.npc}' is no NPC of this pack")
            steps.append(parsed)
        if not steps:
            problems.append(f"{what} has no steps")
        quests.append(
            Quest(
                id=_text(item.get("id"), f"{what}.id", True, problems),
                title=_text(item.get("title"), f"{what}.title", True, problems),
                giver=giver,
                offer=_text(item.get("offer"), f"{what}.offer", False, problems),
                steps=tuple(steps),
                reward=_text(item.get("reward"), f"{what}.reward", False, problems),
                pack=pack_name,
            )
        )
    return npcs, quests, problems


def load_packs(folders) -> Packs:
    """Every `<folder>/*/pack.yaml`. Later folders win on the same id."""
    packs = Packs()
    for folder in folders:
        folder = Path(folder)
        if not folder.is_dir():
            continue
        for pack_dir in sorted(p for p in folder.iterdir() if p.is_dir()):
            path = pack_dir / PACK_FILE
            if not path.is_file():
                continue
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as error:
                packs.problems.append(f"{pack_dir.name}: cannot read pack.yaml ({error})")
                continue
            npcs, quests, problems = parse_pack(data, pack_dir.name)
            if problems:
                packs.problems.append(f"{pack_dir.name}: " + "; ".join(problems[:5]))
                continue
            for npc in npcs:
                packs.npcs[npc.id] = npc
            for quest in quests:
                packs.quests[quest.id] = quest
            packs.loaded.append(pack_dir.name)
    return packs
