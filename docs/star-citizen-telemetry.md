# Star Citizen telemetry

Star Citizen (4.10.2 and later) has a local, read-only gRPC server for its own telemetry. Core reads it
(`services/sc_telemetry`) and hands the ship's and the pilot's state to skills through `self.wingman.sc_telemetry`.
Star Citizen Events reacts to it, next to the game log, and its `star_citizen_status` tool answers about the ship
and the pilot.

The schema, the rules for the quirks of the stream and the field test come from Mallachi's Star Citizen Telemetry
skill. His full report (every field, the warning lights, the quirks, what the API lacks):
https://github.com/Diftic/wingman-skills/blob/feat/sc-telemetry/sc_telemetry/TELEMETRY_REPORT.md

## How the game exposes it

| | |
|---|---|
| Server | `127.0.0.1:2942`, gRPC over HTTP/2, insecure, no token. Core connects to loopback only and sends nothing but the empty request. |
| Service | `sc.game.telemetry.v1.GameTelemetryService`, server-streaming RPC `TelemetryStream` (`services/sc_telemetry/sc_telemetry.proto`) |
| Rate | about 17 frames a second, after the player has spawned. None in menus or while loading. |
| Switch | `GRPC_CLIENT_SERVER_ENABLED=true` in the environment of `StarCitizen.exe` (undocumented, CIG's own) |
| Proof | `Game.log` gets `Service 'sc.game.telemetry.v1.GameTelemetryService' registered` |

On Windows the game inherits the variable from the RSI Launcher, which reads the user environment when it starts.
The setting (Settings > Star Citizen > Star Citizen telemetry) sets the user variable when it is on and removes it
when it is off, but only if Wingman set it: a variable set by hand stays. Either way the launcher must be quit
completely (tray icon too) and started again.

## What Core does with it

| File | Role |
|---|---|
| `service.py` | One reader for the process, the status for the client, events to every subscriber on its own queue |
| `reader.py` | The gRPC stream in its own thread; reconnects every few seconds, stops at once |
| `schema.py`, `schema.desc` | The message classes, built at runtime from the descriptor set (no generated `_pb2` code) |
| `normalize.py` | A frame to a flat state. Missing fields read as defaults; a value a newer game sends is kept as `unknown_<n>`; a part that cannot be read is left out, not the frame |
| `handler.py` | Smoothing, debouncing and the events, with the quirks from the field test |
| `events.py` | The event list, the report wording and a suggested cooldown per event |
| `health.py` | Whether a running game has telemetry, from its `Game.log` |
| `windows_env.py` | The Windows user variable (the only OS code) |

The status the client shows: `off`, `waiting` (nothing answers), `game_without_telemetry` (the game runs, its log has
no telemetry line: restart the launcher), `connected` (menus, loading), `live`, `incompatible` (the game answers in
a shape Wingman does not know: a game patch changed it) and `unavailable` (this build cannot read gRPC).

## Testing without the game

`scripts/sc_telemetry_fake.py` is a fake game on `127.0.0.1:2942`: it flies a short session (power on, take off,
a lock, hits, shields down, a quantum jump, a reward, low fuel, landing, going down, a respawn) at 17 frames a
second. Say you play Star Citizen and switch telemetry on in Settings > Star Citizen, then:

```bash
python scripts/sc_telemetry_fake.py                # telemetry alone
python scripts/sc_telemetry_fake.py --with-gamelog # and the game log, both sources at once
python scripts/sc_telemetry_fake.py --replay tests/star_citizen/sc_telemetry_fixtures/combat_2026-10-28.jsonl.gz
```

With `--with-gamelog` set the game folder to `~/SC-Fake`. The game log then reports the reward, the low fuel and
going down at the same moments as the telemetry: Star Citizen Events says each once, from the source picked in its
settings. `scripts/sc_gamelog_fake.py` plays the game log alone.

## Linux

Everything but the Windows variable is plain Python. Under Wine or Proton the game's sockets are the host's, so the
stream on `127.0.0.1:2942` should reach a native Wingman unchanged. **Not verified on Linux yet.**

1. Start the game with the variable: Lutris > Configure > System options > Environment variables
   `GRPC_CLIENT_SERVER_ENABLED` = `true`, or Steam launch options `GRPC_CLIENT_SERVER_ENABLED=true %command%`.
2. Check `Game.log` for the "registered" line, then `ss -ltn | grep 2942` on the host.
3. If the port is open, Settings > Star Citizen shows the telemetry as live once you have spawned.
4. If the port is only open inside the Wine prefix: run Wingman in the same prefix, or forward the port.
