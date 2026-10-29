"""What state telemetry is in, and what the user should do about it (the field-test report §1)."""
from __future__ import annotations

from pathlib import Path

REGISTERED_LINE = "Service 'sc.game.telemetry.v1.GameTelemetryService' registered"
LOG_TAIL_BYTES = 2_000_000
"""The registration line is written in the first seconds; Game.log grows to tens of MB in a session."""

MESSAGES = {
    "no_grpc": "This Wingman version has no gRPC support, which Star Citizen telemetry needs. "
               "Update Wingman AI once a version with gRPC is out.",
    "off": "Star Citizen telemetry is switched off. Turn on 'Enable Star Citizen telemetry' in this skill's "
           "settings, then quit the RSI Launcher completely (tray icon too) and start it again.",
    "waiting": "Telemetry is switched on, but the game is not sending. Start Star Citizen from the RSI Launcher. "
               "If the game is already running, quit the launcher completely (tray too), start it again, and "
               "restart the game.",
    "unsupported": "Star Citizen is running, but its log does not show the telemetry service. A game patch may "
                   "have changed how telemetry is switched on.",
    "other_os": "Star Citizen telemetry is not on yet. Add the environment variable GRPC_CLIENT_SERVER_ENABLED=true "
                "to how you start the game (Lutris: Configure > System options > Environment variables; Steam: "
                "launch options GRPC_CLIENT_SERVER_ENABLED=true %command%), then restart the game.",
    "connected": "Connected to Star Citizen. Frames start once you have spawned.",
    "live": "Star Citizen telemetry is live.",
    "stopped": "Telemetry reading is stopped.",
}


def overall(reader_status: str, variable_set: bool | None, game_log_registered: bool | None) -> str:
    """One status for the user. `variable_set` is None where the skill can't see the game's environment (not
    Windows), `game_log_registered` is None when the log can't be checked."""
    if reader_status in ("no_grpc", "live", "connected", "stopped"):
        return reader_status
    if variable_set is None:
        return "other_os"
    if not variable_set:
        return "off"
    if game_log_registered is False:
        return "unsupported"
    return "waiting"


def game_log_registered(game_log: Path) -> bool | None:
    """True/False from the current Game.log; None when there is no log (game not run yet)."""
    try:
        size = game_log.stat().st_size
        with game_log.open("rb") as handle:
            if size > LOG_TAIL_BYTES:
                head = handle.read(LOG_TAIL_BYTES)  # the line is near the start of a session's log
            else:
                head = handle.read()
    except OSError:
        return None
    return REGISTERED_LINE.encode() in head
