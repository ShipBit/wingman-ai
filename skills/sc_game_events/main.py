"""Star Citizen Events: the Wingman reacts to what happens in the game.

This skill is also the example for reading the game log from a skill. Core
reads Star Citizen's Game.log (services/sc_gamelog) and every skill gets the
events through `self.wingman.sc_gamelog`:

    self._subscription = self.wingman.sc_gamelog.on("*", self._on_event)
    ...
    self._subscription.unsubscribe()    # in unload()

Which events are worth a word, and how often, decides the policy Mallachi wrote
for the SC Log Reader skill (notifications.py), with its settings: one switch
per type of event, under one master per category. The line itself comes from the
support model, in character and in the user's language, and is shown in the
chat and the HUD, spoken and kept in the conversation.
"""

import asyncio
import random
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from api.enums import SpeechPriority
from api.interface import SettingsConfig, SkillConfig
from services.skill_local_ai import SamplingPreset
from skills.sc_game_events.notifications import (
    _CATEGORIES,
    _DETAIL_FIELDS,
    _TEMPLATES,
    NOTIFICATION_OPTIONS,
    NotificationPolicy,
    _literal,
    enabled_notification_events,
)
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext

# The masters are `react_<category>`, as the 3.2.5 migration saved them, and the
# switches per type `react_<type>`. The policy calls both `notify_...`, the
# names they had in SC Log Reader.
SWITCHES = tuple(_CATEGORIES) + tuple(
    option.removeprefix("notify_") for option in NOTIFICATION_OPTIONS
)
PROMPT_FILE = Path(__file__).parent / "reaction_prompt.md"
REACTION_CHARS = 300
RECENT_LINES = 5
# Events that happen many times in every session: zones, quantum steps, the
# hangar, the login. Each group gets one spoken line per "routine_gap_minutes"
# (2 to 20, default 5); one hour of play had 20 lines about armistice zones and
# monitored space alone.
# Entering and leaving alternate every few minutes, so REPEAT_SECONDS below,
# which only stops the same report, lets them all through. Missions, money,
# injuries and warnings are not in here and always count.
ROUTINE_GROUPS = {
    "armistice_zone": "zone",
    "restricted_area": "zone",
    "entered_monitored_space": "zone",
    "exited_monitored_space": "zone",
    "jurisdiction_change": "zone",
    # Arriving at and leaving a place are not paced: a few per session, and
    # the reason to have the skill on. Paced with the quantum steps, a trip
    # (route, takeoff, jump, arrival) kept only its first line.
    "qt_arrived": "quantum",
    "quantum_route_set": "quantum",
    "quantum_calibration_started": "quantum",
    "quantum_calibration_complete": "quantum",
    "hangar_ready": "hangar",
    "hangar_queue": "hangar",
    "ship_entered": "hangar",
    "ship_exited": "hangar",
    "user_login": "session",
    "session_start": "session",
    "join_pu": "session",
}
ROUTINE_GAP_MINUTES = (2, 5, 20)
"""Minimum, default and maximum of the "routine_gap_minutes" setting. Keep
them in step with its slider in default_config.yaml; these only catch a value
saved outside the slider's range."""
FOLD_SECONDS = 15.0
"""A report from while the Wingman was busy is still worth a word this long.
Arriving somewhere logs zone, jurisdiction and arrival within seconds."""
REPEAT_SECONDS = 90.0
"""The same report is not said again this soon: zones flicker in and out."""
MAX_REPORTS = 4
MAX_WAITING = 16
_now = time.monotonic  # The skill's clock; tests replace it, never asyncio's.
LINK_ANGLE = "Link it to where the pilot is or what the pilot is flying."
# Each line gets one of these. Without it the persona finds one move (the same
# joke, the same opening) and makes it on every event.
ANGLES = (
    "Just report it, plainly, in your own words. No joke.",
    "Give one short practical tip that fits this moment.",
    "Say how you feel about it, in your own voice.",
    LINK_ANGLE,
    "Make a dry remark, if your character would.",
    "Keep it very short, a few words over the comms.",
)


class ScGameEvents(Skill):
    def __init__(
        self, config: SkillConfig, settings: SettingsConfig, wingman: "WingmanContext"
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        self._subscription = None
        self._policy: NotificationPolicy | None = None
        self._events: frozenset[str] = frozenset()
        self._reaction: asyncio.Task | None = None
        self._unanswered = 0
        """Reactions since the user last said something."""
        self._recent_lines: deque[str] = deque(maxlen=RECENT_LINES)
        self._angle = ""
        self._waiting: list[tuple[float, str, str | None]] = []
        """Reports not said yet, with the time they came and their routine group."""
        self._said_at: dict[str, float] = {}
        self._routine_spoken: dict[str, float] = {}
        """When each routine group was last spoken about."""
        self._unnoted: list[str] = []
        """Said since the user last spoke; goes into the history as a note
        right before the user's next message."""

    # --- settings, read fresh -------------------------------------------------

    def _enabled_events(self) -> frozenset[str]:
        settings = {}
        for switch in SWITCHES:
            value = self.retrieve_custom_property_value(f"react_{switch}", [])
            if value is not None:  # A missing switch counts as on.
                settings[f"notify_{switch}"] = bool(value)
        return enabled_notification_events(settings)

    def _max_unanswered(self) -> int:
        """0 means no limit."""
        value = self.retrieve_custom_property_value("max_unanswered", [])
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 10

    def _routine_gap(self) -> float:
        """Seconds between two lines about the same routine group."""
        low, default, high = ROUTINE_GAP_MINUTES
        try:
            minutes = float(self.retrieve_custom_property_value("routine_gap_minutes", []))
        except (TypeError, ValueError):
            minutes = default
        return 60 * min(high, max(low, minutes))

    def _remember(self) -> bool:
        return bool(self.retrieve_custom_property_value("remember_reactions", []))

    def _show_in_hud(self) -> bool:
        return bool(self.retrieve_custom_property_value("show_in_hud", []))

    # --- lifecycle --------------------------------------------------------------

    async def prepare(self) -> None:
        await super().prepare()
        self._subscription = self.wingman.sc_gamelog.on("*", self._on_event)

    async def unload(self) -> None:
        if self._subscription:
            self._subscription.unsubscribe()
            self._subscription = None
        if self._reaction and not self._reaction.done():
            self._reaction.cancel()
        await super().unload()

    async def on_add_user_message(self, message: str) -> None:
        self._unanswered = 0
        # Called before the user's message is added, so the note lands in
        # front of it. Kept out of the history as the Wingman's own lines:
        # the model then appended event lines to its next answers, once word
        # for word.
        lines, self._unnoted = self._unnoted, []
        if lines and self._remember():
            await self.wingman.conversation.add_note(
                "while the user was quiet you said this about the game on your own, "
                "do not say it again: " + " / ".join(lines)
            )

    # --- reacting ---------------------------------------------------------------

    def _on_event(self, event) -> None:
        if event.type in ("shop_buy", "shop_sell") and event.status == "requested":
            return  # React once, to the confirmed trade with its name and amount.
        events = self._enabled_events()
        if not events:
            return
        group = ROUTINE_GROUPS.get(event.type)
        if group and _now() - self._routine_spoken.get(group, float("-inf")) < self._routine_gap():
            return
        if self._policy is None or events != self._events:
            # The policy remembers what it said; a new selection starts fresh.
            self._policy = NotificationPolicy(enabled_events=events)
            self._events = events
        now = _now()
        self._policy.offer(
            {
                "event_type": event.type,
                "status": event.status,
                "data": dict(event.data),
                "amount_auec": event.data.get("amount_auec"),
                "environment": event.environment,
                "generation": event.environment,
            },
            now=now,
            catching_up=event.catching_up,
        )
        self._said_at = {r: t for r, t in self._said_at.items() if now - t < REPEAT_SECONDS}
        reports = []
        for message in self._policy.flush(now=now):
            if message["text"] in self._said_at:
                # Still flickering: stays quiet until it settles for a while.
                self._said_at[message["text"]] = now
            else:
                reports.append(message["text"])
        if not reports:
            return
        self._waiting = (self._waiting + [(now, r, group) for r in reports])[-MAX_WAITING:]
        # One reaction at a time and never over the Wingman's voice. What comes
        # meanwhile waits and goes into the next line while it is still fresh:
        # an arrival logs zone, jurisdiction and place within seconds.
        if self._reaction and not self._reaction.done():
            return
        self._reaction = asyncio.create_task(self._react_to_waiting())

    def _take_fresh(self) -> tuple[list[str], set[str]]:
        """The reports still worth a word, and the routine groups among them."""
        now = _now()
        fresh = [(r, g) for t, r, g in self._waiting if now - t < FOLD_SECONDS]
        self._waiting.clear()
        reports = list(dict.fromkeys(r for r, _ in fresh))[:MAX_REPORTS]
        groups = {g for r, g in fresh if g and r in reports}
        return reports, groups

    def _should_wait(self) -> bool:
        """A voice is playing, or the user is talking to a wingman: holding a
        push-to-talk key, just heard, or a turn runs. A line over a held key
        ends up in the user's own transcript. Radio chatter does not count:
        an event talks over it."""
        return (
            self.wingman.audio.is_playing_at_least(SpeechPriority.EVENT)
            or self.wingman.conversation.user_busy
        )

    async def _react_to_waiting(self) -> None:
        while self._waiting:
            while self._should_wait() and any(
                _now() - t < FOLD_SECONDS for t, _, _ in self._waiting
            ):
                await asyncio.sleep(0.25)
            reports, groups = self._take_fresh()
            if not reports:
                return
            limit = self._max_unanswered()
            if limit and self._unanswered >= limit:
                return
            await self._react(reports, groups)

    async def _react(self, reports: list[str], groups: set[str] = frozenset()) -> bool:
        """Say one line about the reports. True when it was said."""
        try:
            line = await self._phrase(reports)
            if not line:
                return False
            if self._should_wait():
                # The user started talking, or a wingman did, while the line
                # was written. Said afterwards it would be late and in the way.
                return False
            # Only what is said counts, and is not said again soon.
            now = _now()
            self._unanswered += 1
            for report in reports:
                self._said_at[report] = now
            for group in groups:
                self._routine_spoken[group] = now
            self._recent_lines.append(line)
            self._unnoted = (self._unnoted + [line])[-RECENT_LINES:]
            await self.wingman.conversation.show(
                line, skill_name=self.config.display_name
            )
            if self._show_in_hud():
                await self.wingman.hud.show_message(
                    self.wingman.name, line, duration=15
                )
            # Waits again if an answer started meanwhile, and is said after it.
            await self.wingman.tts.speak(line, priority=SpeechPriority.EVENT)
            return True
        except asyncio.CancelledError:
            raise
        except Exception as error:  # The model may be down; the game goes on.
            self.log.warning(f"No reaction: {error}", server_only=True)
            return False

    async def _phrase(self, reports: list[str]) -> str:
        language = self.wingman.language.name
        self._angle = random.choice([a for a in ANGLES if a != self._angle])
        system = PROMPT_FILE.read_text(encoding="utf-8").format(
            name=self.wingman.name,
            # Whole: the client already holds it to 2048 tokens.
            backstory=self.wingman.config.prompts.backstory or "",
            language=language,
        )
        parts = []
        # Only for this angle: given every time, the place and the ship end up
        # in every line.
        state = self.wingman.sc_gamelog.state() if self._angle == LINK_ANGLE else None
        if state:
            parts.append("Situation:\n" + self._situation(state))
        if self._recent_lines:
            parts.append(
                "Your last lines:\n" + "\n".join(f"- {line}" for line in self._recent_lines)
            )
        parts.append("Game log report:\n" + "\n".join(f"- {report}" for report in reports))
        # Repeating the language right before the answer keeps a small model
        # from falling back to English (measured for the filler lines).
        # The angle goes right before the answer, not into the system prompt: a
        # long backstory with its own "always end with a jab" rules outweighs it
        # there, and a system prompt that stays the same can be cached.
        text = "\n\n".join(parts) + f"\n\nThis time: {self._angle}\nYour sentence, in {language}:"
        if self.wingman.local_ai.available:
            line = await self.wingman.local_ai.generate(
                text, system=system, preset=SamplingPreset.CREATIVE
            )
        else:
            line = await self.wingman.ai.generate(text, system=system)
        return line.strip().strip('"').strip()[:REACTION_CHARS]

    @classmethod
    def _situation(cls, state: dict) -> str:
        """The overview without the timestamp and the mission count: where the
        pilot is, the ship, zones, injuries."""
        lines = cls._overview(state).splitlines()[1:]
        return "\n".join(line for line in lines if not line.startswith("Active missions"))

    # --- answering questions ------------------------------------------------------

    @tool(
        description=(
            "What the Star Citizen game log says right now: where the pilot is, "
            "the ship, zones and injuries (overview), the active missions, or the "
            "latest events."
        )
    )
    async def star_citizen_status(
        self, topic: Literal["overview", "missions", "recent_events"] = "overview"
    ) -> str:
        """Args:
        topic: overview, missions or recent_events.
        """
        log = self.wingman.sc_gamelog
        if not log.available:
            return "The Star Citizen log reader is switched off in the settings."
        if topic == "recent_events":
            return self._recent_events()
        state = log.state()
        if state is None:
            return "Nothing from Star Citizen yet. The game has not written a log this session."
        if topic == "missions":
            return self._missions(state)
        return self._overview(state)

    # Everything below comes from the game log, so it goes through _literal
    # (bounded, no markup) like the reactions do.

    @staticmethod
    def _overview(state: dict) -> str:
        lines = [f"As last logged ({state.get('last_source_timestamp') or 'time unknown'}):"]
        if state.get("player_name"):
            lines.append(f"Player: {_literal(state['player_name'])}")
        place = _literal(state.get("location_name"))
        if place:
            where = "Left" if state.get("location_status") == "departed" else "At"
            lines.append(f"{where}: {place}" + (f" ({_literal(state['system'])})" if state.get("system") else ""))
        elif state.get("system"):
            lines.append(f"System: {_literal(state['system'])}")
        if state.get("aboard_ship") and state.get("ship"):
            lines.append(f"Aboard: {_literal(state['ship'])}")
        zones = [
            label
            for key, label in (
                ("armistice", "armistice zone"),
                ("restricted", "restricted area"),
                ("monitored", "monitored space"),
            )
            if state.get(key)
        ]
        if zones:
            lines.append("In: " + ", ".join(zones))
        if state.get("jurisdiction"):
            lines.append(f"Jurisdiction: {_literal(state['jurisdiction'])}")
        injuries = state.get("injuries") or {}
        if injuries:
            lines.append(
                "Injuries: "
                + ", ".join(f"{_literal(part)} ({_literal(info.get('severity'))})" for part, info in injuries.items())
            )
        lines.append(f"Active missions: {len(state.get('active_missions') or {})}")
        return "\n".join(lines)

    @staticmethod
    def _missions(state: dict) -> str:
        missions = list((state.get("active_missions") or {}).values())
        if not missions:
            return "No active missions in the log. The log only knows missions accepted this session."
        lines = []
        for mission in missions[:10]:
            objectives = mission.get("objectives") or (
                [mission["objective"]] if mission.get("objective") else []
            )
            shown = "; ".join(_literal(o) for o in objectives[:6])
            if len(objectives) > 6:
                shown += f"; (and {len(objectives) - 6} more)"
            lines.append(f"- {_literal(mission.get('name')) or 'Unnamed'}" + (f": {shown}" if shown else ""))
        more = f"\n(and {len(missions) - 10} more)" if len(missions) > 10 else ""
        return "Active missions:\n" + "\n".join(lines) + more

    def _recent_events(self) -> str:
        events = [e for e in self.wingman.sc_gamelog.recent(30) if e.type in _TEMPLATES][:8]
        if not events:
            return "No recent events in the Star Citizen log."
        lines = []
        for event in events:
            wording = _TEMPLATES[event.type][1]
            detail = next(
                (value for field in _DETAIL_FIELDS[event.type] if (value := _literal(event.data.get(field)))),
                "",
            )
            when = event.time.strftime("%H:%M") if event.time else "?"
            lines.append(f"- {when} {wording}" + (f": {detail}" if detail else ""))
        return "Latest events, newest first (UTC):\n" + "\n".join(lines)
