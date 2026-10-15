"""Memory work after a turn ran on the turn's own loop.

A turn runs on a throwaway event loop in a worker thread, closed once the
answer is out. The checkpoint task and the idle timer were bound to that loop:
the checkpoint was lost, and unloading the Wingman later gathered a task of a
dead loop on the main loop - "The future belongs to a different loop".
"""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from services.websocket_user import WebSocketUser
from wingmen.wingman import Wingman


def memory_wingman() -> Wingman:
    wingman = Wingman.__new__(Wingman)
    wingman.name = "Computer"
    wingman._unloaded = False
    wingman._background_tasks = set()
    wingman._memory_pending = []
    wingman._memory_turns = 0
    wingman._memory_last_checkpoint = 0  # a checkpoint is due
    wingman._memory_idle_handle = None
    wingman.persistent_memory_service = MagicMock()
    wingman.persistent_memory_service.checkpoint = AsyncMock(return_value={})
    wingman.conversation = SimpleNamespace(conversation_summary="")
    wingman.context_builder = MagicMock()
    wingman.secret_keeper = MagicMock()
    wingman.unload_skills = AsyncMock()
    return wingman


def turn_on_its_own_loop(wingman: Wingman) -> None:
    async def turn():
        wingman._memory_after_turn("the answer")

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=lambda: loop.run_until_complete(turn()))
    thread.start()
    thread.join()
    loop.close()


def test_checkpoint_and_idle_timer_outlive_the_turns_loop(monkeypatch):
    wingman = memory_wingman()

    async def main():
        monkeypatch.setattr(WebSocketUser, "_main_loop", asyncio.get_running_loop())
        turn_on_its_own_loop(wingman)
        await asyncio.sleep(0.05)

        checkpoint = wingman.persistent_memory_service.checkpoint
        checkpoint.assert_awaited_once()
        assert checkpoint.await_args.args[0] == [{"role": "assistant", "content": "the answer"}]
        assert wingman._memory_idle_handle is not None

        await wingman.unload()
        assert wingman._background_tasks == set()

    asyncio.run(main())


def test_unload_skips_a_task_of_another_loop(monkeypatch):
    monkeypatch.setattr(WebSocketUser, "_main_loop", None)
    wingman = memory_wingman()
    wingman.persistent_memory_service = None

    async def make_task():
        return asyncio.get_running_loop().create_task(asyncio.sleep(0))

    other_loop = asyncio.new_event_loop()
    stale = other_loop.run_until_complete(make_task())
    other_loop.close()
    wingman._background_tasks.add(stale)

    asyncio.run(wingman.unload())
    assert wingman._background_tasks == set()
