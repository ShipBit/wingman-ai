"""Callbacks of skills on a Core service's events, each with its own queue.

The Star Citizen log reader and the Star Citizen telemetry hand their events to skills through these. A slow or
failing callback only delays itself: never the reader thread, never another skill.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable

QUEUE_SIZE = 256
CALLBACK_TIMEOUT_SECONDS = 30


class Subscriber:
    """One callback for one event type ("*" for all) with its own queue on one event loop."""

    def __init__(
        self,
        event_type: str,
        callback: Callable,
        loop: asyncio.AbstractEventLoop,
        log: Callable[[str], None],
    ) -> None:
        self.event_type = event_type
        self.callback = callback
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.failures = 0
        self._log = log
        self.task = loop.create_task(self._run())

    def wants(self, event: Any) -> bool:
        return self.event_type == "*" or self.event_type == event.type

    def offer(self, event: Any) -> None:
        """Runs on the subscriber's event loop."""
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
                    self._log(f"{name} failed on {event.type} ({self.failures}x): {error!r}")
