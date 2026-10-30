"""Reads Star Citizen's own telemetry stream and hands the ship's and the pilot's state to skills.

Star Citizen (4.10.2 and later) runs a local, read-only gRPC server on 127.0.0.1:2942 when the variable
GRPC_CLIENT_SERVER_ENABLED=true is in the game's environment. It streams about 17 frames a second after the player
has spawned: flight instruments, power, the warning lights, weapons, countermeasures and the pilot's vitals.

One reader for the whole process, started and stopped by `settings.sc_telemetry` (and only while the user plays Star
Citizen). It runs in its own thread because the gRPC stream blocks. Skills see it as `self.wingman.sc_telemetry`
(wingmen/facade.py): the current state, the recent events and subscriptions, the same shape as the log reader
(services/sc_gamelog).

The schema, the normalising and the event rules come from Mallachi's Star Citizen Telemetry skill and his field test.
What changed with the move into Core: one stream instead of one per Wingman, the state lives in memory instead of in
files, events are published without cooldowns (the skill that speaks decides how often), and the Windows switch is a
Core setting.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from api.enums import LogType, ScTelemetryState
from api.interface import ScTelemetryStatus
from services.event_subscribers import CALLBACK_TIMEOUT_SECONDS, Subscriber
from services.file import get_generated_files_dir
from services.printr import Printr
from services.sc_telemetry import windows_env
from services.sc_telemetry.events import TelemetryEvent
from services.sc_telemetry.handler import Handler
from services.sc_telemetry.health import GameLogCheck
from services.star_citizen.game_folder import ENVIRONMENTS

FRAME_STALE_S = 3.0
"""No frame for this long on an open stream: the player is in a menu or loading. The state is old then."""
RECENT_EVENTS = 200
MONITOR_S = 1.0
GAME_LOG_CHECK_S = 5.0
FAILED_FRAMES_INCOMPATIBLE = 50
"""This many frames in a row that cannot be read at all: the game sends something the schema does not fit."""
MIN_STATE_INTERVAL_S = 0.2
LOG_EVERY_S = 30.0
DATA_DIR_NAME = "sc_telemetry"
VARIABLE_RECORD = "windows_variable.json"
"""Whether Core set the Windows variable. Core removes only a variable it set itself, never one set by hand."""

printr = Printr()


def _log(message: str, color: LogType = LogType.WARNING) -> None:
    printr.print(f"[SC Telemetry] {message}", color=color, server_only=True)


class _StateSubscriber:
    """Gets the latest state at most once per interval, and None once when telemetry stops being live. Polls the
    frame counter on the event loop, so the reader thread never wakes a skill 17 times a second."""

    def __init__(self, service: "ScTelemetryService", callback: Callable, interval: float, loop) -> None:
        self.service = service
        self.callback = callback
        self.interval = max(MIN_STATE_INTERVAL_S, float(interval))
        self.failures = 0
        self.task = loop.create_task(self._run())

    async def _run(self) -> None:
        name = getattr(self.callback, "__qualname__", repr(self.callback))
        seen = -1
        live = False
        while True:
            await asyncio.sleep(self.interval)
            frames = self.service.frames
            if frames == seen and self.service.live:
                continue
            seen = frames
            state = self.service.state()
            if state is None and not live:
                continue
            live = state is not None
            try:
                result = self.callback(state)
                if inspect.isawaitable(result):
                    await asyncio.wait_for(result, CALLBACK_TIMEOUT_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # A skill's bug must not stop delivery.
                self.failures += 1
                if self.failures in (1, 10, 100):
                    _log(f"{name} failed on a state ({self.failures}x): {error!r}")


class ScTelemetryService:
    """Process-wide singleton (house pattern, like Printr/SkillCatalog)."""

    _instance: "ScTelemetryService | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self.status_callback: Optional[Callable[[ScTelemetryStatus], Awaitable[None]]] = None
        """Set by WingmanCore to tell the client when the status changes."""
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._switching = asyncio.Lock()
        """Settings saved twice in a row must not start a second reader while the first is still stopping."""
        self._lock = threading.Lock()
        self._reader = None
        self._generation = 0
        """Raised on every start and stop. Callbacks of an older reader thread are dropped."""
        self._handler = Handler()
        self._state: Optional[dict] = None
        self._last_frame_at = 0.0
        self._frames = 0
        self._failed_frames = 0
        self._reader_state = ""
        self._detail: Optional[str] = None
        self._unavailable: Optional[str] = None
        self._recent: deque[TelemetryEvent] = deque(maxlen=RECENT_EVENTS)
        self._subscribers: list[Subscriber] = []
        self._state_subscribers: list[_StateSubscriber] = []
        self._monitor_task: Optional[asyncio.Task] = None
        self._game_path = ""
        self._game_log = GameLogCheck()
        self._game_without_telemetry = False
        self._game_checked_at = 0.0
        self._variable_set: Optional[bool] = None
        self._published: Optional[ScTelemetryStatus] = None
        self._publishing: set[asyncio.Future] = set()
        self._logged_at: dict[str, float] = {}
        self._to_dict: Callable[[Any], dict] = lambda message: {}

    # --- lifecycle ----------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._reader is not None

    async def apply_settings(self, enabled: bool, game_path: str) -> None:
        """Start or stop to match the settings, and set the game's switch on Windows."""
        async with self._switching:
            self._game_path = game_path
            await asyncio.to_thread(self._apply_variable, enabled)
            if enabled and not self.running:
                await self._start()
            elif not enabled:
                await self._stop()
                self._unavailable = None
            await self._publish_status(force=True)

    async def stop(self) -> None:
        async with self._switching:
            await self._stop()
            await self._publish_status(force=True)

    async def _start(self) -> None:
        self._loop = asyncio.get_running_loop()
        try:
            from services.sc_telemetry import reader
            from services.sc_telemetry.schema import message_classes, to_dict

            message_classes()
        except Exception as error:  # gRPC or protobuf missing in the build, or a damaged schema file
            self._unavailable = f"{type(error).__name__}: {error}"
            _log(f"cannot read telemetry: {self._unavailable}", LogType.ERROR)
            return
        self._unavailable = None
        self._to_dict = to_dict
        self._generation += 1
        generation = self._generation
        with self._lock:
            self._handler = Handler()
            self._state = None
            self._last_frame_at = 0.0
            self._failed_frames = 0
            self._reader_state = ""
            self._detail = None
        self._reader = reader.TelemetryReader(
            on_message=lambda message: self._on_message(generation, message),
            on_state=lambda state, detail: self._on_reader_state(generation, state, detail),
            on_error=lambda error: self._on_frame_error(generation, error),
            address=reader.ADDRESS,
        )
        self._reader.start()
        self._monitor_task = self._loop.create_task(self._monitor())
        _log(f"waiting for the game on {reader.ADDRESS}", LogType.INFO)

    async def _stop(self) -> None:
        if self._reader is None:
            return
        reader, self._reader = self._reader, None
        self._generation += 1
        if self._monitor_task:
            self._monitor_task.cancel()
            self._monitor_task = None
        if not await asyncio.to_thread(reader.stop):
            _log("the reader thread did not stop in time; what it still reads is ignored")
        with self._lock:
            self._state = None
            self._reader_state = ""
            self._detail = None
        self._game_without_telemetry = False

    # --- what skills read ---------------------------------------------------

    @property
    def frames(self) -> int:
        """Frames read since Core started; a cheap way to see whether anything new came."""
        return self._frames

    @property
    def last_frame_age(self) -> Optional[float]:
        """Seconds since the last frame; None before the first one."""
        with self._lock:
            return time.monotonic() - self._last_frame_at if self._last_frame_at else None

    @property
    def live(self) -> bool:
        """Frames are coming right now."""
        with self._lock:
            return self._state is not None and self._fresh()

    def _fresh(self) -> bool:
        return bool(self._last_frame_at) and time.monotonic() - self._last_frame_at < FRAME_STALE_S

    def state(self) -> Optional[dict]:
        """The current state of the ship and the pilot, or None when telemetry is not live (no game, menus,
        loading). A copy."""
        with self._lock:
            if self._state is None or not self._fresh():
                return None
            state = self._state
        # The handler builds a new state for every frame and never changes an old one, so it is copied outside
        # the lock.
        return copy.deepcopy(state)

    def recent(self, limit: int = 10, types: Optional[set[str]] = None) -> list[TelemetryEvent]:
        """The newest events first."""
        with self._lock:
            events = list(self._recent)
        events.reverse()
        if types:
            events = [event for event in events if event.type in types]
        return events[: max(0, limit)]

    def _event_loop(self) -> asyncio.AbstractEventLoop:
        """Core's loop once the reader started, so callbacks run where Core runs; the caller's before that."""
        if self._loop is not None and not self._loop.is_closed():
            return self._loop
        return asyncio.get_running_loop()

    def subscribe(self, event_type: str, callback: Callable) -> Callable[[], None]:
        """Call `callback(event)` for every event of this type ("*" for all). Returns the function that
        unsubscribes."""
        loop = self._event_loop()
        subscriber = Subscriber(event_type, callback, loop, _log)
        self._subscribers.append(subscriber)

        def off() -> None:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)
            subscriber.task.cancel()

        return off

    def subscribe_state(self, callback: Callable, interval: float = 1.0) -> Callable[[], None]:
        """Call `callback(state)` with the latest state at most every `interval` seconds (0.2 at least), and with
        None once when telemetry stops being live. Returns the function that unsubscribes."""
        loop = self._event_loop()
        subscriber = _StateSubscriber(self, callback, interval, loop)
        self._state_subscribers.append(subscriber)

        def off() -> None:
            if subscriber in self._state_subscribers:
                self._state_subscribers.remove(subscriber)
            subscriber.task.cancel()

        return off

    def status(self) -> ScTelemetryStatus:
        vehicle = None
        with self._lock:
            if self._state and self._fresh() and self._state.get("vehicle"):
                vehicle = self._state["vehicle"]["class_name"].replace("_", " ")
        state = self._current_state()
        return ScTelemetryStatus(
            state=state,
            variable_managed=windows_env.MANAGED,
            variable_set=self._variable_set,
            vehicle=vehicle if state == ScTelemetryState.LIVE else None,
            detail=self._unavailable or self._detail,
        )

    def _current_state(self) -> ScTelemetryState:
        if self._unavailable:
            return ScTelemetryState.UNAVAILABLE
        if not self.running:
            return ScTelemetryState.OFF
        from services.sc_telemetry import reader

        if self._failed_frames >= FAILED_FRAMES_INCOMPATIBLE or self._reader_state == reader.INCOMPATIBLE:
            return ScTelemetryState.INCOMPATIBLE
        if self._reader_state == reader.LIVE:
            return ScTelemetryState.LIVE if self._fresh() else ScTelemetryState.CONNECTED
        if self._reader_state == reader.CONNECTED:
            return ScTelemetryState.CONNECTED
        if self._game_without_telemetry:
            return ScTelemetryState.GAME_WITHOUT_TELEMETRY
        return ScTelemetryState.WAITING

    async def _publish_status(self, force: bool = False) -> None:
        status = self.status()
        if not force and status == self._published:
            return
        self._published = status
        if self.status_callback:
            try:
                await self.status_callback(status)
            except Exception as error:
                _log(f"status broadcast failed: {error!r}")

    async def _monitor(self) -> None:
        """Turns what the thread and the clock say into the status the client sees: live goes back to connected
        when the frames stop (menus), and while nothing answers, the Game.log tells whether the game runs without
        telemetry."""
        while True:
            try:
                waiting = self._current_state() in (
                    ScTelemetryState.WAITING,
                    ScTelemetryState.GAME_WITHOUT_TELEMETRY,
                )
                now = time.monotonic()
                if not waiting:
                    self._game_without_telemetry = False
                elif now - self._game_checked_at >= GAME_LOG_CHECK_S:
                    self._game_checked_at = now
                    self._game_without_telemetry = await asyncio.to_thread(
                        self._game_log.game_without_telemetry, self._game_path, ENVIRONMENTS
                    )
                    if windows_env.MANAGED:
                        self._variable_set = await asyncio.to_thread(windows_env.is_set)
                await self._publish_status()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # The status is extra; the stream goes on without it.
                self._log_limited("monitor", f"status check failed: {error!r}")
            await asyncio.sleep(MONITOR_S)

    # --- the reader thread --------------------------------------------------

    def _on_message(self, generation: int, message: Any) -> None:
        if generation != self._generation:
            return
        t = time.time()
        frame = self._to_dict(message)
        with self._lock:
            if generation != self._generation:
                return
            events = self._handler.update(frame, t)
            state = self._handler.latest
            self._state = state
            self._last_frame_at = time.monotonic()
            self._frames += 1
            self._failed_frames = 0
            self._recent.extend(events)
        broken = (state or {}).get("broken")
        if broken:
            self._log_limited("broken", f"part of a frame left out, a game patch may have changed it: {broken[0]}")
        if events:
            self._call_soon(self._deliver, generation, events)

    def _on_frame_error(self, generation: int, error: Exception) -> None:
        if generation != self._generation:
            return
        with self._lock:
            self._failed_frames += 1
            failed = self._failed_frames
            if failed == FAILED_FRAMES_INCOMPATIBLE:
                self._detail = f"frames cannot be read: {type(error).__name__}: {error}"
        self._log_limited("frame", f"frame skipped ({failed} in a row): {type(error).__name__}: {error}")

    def _on_reader_state(self, generation: int, state: str, detail: Optional[str]) -> None:
        if generation != self._generation:
            return
        from services.sc_telemetry import reader

        with self._lock:
            self._reader_state = state
            if state == reader.INCOMPATIBLE:
                self._detail = detail
            elif self._failed_frames < FAILED_FRAMES_INCOMPATIBLE:
                self._detail = None
        if state == reader.INCOMPATIBLE:
            self._log_limited("incompatible", f"the game answers in a way Wingman does not know: {detail}")
        elif state in (reader.CONNECTED, reader.LIVE):
            _log(f"telemetry {state}", LogType.INFO)
        self._call_soon(self._schedule_publish)

    def _call_soon(self, function: Callable, *args: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(function, *args)
        except RuntimeError:  # The loop closed while Core shuts down.
            pass

    def _schedule_publish(self) -> None:
        """Runs on the event loop. The task is kept until it is done, or the loop may drop it half way."""
        task = asyncio.ensure_future(self._publish_status())
        self._publishing.add(task)
        task.add_done_callback(self._publishing.discard)

    def _deliver(self, generation: int, events: list[TelemetryEvent]) -> None:
        """Runs on the event loop."""
        if generation != self._generation:
            return
        for event in events:
            for subscriber in list(self._subscribers):
                if subscriber.wants(event):
                    subscriber.offer(event)

    def _log_limited(self, kind: str, message: str) -> None:
        """At most one line per kind every LOG_EVERY_S: a fault can repeat 17 times a second."""
        now = time.monotonic()
        if now - self._logged_at.get(kind, -LOG_EVERY_S) >= LOG_EVERY_S:
            self._logged_at[kind] = now
            _log(message)

    # --- the switch in the game (Windows) -------------------------------------

    def _apply_variable(self, enabled: bool) -> None:
        """On: set the user variable if it is not set. Off: remove it, but only if Core set it. Runs in a
        thread: the registry and the broadcast to every window block."""
        if not windows_env.MANAGED:
            self._variable_set = None
            return
        record = Path(get_generated_files_dir(DATA_DIR_NAME)) / VARIABLE_RECORD
        try:
            set_by_core = bool(json.loads(record.read_text(encoding="utf-8")).get("set_by_core"))
        except (OSError, ValueError, AttributeError):
            set_by_core = False
        try:
            current = bool(windows_env.is_set())
            if enabled and not current:
                told = windows_env.set_variable(True)
                self._write_record(record, True)
                current = True
                _log(
                    "switched telemetry on in the game (GRPC_CLIENT_SERVER_ENABLED=true). It works after the RSI "
                    "Launcher is quit completely and started again.",
                    LogType.INFO,
                )
                if not told:
                    _log("Windows did not confirm the new variable in time; sign out and in if the launcher misses it")
            elif not enabled and current and set_by_core:
                windows_env.set_variable(False)
                self._write_record(record, False)
                current = False
                _log("switched telemetry off in the game again.", LogType.INFO)
            self._variable_set = current
        except OSError as error:
            _log(f"cannot switch telemetry in the game: {error!r}", LogType.ERROR)
            try:
                self._variable_set = windows_env.is_set()
            except OSError:
                self._variable_set = None

    @staticmethod
    def _write_record(record: Path, set_by_core: bool) -> None:
        try:
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text(json.dumps({"set_by_core": set_by_core}), encoding="utf-8")
        except OSError as error:
            _log(f"cannot remember who set the variable: {error!r}")
