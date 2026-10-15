"""Star Citizen Events: the Wingman reacts to what happens in the game.

This skill is also the example for reading the game log from a skill. Core
reads Star Citizen's Game.log (services/sc_gamelog) and every skill gets the
events through `self.wingman.sc_gamelog`:

    self._subscription = self.wingman.sc_gamelog.on("*", self._on_event)
    ...
    self._subscription.unsubscribe()    # in unload()

Which events are worth a word, and how often, decides the policy Mallachi wrote
for the SC Log Reader skill (notifications.py). The line itself comes from the
support model, in character and in the user's language, and is shown in the
chat and the HUD, spoken and kept in the conversation.
"""

import asyncio
import re
import random
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from api.interface import SettingsConfig, SkillConfig
from services.skill_local_ai import SamplingPreset
from skills.sc_game_events.notifications import (
    _DETAIL_FIELDS,
    _TEMPLATES,
    NotificationPolicy,
    _literal,
)
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext

CATEGORIES = ("session", "mission", "safety", "health", "location", "ship", "money")
PROMPT_FILE = Path(__file__).parent / "reaction_prompt.md"
REACTION_CHARS = 300
RECENT_LINES = 5
# Events that happen many times in every session: zones, arrivals, the
# hangar, the login. Each group gets one spoken line per ROUTINE_GAP_S; one
# hour of play had 20 lines about armistice zones and monitored space alone.
# Missions, money, injuries and warnings are not in here and always count.
ROUTINE_GROUPS = {
    "armistice_zone": "zone",
    "restricted_area": "zone",
    "entered_monitored_space": "zone",
    "exited_monitored_space": "zone",
    "jurisdiction_change": "zone",
    "location_arrived": "travel",
    "location_departed": "travel",
    "location_change": "travel",
    "qt_arrived": "travel",
    "quantum_route_set": "travel",
    "quantum_calibration_started": "travel",
    "quantum_calibration_complete": "travel",
    "hangar_ready": "hangar",
    "hangar_queue": "hangar",
    "ship_entered": "hangar",
    "ship_exited": "hangar",
    "user_login": "session",
    "session_start": "session",
    "join_pu": "session",
}
ROUTINE_GAP_S = 600.0
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


_ITEM_CODE = re.compile(r"^(?:[A-Z0-9]{2,5}|S\d{1,2})$")


def readable_item_name(raw) -> str:
    """The name in a game item's class: "COOL_WCPR_S02_Aufeis_SCItem" is
    "Aufeis", "KLWE_LaserRepeater_S3" is "Laser Repeater". The log only has
    the class, and read out as it is the class sounds like a serial number.
    Type and maker codes are short capitals, sizes are S and a number; what
    is left is the name. A name that is all codes stays as it was."""
    if not isinstance(raw, str) or "_" not in raw:
        return raw
    parts = [p for p in raw.split("_") if p and p.lower() != "scitem"]
    words = [p for p in parts if not _ITEM_CODE.match(p)]
    if not words:
        return raw
    return " ".join(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", word) for word in words)


class ScGameEvents(Skill):
    def __init__(
        self, config: SkillConfig, settings: SettingsConfig, wingman: "WingmanContext"
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        self._subscription = None
        self._policy: NotificationPolicy | None = None
        self._categories: frozenset[str] = frozenset()
        self._reaction: asyncio.Task | None = None
        self._unanswered = 0
        """Reactions since the user last said something."""
        self._recent_lines: deque[str] = deque(maxlen=RECENT_LINES)
        self._angle = ""
        # When each routine group was last spoken about, monotonic.
        self._routine_spoken: dict[str, float] = {}
        # Said since the user last spoke; goes into the history as a note
        # right before the user's next message.
        self._unnoted: list[str] = []

    # --- settings, read fresh -------------------------------------------------

    def _enabled_categories(self) -> frozenset[str]:
        return frozenset(
            category
            for category in CATEGORIES
            if self.retrieve_custom_property_value(f"react_{category}", [])
        )

    def _max_unanswered(self) -> int:
        """0 means no limit."""
        value = self.retrieve_custom_property_value("max_unanswered", [])
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 10

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
        categories = self._enabled_categories()
        if not categories:
            return
        if self._policy is None or categories != self._categories:
            # The policy remembers what it said; a new selection starts fresh.
            self._policy = NotificationPolicy(enabled_categories=categories)
            self._categories = categories
        now = time.monotonic()
        self._policy.offer(
            {
                "event_type": event.type,
                "status": event.status,
                "data": self._readable(event.data),
                "amount_auec": event.data.get("amount_auec"),
                "environment": event.environment,
                "generation": event.environment,
            },
            now=now,
            catching_up=event.catching_up,
        )
        reports = [message["text"] for message in self._policy.flush(now=now)]
        if not reports:
            return
        # One reaction at a time, never over a voice and never while the user
        # talks to a wingman. What happens meanwhile is not queued: by the
        # time the Wingman is free it would be old news. The policy above
        # already thins out bursts.
        if self._reaction and not self._reaction.done():
            return
        if self._should_wait():
            return
        group = ROUTINE_GROUPS.get(event.type)
        if group and now - self._routine_spoken.get(group, float("-inf")) < ROUTINE_GAP_S:
            return
        limit = self._max_unanswered()
        if limit and self._unanswered >= limit:
            return
        self._unanswered += 1
        self._reaction = asyncio.create_task(self._react(reports[:3], group))

    @staticmethod
    def _readable(data) -> dict:
        data = dict(data)
        if "item_name" in data:
            data["item_name"] = readable_item_name(data["item_name"])
        return data

    def _should_wait(self) -> bool:
        return self.wingman.audio.is_playing or self.wingman.conversation.user_busy

    async def _react(self, reports: list[str], group: str | None = None) -> None:
        try:
            line = await self._phrase(reports)
            if not line:
                return
            if self._should_wait():
                # The user started talking, or another wingman did, while the
                # line was written. Said afterwards it would be late and in
                # the way.
                return
            if group:
                self._routine_spoken[group] = time.monotonic()
            self._recent_lines.append(line)
            self._unnoted.append(line)
            del self._unnoted[:-RECENT_LINES]
            await self.wingman.conversation.show(
                line, skill_name=self.config.display_name
            )
            if self._show_in_hud():
                await self.wingman.hud.show_message(
                    self.wingman.name, line, duration=15
                )
            await self.wingman.tts.speak(line, interrupt=False)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # The model may be down; the game goes on.
            self.log.warning(f"No reaction: {error}", server_only=True)

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
        lines = [
            f"- {_literal(mission.get('name')) or 'Unnamed'}"
            + (f": {_literal(mission['objective'])}" if mission.get("objective") else "")
            for mission in missions[:10]
        ]
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
                (
                    value
                    for field in _DETAIL_FIELDS[event.type]
                    if (value := _literal(self._readable(event.data).get(field)))
                ),
                "",
            )
            when = event.time.strftime("%H:%M") if event.time else "?"
            lines.append(f"- {when} {wording}" + (f": {detail}" if detail else ""))
        return "Latest events, newest first (UTC):\n" + "\n".join(lines)
