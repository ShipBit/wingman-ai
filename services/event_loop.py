"""Event loops that survive a stale I/O completion on Windows.

On Windows asyncio uses the proactor: every open socket has a read pending,
and ``IocpProactor._poll`` puts each finished read on its future. When code
on another thread closes a socket of this loop, or cancels a task waiting on
it, the read's future is cancelled from that thread while ``_poll`` is
finishing it. ``set_exception`` on the cancelled future raises
``InvalidStateError``, nothing in ``_poll`` catches it, and it ends
``run_forever``. For Core that was the main loop: the API, the websocket to
the client and every hotkey stopped, while the process kept running.

The read in question is already cancelled, so there is nothing left to
deliver. ``select`` drops it, keeps the completions ``_poll`` collected
before it, and the next poll picks up the rest from the completion port.

Each turn and many skills run on loops of their own, on their own threads, so
the policy makes every new loop tolerant, not just the main loop.
"""

import asyncio
import platform

from api.enums import LogType
from services.printr import Printr

printr = Printr()


class StaleCompletionTolerance:
    """Mixed in before ``IocpProactor``."""

    def select(self, timeout=None):
        try:
            return super().select(timeout)
        except asyncio.InvalidStateError:
            printr.print(
                "Event loop: dropped the result of a socket read that another thread had already cancelled.",
                color=LogType.WARNING,
                server_only=True,
            )
            results, self._results = self._results, []
            return results


if platform.system() == "Windows":
    from asyncio import windows_events

    class TolerantProactor(StaleCompletionTolerance, windows_events.IocpProactor):
        pass

    class TolerantEventLoopPolicy(windows_events.WindowsProactorEventLoopPolicy):
        @staticmethod
        def _loop_factory():
            return windows_events.ProactorEventLoop(proactor=TolerantProactor())


def install():
    """Make every event loop created from now on tolerant. Call before the
    first loop is created. Does nothing outside Windows: the selector loops
    there have no completions to finish late."""
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(TolerantEventLoopPolicy())
