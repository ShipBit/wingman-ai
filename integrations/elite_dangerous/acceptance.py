"""Opt-in private gameplay trials. Never sends input unless direct --send-input is used.

Run with .venv-core/Scripts/python.exe -m integrations.elite_dangerous.acceptance.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import yaml

from services.elite_runtime_identity import ROOT, compare, expected_files, fingerprint, process_started
from services.printr import Printr
from skills.elite_dangerous import telemetry
from skills.elite_dangerous_controls.input import WindowsInput
from skills.elite_dangerous_controls.observation import observe_status
from skills.elite_dangerous_controls.runtime import BindingResolver, ControlEngine, default_bindings, validate_turn, InvalidRequest

STATE = ROOT / ".elite-local/acceptance"
FAILURES = ("focus_loss", "chat_menu", "stale_session", "binding_change", "escape_cancellation",
            "unavailable_control", "negated_request", "contradictory_request")


def protocol(single_press=True):
    result = []
    for path in ("physical", "direct", "voice", "voice_after_restart"):
        for action in ("lights", "night_vision"):
            states = (["off", "on", "off"] if path == "physical" else
                      ([] if single_press else ["off"]) + ["on", "on", "off", "off"] * 5 + ["toggle", "toggle"])
            previous = None
            for state in states:
                press = single_press and path != "physical"
                desired = ("off" if previous == "on" else "on") if press or state == "toggle" else state
                result.append({"case": len(result) + 1, "path": path, "action": action, "state": state,
                               "desired": desired, "already_set": not press and previous == desired, "initial": previous is None,
                               "execution": "single_press" if press else "set_state",
                               "spoken_request": ("toggle " if state == "toggle" else "turn " + state + " ") + action.replace("_", " ")})
                previous = desired
    return result


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def append(directory, record):
    directory.mkdir(parents=True, exist_ok=True)
    record = {"recorded_at": datetime.now(timezone.utc).isoformat(), **record}
    path = directory / (uuid4().hex + ".json")
    with path.open("x", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
    return path


def active():
    directory = (STATE / read(STATE / "active.json")["session"]).resolve()
    if not directory.is_relative_to(STATE.resolve()):
        raise ValueError("Invalid acceptance session path")
    return directory, read(directory / "session.json")


def initialize(profile, presets, journal, game_version):
    profile = Path(profile).resolve()
    config = yaml.safe_load(profile.read_text(encoding="utf-8-sig"))
    binding = BindingResolver(default_bindings(), presets, config).read()
    if game_version == "auto":
        reader = telemetry.JournalReader(Path(journal))
        for _ in range(100):
            reader.refresh()
            if not reader.catch_up:
                break
        if reader.catch_up or not reader.game_version:
            raise ValueError("Cannot establish game version from local journal; supply --game-version")
        game_version = reader.game_version
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    directory = STATE / name
    directory.mkdir(parents=True, exist_ok=False)
    record = {"session": name, "kind": "live_acceptance_pending", "protocol_revision": 3,
              "control_semantics": "single_press", "profile": fingerprint(profile),
              "expected_files": expected_files(), "binding_revision": binding["revision"],
              "bindings": str(default_bindings()), "presets": str(Path(presets).resolve()),
              "journal": str(Path(journal).resolve()), "game_version": game_version,
              "protocol": protocol()}
    (directory / "session.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    (STATE / "active.json").write_text(json.dumps({"session": name}), encoding="utf-8")
    return {"session": str(directory), "acceptance": "pending", "next": "Restart Core yourself using the companion shortcut, then record restart --dropdown-visible."}


def deployment(session):
    from tools.managed_launch import port_owner, owns_core
    profile = Path(session["profile"]["path"])
    identity = read(profile.parent.parent.parent / "elite-runtime.json")
    owner = port_owner()
    if not owner or not owns_core(owner):
        raise ValueError("Managed source Core is not listening; acceptance pending")
    problems = compare(identity, session["expected_files"], pid=owner["ProcessId"],
                       process_started=process_started(owner["ProcessId"]),
                       profile=profile.parent.name, config_root=profile.parent.parent)
    if expected_files() != session["expected_files"]:
        problems.append("source_changed_start_new_sequence")
    if fingerprint(profile) != session["profile"]:
        problems.append("profile_changed_start_new_sequence")
    config = yaml.safe_load(profile.read_text(encoding="utf-8-sig"))
    binding = BindingResolver(session["bindings"], session["presets"], config).read()
    if binding["revision"] != session["binding_revision"]:
        problems.append("bindings_changed_start_new_sequence")
    if problems:
        raise ValueError(", ".join(problems))
    return identity


def records(directory, name):
    return [read(p) for p in sorted((directory / name).glob("*.json"))]


def assigned_events(directory):
    """Associate a voice block by request IDs and execution time; retain raw files."""
    events = records(directory, "events")
    for block in records(directory, "blocks"):
        if not block["path"].startswith("voice"):
            continue
        selected = [e for e in events if e.get("case") == block["cases"][0] and e.get("outcome")]
        selected.sort(key=lambda e: e.get("evidence", {}).get("started_at", ""))
        requests = list(dict.fromkeys(e["request_id"] for e in selected))
        mapping = {request: block["cases"][min(index, len(block["cases"]) - 1)] for index, request in enumerate(requests)}
        for event in events:
            if event.get("case") == block["cases"][0] and event.get("request_id") in mapping:
                event["armed_case"] = event["case"]
                event["case"] = mapping[event["request_id"]]
    return events


def assess_case(case, events, checkpoint):
    if checkpoint["visible"] != case["desired"]:
        return "player_observation"
    results = [e for e in events if e.get("outcome")]
    if len(results) != 1:
        return "routing" if not results else "duplicate_execution"
    result = results[0]
    if case["path"] == "physical":
        return "" if result.get("outcome") == "physical_observed" else "physical_telemetry"
    if result.get("intent", {}).get("action") != case["action"] or result.get("intent", {}).get("state") != case["state"]:
        return "user_intent"
    press = case.get("execution") == "single_press"
    allowed_outcomes = {"input_sent"} if press else {"confirmed", "already_set"}
    if result.get("outcome") not in allowed_outcomes:
        return result.get("first_failing_stage") or "game_observation"
    # A result label is not evidence. Recheck the recorded observation and
    # insertion trace so an accidentally optimistic renderer cannot pass a gate.
    evidence = result.get("evidence", {})
    before = evidence.get("before", {})
    if press:
        observations = [e for e in events if e.get("event") == "game_observation" and e.get("request_id") == result.get("request_id")]
        if len(observations) != 1 or observations[0].get("observation_outcome") != "gameplay_observed":
            return "game_observation"
        after = observations[0].get("after", {})
    else:
        after = evidence.get("after", {}) if result["outcome"] == "confirmed" else before
    bit = 8 if case["action"] == "lights" else 28
    flags = after.get("data", {}).get("Flags")
    if (type(flags) is not int or bool(flags & (1 << bit)) != (case["desired"] == "on") or
            not before.get("session") or before.get("session") != after.get("session") or
            not before.get("revision") or not after.get("revision") or
            type(before.get("observed")) not in (int, float) or type(after.get("observed")) not in (int, float) or
            after["observed"] < before["observed"]):
        return "game_observation"
    input_events = result.get("input_events", [])
    if result["outcome"] in {"confirmed", "input_sent"}:
        before_flags = before.get("data", {}).get("Flags")
        if (type(before_flags) is not int or not (flags ^ before_flags) & (1 << bit) or
                before["revision"] == after["revision"]):
            return "game_observation"
        if (not input_events or any(e.get("inserted", 0) != e.get("requested") or e.get("inserted", 0) <= 0 for e in input_events) or
                not any(e.get("release") is False for e in input_events) or not any(e.get("release") is True for e in input_events)):
            return "input"
    elif input_events:
        return "unexpected_input"
    if case["already_set"] and (result["outcome"] != "already_set" or result.get("input_events")):
        return "unexpected_input"
    if not case.get("initial") and not case["already_set"] and result["outcome"] not in {"confirmed", "input_sent"}:
        return "game_observation"
    if case["path"].startswith("voice"):
        speech = [e for e in events if e.get("event") == "speech_requested"]
        expected_speech = result["speech"]
        generated = [e for e in events if e.get("event") == "acknowledgment_generated"
                     and e.get("request_id") == result.get("request_id")]
        if generated:
            from skills.elite_dangerous_controls.speech import suitable_acknowledgment
            if (not press or len(generated) != 1 or generated[0].get("outcome_basis") != "input_sent"
                    or not suitable_acknowledgment(generated[0].get("speech"), result.get("intent", {}).get("action"))):
                return "speech"
            expected_speech = generated[0]["speech"]
        if (len(speech) != 1 or checkpoint.get("heard", "").strip() != expected_speech or
                speech[0].get("request_id") != result.get("request_id") or speech[0].get("speech") != expected_speech):
            return "speech"
        try:
            validate_turn(speech[0].get("transcript", ""), case["action"], case["state"], "ship", require_state=not press)
        except InvalidRequest:
            return "transcription"
    return ""


def summary(directory, session):
    checkpoints = records(directory, "checkpoints")
    events = assigned_events(directory)
    failures, passed = [], []
    for case in session["protocol"]:
        notes = [c for c in checkpoints if c.get("case") == case["case"]]
        if not notes:
            continue
        issue = "repeated_trial_start_new_sequence" if len(notes) != 1 else assess_case(
            case, [e for e in events if e.get("case") == case["case"]], notes[0])
        if issue:
            failures.append({"case": case["case"], "stage": issue})
        else:
            passed.append(case["case"])
    restarts = records(directory, "restarts")
    restart_count = len({r["identity"]["instance"] for r in restarts if r.get("dropdown_visible")})
    manual = records(directory, "failure_checks")
    missing_failures = [name for name in FAILURES if not any(r["check"] == name and r["passed"] for r in manual)]
    failed_checks = [r["check"] for r in manual if not r["passed"]]
    basic_pass = (len(passed) == len(session["protocol"]) and not failures and not missing_failures
                  and not failed_checks and restart_count >= 2)
    return {"acceptance": "basic_controls_passed_workflows_pending" if basic_pass else "pending",
            "basic_controls_passed": basic_pass, "passed_cases": len(passed),
            "required_cases": len(session["protocol"]), "failed_trials": failures,
            "failed_manual_checks": failed_checks, "manual_checks_pending": missing_failures,
            "distinct_user_restarts": restart_count,
            "next_case": next((c for c in session["protocol"] if c["case"] not in passed), None),
            "workflow_acceptance": "gated_on_basic_controls; no workflows accepted"}


def next_case(directory, session):
    report = summary(directory, session)
    if report["failed_trials"] or report["failed_manual_checks"]:
        raise ValueError("This sequence contains failed trials. Preserve it; correct the cause and initialize a new sequence.")
    if not report["next_case"]:
        raise ValueError("Action trials are complete; finish failure and persistence checkpoints")
    case = report["next_case"]
    needed = 2 if case["path"] == "voice_after_restart" else 1
    if report["distinct_user_restarts"] < needed:
        raise ValueError("Record the required user-operated restart and visible profile dropdown first")
    if (directory / "armed.json").exists():
        armed = read(directory / "armed.json")
        if armed["case"] == case["case"]:
            raise ValueError("This trial is already armed; record its checkpoint before advancing")
    return case


async def run_trial(directory, session, case, physical=False, delay=5, watch_seconds=8):
    identity = deployment(session)
    config = yaml.safe_load(Path(session["profile"]["path"]).read_text(encoding="utf-8-sig"))
    backend = WindowsInput()
    reader = telemetry.JournalReader(Path(session["journal"]))
    resolver = BindingResolver(session["bindings"], session["presets"], config)
    async def observe():
        result = await observe_status(reader, telemetry)
        if result["game_version"] != session["game_version"]:
            raise ValueError("Game version changed; begin a new acceptance sequence")
        if result["data"].get("Flags", 0) & 3:
            raise ValueError("Basic acceptance requires a stationary, undocked ship with a visible exterior")
        return result
    def log(record):
        append(directory / "events", {**record, "case": case["case"], "path": case["path"]})
    await asyncio.sleep(delay)
    if physical:
        context = backend.context()
        before = await observe()
        Printr().print("Physical trial observing now: press the physical key once if needed.", server_only=True)
        await asyncio.sleep(watch_seconds)
        after = await observe()
        bit = 8 if case["action"] == "lights" else 28
        valid = (backend.context() == context and before["session"] == after["session"] and
                 before["observed"] >= context["started"] and after["data"].get("GuiFocus") == 0 and
                 bool(after["data"]["Flags"] & (1 << bit)) == (case["desired"] == "on"))
        if case["state"] == "on" or case["case"] % 3 == 0:
            valid = valid and before["revision"] != after["revision"] and bool((before["data"]["Flags"] ^ after["data"]["Flags"]) & (1 << bit))
        record = {"request_id": uuid4().hex, "outcome": "physical_observed" if valid else "unverified",
                  "input_events": [], "evidence": {"before": before, "after": after, "runtime_identity": identity}}
        log(record)
        return record
    engine = ControlEngine(backend, resolver, observe, log,
                           identity={"pid": os.getpid(), "process_started": process_started(os.getpid()),
                                     "role": "direct_acceptance", "files": expected_files(), "core_deployment": identity})
    from keyboard import keyboard
    loop = asyncio.get_running_loop()
    hook = keyboard.on_press_key("esc", lambda _: loop.call_soon_threadsafe(engine.cancel))
    try:
        result = (await engine.run_result(case["action"], case["state"], "ship", user_text=case["spoken_request"])).to_dict()
        if result["outcome"] == "input_sent":
            observation = await capture_press_observation(directory, session, case, result)
            return {**result, "acceptance_state_observed": observation["observation_outcome"] == "gameplay_observed"}
        return result
    finally:
        keyboard.unhook(hook)
        await engine.close()


async def capture_press_observation(directory, session, case, result):
    """Acceptance-only observation. Normal key commands never wait for this."""
    reader = telemetry.JournalReader(Path(session["journal"]))
    before = result.get("evidence", {}).get("before", {})
    bit = 8 if case["action"] == "lights" else 28
    record = {"event": "game_observation", "request_id": result["request_id"],
              "case": case["case"], "path": case["path"], "observation_outcome": "unverified"}
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            after = await observe_status(reader, telemetry)
            record["after"] = after
            if (before.get("session") == after["session"] and after["observed"] >= before.get("observed", float('inf')) and
                    after["revision"] != before.get("revision") and after["game_version"] == session["game_version"] and
                    after["data"].get("GuiFocus") == 0 and
                    bool(after["data"]["Flags"] & (1 << bit)) == (case["desired"] == "on") and
                    (after["data"]["Flags"] ^ before.get("data", {}).get("Flags", 0)) & (1 << bit)):
                record["observation_outcome"] = "gameplay_observed"
                break
        except (ValueError, OSError) as exc:
            record["observation_error"] = str(exc)
        await asyncio.sleep(0.1)
    append(directory / "events", record)
    return record


async def physical_snapshot(session, delay, known_context=None):
    """Player-paced baseline capture; never constructs an input packet."""
    await asyncio.sleep(delay)
    context = known_context or WindowsInput().context()
    if abs(process_started(context["pid"]) - context["started"]) > 0.01:
        raise ValueError("Physical baseline game process changed")
    reader = telemetry.JournalReader(Path(session["journal"]))
    observation = await observe_status(reader, telemetry)
    data = observation["data"]
    if (observation["observed"] < context["started"] or observation["game_version"] != session["game_version"] or
            data.get("GuiFocus") != 0 or not data.get("Flags", 0) & (1 << 24) or data["Flags"] & 3):
        raise ValueError("A current ship cockpit observation is required; stay undocked with chat and menus closed")
    return {"context": context, "observation": observation}


async def direct_block(directory, session, cases, delay):
    from keyboard import keyboard
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    hook = keyboard.on_press_key("esc", lambda _: loop.call_soon_threadsafe(task.cancel))
    attempted = []
    try:
        for case in cases:
            result = await run_trial(directory, session, case, delay=delay)
            attempted.append(case["case"])
            Printr().print(f"Trial {case['case']}: {result['speech']}", server_only=True)
            if (result["outcome"] not in {"confirmed", "already_set", "input_sent"} or
                    (result["outcome"] == "input_sent" and not result.get("acceptance_state_observed")) or
                    (case["already_set"] and result["input_events"])):
                break
    finally:
        keyboard.unhook(hook)
    return {"attempted_cases": attempted, "player_observation": "pending", "gameplay_acceptance": "pending"}


def physical_result(case, before, after):
    first, last = before["observation"], after["observation"]
    bit = 8 if case["action"] == "lights" else 28
    desired = case["desired"] == "on"
    valid = (before["context"] == after["context"] and first["session"] == last["session"] and
             not first["data"]["Flags"] & 3 and not last["data"]["Flags"] & 3 and
             last["observed"] >= first["observed"] and bool(last["data"]["Flags"] & (1 << bit)) == desired)
    if not case["initial"]:
        valid = valid and first["revision"] != last["revision"] and bool((first["data"]["Flags"] ^ last["data"]["Flags"]) & (1 << bit))
    return {"request_id": uuid4().hex, "case": case["case"], "path": "physical",
            "outcome": "physical_observed" if valid else "unverified", "input_events": [],
            "evidence": {"before": first, "after": last},
            "harness_sha256": fingerprint(Path(__file__))["sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    init = subs.add_parser("init")
    for arg in ("profile", "presets", "journal"):
        init.add_argument("--" + arg, required=True)
    init.add_argument("--game-version", default="auto")
    subs.add_parser("report")
    subs.add_parser("next")
    for name in ("direct-block", "arm-voice-block"):
        sub = subs.add_parser(name)
        if name == "direct-block":
            sub.add_argument("--send-input", action="store_true", required=True)
            sub.add_argument("--delay", type=int, choices=range(3, 31), default=5)
    block_note = subs.add_parser("checkpoint-block")
    block_note.add_argument("--all-matched", action="store_true", required=True)
    block_note.add_argument("--notes", required=True)
    restart = subs.add_parser("restart")
    restart.add_argument("--dropdown-visible", action="store_true", required=True)
    restart.add_argument("--notes", required=True)
    for name in ("physical", "physical-before", "physical-after", "direct", "arm-voice"):
        sub = subs.add_parser(name)
        if name != "arm-voice":
            sub.add_argument("--delay", type=int, choices=range(3, 31), default=5)
        if name == "direct":
            sub.add_argument("--send-input", action="store_true", required=True)
    checkpoint = subs.add_parser("checkpoint")
    checkpoint.add_argument("--visible", choices=("on", "off", "unknown"), required=True)
    checkpoint.add_argument("--heard", default="")
    checkpoint.add_argument("--notes", required=True)
    check = subs.add_parser("failure-check")
    check.add_argument("--check", choices=FAILURES, required=True)
    check.add_argument("--result", choices=("pass", "fail"), required=True)
    check.add_argument("--evidence", type=Path, required=True, help="Private JSON trace with first_failing_stage, input_events, observation and speech")
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = initialize(args.profile, args.presets, args.journal, args.game_version)
        else:
            directory, session = active()
            if args.command in ("report", "next"):
                result = summary(directory, session)
            elif args.command == "restart":
                result = {"identity": deployment(session), "dropdown_visible": True, "notes": args.notes}
                append(directory / "restarts", result)
            elif args.command == "checkpoint":
                case = read(directory / "armed.json")
                if case.get("execution") == "single_press" and case["path"].startswith("voice"):
                    case_events = [e for e in records(directory, "events") if e.get("case") == case["case"]]
                    outcomes = [e for e in case_events if e.get("outcome") == "input_sent"]
                    if len(outcomes) == 1 and not any(e.get("event") == "game_observation" for e in case_events):
                        asyncio.run(capture_press_observation(directory, session, case, outcomes[0]))
                result = {"case": case["case"], "visible": args.visible, "heard": args.heard, "notes": args.notes}
                append(directory / "checkpoints", result)
            elif args.command == "checkpoint-block":
                block = read(directory / "current-block.json")
                events = assigned_events(directory)
                notes = []
                for case in session["protocol"]:
                    if case["case"] not in block["cases"]:
                        continue
                    outcomes = [e for e in events if e.get("case") == case["case"] and e.get("outcome")]
                    if len(outcomes) != 1:
                        raise ValueError("Block is incomplete or contains duplicate calls; record individual failed checkpoints")
                    note = {"case": case["case"], "visible": case["desired"], "notes": args.notes,
                            "heard": outcomes[0].get("speech", "") if case["path"].startswith("voice") else "",
                            "attestation": "player_explicitly_confirmed_every_trial_in_this_block"}
                    if assess_case(case, [e for e in events if e.get("case") == case["case"]], note):
                        raise ValueError("A trace in this block failed; record individual checkpoints and preserve the failure")
                    notes.append(note)
                for note in notes:
                    append(directory / "checkpoints", note)
                result = {"player_confirmed_cases": len(notes)}
            elif args.command == "failure-check":
                evidence = read(args.evidence)
                if not all(key in evidence for key in ("first_failing_stage", "input_events", "observation", "speech")):
                    raise ValueError("Failure check needs the actual trace, observation and spoken result")
                result = {"check": args.check, "passed": args.result == "pass", "evidence": evidence}
                append(directory / "failure_checks", result)
            elif args.command == "physical-after":
                deployment(session)
                case = read(directory / "armed.json")
                if case["path"] != "physical" or any(e.get("case") == case["case"] and e.get("outcome") for e in records(directory, "events")):
                    raise ValueError("No unfinished physical trial is armed")
                before = read(directory / f"physical-before-{case['case']}.json")
                after = asyncio.run(physical_snapshot(session, args.delay, before["context"]))
                result = physical_result(case, before, after)
                append(directory / "events", result)
            elif args.command in ("direct-block", "arm-voice-block"):
                case = next_case(directory, session)
                path = "direct" if args.command == "direct-block" else "voice"
                if not case["path"].startswith(path):
                    raise ValueError("Next case requires " + case["path"])
                if path == "voice" and case.get("execution") == "single_press":
                    raise ValueError("Use individual arm-voice/checkpoint trials for single-press observation; voice blocks are legacy-only")
                deployment(session)
                cases = [c for c in session["protocol"] if c["path"] == case["path"] and c["action"] == case["action"] and c["case"] >= case["case"]]
                block = {"path": case["path"], "cases": [c["case"] for c in cases]}
                append(directory / "blocks", block)
                (directory / "current-block.json").write_text(json.dumps(block), encoding="utf-8")
                (directory / "armed.json").write_text(json.dumps(case), encoding="utf-8")
                result = {"cases": cases} if path == "voice" else asyncio.run(direct_block(directory, session, cases, args.delay))
            else:
                case = next_case(directory, session)
                required = "voice" if args.command == "arm-voice" else args.command.split("-")[0]
                if not case["path"].startswith(required):
                    raise ValueError("Next trial requires the " + case["path"] + " path")
                deployment(session)
                if args.command == "physical-before":
                    previous = sorted(directory.glob('physical-before-*.json'), key=lambda p: int(p.stem.rsplit('-', 1)[1]))
                    known = read(previous[-1])["context"] if previous else None
                    result = asyncio.run(physical_snapshot(session, args.delay, known))
                    with (directory / f"physical-before-{case['case']}.json").open("x", encoding="utf-8") as handle:
                        json.dump(result, handle, indent=2)
                    (directory / "armed.json").write_text(json.dumps(case), encoding="utf-8")
                    result = {"case": case, "next": "Use the physical key if needed, observe the game, then run physical-after and checkpoint."}
                else:
                    (directory / "armed.json").write_text(json.dumps(case), encoding="utf-8")
                    result = case if args.command == "arm-voice" else asyncio.run(run_trial(
                        directory, session, case, physical=args.command == "physical", delay=args.delay))
        Printr().print(json.dumps(result, indent=2), server_only=True)
    except (ValueError, OSError, KeyError, asyncio.CancelledError) as exc:
        Printr().print("Acceptance pending: " + str(exc), server_only=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
