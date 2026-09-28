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
import time
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
HUD_SKILL = "HUD"
BACKSTORY_CHARS = 1200
REACTION_CHARS = 300


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

    # --- settings, read fresh -------------------------------------------------

    def _enabled_categories(self) -> frozenset[str]:
        return frozenset(
            category
            for category in CATEGORIES
            if self.retrieve_custom_property_value(f"react_{category}", [])
        )

    def _max_unanswered(self) -> int:
        value = self.retrieve_custom_property_value("max_unanswered", [])
        return int(value) if value else 10

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
                "data": dict(event.data),
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
        # One reaction at a time. What happens meanwhile is not queued: by the
        # time the Wingman is done talking it would be old news.
        if self._reaction and not self._reaction.done():
            return
        if self._unanswered >= self._max_unanswered():
            return
        self._unanswered += 1
        self._reaction = asyncio.create_task(self._react(reports[:3]))

    async def _react(self, reports: list[str]) -> None:
        try:
            line = await self._phrase(reports)
        except Exception as error:  # The model may be down; the game goes on.
            self.log.warning(f"No reaction: {error}", server_only=True)
            return
        if not line:
            return
        await self.wingman.conversation.show(line, skill_name=self.config.display_name)
        if self._remember():
            await self.wingman.conversation.add_assistant(line)
        # The HUD skill already shows every line that goes into the history.
        hud_skill_shows_it = self._remember() and self.wingman.skills.has(HUD_SKILL)
        if self._show_in_hud() and not hud_skill_shows_it:
            await self.wingman.hud.show_message(self.wingman.name, line, duration=15)
        await self.wingman.tts.speak(line, interrupt=False)

    async def _phrase(self, reports: list[str]) -> str:
        language = self.wingman.language.name
        system = PROMPT_FILE.read_text(encoding="utf-8").format(
            name=self.wingman.name,
            backstory=(self.wingman.config.prompts.backstory or "")[:BACKSTORY_CHARS],
            language=language,
        )
        # Repeating the language right before the answer keeps a small model
        # from falling back to English (measured for the filler lines).
        text = (
            "Game log report:\n"
            + "\n".join(f"- {report}" for report in reports)
            + f"\n\nYour sentence, in {language}:"
        )
        if self.wingman.local_ai.available:
            line = await self.wingman.local_ai.generate(
                text, system=system, preset=SamplingPreset.CREATIVE
            )
        else:
            line = await self.wingman.ai.generate(text, system=system)
        return line.strip().strip('"').strip()[:REACTION_CHARS]

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

    @staticmethod
    def _overview(state: dict) -> str:
        lines = [f"As last logged ({state.get('last_source_timestamp') or 'time unknown'}):"]
        if state.get("player_name"):
            lines.append(f"Player: {state['player_name']}")
        place = state.get("location_name")
        if place:
            where = "Left" if state.get("location_status") == "departed" else "At"
            lines.append(f"{where}: {place}" + (f" ({state['system']})" if state.get("system") else ""))
        elif state.get("system"):
            lines.append(f"System: {state['system']}")
        if state.get("aboard_ship") and state.get("ship"):
            lines.append(f"Aboard: {state['ship']}")
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
            lines.append(f"Jurisdiction: {state['jurisdiction']}")
        injuries = state.get("injuries") or {}
        if injuries:
            lines.append(
                "Injuries: "
                + ", ".join(f"{part} ({info.get('severity')})" for part, info in injuries.items())
            )
        lines.append(f"Active missions: {len(state.get('active_missions') or {})}")
        return "\n".join(lines)

    @staticmethod
    def _missions(state: dict) -> str:
        missions = list((state.get("active_missions") or {}).values())
        if not missions:
            return "No active missions in the log. The log only knows missions accepted this session."
        lines = [
            f"- {mission.get('name') or 'Unnamed'}"
            + (f": {mission['objective']}" if mission.get("objective") else "")
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
                (value for field in _DETAIL_FIELDS[event.type] if (value := _literal(event.data.get(field)))),
                "",
            )
            when = event.time.strftime("%H:%M") if event.time else "?"
            lines.append(f"- {when} {wording}" + (f": {detail}" if detail else ""))
        return "Latest events, newest first (UTC):\n" + "\n".join(lines)
