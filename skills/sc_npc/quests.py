"""The quest engine: which quests are running, which step is current, and
what moves a step on.

Four kinds of step: `visit` is done when the Game.log reports the place,
`talk` when the player talks to that NPC, `reach` when the position skill
says the target is within tolerance, `confirm` when the player says so. The
state is one JSON file; the engine is pure and the skill feeds it.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from skills.sc_npc.packs import Packs, Quest, Step
from skills.sc_npc.store import read_json, write_json

OFFERED, ACTIVE, DONE, ABANDONED = "offered", "active", "done", "abandoned"


@dataclass
class QuestState:
    quest: str
    status: str
    step: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0


@dataclass
class Advance:
    """What happened to a quest after an input."""

    quest: Quest
    step: Optional[Step]
    """The step that was completed, None if nothing moved."""
    finished: bool
    next_step: Optional[Step]


class QuestLog:
    def __init__(self, path: Path, packs: Packs) -> None:
        self.path = Path(path)
        self.packs = packs
        self._states: Optional[dict] = None

    # --- state --------------------------------------------------------------------

    def _load(self) -> dict:
        if self._states is None:
            self._states = {}
            data = read_json(self.path) or {}
            for item in (data.get("quests") or []) if isinstance(data, dict) else []:
                try:
                    state = QuestState(**item)
                except TypeError:
                    continue
                self._states[state.quest] = state
        return self._states

    def _save(self) -> None:
        write_json(self.path, {"quests": [asdict(s) for s in self._load().values()]})

    def state(self, quest_id: str) -> Optional[QuestState]:
        return self._load().get(quest_id)

    def active(self) -> list:
        """(Quest, QuestState) of every running quest, in the order they were taken."""
        pairs = []
        for state in sorted(self._load().values(), key=lambda s: s.started_at):
            quest = self.packs.quests.get(state.quest)
            if quest and state.status == ACTIVE:
                pairs.append((quest, state))
        return pairs

    def done(self) -> list:
        """(Quest, QuestState) of every finished quest, oldest first."""
        pairs = []
        for state in sorted(self._load().values(), key=lambda s: s.finished_at):
            quest = self.packs.quests.get(state.quest)
            if quest and state.status == DONE:
                pairs.append((quest, state))
        return pairs

    def current_step(self, quest: Quest, state: QuestState) -> Optional[Step]:
        if state.status != ACTIVE or state.step >= len(quest.steps):
            return None
        return quest.steps[state.step]

    def offerable(self, npc_id: str) -> list:
        """Quests this NPC gives that the player has not taken or finished,
        and whose required quests are done."""
        return [
            q for q in self.packs.quests_of(npc_id)
            if (self.state(q.id) is None or self.state(q.id).status in (OFFERED, ABANDONED))
            and all(self.is_done(required) for required in q.requires)
        ]

    def is_done(self, quest_id: str) -> bool:
        state = self.state(quest_id)
        return state is not None and state.status == DONE

    def done_for(self, npc_id: str) -> int:
        """How many finished quests this NPC gave or was talked to in."""
        return sum(1 for quest, _ in self.done() if quest.involves(npc_id))

    # --- transitions ----------------------------------------------------------------

    def offer(self, quest: Quest) -> None:
        state = self.state(quest.id)
        if state is None or state.status == ABANDONED:
            self._load()[quest.id] = QuestState(quest=quest.id, status=OFFERED)
            self._save()

    def accept(self, quest: Quest, now: Optional[float] = None) -> QuestState:
        state = QuestState(quest=quest.id, status=ACTIVE, step=0, started_at=now or time.time())
        self._load()[quest.id] = state
        self._save()
        return state

    def abandon(self, quest: Quest) -> bool:
        state = self.state(quest.id)
        if state is None or state.status != ACTIVE:
            return False
        state.status = ABANDONED
        self._save()
        return True

    def _complete_current(self, quest: Quest, state: QuestState, now: float) -> Advance:
        step = quest.steps[state.step]
        state.step += 1
        finished = state.step >= len(quest.steps)
        if finished:
            state.status = DONE
            state.finished_at = now
        self._save()
        return Advance(quest, step, finished, None if finished else quest.steps[state.step])

    def on_place(self, place_name: str, now: Optional[float] = None) -> list:
        """The Game.log reported arrival at `place_name`: every `visit` step
        waiting for it is done. Returns the advances."""
        advances = []
        for quest, state in self.active():
            step = self.current_step(quest, state)
            if step and step.type == "visit" and step.place.lower() == (place_name or "").lower():
                advances.append(self._complete_current(quest, state, now or time.time()))
        return advances

    def on_talk(self, npc_id: str, now: Optional[float] = None) -> list:
        """The player talked to `npc_id`: every `talk` step waiting for them is done."""
        advances = []
        for quest, state in self.active():
            step = self.current_step(quest, state)
            if step and step.type == "talk" and step.npc == npc_id:
                advances.append(self._complete_current(quest, state, now or time.time()))
        return advances

    def on_reached(self, quest: Quest, now: Optional[float] = None) -> Optional[Advance]:
        """The position skill confirmed the current `reach` step's target."""
        state = self.state(quest.id)
        step = self.current_step(quest, state) if state else None
        if step and step.type == "reach":
            return self._complete_current(quest, state, now or time.time())
        return None

    def on_confirm(self, quest: Quest, now: Optional[float] = None) -> Optional[Advance]:
        """The player confirmed the current `confirm` step."""
        state = self.state(quest.id)
        step = self.current_step(quest, state) if state else None
        if step and step.type == "confirm":
            return self._complete_current(quest, state, now or time.time())
        return None

    # --- wording ----------------------------------------------------------------------

    def summary(self) -> str:
        """The quest log as the model and the HUD see it."""
        lines = []
        for quest, state in self.active():
            step = self.current_step(quest, state)
            what = describe_step(step, self.packs.npcs)
            where = f"step {state.step + 1} of {len(quest.steps)}: {what}" if step else "done"
            lines.append(f"- {quest.title} ({where})")
        return "\n".join(lines)


def attitude_of(jobs_done: int) -> str:
    """How an NPC stands to the player after this many jobs for them."""
    if jobs_done <= 0:
        return ""
    return "Knows you" if jobs_done == 1 else "Trusts you"


def describe_step(step: Optional[Step], npcs: Optional[dict] = None) -> str:
    """One short clause per step; `npcs` (id -> Npc) puts names in place of ids."""
    if step is None:
        return ""
    if step.type == "visit":
        return f"go to {step.place}"
    if step.type == "talk":
        npc = (npcs or {}).get(step.npc)
        return f"talk to {npc.name if npc else step.npc}"
    if step.type == "reach":
        return "reach the marked spot"
    return "confirm when done"
