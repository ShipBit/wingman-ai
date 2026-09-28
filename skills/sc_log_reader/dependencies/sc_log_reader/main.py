"""Selected Diftic 3.1.2 source contract; core and CLI never import Wingman."""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from pathlib import Path

from skills.skill_base import Skill

from .host_boundary import claim_runtime
from .host_notifications import (
    REACTION_PROMPT,
    LiteralGuiSink,
    WingmanReactionSink,
    present_poll,
)
from .notifications import NotificationPolicy, enabled_notification_events
from .review_launcher import invalidate_launcher, write_launcher
from .service import Service, Tailer, ToolInterface
from .updates import UpdateManager


class SCLogReader(Skill):
    def __init__(self, config, settings, wingman):
        super().__init__(config, settings, wingman)
        self.service = None
        self.interface = None
        self.tasks = []
        self.stop = asyncio.Event()
        self.notifications = 0
        self.poll_task = None
        self._lifecycle_lock = asyncio.Lock()
        self._running = False
        self._workers = set()
        self._cleanup_task = None
        self.cleanup_warning = None
        self._base_cleanup_pending = False
        self._initialization = None
        self._owner = None
        self.notification_policy = None
        self.notification_sink = None

    def _setting(self, name, default=None):
        return next(
            (p.value for p in self.config.custom_properties if p.id == name), default
        )

    async def prepare(self):
        while True:
            async with self._lifecycle_lock:
                if self._running:
                    return
                cleanup = self._cleanup_task
                if cleanup is None or cleanup.done():
                    if cleanup is not None:
                        cleanup.result()
                        self._cleanup_task = None
                    if self._initialization is None:
                        game = self._setting("sc_game_path", "")
                        runtime = self._setting("runtime_directory", "")
                        if not game or not runtime:
                            raise ValueError(
                                "SC Log Reader requires Star Citizen Path and Runtime Directory settings"
                            )
                        if self._base_cleanup_pending:
                            self.is_unloaded = False
                            await asyncio.wait_for(super().unload(), timeout=2)
                            self._base_cleanup_pending = False
                        self.stop = asyncio.Event()
                        self.is_unloaded = False
                        try:
                            await super().prepare()
                        except BaseException:
                            self._cleanup_task = asyncio.create_task(
                                self._finish_shutdown(None, [], None)
                            )
                            raise
                        self._initialization = self._start_worker(
                            self._create_service,
                            runtime,
                            self._setting("instruction_url") or None,
                            self._setting("instruction_recovery", "automatic"),
                        )
                    initialization = self._initialization
                    break
            # Keep the lifecycle lock free for unload while a previous
            # generation still has threads using its database or update files.
            await asyncio.shield(cleanup)
        try:
            service, owner = await asyncio.shield(initialization)
            async with self._lifecycle_lock:
                if self.stop.is_set():
                    raise asyncio.CancelledError
                if not self._running:
                    self.service, self._owner = service, owner
                    self._publish_service()
        except BaseException:
            # Cancellation must not cancel a running initialization thread.
            # Retain its result owner until shutdown closes the late Service.
            asyncio.create_task(self.unload())
            raise

    @staticmethod
    def _create_service(runtime, url, recovery="automatic"):
        owner = claim_runtime(runtime)
        try:
            updates = UpdateManager(Path(runtime) / "instructions", url)
            recovery_result = updates.recover(recovery)
            instructions = updates.host_startup(owner)
            service = Service(
                runtime, instructions=instructions, activate_updates=False
            )
            service.updates = updates
            service.recovery_result = recovery_result
            try:
                service.review_launcher_command = write_launcher(runtime)
            except (OSError, RuntimeError) as exc:
                service.worker_errors["review_launcher"] = {
                    "status": "unavailable",
                    "reason": str(exc),
                }
            return service, owner
        except BaseException:
            owner.release()
            raise

    def _publish_service(self):
        game = Path(self._setting("sc_game_path"))
        self.poll_task = None
        if self.cleanup_warning:
            self.service.worker_errors["previous_host_cleanup"] = self.cleanup_warning
        self.interface = ToolInterface(self.service)
        recovery = getattr(self.service, "recovery_result", {})
        if recovery.get("status") == "rollback_staged_for_next_startup":
            self.printr.toast_info(
                f"Star Citizen Log Reader: instructions will revert to {recovery['version']} after restarting Wingman. "
                "Rejected revisions will not reinstall automatically."
            )
        paths = {
            env: game / env / "Game.log"
            for env in ("LIVE", "PTU", "EPTU", "HOTFIX", "TECH-PREVIEW")
        }
        self.tailer = Tailer(self.service, paths)
        self.notification_policy = None
        self.notification_sink = None
        if self._setting("react_game_events", False) or self._setting(
            "notify_game_events", False
        ):
            selected_events = enabled_notification_events(
                {p.id: p.value for p in self.config.custom_properties or []}
            )
            try:
                self.notification_sink = (
                    WingmanReactionSink(
                        self.wingman,
                        on_pause=self.log.info,
                        display=self._display_reaction,
                    )
                    if self._setting("react_game_events", False)
                    else LiteralGuiSink.selected_host()
                )
                self.notification_policy = NotificationPolicy(enabled_events=selected_events)
            except (ImportError, AttributeError, RuntimeError) as exc:
                self.service.worker_errors["notifications"] = {
                    "status": "unavailable",
                    "reason": type(exc).__name__,
                }
        self.tasks = [
            asyncio.create_task(self._monitor()),
            asyncio.create_task(self._updates()),
        ]

        self._running = True

    async def update_config(self, new_config):
        old = {p.id: p.value for p in self.config.custom_properties or []}
        new = {p.id: p.value for p in new_config.custom_properties or []}
        restart = self._running or self._initialization is not None
        if old != new:
            await self.unload()
            if self._cleanup_task is not None:
                await asyncio.shield(self._cleanup_task)
            if old.get("runtime_directory") and old.get("runtime_directory") != new.get(
                "runtime_directory"
            ):
                await asyncio.to_thread(invalidate_launcher, old["runtime_directory"])
        await super().update_config(new_config)
        if old != new:
            self.is_prepared = False
            if restart:
                await self.prepare()
                self.is_prepared = True

    def _start_worker(self, function, *args):
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        self._workers.add(task)

        def finished(worker):
            self._workers.discard(worker)
            # A cancelled host caller no longer retrieves worker exceptions.
            if not worker.cancelled():
                worker.exception()

        task.add_done_callback(finished)
        return task

    async def _wait(self, seconds):
        with suppress(TimeoutError):
            await asyncio.wait_for(self.stop.wait(), timeout=seconds)

    async def _monitor(self):
        failures = 0
        while not self.stop.is_set():
            try:
                before = {
                    env: dict(health)
                    for env, health in self.service.live_health.items()
                }
                self.poll_task = self._start_worker(self.tailer.poll)
                events = await asyncio.shield(self.poll_task)
                if self.notification_policy and not self.stop.is_set():
                    await present_poll(
                        self.notification_policy,
                        self.notification_sink,
                        events,
                        before,
                        self.service.live_health,
                        now=time.monotonic(),
                    )
                self.service.worker_errors.pop("monitor", None)
                failures = 0
            except Exception as exc:  # isolate unexpected worker failure from Wingman
                failures += 1
                self.service.worker_errors["monitor"] = {
                    "error": type(exc).__name__,
                    "consecutive_failures": failures,
                    "paused": failures >= 3,
                }
                if failures in (1, 3):
                    self.log.warning(
                        "SC Log Reader monitoring failed. See reader health."
                        + (
                            " Restart the skill to retry."
                            if failures >= 3
                            else " Retrying."
                        )
                    )
                if failures >= 3:
                    return
            # A positive catch-up yield leaves the host responsive without
            # paying the idle quarter-second delay for every bounded poll.
            delay = 1 if failures else (0.01 if self.tailer.has_backlog() else 0.25)
            await self._wait(delay)

    async def _updates(self):
        last_digest = None
        while not self.stop.is_set():
            try:
                result = await asyncio.shield(
                    self._start_worker(self.service.updates.check_automatically)
                )
                self.service.worker_errors.pop("updates", None)
                if result["status"] == "staged_for_next_startup" and result["sha256"] != last_digest:
                    self.printr.toast_info(
                        f"Star Citizen Log Reader: instructions {result['version']} downloaded and scheduled. "
                        "Changes take effect after restarting Wingman."
                    )
                    last_digest = result["sha256"]
                elif result["status"] == "reader_upgrade_required":
                    self.service.worker_errors["updates"] = result
                    self.log.warning(
                        "SC Log Reader needs a reader upgrade before new definitions can be used."
                    )
            except (
                Exception
            ) as exc:  # network/protocol/host failures must not kill checking
                self.service.worker_errors["updates"] = {
                    "error": type(exc).__name__,
                    "retry_in_seconds": 6 * 3600,
                }
            await self._wait(6 * 3600)

    def get_tools(self):
        return (
            self.interface.get_tools()
            if self.interface
            else ToolInterface(None).get_tools()
        )

    async def get_prompt(self):
        prompt = await super().get_prompt()
        if self._setting("react_game_events", False):
            # Host context includes this even when a saved profile overrides
            # default_config.prompt. Never prepend guidance to visible events.
            return "\n\n".join(part for part in (prompt, REACTION_PROMPT) if part)
        return prompt

    async def execute_tool(self, tool_name, parameters, benchmark):
        if not self._running or self.interface is None:
            return json.dumps({"error": "SC Log Reader is not running"}), ""
        # Register before yielding so unload cannot miss an admitted read.
        worker = self._start_worker(self.interface.call, tool_name, parameters)
        try:
            result = await asyncio.shield(worker)
            if tool_name == "get_reader_health":
                result["presentation"] = {
                    "status": "available"
                    if self.notification_sink
                    else "disabled_or_unavailable",
                    "policy": self.notification_policy.stats
                    if self.notification_policy
                    else {},
                    "sink": dict(self.notification_sink.stats)
                    if self.notification_sink
                    else {},
                    "mode": "wingman_reactions"
                    if isinstance(self.notification_sink, WingmanReactionSink)
                    else "gui_display",
                    "scope": (
                        "admission and host calls returned, not confirmation of speech"
                        if isinstance(self.notification_sink, WingmanReactionSink)
                        else "transport completion, not confirmation of GUI rendering"
                    ),
                }
            return json.dumps(result, ensure_ascii=False), ""
        except (ValueError, TypeError):
            return json.dumps({"error": "Invalid tool name or parameters"}), ""

    async def on_add_user_message(self, message):
        if not message.startswith(("[Game Event]", "[Game Events]")):
            self.notifications = 0
            if isinstance(self.notification_sink, WingmanReactionSink):
                self.notification_sink.reset_budget()

    async def _finish_shutdown(self, service, tasks, initialization):
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if isinstance(self.notification_sink, WingmanReactionSink):
            await self.notification_sink.close()
        # Polls, update checks and tool reads are shielded from their callers'
        # cancellation. No new work is admitted after _running becomes false.
        await asyncio.gather(*tuple(self._workers), return_exceptions=True)
        owner = self._owner
        if initialization is not None:
            with suppress(Exception):
                service, owner = await asyncio.shield(initialization)
        if service is not None:
            await asyncio.to_thread(service.close)
        if owner is not None:
            await asyncio.to_thread(owner.release)
        self._initialization = None
        self._owner = None
        try:
            await asyncio.wait_for(super().unload(), timeout=2)
        except Exception as exc:
            # Our threads and database have already drained safely. A host
            # cleanup failure is observable but must not poison later starts.
            self.cleanup_warning = {
                "error": type(exc).__name__,
                "local_cleanup_complete": True,
            }
            # V3 owns a private secret subscription. Retry its public cleanup
            # before another prepare; never reach into the host's internals.
            self._base_cleanup_pending = True

    async def _display_reaction(self, role, text):
        from api.enums import LogSource, LogType

        await self.printr.print_async(
            text,
            color=LogType.INFO,
            source=LogSource.USER if role == "user" else LogSource.WINGMAN,
            source_name=self.wingman.name,
            skill_name="Game Events" if role == "user" else "",
        )

    async def unload(self):
        async with self._lifecycle_lock:
            if self._cleanup_task is None:
                self._running = False
                self.is_prepared = False
                self.stop.set()
                if hasattr(self, "tailer"):
                    self.tailer.stop_requested.set()
                self._cleanup_task = asyncio.create_task(
                    self._finish_shutdown(
                        self.service, self.tasks, self._initialization
                    )
                )
                self.tasks = []
            cleanup = self._cleanup_task
        # Cancellation cannot stop a thread. Keep cleanup alive after this
        # bounded host wait; prepare will await it before opening a service.
        with suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(cleanup), timeout=2)
