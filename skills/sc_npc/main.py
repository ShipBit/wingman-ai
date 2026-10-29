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
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional

from api.enums import ImageStyle, SpeechPriority
from api.interface import SettingsConfig, SkillConfig
from services.image_generation import AVATAR_FRAMING, compose_prompt, store_image, vision_base64
from services.skill_local_ai import SamplingPreset
from skills.sc_npc import dialogue
from skills.sc_npc.packs import Npc, Packs, Quest, load_packs
from skills.sc_npc.quests import Advance, QuestLog, attitude_of, describe_step
from skills.skill_base import Skill, tool

SILENT = "."
"""A tool's instant response that ends the turn without a word (skills/README.md)."""

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext

BUNDLED_PACKS = Path(__file__).parent / "packs"
HINT_COOLDOWN_SECONDS = 20 * 60
TALK_IDLE_SECONDS = 5 * 60
"""Without a word for this long, a conversation with an NPC is over."""
"""The same NPC is not hinted at again within this time."""
LINE_CHARS = 400
HUD_GROUP = "npc"
QUESTS_PANEL = "Quests"
LISTED = 8
PORTRAITS_DIR = "portraits"
"""Generated pictures, <npc id>.<ext>, in the skill's files folder."""
PORTRAIT_STYLE = ImageStyle.CINEMATIC
PORTRAIT_EXTENSIONS = ("png", "jpg", "jpeg", "webp")


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
        self._speakers: list = []
        """Subscriptions for the NPC names the user can address directly."""
        self._names: dict = {}
        """Addressable name to NPC id."""
        self._talking: Optional[Npc] = None
        """The NPC the user is talking to right now (the skill has the conversation)."""
        self._portrait_tried: set = set()
        """NPC ids a picture was generated for this session, or tried."""

    # --- settings, read fresh -------------------------------------------------

    def _hint_on_arrival(self) -> bool:
        value = self.retrieve_custom_property_value("hint_on_arrival", [])
        return True if value is None else bool(value)

    def _show_in_hud(self) -> bool:
        value = self.retrieve_custom_property_value("show_in_hud", [])
        return True if value is None else bool(value)

    def _generate_portraits(self) -> bool:
        value = self.retrieve_custom_property_value("generate_portraits", [])
        return True if value is None else bool(value)

    def _npc_voice_setting(self):
        return self.retrieve_custom_property_value("npc_voice", [])

    def _look_at_screen(self) -> bool:
        value = self.retrieve_custom_property_value("look_at_screen", [])
        return True if value is None else bool(value)

    def _display(self) -> int:
        try:
            return max(1, int(self.retrieve_custom_property_value("display", []) or 1))
        except (TypeError, ValueError):
            return 1

    # --- lifecycle --------------------------------------------------------------

    def _files(self) -> Path:
        return Path(self.get_generated_files_dir())

    def _reload_packs(self) -> None:
        self._packs = load_packs([BUNDLED_PACKS, self._files() / "packs"])
        self._log = QuestLog(self._files() / "quests.json", self._packs)
        for problem in self._packs.problems:
            self.log.warning(f"NPC pack left out: {problem}")
        for warning in self._packs.warnings:
            self.log.warning(f"NPC pack: {warning}")
        self.log.info(
            f"NPC packs: {', '.join(self._packs.loaded) or 'none'} "
            f"({len(self._packs.npcs)} NPCs, {len(self._packs.quests)} quests)",
            server_only=True,
        )

    async def prepare(self) -> None:
        await super().prepare()
        self._reload_packs()
        self._subscription = self.wingman.sc_gamelog.on("*", self._on_event)
        self._teach_names()
        state = self.wingman.sc_gamelog.state() if self.wingman.sc_gamelog.available else None
        if state and state.get("location_status") == "at":
            self._here = str(state.get("location_name") or "")
        self._register_here()
        # The HUD brings its info panels back from its own file at start, so
        # the quest log of the last session is on screen before this runs.
        # Draw it from quests.json, which takes a deleted or finished one off.
        await self._questlog()

    async def unload(self) -> None:
        if self._subscription:
            self._subscription.unsubscribe()
            self._subscription = None
        self._end_talk()
        try:
            if self._show_in_hud() and self.wingman.hud.available:
                await self.wingman.hud.remove_info(QUESTS_PANEL)
        except Exception:
            pass
        for speaker in self._speakers:
            speaker.unsubscribe()
        self._speakers.clear()
        try:
            self.wingman.stt.remove_hotwords(self._hotwords())
        except Exception:
            pass
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
                parts.append(
                    f"People at {self._here} the user can talk to: {people}. The user addresses them "
                    "by name ('Lena, ...') or you hand over with talk_to_npc; from then on they talk "
                    "directly and you stay silent until the user says your name."
                )
        summary = self._log.summary() if self._log else ""
        if summary:
            parts.append(
                "The user's NPC quests:\n" + summary
                + "\nWhether the user has reached a quest spot is answered by quests(check), "
                "which measures the position itself; do not guess coordinates for check_position."
            )
        text = "\n".join(p for p in parts if p)
        return text or None

    # --- the game log ------------------------------------------------------------

    def _on_event(self, event) -> None:
        if event.type == "location_arrived":
            place = str(event.data.get("location_name") or "")
            self._here = place
            self._register_here()
            if not event.catching_up and place:
                self._schedule(self._arrived(place))
        elif event.type == "location_departed":
            self._here = ""
            self._register_here()
            if not event.catching_up:
                self._schedule(self._departed())

    def _schedule(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _arrived(self, place: str) -> None:
        try:
            advances = self._log.on_place(place) if self._log else []
            if advances:
                await self._questlog()
            for advance in advances:
                line = await self._after_advance(advance)
                await self.wingman.conversation.show(line, skill_name=self.config.display_name)
                await self.wingman.tts.speak(line, priority=SpeechPriority.EVENT)
            npcs = self._packs.npcs_at(place)
            if not npcs:
                return
            await self._cards(npcs, place)
            for npc in npcs:
                self._schedule(self._ensure_portrait(npc))
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
        self._end_talk()
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
            parts = []
            portrait = self._portrait(npc)
            if portrait:
                # Forward slashes: in Markdown a backslash escapes the next character
                parts.append(f"![{npc.name}]({portrait.replace(chr(92), '/')})")
            where = (npc.shop + " · " if npc.shop else "") + place
            parts.append(where + (f"\n{npc.wants[:90]}" if npc.wants else ""))
            jobs = self._log.done_for(npc.id) if self._log else 0
            if jobs:
                parts.append(f"{attitude_of(jobs)} · {jobs} job{'s' if jobs > 1 else ''} done")
            await group.add_info(npc.name, "\n\n".join(parts))

    # --- pictures ---------------------------------------------------------------------

    def _portrait(self, npc: Npc) -> str:
        """The path of the NPC's picture: the pack's, else a generated one, else ""."""
        if npc.avatar and os.path.isfile(npc.avatar):
            return npc.avatar
        folder = self._files() / PORTRAITS_DIR
        for extension in PORTRAIT_EXTENSIONS:
            file = folder / f"{npc.id}.{extension}"
            if file.is_file():
                return str(file)
        return ""

    async def _ensure_portrait(self, npc: Npc) -> None:
        """An NPC without a picture gets one made from their persona, once.
        In the background: the conversation does not wait for it."""
        if self._portrait(npc) or npc.id in self._portrait_tried or not self._generate_portraits():
            return
        self._portrait_tried.add(npc.id)
        try:
            prompt = compose_prompt(dialogue.portrait_prompt(npc), PORTRAIT_STYLE, AVATAR_FRAMING)
            image = await self.wingman.ai.generate_image(prompt)
            if not image:
                self.log.info(
                    f"No picture for {npc.name}: image generation is off or failed.", server_only=True
                )
                return
            folder = self._files() / PORTRAITS_DIR
            folder.mkdir(parents=True, exist_ok=True)
            stored = await asyncio.to_thread(store_image, image, str(folder), npc.id)
            final = folder / f"{npc.id}{Path(stored).suffix.lower()}"
            os.replace(stored, final)
            self.log.info(f"Picture of {npc.name} saved: {final}", server_only=True)
            if self._here and npc.at(self._here):
                await self._cards([npc], self._here)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.log.warning(f"Picture of {npc.name}: {error}", server_only=True)

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
        done = [q.title for q, _ in (self._log.done() if self._log else []) if q.involves(npc.id)]
        system = dialogue.npc_system_prompt(
            npc,
            language=self.wingman.language.name,
            place=npc.place,
            world=self._world(npc),
            memory=await self._memory_about(npc),
            offers=offers,
            active_titles=active,
            done_titles=done[-LISTED:],
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
            "Hand the user over to an NPC from the content packs to talk directly: the one at the "
            "current place, or the one named. The NPC then answers in their own voice and you stay "
            "silent until the user addresses you by name."
        )
    )
    async def talk_to_npc(self, text: str, npc: str = ""):
        """Args:
        text: What the user says to the NPC, in the user's own words. Nothing said to them yet: a plain greeting.
        npc: Who, by name. Empty = the NPC at the current place.
        """
        target, note = self._resolve_npc(npc)
        if target is None:
            return note
        if not (npc or "").strip():
            here = self._packs.npcs_at(self._here) if self._here else []
            if len(here) > 1:
                seen = await self._look_for(here)
                if seen is not None:
                    target, note = seen, ""
        await self._start_talk(target, (text or "").strip() or "Hello.")
        return (
            f"{target.name} is talking to the user now, in their own voice. You are out of the "
            f"conversation until the user says your name. {note}"
        ).strip(), SILENT

    # --- the conversation with an NPC ------------------------------------------------

    def _hotwords(self) -> list:
        """The names of every NPC in the loaded packs, for the transcription."""
        words = []
        for npc in self._packs.npcs.values():
            words += [npc.name, npc.name.split()[0], *npc.aliases]
        return list(dict.fromkeys(words))

    def _teach_names(self) -> None:
        """The transcription corrects what it heard against these names, so
        "Lena" does not come out as "Lehna" and never match."""
        try:
            self.wingman.stt.add_hotwords(self._hotwords())
        except Exception as error:
            self.log.warning(f"Hotwords: {error}", server_only=True)

    def _register_here(self) -> None:
        """The people at the current place become addressable like a Wingman,
        by full name, first name and alias. Nobody elsewhere: a name only
        reaches someone who is here, and whoever routes the sentence sees a
        short list."""
        for speaker in self._speakers:
            speaker.unsubscribe()
        self._speakers.clear()
        self._names.clear()
        for npc in (self._packs.npcs_at(self._here) if self._here else []):
            description = dialogue.speaker_description(npc)
            for name in dict.fromkeys([npc.name, npc.name.split()[0], *npc.aliases]):
                self._names[name] = npc.id
                self._speakers.append(
                    self.wingman.conversation.register_speaker(
                        name, self._addressed, description=description
                    )
                )

    async def _addressed(self, name: str, text: str) -> bool:
        npc = self._packs.npcs.get(self._names.get(name, ""))
        if npc is None:
            return False
        await self._start_talk(npc, text)
        return True

    async def _start_talk(self, npc: Npc, text: str) -> bool:
        """The user starts talking to `npc`: the skill takes the conversation,
        the NPC greets once per session, then answers what was said."""
        self._talking = npc
        self.wingman.conversation.take_over(npc.name, self._turn, idle_s=TALK_IDLE_SECONDS)
        self._schedule(self._ensure_portrait(npc))
        if npc.id not in self._met and npc.greeting:
            self._met.add(npc.id)
            self._history.setdefault(npc.id, []).append(("assistant", npc.greeting))
            await self._say(npc, npc.greeting)
        self._met.add(npc.id)
        return await self._turn(text)

    def _end_talk(self) -> None:
        self._talking = None
        takeover = self.wingman.conversation.takeover
        if takeover is not None and takeover.speaker in {n.name for n in self._packs.npcs.values()}:
            takeover.release()

    async def _turn(self, text: str) -> bool:
        """What the user said to the NPC they are talking to. False ends it."""
        npc = self._talking
        if npc is None:
            return False
        over, accepted = await self._judge(npc, text)
        said_by_wingman = []
        if accepted is not None:
            said_by_wingman.append(await self._accept(accepted))
        line = await self._npc_answer(npc, text)
        if line:
            self._history.setdefault(npc.id, []).extend([("user", text), ("assistant", line)])
            await self._say(npc, line)
        else:
            self.log.warning(f"{npc.name} gave no answer.", server_only=True)
        if self._log:
            for quest in self._log.offerable(npc.id):
                self._log.offer(quest)
            for advance in self._log.on_talk(npc.id):
                said_by_wingman.append(await self._after_advance(advance))
        for note in said_by_wingman:
            await self.wingman.conversation.show(note, skill_name=self.config.display_name)
            await self.wingman.tts.speak(note)
        if line:
            await self._remember(npc, text, line)
        await self._questlog()
        if over:
            self._talking = None
        return not over

    async def _judge(self, npc: Npc, text: str) -> tuple:
        """(the pilot is ending the conversation, the offered quest they just
        agreed to or None), judged by System One. Without it: (False, None);
        the conversation then ends by name, by leaving, or by silence."""
        so = self.wingman.system_one
        if not so.available:
            return False, None
        offered = [
            q for q in (self._log.offerable(npc.id) if self._log else [])
            if self._log.state(q.id) is not None and self._log.state(q.id).status == "offered"
        ]
        questions = {
            "over": so.noul("Is the pilot ending the conversation: saying goodbye, leaving, or done talking?")
        }
        if offered:
            questions["accept"] = so.choice(
                "Does the pilot agree to take on the work this person offered?",
                {
                    "yes": "agrees, accepts, says they will do it",
                    "no": "declines, asks more, or talks about something else",
                },
            )
        history = self._history.get(npc.id, [])
        last = next((t for role, t in reversed(history) if role == "assistant"), "")
        try:
            answers = await so.decide(
                state={
                    "person": npc.name,
                    "person_last_said": last,
                    "pilot_said": text,
                    "offered_work": [q.title for q in offered],
                },
                questions=questions,
            )
        except Exception as error:
            self.log.warning(f"System One: {error}", server_only=True)
            return False, None
        over = bool(answers.yes_no("over", 0.7))
        accepted = offered[0] if offered and answers.choice("accept", min_confidence=0.7) == "yes" else None
        return over, accepted

    async def _look_for(self, npcs: list) -> Optional[Npc]:
        """Which of `npcs` is in front of the user, told from a screenshot: a
        shop sign, a counter, a name on screen. None when the screen does not
        say, the model cannot see, or the setting is off."""
        if not self._look_at_screen() or not npcs:
            return None
        try:
            if not await self.wingman.ai.sees_images():
                self.log.info("The main model does not take images; no look at the screen.", server_only=True)
                return None
            image = await self.wingman.screen.capture(self._display())
            jpeg = await asyncio.to_thread(vision_base64, image)
            answer = await self.wingman.ai.generate(
                dialogue.look_prompt(npcs), image=f"data:image/jpeg;base64,{jpeg}"
            )
        except Exception as error:
            self.log.warning(f"Could not look at the screen: {error}", server_only=True)
            return None
        seen = dialogue.npc_in_answer(answer, npcs)
        self.log.info(
            f"On screen: {seen.name if seen else 'none of ' + ', '.join(n.name for n in npcs)}",
            server_only=True,
        )
        return seen

    async def _say(self, npc: Npc, line: str) -> None:
        await self.wingman.conversation.said_by(
            npc.name, line, skill_name=self.config.display_name, avatar=self._portrait(npc) or None
        )
        await self._speak_as(npc, line)

    def _giver_name(self, quest: Quest) -> str:
        npc = self._packs.npcs.get(quest.giver)
        return npc.name if npc else quest.giver

    async def _accept(self, quest: Quest) -> str:
        self._log.accept(quest)
        if self.wingman.memory.available:
            # The step is not part of it: the quest log in the context has the
            # current one, a step written here would go stale.
            try:
                await self.wingman.memory.track(
                    f"Quest '{quest.title}' for {self._giver_name(quest)} (steps in the NPC quest log)"
                )
            except Exception:
                pass
        await self._questlog()
        return f"Accepted '{quest.title}'. First step: {quest.steps[0].hint or describe_step(quest.steps[0], self._packs.npcs)}"

    # --- quests ---------------------------------------------------------------------------

    async def _after_advance(self, advance: Advance) -> str:
        quest = advance.quest
        if advance.finished:
            if self.wingman.memory.available:
                try:
                    await self.wingman.memory.close(f"Quest '{quest.title}'", f"Quest '{quest.title}' completed.")
                    await self.wingman.memory.remember(
                        f"The user completed the quest '{quest.title}' for {self._giver_name(quest)}."
                    )
                except Exception:
                    pass
            text = f"Quest '{quest.title}' is complete."
            if quest.reward:
                text += f" {quest.reward}"
            if advance.step and advance.step.done:
                text = f"{advance.step.done} {text}"
            if self._here:
                here = [n for n in self._packs.npcs_at(self._here) if quest.involves(n.id)]
                if here:
                    await self._cards(here, self._here)
            return text
        text = advance.step.done or f"Step done for '{quest.title}'."
        if advance.next_step:
            text += f" Next: {advance.next_step.hint or describe_step(advance.next_step, self._packs.npcs)}"
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
            "The user's quests from NPC packs: list them (active, offered and completed), accept "
            "one an NPC offered, check the current step (a spot to reach is measured with the "
            "position skill; a confirm step is completed), or abandon one."
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
            done = self._log.done()
            if done:
                lines.append("Completed: " + ", ".join(
                    f"'{q.title}' ({time.strftime('%Y-%m-%d', time.localtime(s.finished_at))})"
                    for q, s in done[-LISTED:]
                ) + ".")
            if self._packs.problems:
                lines.append("Packs with problems: " + "; ".join(self._packs.problems[:3]))
            return "\n".join(lines)
        if action == "accept":
            picked, note = self._pick_quest(quest, ("offered",))
            if picked is None:
                return note
            return await self._accept(picked)
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
        if "could not" in response.lower():
            # No reading at all: the position skill's text says what to do.
            return f"The spot could not be checked, the step stays open. {response}"
        return f"Not there yet. {response} {step.hint}".strip()
