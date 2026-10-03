"""Resolve active controls and verify outcomes; never trust an input call as success."""

import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import re
from uuid import uuid4
from typing import Literal
import xml.etree.ElementTree as ET

from .bindings import ACTIONS, MODES, resolve_preset
from .catalog import ACTION_IDS, BY_MODE_TAG, GENERAL_TAGS, source_mode
from .input import SCAN, MODIFIERS, MOUSE, INPUT_LOCK, InputBlocked
from .result import ControlResult, SCHEMA_REVISION


STATE_BITS = {
    "LandingGearToggle": 2, "ToggleCargoScoop": 9, "ShipSpotLightToggle": 8,
    "NightVisionToggle": 28, "DeployHardpointToggle": 6,
    "ToggleCargoScoop_Buggy": 9, "ToggleBuggyTurretButton": 13, "ToggleDriveAssist": 15,
}
# SRV headlights cycle through multiple intensities; bit 8 cannot verify a toggle.
ALIASES = {"light": "lights", "headlights": "lights", "ship lights": "lights",
           "nightvision": "night vision", "gear": "landing gear", "scoop": "cargo scoop"}
SPOKEN_ACTIONS = {
    "deploy landing gear": "turn on landing gear", "lower landing gear": "turn on landing gear",
    "retract landing gear": "turn off landing gear", "raise landing gear": "turn off landing gear",
    "deploy hardpoints": "turn on hardpoints", "retract hardpoints": "turn off hardpoints",
    "open cargo scoop": "turn on cargo scoop", "close cargo scoop": "turn off cargo scoop",
    "open galaxy map": "toggle galaxy map", "close galaxy map": "toggle galaxy map",
    "open system map": "toggle system map", "close system map": "toggle system map",
    "engage supercruise": "toggle supercruise", "engage frame shift drive": "toggle frame shift drive",
    "engage hyperspace": "request hyperspace jump", "jump to next system": "request hyperspace jump",
    "launch heat sink": "deploy heat sink", "launch chaff": "deploy chaff",
    "pips to engines": "increase engine power", "pips to weapons": "increase weapon power",
    "pips to systems": "increase system power", "balance power": "reset power distribution",
}
# One shared vocabulary for the model schema and the runtime, across vehicle modes.
ControlAction = Literal[ACTION_IDS]


class InvalidRequest(ValueError):
    """The instruction cannot be interpreted safely; no input should be sent."""
UI_ONLY = {"UI_Up", "UI_Down", "UI_Left", "UI_Right", "UI_Select", "UI_Back",
           "CycleNextPanel", "CyclePreviousPanel", "CycleNextPage", "CyclePreviousPage",
           "GalaxyMapHome", "FStopInc", "FStopDec", "FocusDistanceInc", "FocusDistanceDec",
           "ChangeConstructionOption", "PlaceSettlement"}
COCKPIT_INPUTS = {"ForwardKey", "BackwardKey", "PrimaryFire", "SecondaryFire",
    "SteerLeftButton", "SteerRightButton", "VerticalThrustersButton", "ToggleButtonUpInput",
    "IncreaseSpeedButtonMax", "DecreaseSpeedButtonMax", "IncreaseSpeedButtonPartial", "DecreaseSpeedButtonPartial",
    "OrbitLinesToggle", "ChargeECM", "TriggerFieldNeutraliser"}
CAMERA_INPUTS = {"FixCameraWorldToggle", "FixCameraRelativeToggle", "QuitCamera", "ToggleFreeCam",
                 "ToggleRotationLock", "ToggleAdvanceMode", "ExitSettlementPlacementCamera"}


def inactive_tag(tag, mode):
    if tag in UI_ONLY:
        return True  # Execution checks GuiFocus before every press.
    if tag in CAMERA_INPUTS or tag.startswith(("Cam", "FreeCam", "MoveFreeCam", "MovePlacementCam", "PlacementCam", "RollCamera",
            "PhotoCamera", "VanityCamera", "StoreCam", "CommanderCreator_", "ExplorationFSS", "MultiCrew")):
        return True
    if mode != "on_foot" and (tag.startswith("Humanoid") or tag.endswith("_Humanoid")):
        return True
    if mode != "srv" and ("Buggy" in tag or tag == "ToggleDriveAssist"):
        return True
    if mode != "ship" and (tag.startswith("TargetWingman") or tag in {"ToggleFlightAssist", "PrimaryFire", "SecondaryFire"}):
        return True
    return False


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def default_bindings():
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Frontier Developments/Elite Dangerous/Options/Bindings"


def chord_of(binding):
    if binding is None:
        raise ValueError("Unbound slot")
    keys = []
    for child in binding:
        key = child.get("Key")
        if child.tag != "Modifier" or child.get("Device") != "Keyboard" or key not in MODIFIERS or len(child):
            raise ValueError("Unsupported modifier or hold semantics")
        keys.append(key)
    key, device = binding.get("Key"), binding.get("Device")
    if not ((device == "Keyboard" and key in SCAN) or (device == "Mouse" and key in MOUSE)):
        raise ValueError("Needs a keyboard or mouse companion binding")
    keys.append(key)
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate keys in chord")
    return tuple(keys)


def ptt_keys(config):
    """Conservatively exclude every PTT component, including scan-code PTT."""
    result = set()
    codes = config.get("record_key_codes") or []
    if codes:
        result.update(k for k, (code, _) in SCAN.items() if code in codes)
        if not result:
            raise ValueError("Unrecognized push-to-talk scan codes; configure a named key")
    else:
        names = {"ctrl": ("LeftControl", "RightControl"), "control": ("LeftControl", "RightControl"),
                 "shift": ("LeftShift", "RightShift"), "alt": ("LeftAlt", "RightAlt"),
                 "enter": ("Return",), "esc": ("Escape",), "num -": ("Numpad_Subtract",),
                 "num +": ("Numpad_Add",), "page up": ("PageUp",), "page down": ("PageDown",),
                 "up": ("UpArrow",), "down": ("DownArrow",), "left": ("LeftArrow",), "right": ("RightArrow",)}
        names.update({"num " + str(i): ("Numpad_" + str(i),) for i in range(10)})
        names.update({"num /": ("Numpad_Divide",), "num *": ("Numpad_Multiply",),
                      "num .": ("Numpad_Decimal",), "num enter": ("Numpad_Enter",)})
        for key in SCAN:
            short = key[4:]
            names.setdefault(short.casefold(), (short,))
            for prefix in ("Left", "Right"):
                if short.startswith(prefix):
                    suffix = short[len(prefix):].replace("Control", "ctrl").casefold()
                    names[prefix.casefold() + " " + suffix] = (short,)
        named = (config.get("record_key") or "").casefold().replace("num +", "numpad_add")
        for token in named.split("+"):
            token = token.strip()
            if not token:
                continue
            if token not in names:
                raise ValueError("Unrecognized push-to-talk key; inspect controls setup")
            result.update("Key_" + key for key in names[token])
    mouse = config.get("record_mouse_button")
    if mouse:
        key = {"left": "Mouse_1", "right": "Mouse_2", "middle": "Mouse_3", "x": "Mouse_4", "x1": "Mouse_4", "x2": "Mouse_5"}.get(mouse)
        if not key:
            raise ValueError("Unrecognized mouse push-to-talk button")
        result.add(key)
    return result


def overlaps(a, b):
    # Every modifier is also a physical key press. For example, Shift+F10
    # still presses UIFocus when UIFocus is bound to Shift alone.
    def triggers(chord, other):
        return other[-1] in chord and set(other[:-1]) <= set(chord)
    return triggers(a, b) or triggers(b, a)


def all_chords(root):
    result = []
    for node in root:
        for slot in ("Primary", "Secondary", "Binding"):
            try:
                result.append((node.tag, chord_of(node.find(slot))))
            except ValueError:
                pass
    return result


def active_chords(roots, mode):
    occupied = [(t, c) for t, c in all_chords(roots[mode]) if t not in GENERAL_TAGS]
    occupied += [(t, c) for t, c in all_chords(roots["general"]) if t in GENERAL_TAGS]
    return occupied


def conflicting_tags(roots, mode, tag, chord, occupied=None):
    """Shared setup/runtime check against controls active in the same context."""
    metadata = BY_MODE_TAG[(mode, tag)]
    if occupied is None:
        occupied = active_chords(roots, mode)
    other = {t for m, cat in ACTIONS.items() if m != mode for t in cat}

    def relevant(other_tag):
        other_action = BY_MODE_TAG.get((mode, other_tag))
        if other_action:
            return bool(metadata.contexts & other_action.contexts)
        if other_tag in other:
            return False
        if other_tag in UI_ONLY:
            return other_tag in GENERAL_TAGS and bool(metadata.contexts & {1, 2, 4, 5, 6, 7, 8})
        if other_tag.startswith("ExplorationFSS"):
            return 9 in metadata.contexts
        if other_tag.startswith("ExplorationSAA"):
            return 10 in metadata.contexts
        if (other_tag in COCKPIT_INPUTS or "ThrustButton" in other_tag or
                other_tag.startswith(("Humanoid", "Yaw", "Pitch", "Roll", "HeadLook"))):
            return 0 in metadata.contexts and not inactive_tag(other_tag, mode)
        return not inactive_tag(other_tag, mode)

    return {t for t, c in occupied if t != tag and relevant(t) and overlaps(chord, c)}


class BindingResolver:
    def __init__(self, directory, presets, config=None):
        self.directory, self.presets = Path(directory), Path(presets)
        self.config = config or {}

    def read(self):
        selector = self.directory / "StartPreset.4.start"
        raw = selector.read_bytes()
        names = raw.decode("utf-8-sig").splitlines()
        if len(names) != 4 or not all(n.strip() for n in names):
            raise ValueError("Elite's active preset selection is incomplete; retry after saving controls")
        roots, sources = {}, {}
        for mode, name in zip(MODES, names):
            roots[mode], sources[mode] = resolve_preset(name.strip(), self.directory, self.presets)
        blocked = ptt_keys(self.config() if callable(self.config) else self.config)
        available, unavailable = {}, {}
        for mode, catalog in ACTIONS.items():
            occupied = active_chords(roots, mode)
            for tag in catalog:
                nodes = roots[source_mode(mode, tag)].findall(tag)
                reason = "Action is absent from this preset"
                if len(nodes) == 1:
                    node = nodes[0]
                    toggle = node.find("ToggleOn")
                    if toggle is not None and toggle.get("Value", "1") != "1":
                        unavailable[(mode, tag)] = "Configured as hold; choose toggle in Elite controls first"
                        continue
                    reasons = []
                    for slot in ("Primary", "Secondary"):
                        try:
                            chord = chord_of(node.find(slot))
                            if "Key_Escape" in chord:
                                raise ValueError("Escape is reserved for local cancellation")
                            if blocked.intersection(chord):
                                raise ValueError("Binding overlaps push-to-talk")
                            conflicts = conflicting_tags(roots, mode, tag, chord, occupied)
                            if conflicts:
                                raise ValueError("Binding overlaps " + ", ".join(sorted(conflicts)[:3]))
                            available[(mode, tag)] = {"chord": chord, "slot": slot}
                            break
                        except ValueError as exc:
                            reasons.append(str(exc))
                    else:
                        unavailable[(mode, tag)] = "; ".join(dict.fromkeys(reasons))
                else:
                    unavailable[(mode, tag)] = reason
        if raw != selector.read_bytes() or any(digest(Path(s["file"]).read_bytes()) != s["sha256"] for s in sources.values()):
            raise ValueError("Bindings changed while reading; retry after saving controls")
        revision = digest((digest(raw) + json.dumps(sources, sort_keys=True) + repr(sorted(blocked))).encode())
        return {"roots": roots, "sources": sources, "revision": revision, "selector_sha256": digest(raw),
                "available": available, "unavailable": unavailable}

    async def stable(self):
        first = await asyncio.to_thread(self.read)
        await asyncio.sleep(0.15)
        second = await asyncio.to_thread(self.read)
        if first["revision"] != second["revision"]:
            raise InputBlocked("Bindings are changing; finish saving controls and repeat the request.")
        return second


def mode_of(data):
    flags, flags2 = data.get("Flags"), data.get("Flags2", 0)
    if type(flags) is not int or type(flags2) is not int or flags < 0 or flags2 < 0:
        raise InputBlocked("Vehicle telemetry is unavailable.")
    if flags2 & 6 or flags & (1 << 25):
        raise InputBlocked("Controls are unavailable in taxi, multicrew or fighter mode.")
    modes = [m for m, active in (("on_foot", flags2 & 1), ("srv", flags & (1 << 26)), ("ship", flags & (1 << 24))) if active]
    if len(modes) != 1:
        raise InputBlocked("No unambiguous active vehicle; enter gameplay and repeat the request.")
    return modes[0]


def normalize_request(action, state=None, mode="auto"):
    """Accept a bounded grammar, never fuzzy substrings or multiple actions."""
    if not isinstance(action, str) or not action.strip() or len(action) > 100:
        raise InvalidRequest("Choose one supported action, such as lights or night_vision.")
    if state not in (None, "on", "off", "toggle") or mode not in ("auto", "ship", "srv", "on_foot"):
        raise InvalidRequest("Invalid state or vehicle mode.")
    value = " ".join(action.casefold().replace("_", " ").strip(" .!").split())
    # Allow a vehicle prefix before or after the state verb, but never contradict it.
    def vehicle(value, mode):
        for candidate in ACTIONS:
            prefix = candidate.replace("_", " ") + " "
            if value.startswith(prefix):
                if mode not in ("auto", candidate):
                    raise InvalidRequest("The action wording and requested vehicle conflict.")
                return value[len(prefix):], candidate
        return value, mode
    value, mode = vehicle(value, mode)
    value = SPOKEN_ACTIONS.get(value, value)
    phrase_state = None
    for verb, intent in (("turn on ", "on"), ("switch on ", "on"), ("enable ", "on"),
                         ("activate ", "on"), ("deactivate ", "off"),
                         ("turn off ", "off"), ("switch off ", "off"), ("disable ", "off"),
                         ("toggle ", "toggle")):
        if value.startswith(verb):
            value, phrase_state = value[len(verb):], intent
            break
    if value.startswith("the "):
        value = value[4:]
    value, mode = vehicle(value, mode)
    if phrase_state is not None:
        if state is not None and state != phrase_state:
            raise InvalidRequest("The action wording and requested on/off state conflict.")
        state = phrase_state
    state = state or "toggle"  # Only omitted legacy state can be inferred.
    value = ALIASES.get(value, value)
    if value in ("status", "diagnostics", "readiness", "controls status"):
        return "status", state, mode
    known = {phrase.removeprefix("toggle ") for cat in ACTIONS.values() for phrase in cat.values()}
    known.update(tag.casefold().replace("_", " ") for cat in ACTIONS.values() for tag in cat)
    if value not in known:
        raise InvalidRequest("Choose one supported action, such as lights or night_vision, with state on, off or toggle.")
    return value, state, mode


def parse_turn(text):
    """Recognize one bounded control phrase; never use substring/fuzzy matching."""
    if text.strip().endswith("?") and not re.match(
            r"\s*(?:please |(?:can|could|would) you |turn |switch |toggle |engage |deploy |retract )", text, re.I):
        raise InvalidRequest("A question is not a control order.")
    value = " ".join(text.casefold().replace("_", " ").replace("’", "'").strip(" .!? ").split())
    if re.search(r"\b(no|not|never|don't|dont|stop|cancel|without|unless|if|except|instead)\b", value):
        raise InvalidRequest("A negated or conditional instruction needs clarification. No input sent.")
    for prefix in ("could you please ", "can you please ", "would you please ",
                   "please ", "can you ", "could you ", "would you "):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    value = value.removesuffix(" please")
    # Common spoken suffix grammar: 'turn the lights on', 'lights off'.
    suffix = re.fullmatch(r"(?:turn |switch )?(?:the )?(.+?) (on|off)", value)
    if suffix:
        value = "turn " + suffix[2] + " " + suffix[1]
    return normalize_request(value)


def validate_turn(text, action, state, mode, *, require_state=True):
    """Conservative English checkpoint; conflicting wording never authorizes input."""
    expected_action, expected_state, expected_mode = parse_turn(text)
    proposed, proposed_state, proposed_mode = normalize_request(action, state, mode)
    if expected_mode != "auto" and proposed_mode not in ("auto", expected_mode):
        raise InvalidRequest("The tool vehicle conflicts with your request. Please clarify.")
    matched_mode = expected_mode if expected_mode != "auto" else proposed_mode
    # Resolve tags to the shared model-facing ID without guessing a vehicle.
    def canonical(value):
        for catalog in ACTIONS.values():
            for tag, phrase in catalog.items():
                if value == tag.casefold().replace("_", " "):
                    return phrase.removeprefix("toggle ")
        return value
    if canonical(expected_action) != canonical(proposed) or expected_state != proposed_state:
        raise InvalidRequest("The tool action or state conflicts with your request. Please clarify.")
    if require_state and expected_state == "toggle" and canonical(expected_action) in {
            "lights", "night vision", "landing gear", "cargo scoop", "hardpoints"} and "toggle " not in text.casefold():
        raise InvalidRequest("Specify on, off or toggle for this action. No input sent.")
    return proposed, proposed_state, matched_mode


def resolve_action(action, mode):
    value, _, requested = normalize_request(action, mode=mode)
    if requested != mode:
        raise InvalidRequest("The action wording and requested vehicle conflict.")
    for tag, phrase in ACTIONS[mode].items():
        if value in (tag.casefold().replace("_", " "), phrase.removeprefix("toggle ")):
            return tag
    raise InputBlocked("That action is not supported in this mode. Ask for controls status or use Elite's controls.")


class ControlEngine:
    def __init__(self, input_backend, resolver, observe, log=lambda _: None, timeout=3,
                 identity=None, requests=None, single_press=True):
        self.input, self.resolver, self.observe, self.log = input_backend, resolver, observe, log
        self.timeout = timeout
        self.stopping = False
        self.tasks = set()
        self.identity = identity or {}
        self.requests = requests if requests is not None else OrderedDict()
        self.cancel_epoch = 0
        # Spoken individual commands act as keys. The state-aware primitive is
        # retained internally for explicit supervised prerequisites/replay tests.
        self.single_press = single_press

    def cancel(self):
        """Local cancellation invalidates pending checks without an AI round trip."""
        self.cancel_epoch += 1
        for task in tuple(self.tasks):
            task.cancel()

    async def close(self):
        self.stopping = True
        for task in tuple(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)

    async def run(self, action, state=None, mode="auto", **kwargs):
        return (await self.run_result(action, state, mode, **kwargs)).speech

    async def run_result(self, action, state=None, mode="auto", *, request_id=None,
                         user_text=None, still_current=lambda: True, authorization=None):
        request_id = request_id or uuid4().hex
        intent = {"action": action, "state": state, "mode": mode}
        if request_id in self.requests:
            previous = self.requests[request_id]
            result = ControlResult(request_id, intent, "duplicate", "No new input sent.",
                                   evidence={"original_outcome": previous.outcome if previous else "in_progress"})
            self.log(result.to_dict())
            return result
        if len(self.requests) >= 256:
            result = ControlResult(request_id, intent, "blocked", "Too many calls in this turn. Make a fresh user request.", "routing")
            self.log(result.to_dict())
            return result
        if self.stopping:
            result = ControlResult(request_id, intent, "blocked", "Elite controls are disabled.", "prerequisites")
            self.log(result.to_dict())
            return result
        if not INPUT_LOCK.acquire(blocking=False):
            result = ControlResult(request_id, intent, "blocked", "Another Elite action is in progress. Repeat the request when it finishes.", "prerequisites")
            self.log(result.to_dict())
            return result
        task = asyncio.current_task()
        self.tasks.add(task)
        self.requests[request_id] = None
        started = time.monotonic()
        epoch = self.cancel_epoch
        audit = {"request_id": request_id, "action": str(action)[:100], "state": state,
                 "requested_mode": mode, "started_at": datetime.now(timezone.utc).isoformat(),
                 "runtime_identity": self.identity, "stage": "user_intent", "timing_ms": {}}
        def stage(name):
            audit["timing_ms"][name] = round((time.monotonic() - started) * 1000, 3)
            audit["stage"] = name
        def current():
            if not still_current() or self.cancel_epoch != epoch:
                return False
            if authorization is not None:
                turn_id, _, call_id = request_id.partition(":")
                authorization.validate(turn_id, action, state, mode, call_id)
            return True
        self.input.sent = []
        outcome, reason = "failed", "Control execution did not finish."
        cancelled = False
        try:
            if authorization is not None:
                turn_id, _, call_id = request_id.partition(":")
                authorization.validate(turn_id, action, state, mode, call_id)
                audit["routing_context"] = authorization.context
            elif user_text is not None:
                action, state, mode = validate_turn(user_text, action, state, mode,
                                                   require_state=not self.single_press)
            action, state, mode = normalize_request(action, state, mode)
            if user_text is not None and any(a.explicit and action in {
                    a.id.replace("_", " "), a.tag.casefold().replace("_", " ")} for a in BY_MODE_TAG.values()):
                from .routing import explicit_cargo_order
                if not explicit_cargo_order(user_text):
                    raise InvalidRequest("Please explicitly order eject all cargo, Commander.")
            intent = {"action": action.replace(" ", "_"), "state": state, "mode": mode,
                      "execution": "single_press" if self.single_press else "set_state"}
            if not current():
                raise InvalidRequest("The originating user turn is no longer current. No input sent.")
            stage("routing")
            outcome, reason = await self._run(action, state, mode, audit, stage, current)
        except InvalidRequest as exc:
            outcome, reason = "invalid", str(exc)
        except asyncio.CancelledError:
            cancelled = True
            outcome = "unverified" if self.input.sent else "cancelled"
            reason = "Control cancelled; no retry sent." + (" Input was attempted; check the game." if self.input.sent else "")
        except Exception as exc:
            if getattr(exc, "evidence", None):
                audit["observation_error"] = exc.evidence
            if getattr(exc, "stage", None):
                audit["stage"] = exc.stage
            if any(event.get("inserted") for event in self.input.sent):
                outcome, reason = "unverified", "Input was attempted. "
            elif self.input.sent:
                outcome, reason = "failed", "Windows did not accept the input. "
            else:
                outcome, reason = "blocked", ""
            reason += str(exc)[:220]
        finally:
            audit["input_events"] = list(self.input.sent)
            audit["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
            result = ControlResult(request_id, intent, outcome, reason,
                                   "" if outcome in {"confirmed", "already_set", "status", "input_sent"} else audit["stage"],
                                   list(self.input.sent), audit)
            self.requests[request_id] = result
            try:
                self.log({**audit, **result.to_dict()})
            finally:
                self.tasks.discard(task)
                INPUT_LOCK.release()
        if cancelled:
            raise asyncio.CancelledError
        return result

    async def _run(self, action, state, mode, audit, stage, still_current):
        action, state, mode = normalize_request(action, state, mode)
        audit.update(normalized_action=action, resolved_state=state, resolved_mode=mode)
        stage("prerequisites")
        context = self.input.context()
        audit["foreground_pid"] = context["pid"]
        audit["game_started"] = context["started"]
        stage("binding")
        binding = await self.resolver.stable()
        audit["binding_revision"] = binding["revision"]
        stage("prerequisites")
        before = await self.observe()
        data = before["data"]
        actual = mode_of(data)
        routed_context = audit.get("routing_context")
        if routed_context and routed_context != routing_context(context, before):
            raise InputBlocked("Game context changed while interpreting the request. Please repeat it.")
        if mode != "auto" and mode != actual:
            raise InputBlocked("Requested controls do not match the active vehicle.")
        if action.casefold().strip() in ("status", "diagnostics", "readiness"):
            ready = sum(m == actual for m, _ in binding["available"])
            missing = [ACTIONS[m][tag] for m, tag in binding["unavailable"] if m == actual]
            return "status", f"{ready}/{len(ACTIONS[actual])} configured for {actual.replace('_', ' ')}; Windows acceptance and gameplay verification require separate trials." + (
                " Needs setup: " + ", ".join(missing[:5]) + ("; more in the setup report." if len(missing) > 5 else ".") if missing else "")
        tag = resolve_action(action, actual)
        metadata = BY_MODE_TAG[(actual, tag)]
        audit["tag"], audit["mode"] = tag, actual
        stage("binding")
        if (actual, tag) not in binding["available"]:
            raise InputBlocked(binding["unavailable"][(actual, tag)] + ". Run controls inspect/repair.")
        entry = binding["available"][(actual, tag)]
        audit["binding"] = entry
        bit = STATE_BITS.get(tag)
        map_focus = {"galaxy_map": 6, "system_map": 7}.get(metadata.id)
        if not self.single_press and state != "toggle" and bit is None:
            raise InputBlocked("This action has no reliable on/off observation. Request a toggle or the named action instead.")
        current = bool(data["Flags"] & (1 << bit)) if bit is not None else None
        desired = (not current if state == "toggle" else state == "on") if bit is not None else None
        label = ACTIONS[actual][tag].removeprefix("toggle ")
        sending = True

        async def check():
            if self.stopping or not still_current():
                raise InputBlocked("Controls were cancelled or a new user turn arrived.", "prerequisites")
            try:
                now_context = self.input.context()
            except (ValueError, OSError) as exc:
                raise InputBlocked(str(exc), "prerequisites") from exc
            if now_context["pid"] != context["pid"] or now_context["started"] != context["started"]:
                raise InputBlocked("Game process changed; repeat the request.", "prerequisites")
            try:
                current_binding = await asyncio.to_thread(self.resolver.read)
            except (ValueError, OSError, ET.ParseError) as exc:
                raise InputBlocked("Cannot read current bindings: " + str(exc), "binding") from exc
            if current_binding["revision"] != binding["revision"]:
                raise InputBlocked("Bindings changed; repeat the request.", "binding")
            now = await self.observe()
            if now["session"] != before["session"] or now["observed"] < context["started"] or mode_of(now["data"]) != actual:
                raise InputBlocked("Game session or vehicle changed; repeat the request.", "prerequisites")
            focus = now["data"].get("GuiFocus")
            if type(focus) is not int or focus not in metadata.contexts or now["data"]["Flags"] & (1 << 30):
                raise InputBlocked("This control is unavailable in the current menu/chat context, Commander.", "prerequisites")
            observed_context = routing_context(now_context, now)
            if not sending and map_focus is not None and routed_context:
                # Only the expected map UI transition is allowed after input.
                # Vehicle, process, session and other context remain mandatory.
                observed_context["ui"] = routed_context["ui"]
            if routed_context and routed_context != observed_context:
                raise InputBlocked("Game context changed after routing. Please repeat the request.")
            if metadata.flight_only and now["data"]["Flags"] & 3:
                raise InputBlocked("This action is unavailable while docked or landed.")
            if metadata.supercruise_only and not now["data"]["Flags"] & (1 << 4):
                raise InputBlocked("Enter supercruise before opening the full spectrum scanner.")
            if not self.single_press and sending and bit is not None and bool(now["data"]["Flags"] & (1 << bit)) != current:
                raise InputBlocked("State changed before input; repeat the request.")
            # Observation may wait briefly for the game's clock. Focus must
            # still be valid immediately before a new press or confirmation.
            if self.stopping or not still_current():
                raise InputBlocked("Controls were cancelled or a new user turn arrived.", "prerequisites")
            try:
                final_context = self.input.context()
            except (ValueError, OSError) as exc:
                raise InputBlocked(str(exc), "prerequisites") from exc
            if final_context != context:
                raise InputBlocked("Game focus or process changed; repeat the request.", "prerequisites")
            return now

        stage("prerequisites")
        await check()
        audit["before"] = before
        if not self.single_press and bit is not None and current == desired:
            return "already_set", f"{label} {'on' if desired else 'off'}."
        stage("input")
        await self.input.send(entry["chord"], check)
        sending = False
        if map_focus is not None:
            stage("game_observation")
            expected_focus = 0 if data.get("GuiFocus") == map_focus else map_focus
            audit["expected_gui_focus"] = expected_focus
            try:
                async with asyncio.timeout(self.timeout):
                    while True:
                        await asyncio.sleep(0.1)
                        after = await check()
                        audit["after"] = after
                        if (after["revision"] != before["revision"] and
                                after["observed"] >= before["observed"] and
                                after["data"].get("GuiFocus") == expected_focus):
                            return "confirmed", f"{label} {'closed' if expected_focus == 0 else 'open'}."
            except TimeoutError:
                return "unverified", f"{label} input was sent, but the map {'closing' if expected_focus == 0 else 'opening'} was not observed. No retry was sent."
        if self.single_press:
            return "input_sent", f"{label.capitalize()} key sent."
        stage("game_observation")
        if bit is None:
            return "unverified", f"{label} input sent; the game does not expose a reliable confirmation for this action."
        end = time.monotonic() + self.timeout
        while time.monotonic() < end:
            await asyncio.sleep(0.1)
            after = await check()
            audit["after"] = after
            if after["revision"] != before["revision"] and after["observed"] >= before["observed"] and bool(after["data"]["Flags"] & (1 << bit)) == desired:
                return "confirmed", f"{label} {'on' if desired else 'off'}."
        return "unverified", f"{label} input was sent, but the requested state was not observed. No retry was sent."


def routing_context(process, observation):
    """Only stable safety context, not timestamps or unrelated changing telemetry."""
    data = observation["data"]
    return {"pid": process["pid"], "started": process["started"], "session": observation["session"],
            "mode": mode_of(data), "ui": data.get("GuiFocus"),
            "flight": data["Flags"] & (3 | (1 << 4) | (1 << 30)),
            "flags2": data.get("Flags2", 0) & 7}
