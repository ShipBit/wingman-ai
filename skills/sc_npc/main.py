"""Star Citizen NPCs: the people of the verse get a voice, a memory and work
to hand out.

Content comes in packs (packs.py): NPCs anchored to places the Game.log
names, and quests they give. The skill listens to the log reader for
arrivals, drops a hint when someone at that place has something to say,
and lets the user talk to them: the answer is written from the NPC's persona
by the main model, spoken in the NPC's own voice, and remembered in the
Wingman's memory. Quests run as steps the log, the position skill, a talk or
the user's word complete (quests.py).

The Wingman stays the go-between: the user talks to the Wingman, the Wingman
calls talk_to_npc, the NPC answers aloud. Nothing here polls the game.
"""

import asyncio
import math
import time
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional

from api.enums import SpeechPriority
from api.interface import SettingsConfig, SkillConfig
from services.skill_local_ai import SamplingPreset
from skills.sc_npc import dialogue
from skills.sc_npc.packs import Npc, Packs, Quest, load_packs
from skills.sc_npc.quests import Advance, QuestLog, describe_step
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext

BUNDLED_PACKS = Path(__file__).parent / "packs"
HINT_COOLDOWN_SECONDS = 20 * 60
"""The same NPC is not hinted at again within this time."""
LINE_CHARS = 400
HUD_GROUP = "npc"
QUESTS_PANEL = "Quests"
LISTED = 8


class ScNpc(Skill):
    def __init__(
        self, config: SkillConfig, settings: SettingsConfig, wingman: "WingmanContext"
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        self._packs: Packs = Packs()
        self._log: Optional[QuestLog] = None
        self._subscription = None
        self._here: str = ""
        """The place the log last reported the player at, "" when away."""
        self._hinted: dict = {}
        """NPC id to when the hint about them was last said (monotonic)."""
        self._history: dict = {}
        """NPC id to this session's turns with them: [(role, text), ...]."""
        self._met: set = set()
        """NPC ids greeted this session."""
        self._tasks: set = set()

    # --- settings, read fresh -------------------------------------------------

    def _hint_on_arrival(self) -> bool:
        value = self.retrieve_custom_property_value("hint_on_arrival", [])
        return True if value is None else bool(value)

    def _show_in_hud(self) -> bool:
        value = self.retrieve_custom_property_value("show_in_hud", [])
        return True if value is None else bool(value)

    def _npc_voice_setting(self):
        return self.retrieve_custom_property_value("npc_voice", [])

    # --- lifecycle --------------------------------------------------------------

    def _files(self) -> Path:
        return Path(self.get_generated_files_dir())

    def _reload_packs(self) -> None:
        self._packs = load_packs([BUNDLED_PACKS, self._files() / "packs"])
        self._log = QuestLog(self._files() / "quests.json", self._packs)
        for problem in self._packs.problems:
            self.log.warning(f"NPC pack left out: {problem}")
        self.log.info(
            f"NPC packs: {', '.join(self._packs.loaded) or 'none'} "
            f"({len(self._packs.npcs)} NPCs, {len(self._packs.quests)} quests)",
            server_only=True,
        )

    async def prepare(self) -> None:
        await super().prepare()
        self._reload_packs()
        self._subscription = self.wingman.sc_gamelog.on("*", self._on_event)
        state = self.wingman.sc_gamelog.state() if self.wingman.sc_gamelog.available else None
        if state and state.get("location_status") == "at":
            self._here = str(state.get("location_name") or "")

    async def unload(self) -> None:
        if self._subscription:
            self._subscription.unsubscribe()
            self._subscription = None
        for task in list(self._tasks):
            if not task.done():
                task.cancel()
        self._tasks.clear()
        await super().unload()

    async def get_prompt(self) -> str | None:
        parts = [await super().get_prompt() or ""]
        if self._here:
            npcs = self._packs.npcs_at(self._here)
            if npcs:
                people = ", ".join(n.name + (f" at {n.shop}" if n.shop else "") for n in npcs)
                parts.append(f"People at {self._here} the user can talk to (use talk_to_npc): {people}.")
        summary = self._log.summary() if self._log else ""
        if summary:
            parts.append("The user's NPC quests:\n" + summary)
        text = "\n".join(p for p in parts if p)
        return text or None

    # --- the game log ------------------------------------------------------------

    def _on_event(self, event) -> None:
        if event.type == "location_arrived":
            place = str(event.data.get("location_name") or "")
            self._here = place
            if not event.catching_up and place:
                self._schedule(self._arrived(place))
        elif event.type == "location_departed":
            self._here = ""
            if not event.catching_up:
                self._schedule(self._departed())

    def _schedule(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _arrived(self, place: str) -> None:
        try:
            for advance in (self._log.on_place(place) if self._log else []):
                line = await self._after_advance(advance)
                await self.wingman.conversation.show(line, skill_name=self.config.display_name)
                await self.wingman.tts.speak(line, priority=SpeechPriority.EVENT)
            npcs = self._packs.npcs_at(place)
            if not npcs:
                return
            await self._cards(npcs, place)
            if not self._hint_on_arrival():
                return
            now = time.monotonic()
            due = [n for n in npcs if now - self._hinted.get(n.id, -math.inf) > HINT_COOLDOWN_SECONDS]
            if not due:
                return
            npc = due[0]
            self._hinted[npc.id] = now
            line = await self._phrase(
                dialogue.arrival_hint_prompt(self.wingman.name, self.wingman.language.name, npc, place)
            )
            if line:
                await self.wingman.conversation.show(line, skill_name=self.config.display_name)
                await self.wingman.tts.speak(line, priority=SpeechPriority.EVENT)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # the game goes on
            self.log.warning(f"Arrival at {place}: {error}", server_only=True)

    async def _departed(self) -> None:
        try:
            if self._show_in_hud() and self.wingman.hud.available:
                await self._group().clear()
        except Exception as error:
            self.log.warning(f"Departure: {error}", server_only=True)

    async def _phrase(self, prompt: str) -> str:
        try:
            if self.wingman.local_ai.available:
                line = await self.wingman.local_ai.generate(prompt, preset=SamplingPreset.CREATIVE)
            else:
                line = await self.wingman.ai.generate(prompt)
        except Exception as error:
            self.log.warning(f"No line: {error}", server_only=True)
            return ""
        return (line or "").strip().strip('"')[:LINE_CHARS]

    # --- HUD ---------------------------------------------------------------------------

    def _group(self):
        return self.wingman.hud.group(HUD_GROUP, anchor="top_right", width=320)

    async def _cards(self, npcs: list, place: str) -> None:
        if not self._show_in_hud() or not self.wingman.hud.available:
            return
        group = self._group()
        for npc in npcs:
            where = (npc.shop + " · " if npc.shop else "") + place
            await group.add_info(npc.name, where + (f"\n{npc.wants[:90]}" if npc.wants else ""))

    async def _questlog(self) -> None:
        if not self._show_in_hud() or not self.wingman.hud.available or not self._log:
            return
        summary = self._log.summary()
        if summary:
            await self.wingman.hud.add_info(QUESTS_PANEL, summary)
        else:
            await self.wingman.hud.remove_info(QUESTS_PANEL)

    # --- talking ------------------------------------------------------------------------

    def _resolve_npc(self, name: str) -> tuple:
        """(Npc, note) or (None, why not)."""
        if name and name.strip():
            npc = self._packs.find_npc(name)
            if npc is None:
                known = ", ".join(n.name for n in list(self._packs.npcs.values())[:LISTED])
                return None, f"No NPC called '{name.strip()}'." + (f" Known: {known}." if known else " No packs loaded.")
            return npc, ""
        here = self._packs.npcs_at(self._here) if self._here else []
        if not here:
            where = f"at {self._here}" if self._here else "here (the game log has not reported a place)"
            return None, f"There is no one to talk to {where}. Name the NPC to reach them over comms."
        note = ""
        if len(here) > 1:
            note = "Others here: " + ", ".join(n.name for n in here[1:LISTED]) + "."
        return here[0], note

    def _world(self, npc: Npc) -> str:
        state = self.wingman.sc_gamelog.state() if self.wingman.sc_gamelog.available else None
        lines = []
        if self._here and not npc.at(self._here):
            lines.append(f"The pilot is not here in person; they reach you over comms from {self._here}.")
        elif not self._here:
            lines.append("The pilot reaches you over comms from somewhere in space.")
        if state:
            if state.get("ship") and state.get("aboard_ship"):
                lines.append(f"The pilot flies a {state['ship']}.")
            if state.get("player_name"):
                lines.append(f"The pilot's name is {state['player_name']}.")
        return "\n".join(lines)

    async def _memory_about(self, npc: Npc) -> str:
        if not self.wingman.memory.available:
            return ""
        try:
            block = await self.wingman.memory.context(npc.name)
        except Exception:
            return ""
        first = npc.name.split()[0].lower()
        return "\n".join(line for line in (block or "").splitlines() if first in line.lower())

    async def _npc_answer(self, npc: Npc, text: str) -> str:
        offers = self._log.offerable(npc.id) if self._log else []
        active = [q.title for q, _ in (self._log.active() if self._log else []) if q.giver == npc.id]
        system = dialogue.npc_system_prompt(
            npc,
            language=self.wingman.language.name,
            place=npc.place,
            world=self._world(npc),
            memory=await self._memory_about(npc),
            offers=offers,
            active_titles=active,
        )
        history = self._history.setdefault(npc.id, [])
        messages = [{"role": "system", "content": system}, *dialogue.history_messages(history),
                    {"role": "user", "content": text}]
        try:
            reply = await self.wingman.ai.generate(messages=messages)
        except Exception as error:
            self.log.warning(f"{npc.name} did not answer: {error}", server_only=True)
            return ""
        return (reply or "").strip().strip('"')[:LINE_CHARS]

    def _voice_for(self, npc: Npc):
        provider = self.wingman.config.features.tts_provider
        key = getattr(provider, "value", str(provider))
        if npc.voices.get(key):
            return npc.voices[key]
        selection = self._npc_voice_setting()
        if selection is not None and getattr(selection, "provider", None) == provider:
            return selection.voice
        return None

    async def _speak_as(self, npc: Npc, line: str) -> None:
        voice = self._voice_for(npc)
        original = self.wingman.tts.voice if voice is not None else None
        if voice is not None and voice != original:
            result = await self.wingman.tts.set_voice(voice)
            if result.startswith("Voice change failed"):
                self.log.warning(f"{npc.name}: {result}", server_only=True)
                voice = None
        try:
            await self.wingman.tts.speak(line)
        finally:
            if voice is not None and original is not None:
                await self.wingman.tts.set_voice(original)

    async def _remember(self, npc: Npc, said: str, answer: str) -> None:
        if not self.wingman.memory.available:
            return
        try:
            await self.wingman.memory.remember(
                f"Talked with {npc.name} at {npc.place}: the user said \"{said[:120]}\", "
                f"{npc.name} said \"{answer[:160]}\"."
            )
        except Exception as error:
            self.log.warning(f"Memory: {error}", server_only=True)

    @tool(
        description=(
            "Let the user talk to an NPC from the content packs: the one at the current place, "
            "or the one named. Pass what the user says to them. The NPC's answer is spoken aloud "
            "in their own voice by this skill."
        )
    )
    async def talk_to_npc(self, text: str, npc: str = "") -> str:
        """Args:
        text: What the user says to the NPC, in the user's own words.
        npc: Who, by name. Empty = the NPC at the current place.
        """
        target, note = self._resolve_npc(npc)
        if target is None:
            return note
        text = (text or "").strip() or "Hello."
        history = self._history.setdefault(target.id, [])
        if target.id not in self._met and target.greeting and not history:
            self._met.add(target.id)
            await self._speak_as(target, target.greeting)
            history.append(("assistant", target.greeting))
        self._met.add(target.id)
        line = await self._npc_answer(target, text)
        if not line:
            return f"{target.name} did not answer; the model gave nothing. Try again."
        await self._speak_as(target, line)
        history.extend([("user", text), ("assistant", line)])
        offered = self._log.offerable(target.id) if self._log else []
        for quest in offered:
            self._log.offer(quest)
        advances = self._log.on_talk(target.id) if self._log else []
        notes = [note] + [await self._after_advance(a) for a in advances]
        await self._remember(target, text, line)
        await self._questlog()
        return dialogue.tool_result(target, line, offered=offered, note=" ".join(n for n in notes if n))

    # --- quests ---------------------------------------------------------------------------

    async def _after_advance(self, advance: Advance) -> str:
        quest = advance.quest
        if advance.finished:
            if self.wingman.memory.available:
                try:
                    await self.wingman.memory.close(f"Quest '{quest.title}'", f"Quest '{quest.title}' completed.")
                    await self.wingman.memory.remember(f"The user completed the quest '{quest.title}' for {quest.giver}.")
                except Exception:
                    pass
            text = f"Quest '{quest.title}' is complete."
            if quest.reward:
                text += f" {quest.reward}"
            if advance.step and advance.step.done:
                text = f"{advance.step.done} {text}"
            return text
        text = advance.step.done or f"Step done for '{quest.title}'."
        if advance.next_step:
            text += f" Next: {advance.next_step.hint or describe_step(advance.next_step)}"
        return text

    def _pick_quest(self, name: str, statuses: tuple) -> tuple:
        """(Quest, note) by title among quests in `statuses`, or the only one."""
        if name and name.strip():
            quest = self._packs.find_quest(name)
            if quest is None:
                return None, f"No quest called '{name.strip()}'."
            state = self._log.state(quest.id)
            if (state.status if state else None) not in statuses:
                return None, f"'{quest.title}' is not {' or '.join(statuses)}."
            return quest, ""
        candidates = [q for q in self._packs.quests.values()
                      if (self._log.state(q.id).status if self._log.state(q.id) else None) in statuses]
        if len(candidates) == 1:
            return candidates[0], ""
        if not candidates:
            return None, f"No quest is {' or '.join(statuses)}."
        return None, "Which one? " + ", ".join(f"'{q.title}'" for q in candidates[:LISTED])

    @tool(
        description=(
            "The user's quests from NPC packs: list them, accept one an NPC offered, check the "
            "current step (a spot to reach is measured with the position skill; a confirm step "
            "is completed), or abandon one."
        )
    )
    async def quests(
        self, action: Literal["list", "accept", "check", "abandon"] = "list", quest: str = ""
    ) -> str:
        """Args:
        action: list, accept, check or abandon.
        quest: The quest's title for accept, check and abandon. Empty = the only one that fits.
        """
        if self._log is None:
            return "No content packs are loaded."
        if action == "list":
            lines = [self._log.summary() or "No active quests."]
            offered = [q for q in self._packs.quests.values()
                       if (self._log.state(q.id).status if self._log.state(q.id) else None) == "offered"]
            if offered:
                lines.append("Offered, not yet accepted: " + ", ".join(f"'{q.title}'" for q in offered) + ".")
            if self._packs.problems:
                lines.append("Packs with problems: " + "; ".join(self._packs.problems[:3]))
            return "\n".join(lines)
        if action == "accept":
            picked, note = self._pick_quest(quest, ("offered",))
            if picked is None:
                return note
            self._log.accept(picked)
            if self.wingman.memory.available:
                try:
                    await self.wingman.memory.track(f"Quest '{picked.title}' for {picked.giver}: {describe_step(picked.steps[0])}")
                except Exception:
                    pass
            await self._questlog()
            return f"Accepted '{picked.title}'. First step: {picked.steps[0].hint or describe_step(picked.steps[0])}"
        if action == "abandon":
            picked, note = self._pick_quest(quest, ("active",))
            if picked is None:
                return note
            self._log.abandon(picked)
            if self.wingman.memory.available:
                try:
                    await self.wingman.memory.close(f"Quest '{picked.title}'", f"Quest '{picked.title}' abandoned.")
                except Exception:
                    pass
            await self._questlog()
            return f"Abandoned '{picked.title}'."
        picked, note = self._pick_quest(quest, ("active",))
        if picked is None:
            return note
        step = self._log.current_step(picked, self._log.state(picked.id))
        if step is None:
            return f"'{picked.title}' has no open step."
        if step.type == "visit":
            return f"Waiting for the game log to report arrival at {step.place}. {step.hint}".strip()
        if step.type == "talk":
            npc = self._packs.npcs.get(step.npc)
            return f"The user has to talk to {npc.name if npc else step.npc}. {step.hint}".strip()
        if step.type == "confirm":
            advance = self._log.on_confirm(picked)
            await self._questlog()
            return await self._after_advance(advance) if advance else "Nothing to confirm."
        if not self.wingman.tools.has("check_position"):
            return "The Star Citizen Position skill is not active, so the spot cannot be checked."
        result = await self.wingman.tools.invoke("check_position", {"waypoint": step.target})
        response = (result.response or "").strip()
        if "arrived" in response.lower():
            advance = self._log.on_reached(picked)
            await self._questlog()
            return await self._after_advance(advance) if advance else response
        return f"Not there yet. {response} {step.hint}".strip()
