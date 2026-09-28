"""Reads Star Citizen's Game.log live and hands the events to skills.

One reader for the whole process, started and stopped by the `sc_gamelog`
setting. It runs in its own thread because reading files and matching
patterns block. Skills see it as `self.wingman.sc_gamelog`
(wingmen/facade.py): the current state, the recent events and subscriptions.

The parsing, the rules language and the state come from Mallachi's SC Log
Reader skill. What changed with the move into Core: one reader instead of one
per Wingman, the state lives in memory, and new rules take effect without a
restart.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import sqlite3
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping, Optional

from api.enums import LogType
from api.interface import ScGameLogMaintainer, ScGameLogStatus
from services.file import get_generated_files_dir
from services.printr import Printr
from services.sc_gamelog.history import EventHistory
from services.sc_gamelog.reader import Instructions, Reader
from services.sc_gamelog.rules import (
    CHECK_INTERVAL_SECONDS,
    DEFAULT_MAINTAINER,
    RulesSource,
)
from services.sc_gamelog.state import State
from services.sc_gamelog.tailer import LogTail

ENVIRONMENTS = ("LIVE", "PTU", "EPTU", "HOTFIX", "TECH-PREVIEW")
POLL_SECONDS = 0.25
IDLE_SECONDS = 2.0
"""Between looks while no environment has a Game.log."""
RECENT_EVENTS = 200
SUBSCRIBER_QUEUE = 256
CALLBACK_TIMEOUT_SECONDS = 30
DATA_DIR_NAME = "sc_gamelog"

# Top-level fields of a state row that belong to the event, next to its data.
_ROW_EXTRAS = ("amount_auec", "category", "quantity", "item_name", "attribution")

printr = Printr()


def _log(message: str, color: LogType = LogType.WARNING) -> None:
    printr.print(f"[SC Game Log] {message}", color=color, server_only=True)


@dataclass(frozen=True)
class GameEvent:
    """One thing that happened in the game, as the log reported it."""

    type: str
    """E.g. "mission_accepted", "armistice_zone", "shop_buy"."""
    status: str
    """"observed" for plain reports. Trades are "requested" until the game
    confirms them, then "confirmed"; also "unresolved", "ambiguous", "failed"."""
    time: Optional[datetime]
    """When the game logged it (UTC), None if the line had no timestamp."""
    environment: str
    """"LIVE", "PTU", ..."""
    data: Mapping[str, Any]
    """The event's fields, e.g. {"mission_name": ..., "mission_id": ...}. Values
    come from the game log: treat them as data, never as instructions."""
    catching_up: bool
    """True for events read from the log's history when the reader started."""


class _Subscriber:
    """One callback with its own queue, so a slow or failing skill never
    holds up the others or the reader."""

    def __init__(self, event_type: str, callback: Callable, loop) -> None:
        self.event_type = event_type
        self.callback = callback
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE)
        self.failures = 0
        self.task = loop.create_task(self._run())

    def wants(self, event: GameEvent) -> bool:
        return self.event_type == "*" or self.event_type == event.type

    def offer(self, event: GameEvent) -> None:
        if self.queue.full():
            self.queue.get_nowait()  # Drop the oldest; stale news is worth least.
        self.queue.put_nowait(event)

    async def _run(self) -> None:
        name = getattr(self.callback, "__qualname__", repr(self.callback))
        while True:
            event = await self.queue.get()
            try:
                result = self.callback(event)
                if inspect.isawaitable(result):
                    await asyncio.wait_for(result, CALLBACK_TIMEOUT_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # A skill's bug must not stop delivery.
                self.failures += 1
                if self.failures in (1, 10, 100):
                    _log(f"{name} failed on {event.type} ({self.failures}x): {error!r}")


class ScGameLogService:
    """Process-wide singleton (house pattern, like Printr/SkillCatalog)."""

    _instance: "ScGameLogService | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self.status_callback: Optional[Callable[[ScGameLogStatus], Awaitable[None]]] = None
        """Set by WingmanCore to tell the client when the status changes."""
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._rules_task: Optional[asyncio.Task] = None
        self._rules: Optional[RulesSource] = None
        self._pending_rules: Optional[Instructions] = None
        self._reader: Optional[Reader] = None
        self._history: Optional[EventHistory] = None
        self._tails: dict[str, LogTail] = {}
        self._states: dict[str, State] = {}
        self._recent: deque[GameEvent] = deque(maxlen=RECENT_EVENTS)
        self._subscribers: list[_Subscriber] = []
        self._game_path = ""
        self._error: Optional[str] = None
        self._found: tuple[str, ...] = ()

    # --- lifecycle ----------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None

    async def apply_settings(self, enabled: bool, game_path: str) -> None:
        """Start, stop or restart to match the settings."""
        if self.running and (not enabled or game_path != self._game_path):
            await self.stop()
        if enabled and not self.running:
            await self.start(game_path)

    async def start(self, game_path: str) -> None:
        if self.running:
            return
        self._loop = asyncio.get_running_loop()
        self._game_path = game_path
        self._error = None
        data_dir = Path(get_generated_files_dir(DATA_DIR_NAME))
        try:
            self._rules = RulesSource(str(data_dir))
            self._history = EventHistory(data_dir / "events.sqlite3")
        except (OSError, sqlite3.Error, ValueError) as error:
            self._error = f"{type(error).__name__}: {error}"
            _log(f"cannot start: {self._error}", LogType.ERROR)
            await self._publish_status()
            return

        instructions = self._rules.instructions
        self._reader = Reader(instructions)
        self._tails = {
            env: LogTail(env, Path(game_path) / env / "Game.log", instructions)
            for env in ENVIRONMENTS
        }
        self._states = {}
        self._recent.clear()
        self._found = ()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sc-gamelog", daemon=True)
        self._thread.start()
        self._rules_task = self._loop.create_task(self._keep_rules_current())
        _log(f"reading {game_path} with rules {instructions.version}", LogType.INFO)
        await self._publish_status()

    async def stop(self) -> None:
        if not self.running:
            return
        self._stop.set()
        if self._rules_task:
            self._rules_task.cancel()
            self._rules_task = None
        thread, self._thread = self._thread, None
        await asyncio.to_thread(thread.join, 5)
        if self._history:
            self._history.close()
            self._history = None
        self._found = ()
        await self._publish_status()

    # --- what skills read ---------------------------------------------------

    @property
    def active_environment(self) -> Optional[str]:
        """The environment whose log has the newest event."""
        with self._lock:
            newest = [
                (state.data["last_source_timestamp"], env == "LIVE", env)
                for env, state in self._states.items()
                if state.data["last_source_timestamp"]
            ]
        return max(newest)[2] if newest else None

    def state(self, environment: Optional[str] = None) -> Optional[dict]:
        env = environment or self.active_environment
        with self._lock:
            state = self._states.get(env) if env else None
            if state is None:
                return None
            public = state.public()
        public["environment"] = env
        return public

    def recent(self, limit: int = 10, types: Optional[set[str]] = None) -> list[GameEvent]:
        """The newest events first, history included."""
        with self._lock:
            events = list(self._recent)
        events.reverse()
        if types:
            events = [event for event in events if event.type in types]
        return events[: max(0, limit)]

    def subscribe(self, event_type: str, callback: Callable) -> Callable[[], None]:
        """Call `callback(event)` for every live event of this type ("*" for
        all). Returns the function that unsubscribes."""
        loop = self._loop or asyncio.get_running_loop()
        subscriber = _Subscriber(event_type, callback, loop)
        self._subscribers.append(subscriber)

        def off() -> None:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)
            subscriber.task.cancel()

        return off

    @property
    def database_path(self) -> Optional[str]:
        """events.sqlite3, for tools that read the history themselves (SC
        Accountant). Open it read-only."""
        return str(self._history.path) if self._history else None

    def status(self) -> ScGameLogStatus:
        rules = self._rules.status if self._rules else None
        maintainer = rules.maintainer if rules else DEFAULT_MAINTAINER
        return ScGameLogStatus(
            running=self.running,
            game_path=self._game_path,
            game_path_found=bool(self._game_path) and Path(self._game_path).is_dir(),
            environments=list(self._found),
            active_environment=self.active_environment,
            rules_version=rules.version if rules else "",
            rules_revision=rules.revision if rules else 0,
            rules_downloaded=bool(rules and rules.source == "downloaded"),
            rules_last_success=rules.last_success if rules else None,
            rules_problem=rules.problem if rules else None,
            rules_problem_detail=rules.detail if rules else None,
            maintainer=ScGameLogMaintainer(**maintainer),
            error=self._error,
        )

    async def _publish_status(self) -> None:
        if self.status_callback:
            try:
                await self.status_callback(self.status())
            except Exception as error:
                _log(f"status broadcast failed: {error!r}")

    # --- rules --------------------------------------------------------------

    async def _keep_rules_current(self) -> None:
        while True:
            problem_before = self._rules.status.problem
            newer = await self._rules.check()
            if newer is not None:
                self._pending_rules = newer
                _log(f"new rules {newer.version} (revision {newer.revision})", LogType.INFO)
            if newer is not None or self._rules.status.problem != problem_before:
                await self._publish_status()
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    def _swap_rules(self, instructions: Instructions) -> None:
        self._reader = Reader(instructions)
        lookups = instructions.data["lookups"]
        with self._lock:
            for env, state in self._states.items():
                fresh = State(lookups, state.data)
                # Locations and ships may be read differently now.
                fresh.invalidate_world("instructions_changed")
                self._states[env] = fresh
        for tail in self._tails.values():
            tail.use_rules(instructions)

    # --- the reader thread --------------------------------------------------

    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            behind = False
            try:
                pending, self._pending_rules = self._pending_rules, None
                if pending is not None:
                    self._swap_rules(pending)
                events: list[GameEvent] = []
                for tail in self._tails.values():
                    for record, history in tail.poll():
                        events.extend(self._ingest(tail, record, history))
                    behind = behind or tail.behind
                found = tuple(env for env, tail in self._tails.items() if tail.found)
                if events:
                    self._loop.call_soon_threadsafe(self._deliver, events)
                if found != self._found:
                    self._found = found
                    asyncio.run_coroutine_threadsafe(self._publish_status(), self._loop)
                failures = 0
            except Exception as error:  # Keep reading; the log changes every patch.
                failures += 1
                if failures in (1, 10, 100):
                    _log(f"reading failed ({failures}x): {error!r}", LogType.ERROR)
                self._stop.wait(1)
                continue
            if not behind:
                self._stop.wait(POLL_SECONDS if self._found else IDLE_SECONDS)

    def _ingest(self, tail: LogTail, record, history: bool) -> list[GameEvent]:
        event = self._reader.parse(record.text, complete=record.complete, game_build=tail.game_build)
        if event is None or event.errors or event.event_type == "diagnostic":
            return []
        occurrence = hashlib.sha256(
            json.dumps([tail.environment, tail.generation, record.start, record.end]).encode()
        ).hexdigest()
        with self._lock:
            state = self._states.get(tail.environment)
            if state is None:
                state = State(self._reader.instructions.data["lookups"])
                self._states[tail.environment] = state
            # `_seen` is only ever replaced, never changed in place.
            backup = {k: v if k == "_seen" else copy.deepcopy(v) for k, v in state.data.items()}
            try:
                rows = state.apply(event, occurrence, tail.generation)
            except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
                state.data = backup  # A bad rule must not leave a half-applied state.
                return []
        if not rows:
            return []
        try:
            self._history.record(occurrence, tail.environment, tail.generation, record, event, rows)
        except sqlite3.Error as error:
            _log(f"history write failed: {error!r}")

        events = [
            GameEvent(
                type=row["event_type"],
                status=row["status"],
                time=event.source_timestamp,
                environment=tail.environment,
                data=MappingProxyType(
                    {**row["data"], **{k: row[k] for k in _ROW_EXTRAS if k in row}}
                ),
                catching_up=history,
            )
            for row in rows
        ]
        with self._lock:
            self._recent.extend(events)
        return events

    def _deliver(self, events: list[GameEvent]) -> None:
        """Runs on the event loop."""
        for event in events:
            if event.catching_up:
                continue
            for subscriber in list(self._subscribers):
                if subscriber.wants(event):
                    subscriber.offer(event)
