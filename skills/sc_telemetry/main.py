"""Star Citizen Telemetry: reads the game's built-in local telemetry stream, reacts to what happens to the ship
and the pilot, answers questions about them, and serves the data to other skills (NavPoint).

Layers (log reader terminology): Reader = reader.py (gRPC stream, own thread); Handler = handler.py (state, quirks,
events); Orchestrator = this file (settings, the enable switch, reactions, tools, feed). Reactions work like
sc_game_events: the line from the support model in character and in the user's language, one line at a time, never
over the user. Every reaction is on; "Enable Proactive Notifications" mutes them all.
"""
from __future__ import annotations

import asyncio
import json
import random
import threading
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

from api.enums import SpeechPriority
from api.interface import SettingsConfig, SkillConfig
from services.skill_local_ai import SamplingPreset
from skills.sc_telemetry import describe, enable, health
from skills.sc_telemetry.events import BY_ID
from skills.sc_telemetry.feed import Feed
from skills.sc_telemetry.handler import Handler, TelemetryEvent, Thresholds
from skills.sc_telemetry.reader import TelemetryReader
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext

PROMPT_FILE = Path(__file__).parent / "reaction_prompt.md"
ENABLE_APPLIED_FILE = "enable_applied.json"
SETTINGS_EVERY_S = 5
THRESHOLDS_EVERY_S = 2.0
STATE_WRITE_EVERY_S = 0.1
FRAME_STALE_S = 3.0
"""No frame for this long on an open stream: the player is in a menu or loading, so don't describe old data."""
ERROR_LOG_EVERY_S = 30.0
REACTION_CHARS = 300
RECENT_LINES = 5
FOLD_SECONDS = 15.0
"""A report from while the Wingman was busy is still worth a word this long."""
MAX_REPORTS = 4
MAX_WAITING = 16
RESTART_LAUNCHER = ("Quit the RSI Launcher completely (also from the tray) and start it again, "
                    "then start Star Citizen from it.")
ANGLES = (
    "Just report it, plainly, in your own words. No joke.",
    "Give one short practical tip that fits this moment.",
    "Say how you feel about it, in your own voice.",
    "Make a dry remark, if your character would.",
    "Keep it very short, a few words over the comms.",
)


class SC_Telemetry(Skill):
    def __init__(self, config: SkillConfig, settings: SettingsConfig, wingman: WingmanContext) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._reader: TelemetryReader | None = None
        self._handler = Handler()
        self._feed: Feed | None = None
        self._lock = threading.Lock()
        self._state: dict = {}
        self._reader_status = "stopped"
        self._run_id = 0
        self._last_state_write = 0.0
        self._thresholds = Thresholds()
        self._thresholds_at = 0.0
        self._reaction: asyncio.Task | None = None
        self._waiting: list[tuple[float, str]] = []
        self._unanswered = 0
        self._recent_lines: deque[str] = deque(maxlen=RECENT_LINES)
        self._unnoted: list[str] = []
        self._angle = ""
        self._prompt = ""
        self._last_frame_at = 0.0
        self._errors_logged_at: dict[str, float] = {}
        self._enable_applied: bool | None = None
        self._enable_record_read = False

    # --- settings, read fresh -------------------------------------------------------------------------------

    def _setting(self, key: str, default: Any) -> Any:
        value = self.retrieve_custom_property_value(key, [])
        return default if value is None else value

    def _number(self, key: str, default: float) -> float:
        try:
            return float(self._setting(key, default))
        except (TypeError, ValueError):
            return default

    def _event_enabled(self, event_id: str) -> bool:
        # Every reaction is on; the only switch is the master (user, 2026-10-29: show just the two main settings).
        return event_id in BY_ID and bool(self._setting("proactive_notifications", True))

    def _current_thresholds(self) -> Thresholds:
        """Read every few seconds, not on all ~17 frames a second."""
        now = time.monotonic()
        if now - self._thresholds_at >= THRESHOLDS_EVERY_S:
            self._thresholds_at = now
            self._thresholds = Thresholds(
                health_low=self._number("health_low_percent", 30) / 100,
                oxygen_low=self._number("oxygen_low_percent", 20) / 100,
                hunger_low=self._number("hunger_thirst_low_percent", 25) / 100,
                thirst_low=self._number("hunger_thirst_low_percent", 25) / 100,
                countermeasure_bursts=int(self._number("countermeasure_low_bursts", 3)),
                hydrogen_low=self._number("hydrogen_low_percent", 15) / 100,
            )
        return self._thresholds

    # --- lifecycle --------------------------------------------------------------------------------------------

    async def prepare(self) -> None:
        await super().prepare()
        self._loop = asyncio.get_running_loop()
        self._prompt = await asyncio.to_thread(PROMPT_FILE.read_text, encoding="utf-8")
        generated = Path(self.get_generated_files_dir())
        try:
            self._feed = await asyncio.to_thread(Feed, generated / "feed")
        except Exception as error:  # noqa: BLE001 - no feed for other skills, but reactions and tools still work
            self.log.warning(f"SC telemetry: feed for other skills unavailable: {error}", server_only=True)
        try:
            await asyncio.to_thread(self._apply_enable_setting)
        except Exception as error:  # noqa: BLE001 - the reader must start anyway; the settings loop retries
            self.log.warning(f"SC telemetry: could not apply the telemetry switch: {error}", server_only=True)
        self._reader = TelemetryReader(self._on_frame_thread, self._on_status_thread,
                                       on_error=self._log_error_thread)
        self._reader.start()
        self._run_id += 1
        self.wingman.run_in_thread(self._settings_loop, self._run_id)

    async def unload(self) -> None:
        self._run_id += 1  # the settings loop checks this and stops
        if self._reader is not None:
            await asyncio.to_thread(self._reader.stop)
            self._reader = None
        if self._reaction and not self._reaction.done():
            self._reaction.cancel()
        self._waiting.clear()
        feed, self._feed = self._feed, None  # the reader thread sees None before the feed closes
        if feed is not None:
            feed.close()
        await super().unload()

    async def _settings_loop(self, run_id: int) -> None:
        """The enable switch can be changed in the UI while the skill runs."""
        while run_id == self._run_id:
            try:
                await asyncio.to_thread(self._apply_enable_setting)
            except Exception as error:  # noqa: BLE001 - the loop must survive anything
                self.log.warning(f"SC telemetry: settings check failed: {error}", server_only=True)
            await asyncio.sleep(SETTINGS_EVERY_S)

    def _apply_enable_setting(self) -> None:
        """Set or remove the Windows user variable, but only when the user changed the setting.

        The last applied value is remembered, so a variable the user set by hand is never removed just because the
        setting still has its default (off)."""
        if not enable.MANAGED:  # not Windows: the user sets the variable in their launcher (enable.py)
            return
        wanted = bool(self._setting("enable_telemetry", False))
        record = Path(self.get_generated_files_dir()) / ENABLE_APPLIED_FILE
        if not self._enable_record_read:
            self._enable_record_read = True
            try:
                saved = json.loads(record.read_text(encoding="utf-8"))
                self._enable_applied = saved.get("enabled") if isinstance(saved, dict) else None
            except (OSError, ValueError):
                self._enable_applied = None
        if self._enable_applied == wanted or (self._enable_applied is None and not wanted):
            return
        if enable.is_enabled() != wanted:  # a value the user already set by hand (e.g. "1") stays as it is
            enable.set_enabled(wanted)
        # Remembered in memory first: if the record can't be written, this is still not repeated every 5 s.
        self._enable_applied = wanted
        try:
            record.write_text(json.dumps({"enabled": wanted}), encoding="utf-8")
        except OSError as error:
            self.log.warning(f"SC telemetry: could not save the switch state: {error}", server_only=True)
        if wanted:
            self.log.info(f"Star Citizen telemetry is switched on. {RESTART_LAUNCHER}")
        else:
            self.log.info("Star Citizen telemetry is switched off. It stops after the RSI Launcher restarts.")

    # --- frames (reader thread) -----------------------------------------------------------------------------

    def _on_status_thread(self, status: str) -> None:
        self._reader_status = status
        self.log.info(f"SC telemetry: {status}", server_only=True)

    def _log_error_thread(self, message: str) -> None:
        """At most one line per kind of problem every ERROR_LOG_EVERY_S: a fault can repeat 17 times a second."""
        kind = message.split(":", 1)[0]
        now = time.monotonic()
        if now - self._errors_logged_at.get(kind, -ERROR_LOG_EVERY_S) >= ERROR_LOG_EVERY_S:
            self._errors_logged_at[kind] = now
            self.log.warning(f"SC telemetry: {message}", server_only=True)

    def _on_frame_thread(self, frame: dict, t: float) -> None:
        with self._lock:
            events = self._handler.update(frame, t, self._current_thresholds())
            unfiltered = self._handler.last_unfiltered
            self._state = self._handler.state
            self._last_frame_at = time.monotonic()
            state = self._state
        # Reactions first: a busy feed file must never cost the Wingman an event.
        if events and self._loop is not None:
            self._loop.call_soon_threadsafe(self._offer, events)
        feed = self._feed
        if feed is None:
            return
        try:
            if t - self._last_state_write >= STATE_WRITE_EVERY_S:
                self._last_state_write = t
                feed.write_state(state, self._reader_status)
        except Exception as error:  # noqa: BLE001 - e.g. a consumer has the file open; the next frame retries
            self._log_error_thread(f"state file: {error}")
        for event in unfiltered:
            try:
                feed.add_event(event.id, event.group, event.t, event.data)
            except Exception as error:  # noqa: BLE001 - one lost feed row, not a lost stream
                self._log_error_thread(f"event feed: {error}")

    # --- reacting (event loop) --------------------------------------------------------------------------------

    def _offer(self, events: list[TelemetryEvent]) -> None:
        reports = [event.text for event in events if self._event_enabled(event.id)]
        if not reports:
            return
        now = time.monotonic()
        self._waiting = (self._waiting + [(now, report) for report in reports])[-MAX_WAITING:]
        if self._reaction and not self._reaction.done():
            return
        self._reaction = asyncio.create_task(self._react_to_waiting())

    def _should_wait(self) -> bool:
        return self.wingman.audio.is_playing_at_least(SpeechPriority.EVENT) or self.wingman.conversation.user_busy

    async def _react_to_waiting(self) -> None:
        while self._waiting:
            while self._should_wait() and any(time.monotonic() - t < FOLD_SECONDS for t, _ in self._waiting):
                await asyncio.sleep(0.25)
            now = time.monotonic()
            reports = list(dict.fromkeys(r for t, r in self._waiting if now - t < FOLD_SECONDS))[:MAX_REPORTS]
            self._waiting.clear()
            if not reports:
                return
            limit = int(self._number("max_unanswered", 10))
            if limit and self._unanswered >= limit:
                return
            await self._react(reports)

    async def _react(self, reports: list[str]) -> None:
        try:
            line = await self._phrase(reports)
            if not line or self._should_wait():
                return
            self._unanswered += 1
            self._recent_lines.append(line)
            self._unnoted = (self._unnoted + [line])[-RECENT_LINES:]
            await self.wingman.conversation.show(line, skill_name=self.config.display_name)
            if bool(self._setting("show_in_hud", True)):
                await self.wingman.hud.show_message(self.wingman.name, line, duration=15)
            await self.wingman.tts.speak(line, priority=SpeechPriority.EVENT)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - the model may be down; the game goes on
            self.log.warning(f"SC telemetry: no reaction: {error}", server_only=True)

    async def _phrase(self, reports: list[str]) -> str:
        language = self.wingman.language.name
        self._angle = random.choice([a for a in ANGLES if a != self._angle])
        system = self._prompt.format(
            name=self.wingman.name, backstory=self.wingman.config.prompts.backstory or "", language=language)
        parts = []
        if self._recent_lines:
            parts.append("Your last lines:\n" + "\n".join(f"- {line}" for line in self._recent_lines))
        parts.append("Telemetry report:\n" + "\n".join(f"- {report}" for report in reports))
        text = "\n\n".join(parts) + f"\n\nThis time: {self._angle}\nYour sentence, in {language}:"
        if self.wingman.local_ai.available:
            line = await self.wingman.local_ai.generate(text, system=system, preset=SamplingPreset.CREATIVE)
        else:
            line = await self.wingman.ai.generate(text, system=system)
        return line.strip().strip('"').strip()[:REACTION_CHARS]

    async def on_add_user_message(self, message: str) -> None:
        self._unanswered = 0
        lines, self._unnoted = self._unnoted, []
        if lines and bool(self._setting("remember_reactions", True)):
            await self.wingman.conversation.add_note(
                "while the user was quiet you said this about the ship on your own, do not say it again: "
                + " / ".join(lines))

    # --- answering questions ------------------------------------------------------------------------------------

    def _game_log(self) -> Path | None:
        try:
            folder = self.wingman.star_citizen.environment_path("LIVE")
        except AttributeError:  # an older Wingman without the star_citizen facade
            return None
        return Path(folder) / "Game.log" if folder else None

    def _health_line(self) -> str:
        status = self._reader_status
        if status in ("live", "connected", "no_grpc"):
            return health.MESSAGES[status]
        log = self._game_log()
        registered = health.game_log_registered(log) if log else None
        return health.MESSAGES[health.overall(status, enable.is_enabled(), registered)]

    def _snapshot(self) -> dict | None:
        """The current state, or None when it is not live or no frame came for FRAME_STALE_S."""
        with self._lock:
            fresh = time.monotonic() - self._last_frame_at < FRAME_STALE_S
            return self._state if self._reader_status == "live" and fresh else None

    async def _answer(self, summary) -> str:
        state = self._snapshot()
        if state is None:
            if self._reader_status == "live":  # stream open, but no frames: menus or loading
                return health.MESSAGES["connected"]
            return await asyncio.to_thread(self._health_line)
        return summary(state)

    @tool(description="Live Star Citizen telemetry of the ship the player sits in: speed, altitude, heading, "
                      "flight modes, power, warning lights, weapons and countermeasures.")
    async def get_ship_status(self, **kwargs: Any) -> str:
        return await self._answer(describe.ship_summary)

    @tool(description="Live Star Citizen telemetry of the player: health, hunger, thirst, oxygen, heart rate, "
                      "surroundings and UEC balance. Also says whether telemetry works and how to switch it on.")
    async def get_player_status(self, **kwargs: Any) -> str:
        return await self._answer(describe.player_summary)
