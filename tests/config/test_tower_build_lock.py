"""A Tower is built by one caller at a time.

During sign-in Core waits on the backend before it builds the Tower. A
language change in that window reloads the config, which builds a Tower too.
Two builds at once unloaded each other's Wingmen and hooked keys twice.
"""

import asyncio
from types import SimpleNamespace

from wingman_core import WingmanCore


def test_two_tower_builds_never_overlap():
    running = []
    overlapped = []

    async def build(_config):
        running.append(1)
        if len(running) > 1:
            overlapped.append(True)
        await asyncio.sleep(0.01)
        running.pop()

    async def both():
        core = SimpleNamespace(_tower_lock=asyncio.Lock(), _initialize_tower=build)
        await asyncio.gather(
            WingmanCore.initialize_tower(core, "sign-in"),
            WingmanCore.initialize_tower(core, "language change"),
        )

    asyncio.run(both())

    assert not overlapped
