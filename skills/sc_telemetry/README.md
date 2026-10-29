# Star Citizen Telemetry (`sc_telemetry`)

Reads the telemetry that Star Citizen 4.10.2 sends on its own local gRPC server. The Wingman reacts to what happens
to the ship and the pilot, and answers questions about them through two tools. Other skills can read a feed.

Full field-test report (every field, the warning lights, quirks, measured examples, what the API lacks):
https://github.com/Diftic/wingman-skills/blob/feat/sc-telemetry/sc_telemetry/TELEMETRY_REPORT.md

## Connection

| | |
|---|---|
| Server | `127.0.0.1:2942`, gRPC over HTTP/2, insecure, no token. Loopback only: the skill never connects elsewhere. |
| Service | `sc.game.telemetry.v1.GameTelemetryService`, server-streaming RPC `TelemetryStream` (`sc_telemetry.proto`) |
| Rate | about 17 Hz, after the player has spawned |
| Switch | `GRPC_CLIENT_SERVER_ENABLED=true` in the environment of `StarCitizen.exe` (undocumented, CIG's own) |
| Proof | `Game.log` gets `Service 'sc.game.telemetry.v1.GameTelemetryService' registered` |
| Library | `grpcio` (in Core's `requirements.txt`) and Core's `protobuf`. The message classes are built at runtime from `schema.desc`, so no generated `_pb2` code ties the skill to one protobuf version. |

On Windows the game inherits the variable from the RSI Launcher, which reads the user environment when it starts.
The setting "Enable Star Citizen telemetry" sets or removes the user variable (`enable.py`, only on the user's
choice); then the launcher must be quit completely (tray too) and started again.

## Settings

Only two: "Enable Star Citizen telemetry" and "Enable Proactive Notifications" (mutes every reaction). Every
reaction is on, the thresholds are fixed in `main.py`. The skill hint lists every reaction.

## Files

| File | Role | OS code |
|---|---|---|
| `main.py` | Orchestrator: settings, reactions (support model, like `sc_game_events`), tools, feed | none |
| `reader.py` | the gRPC stream in its own thread, reconnects, status `no_grpc/waiting/connected/live/stopped` | none |
| `schema.py`, `schema.desc`, `sc_telemetry.proto` | message classes from the descriptor set | none |
| `normalize.py` | frame dict to a flat state (missing field = default value) | none |
| `handler.py` | state smoothing, debouncing, events | none |
| `events.py` | the event list and wording | none |
| `describe.py` | the tool answers | none |
| `feed.py` | `state.json` (10 Hz) and `events.sqlite` for other skills | none |
| `health.py` | the status line for the user | none |
| `enable.py` | sets the Windows user variable | **Windows only** |

Tests: `tests/star_citizen/test_sc_telemetry_*.py`, on 11 recorded moments in `sc_telemetry_fixtures/` (gzipped
JSON lines cut from live sessions) and an in-process fake game server. They run on Linux CI.

## Porting to Linux

Everything but the switch is plain Python. Under Wine/Proton the game's sockets are the host's sockets, so the
stream on `127.0.0.1:2942` should reach a native Wingman unchanged. **Not verified on Linux yet.**

Already done:

1. `enable.MANAGED` is False off Windows: the setting does nothing, `is_enabled()` returns None, and the status
   line (`health.MESSAGES["other_os"]`) tells the user to add the variable to their launcher. Tested in
   `test_off_windows_the_setting_never_touches_the_system`.
2. No other module imports anything OS-specific; the test suite runs on Linux.

To do on a Linux machine:

1. Start the game with the variable: Lutris > Configure > System options > Environment variables
   `GRPC_CLIENT_SERVER_ENABLED` = `true`, or Steam launch options `GRPC_CLIENT_SERVER_ENABLED=true %command%`.
2. Check `Game.log` for the "registered" line, then `ss -ltn | grep 2942` on the host.
3. If the port is open: add `linux` to `platforms` in `default_config.yaml`, activate the skill, ask "ship status".
4. If `Game.log` is not found: `_game_log()` in `main.py` asks the `star_citizen` facade for the LIVE folder; that is
   Core's Linux game-folder lookup, not this skill's. The status then just skips the "unsupported" check.
5. If the port is only open inside the Wine prefix: run Wingman in the same prefix, or forward the port.
