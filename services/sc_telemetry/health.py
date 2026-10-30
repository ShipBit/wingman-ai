"""Whether the running game has telemetry, from its Game.log.

A game started without the variable never opens the port, so the reader alone only sees "nothing listens". The
Game.log tells the two cases apart: the game writes `Service 'sc.game.telemetry.v1.GameTelemetryService' registered`
in its first seconds when telemetry is on. A log that is written to right now and lacks the line is a game that runs
without telemetry: on Windows the RSI Launcher was started before the variable was set.
"""
from __future__ import annotations

import time
from pathlib import Path

from services.sc_telemetry.schema import SERVICE

REGISTERED_LINE = f"Service '{SERVICE}' registered".encode()
HEAD_BYTES = 2_000_000
"""The line comes in the first seconds of a session; Game.log grows to tens of MB."""
RUNNING_S = 120.0
"""A Game.log written to within this long belongs to a game that runs now."""
SESSION_KEY_BYTES = 128
"""The first bytes ("Log started on ...") tell one session's log from the next."""


class GameLogCheck:
    """Caches the answer per session: the head of a log never changes once the line is in it."""

    def __init__(self) -> None:
        self._registered: dict[tuple[str, bytes], bool] = {}

    def game_without_telemetry(self, game_path: str, environments: tuple[str, ...]) -> bool:
        log = self._newest_running_log(game_path, environments)
        if log is None:
            return False
        return not self._has_line(log)

    @staticmethod
    def _newest_running_log(game_path: str, environments: tuple[str, ...]) -> Path | None:
        if not game_path:
            return None
        newest: tuple[float, Path] | None = None
        for environment in environments:
            log = Path(game_path) / environment / "Game.log"
            try:
                written = log.stat().st_mtime
            except OSError:
                continue
            if newest is None or written > newest[0]:
                newest = (written, log)
        if newest is None or time.time() - newest[0] > RUNNING_S:
            return None
        return newest[1]

    def _has_line(self, log: Path) -> bool:
        try:
            with log.open("rb") as handle:
                key = (str(log), handle.read(SESSION_KEY_BYTES))
                if self._registered.get(key):
                    return True
                head = key[1] + handle.read(HEAD_BYTES - SESSION_KEY_BYTES)
        except OSError:
            return True  # can't tell: don't send the user to restart the launcher for nothing
        found = REGISTERED_LINE in head
        if found:
            self._registered = {key: True}
        return found
