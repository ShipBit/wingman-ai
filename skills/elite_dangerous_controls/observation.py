"""Shared production status observation for the skill and opt-in direct trials."""

import asyncio
import hashlib
import json


class ObservationUnavailable(ValueError):
    def __init__(self, reason, evidence):
        super().__init__("Current Live game status is unavailable: " + reason)
        self.evidence = evidence


async def observe_status(reader, telemetry):
    # Live testing found an otherwise valid status timestamp 0.248s ahead of
    # Windows. Wait for it to become current; never accept future data or resend
    # input. Re-read the session and file after waiting, under a fixed time bound.
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 1.1
    waited, initial_lead, read_retries = 0.0, 0.0, 0
    while True:
        await asyncio.to_thread(reader.refresh)
        raw = b""
        try:
            raw = await asyncio.to_thread((reader.directory / "Status.json").read_bytes)
            if len(raw) > 65536:
                raise ValueError("Oversized game status.")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            # Status.json is rewritten in place. A read can catch an empty or
            # partial write. Retry the observation only, at most five times,
            # sharing the same overall deadline as timestamp validation.
            if reader.running and read_retries < 5 and loop.time() + 0.025 <= deadline:
                read_retries += 1
                await asyncio.sleep(0.025)
                continue
            raise ObservationUnavailable("the status file is unavailable or incomplete.",
                {"read_error": type(exc).__name__, "raw_length": len(raw), "read_retries": read_retries,
                 "session": reader.session_started, "received_at": telemetry.utc_now().isoformat()}) from exc
        if not isinstance(data, dict):
            raise ObservationUnavailable("the status file is not an object.", {"read_retries": read_retries})
        stamp = telemetry.parsed_time(data.get("timestamp"))
        started = telemetry.parsed_time(reader.session_started)
        now = telemetry.utc_now()
        evidence = {"running": reader.running, "catch_up": reader.catch_up,
                    "session": reader.session_started, "galaxy": reader.galaxy,
                    "status_timestamp": data.get("timestamp"), "received_at": now.isoformat(),
                    "revision": hashlib.sha256(raw).hexdigest(), "timestamp_wait_seconds": waited,
                    "read_retries": read_retries}
        if (not reader.running or reader.catch_up or not stamp or not started or stamp < started or
                data.get("event") != "Status" or reader.galaxy != "live"):
            raise ObservationUnavailable("enter gameplay and repeat the request.", evidence)
        ahead = (stamp - now).total_seconds()
        if ahead > 0:
            evidence["seconds_ahead_of_clock"] = ahead
            if ahead > 1.0 or loop.time() + ahead + 0.01 > deadline:
                raise ObservationUnavailable("the status timestamp is ahead of the system clock.", evidence)
            initial_lead = max(initial_lead, ahead)
            await asyncio.sleep(ahead + 0.01)
            waited += ahead + 0.01
            continue
        return {"session": reader.session_started, "observed": stamp.timestamp(),
                "revision": evidence["revision"], "data": data,
                "game_version": getattr(reader, "game_version", ""),
                "received_at": now.isoformat(), "timestamp_wait_seconds": waited,
                "initial_clock_lead_seconds": initial_lead, "read_retries": read_retries}
