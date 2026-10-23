"""Game.log lines and helpers the Star Citizen tests share."""

import asyncio
from pathlib import Path

FIRST = "<2026-09-28T10:00:00.000Z> Log started on Mon Sep 28 10:00:00 2026\n"
LOGIN = "<2026-09-28T10:00:01.000Z> User Login Success Handle[TestPilot]\n"
ARMISTICE = (
    '<2026-09-28T10:00:02.000Z> [Notice] <SHUDEvent> Added notification '
    '"Entering Armistice Zone" [3] to queue.\n'
)
CONTRACT = (
    '<2026-09-28T10:00:03.000Z> [Notice] <SHUDEvent> Added notification '
    '"Contract Accepted: Big Delivery: " [3] to queue. MissionId[abc-123]\n'
)


def write_game_log(tmp_path, *lines) -> Path:
    log = tmp_path / "game" / "LIVE" / "Game.log"
    log.parent.mkdir(parents=True)
    log.write_text("".join(lines))
    return log


async def until(condition, seconds=5.0):
    for _ in range(int(seconds / 0.02)):
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached")
