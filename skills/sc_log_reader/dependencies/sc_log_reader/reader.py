"""Tier 3: bounded records and a closed, data-only instruction language."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any

import regex

from . import __version__
from .contracts import field_errors

MAX_PACKAGE_BYTES = 512 * 1024
MAX_RECORD_BYTES = 64 * 1024
REGEX_TIMEOUT_SECONDS = 0.050
PARSE_TIMEOUT_SECONDS = 0.100
ENGINE_VERSION = 3
EVENTS = frozenset(
    [
        "armistice_zone",
        "attachment_received",
        "bleeding",
        "blueprint_received",
        "cargo_transfer",
        "channel_change",
        "commodity_buy",
        "commodity_sell",
        "contract_accepted",
        "contract_available",
        "contract_complete",
        "contract_failed",
        "contract_withdrawn",
        "contract_shared",
        "crimestat_increased",
        "emergency_services",
        "entered_monitored_space",
        "exited_monitored_space",
        "fatal_collision",
        "fined",
        "fuel_low",
        "hangar_queue",
        "hangar_ready",
        "incapacitated",
        "incoming_call",
        "injury",
        "insurance_claim",
        "insurance_claim_complete",
        "inventory_location_update",
        "join_pu",
        "journal_entry",
        "jurisdiction_change",
        "location_change",
        "med_bed_heal",
        "monitored_space_down",
        "monitored_space_restored",
        "objective_complete",
        "objective_new",
        "objective_withdrawn",
        "party_invite",
        "party_left",
        "party_member_joined",
        "personal_inventory_data",
        "qt_arrived",
        "qt_calibration_complete_group",
        "quantum_calibration_complete",
        "quantum_calibration_started",
        "quantum_route_set",
        "refinery_complete",
        "refinery_submitted",
        "restricted_area",
        "reward_earned",
        "session_start",
        "shop_buy",
        "shop_sell",
        "shop_transaction_result",
        "transaction_complete",
        "user_login",
        "vehicle_impounded",
        "money_sent",
    ]
)
FLAGS = {"IGNORECASE": regex.I, "DOTALL": regex.S}


class InstructionError(ValueError):
    pass


class ReaderUpgradeRequired(InstructionError):
    pass


def bundled_bytes() -> bytes:
    return files("sc_log_reader").joinpath("data/instructions.json").read_bytes()


def _keys(obj, required, optional=()):
    if (
        not isinstance(obj, dict)
        or not set(required) <= obj.keys()
        or obj.keys() - set(required) - set(optional)
    ):
        raise InstructionError("Unexpected or missing instruction keys")


def _text(value, maximum=4096):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise InstructionError("Expected bounded nonempty text")


def _names(values):
    if not isinstance(values, list) or len(values) > 128:
        raise InstructionError("Expected bounded list")
    for value in values:
        _text(value, 128)


def _repeat_bounds(value):
    """Inspect bounded pattern text without running another matching expression."""
    for fragment in value.split("{")[1:]:
        bound, closing, _ = fragment.partition("}")
        if not closing:
            continue
        parts = bound.split(",")
        if (
            len(parts) <= 2
            and parts[0].isdecimal()
            and (len(parts) == 1 or not parts[1] or parts[1].isdecimal())
        ):
            yield parts


def _pattern(value, flags=()):
    _text(value, 2048)
    # Reject compile-time expansion before invoking the regex compiler.
    repeat_cost = 1
    for bound in _repeat_bounds(value):
        if any(part and (len(part) > 4 or int(part) > 1000) for part in bound):
            raise InstructionError("Regex repeat bound exceeds engine limit")
        repeat_cost *= max(int(part) for part in bound if part)
        if repeat_cost > 10000:
            raise InstructionError("Regex repetition complexity exceeds engine limit")
    if not isinstance(flags, (list, tuple)) or any(f not in FLAGS for f in flags):
        raise InstructionError("Unsupported regex flags")
    try:
        return regex.compile(value, sum(FLAGS[f] for f in set(flags)))
    except regex.error as exc:
        raise InstructionError("Invalid regex") from exc


def _source(value):
    if value not in ("record.text", "notification.text") and not (
        isinstance(value, str) and value.startswith("fields.") and len(value) < 140
    ):
        raise InstructionError("Unsupported input source")


def _condition(c, depth=0):
    if depth > 8 or not isinstance(c, dict):
        raise InstructionError("Invalid condition nesting")
    if "all" in c or "any" in c:
        key = "all" if "all" in c else "any"
        _keys(c, [key])
        if not isinstance(c[key], list) or not 1 <= len(c[key]) <= 32:
            raise InstructionError("Invalid condition list")
        for child in c[key]:
            _condition(child, depth + 1)
    elif "not" in c:
        _keys(c, ["not"])
        _condition(c["not"], depth + 1)
    else:
        key = "contains" if "contains" in c else "regex"
        _keys(c, [key, "source"], ["flags"])
        _source(c["source"])
        _text(c[key])
        if key == "regex":
            _pattern(c[key], c.get("flags", []))
        elif "flags" in c:
            raise InstructionError("Flags require regex")


def _steps(steps, lookups, depth=0):
    if depth > 6 or not isinstance(steps, list) or len(steps) > 32:
        raise InstructionError("Invalid operation list")
    for s in steps:
        if not isinstance(s, dict):
            raise InstructionError("Invalid operation")
        op = s.get("op")
        if op == "capture":
            _keys(s, ["op", "source", "pattern", "groups"], ["flags"])
            _source(s["source"])
            p = _pattern(s["pattern"], s.get("flags", []))
            if not isinstance(s["groups"], dict) or not s["groups"]:
                raise InstructionError("Capture fields missing")
            for index, name in s["groups"].items():
                if not index.isdecimal() or not 1 <= int(index) <= p.groups:
                    raise InstructionError("Invalid capture group")
                _text(name, 128)
        elif op == "bracket_fields":
            _keys(s, ["op", "source", "fields"])
            _source(s["source"])
            if not isinstance(s["fields"], dict) or len(s["fields"]) > 64:
                raise InstructionError("Invalid bracket fields")
            for name, aliases in s["fields"].items():
                _text(name, 128)
                _names(aliases if isinstance(aliases, list) else [aliases])
        elif op == "constant":
            _keys(s, ["op", "fields"])
            if not isinstance(s["fields"], dict) or len(s["fields"]) > 64:
                raise InstructionError("Invalid constants")
            for name, value in s["fields"].items():
                _text(name, 128)
                if (
                    not isinstance(value, (str, int, float, bool))
                    or isinstance(value, str)
                    and len(value) > 1024
                ):
                    raise InstructionError("Only scalar constants supported")
        elif op == "normalize":
            _keys(s, ["op", "field", "steps"])
            _text(s["field"], 128)
            if not isinstance(s["steps"], list) or len(s["steps"]) > 16:
                raise InstructionError("Invalid normalizers")
            for step in s["steps"]:
                if isinstance(step, str):
                    if step not in ("trim", "remove_commas", "int", "float", "lower"):
                        raise InstructionError("Unknown normalizer")
                elif isinstance(step, dict) and set(step) == {"regex_replace"}:
                    _keys(step["regex_replace"], ["pattern", "replacement"])
                    replacement_pattern = _pattern(step["regex_replace"]["pattern"])
                    if (
                        not isinstance(step["regex_replace"]["replacement"], str)
                        or len(step["regex_replace"]["replacement"]) > 256
                        or "\\" in step["regex_replace"]["replacement"]
                    ):
                        raise InstructionError("Invalid replacement")
                    try:
                        replacement_pattern.sub(
                            step["regex_replace"]["replacement"],
                            "",
                            timeout=REGEX_TIMEOUT_SECONDS,
                        )
                    except (regex.error, IndexError, TimeoutError) as exc:
                        raise InstructionError(
                            "Invalid replacement expression"
                        ) from exc
                else:
                    raise InstructionError("Unknown normalizer")
        elif op == "choose":
            _keys(s, ["op", "cases"])
            if not isinstance(s["cases"], list) or not 1 <= len(s["cases"]) <= 16:
                raise InstructionError("Invalid alternatives")
            for case in s["cases"]:
                _keys(case, ["when", "steps"])
                _condition(case["when"])
                _steps(case["steps"], lookups, depth + 1)
        elif op == "collect_true_fields":
            _keys(s, ["op", "field", "names"])
            _text(s["field"], 128)
            _names(s["names"])
        elif op == "exclude_values":
            _keys(s, ["op", "field", "table"])
            _text(s["field"], 128)
            if not isinstance(lookups.get(s["table"]), list):
                raise InstructionError("Exclusion table missing")
        elif op == "quantity_with_unit":
            _keys(s, ["op", "source", "number_field", "unit_field", "accepted_units"])
            _source(s["source"])
            _text(s["number_field"], 128)
            _text(s["unit_field"], 128)
            _names(s["accepted_units"])
        elif op == "notification_payload":
            _keys(s, ["op", "label", "field"])
            _text(s["label"], 256)
            _text(s["field"], 128)
        else:
            raise InstructionError(f"Unknown operation: {op}")


def _unique(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise InstructionError("Duplicate JSON key")
        result[k] = v
    return result


class Instructions:
    def __init__(self, data, raw):
        self.data = data
        self.raw = raw
        self.revision = data["revision"]
        self.version = data["version"]

    @classmethod
    def load(cls, raw: bytes):
        if len(raw) > MAX_PACKAGE_BYTES:
            raise InstructionError("Instruction file exceeds size limit")
        try:
            d = json.loads(
                raw,
                object_pairs_hook=_unique,
                parse_constant=lambda x: (_ for _ in ()).throw(
                    InstructionError("Nonfinite number")
                ),
            )
            _keys(
                d,
                [
                    "format_version",
                    "engine_version",
                    "package_id",
                    "revision",
                    "version",
                    "release_notes",
                    "verified_game_builds",
                    "framing",
                    "ignore_records",
                    "lookups",
                    "rules",
                ],
                ["minimum_reader_version"],
            )
            minimum = d.get("minimum_reader_version", "0.1.0")
            if not isinstance(minimum, str) or not regex.fullmatch(
                r"\d{1,4}\.\d{1,4}\.\d{1,4}", minimum
            ):
                raise InstructionError("Invalid minimum reader version")
            if tuple(map(int, minimum.split("."))) > tuple(
                map(int, __version__.split("."))
            ):
                raise ReaderUpgradeRequired(
                    "Reader " + minimum + " or newer is required"
                )
            if (
                type(d["format_version"]) is not int
                or d["format_version"] != 1
                or type(d["engine_version"]) is not int
                or d["engine_version"] not in (1, 2, ENGINE_VERSION)
                or d["package_id"] not in ("sc_log_reader", "sc_log_reader_2")
            ):
                raise InstructionError("Incompatible instruction package")
            if type(d["revision"]) is not int or d["revision"] < 1:
                raise InstructionError("Invalid revision")
            _text(d["version"], 128)
            if (
                not isinstance(d["release_notes"], str)
                or len(d["release_notes"]) > 4096
            ):
                raise InstructionError("Invalid release notes")
            _names(d["verified_game_builds"])
            _keys(
                d["framing"],
                ["record_start", "timestamp", "notification"],
                ["notification_continuation", "game_build"],
            )
            for p in d["framing"].values():
                _pattern(p)
            if (
                _pattern(d["framing"]["notification"]).groups != 1
                or _pattern(d["framing"]["timestamp"]).groups != 1
            ):
                raise InstructionError("Framing requires exactly one capture")
            if (
                "game_build" in d["framing"]
                and _pattern(d["framing"]["game_build"]).groups != 1
            ):
                raise InstructionError("Game build framing requires one capture")
            if (
                not isinstance(d["ignore_records"], list)
                or len(d["ignore_records"]) > 32
            ):
                raise InstructionError("Invalid ignore conditions")
            for c in d["ignore_records"]:
                _condition(c)
            _keys(
                d["lookups"],
                [
                    "ship_manufacturer_prefixes",
                    "ship_manufacturer_names",
                    "cosmetic_ports",
                    "locations",
                    "system_prefixes",
                ],
            )
            for key in (
                "ship_manufacturer_prefixes",
                "ship_manufacturer_names",
                "cosmetic_ports",
            ):
                _names(d["lookups"][key])
            if (
                not isinstance(d["lookups"]["locations"], dict)
                or len(d["lookups"]["locations"]) > 2048
            ):
                raise InstructionError("Invalid locations")
            for code, loc in d["lookups"]["locations"].items():
                _text(code, 128)
                _keys(loc, ["name", "system"])
                _text(loc["name"], 256)
                _text(loc["system"], 128)
            if not isinstance(d["lookups"]["system_prefixes"], dict):
                raise InstructionError("Invalid system prefixes")
            for key, value in d["lookups"]["system_prefixes"].items():
                _text(key, 128)
                _text(value, 128)
            if not isinstance(d["rules"], list) or not 1 <= len(d["rules"]) <= 128:
                raise InstructionError("Invalid rules")
            ids = set()
            for r in d["rules"]:
                _keys(r, ["id", "event", "match", "read", "required"])
                _text(r["id"], 128)
                if r["id"] in ids or r["event"] not in EVENTS:
                    raise InstructionError("Duplicate rule ID or unknown event")
                ids.add(r["id"])
                _condition(r["match"])
                _steps(r["read"], d["lookups"])
                _names(r["required"])
        except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
            if isinstance(exc, InstructionError):
                raise
            raise InstructionError("Malformed instruction package") from exc
        return cls(d, raw)


@dataclass
class Event:
    event_type: str
    fields: dict[str, Any] = field(default_factory=dict)
    source_timestamp: datetime | None = None
    errors: list[str] = field(default_factory=list)
    rule_id: str = ""
    instruction_version: str = ""
    game_build_verified: bool = False


class _Excluded(Exception):
    pass


class _DeadlineExceeded(TimeoutError):
    pass


class _OperationDeadlineExceeded(TimeoutError):
    pass


class _ParseBudget:
    def __init__(self):
        self.deadline = time.monotonic() + PARSE_TIMEOUT_SECONDS
        self.stage = "record"
        self.rule_id = ""

    def check(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _DeadlineExceeded
        return remaining


class _OperationBudget:
    """One elapsed allowance, including all yields of a lazy regex iterator."""

    def __init__(self, entry):
        self.entry = entry
        now = time.monotonic()
        self.timeout = min(REGEX_TIMEOUT_SECONDS, entry.check())
        self.deadline = now + self.timeout

    def check(self):
        self.entry.check()
        if time.monotonic() >= self.deadline:
            raise _OperationDeadlineExceeded


def _dispatch_literals(condition):
    """Return safe necessary record literals and whether evaluation is harmless.

    Only literal tests can be skipped freely. An earlier regex may produce a
    diagnostic even when a later literal makes the whole condition false, so
    an all-condition contributes literals only through its first unsafe child.
    Unknown forms retain the interpreter path.
    """
    if "all" in condition:
        required = set()
        for child in condition["all"]:
            literals, harmless = _dispatch_literals(child)
            required.update(literals)
            if not harmless:
                return frozenset(required), False
        return frozenset(required), True
    if "any" in condition:
        branches = [_dispatch_literals(child) for child in condition["any"]]
        required = frozenset.intersection(*(literals for literals, _ in branches))
        return required, all(harmless for _, harmless in branches)
    if "not" in condition:
        return frozenset(), _dispatch_literals(condition["not"])[1]
    if "contains" in condition:
        required = (
            frozenset([condition["contains"]])
            if condition.get("source") == "record.text"
            else frozenset()
        )
        return required, True
    return frozenset(), False


class Reader:
    def __init__(self, instructions: Instructions):
        self.instructions = instructions
        self._compiled = {}
        groups = {}
        for index, rule in enumerate(instructions.data["rules"]):
            literals, _ = _dispatch_literals(rule["match"])
            groups.setdefault(literals, []).append((index, rule))
        self._dispatch_groups = tuple(
            (tuple(sorted(literals, key=lambda value: (-len(value), value))), rules)
            for literals, rules in groups.items()
        )

    def _candidates(self, text, budget):
        candidates = []
        for literals, rules in self._dispatch_groups:
            budget.check()
            if all(literal in text for literal in literals):
                candidates.extend(rules)
        # Grouping must never reorder potentially diagnostic rule evaluations.
        return (rule for _, rule in sorted(candidates, key=lambda item: item[0]))

    def _compiled_pattern(self, pattern, flags=()):
        """Validate and compile without a redundant trial search."""
        key = (pattern, tuple(flags))
        if key not in self._compiled:
            self._compiled[key] = _pattern(pattern, flags)
        return self._compiled[key]

    def parse(self, text: str, *, complete=True, game_build=None) -> Event | None:
        budget = _ParseBudget()
        self.last_disposition = "unknown"
        self.last_record_kind = "unknown"
        self.last_notification_complete = None
        if len(text) > MAX_RECORD_BYTES or len(text.encode("utf-8")) > MAX_RECORD_BYTES:
            return Event(
                "diagnostic",
                errors=["record_too_large"],
                instruction_version=self.instructions.version,
            )
        context = {"record.text": text, "notification.text": ""}
        fields = {}
        errors = [] if complete else ["incomplete_record"]

        def search(pattern, value, flags=(), replace=None):
            budget.check()
            p = self._compiled_pattern(pattern, flags)
            operation = _OperationBudget(budget)
            if replace is not None:
                result = p.sub(replace, value, timeout=operation.timeout)
            else:
                result = p.search(value, timeout=operation.timeout)
            operation.check()
            return result

        def iterate(pattern, value):
            budget.check()
            p = self._compiled_pattern(pattern)
            operation = _OperationBudget(budget)
            iterator = p.finditer(value, timeout=operation.timeout)
            while True:
                operation.check()
                try:
                    match = next(iterator)
                except StopIteration:
                    operation.check()
                    return
                operation.check()
                yield match

        def source(name):
            return (
                str(fields.get(name[7:], ""))
                if name.startswith("fields.")
                else context[name]
            )

        def matches(c):
            budget.check()
            if "all" in c:
                return all(matches(x) for x in c["all"])
            if "any" in c:
                return any(matches(x) for x in c["any"])
            if "not" in c:
                return not matches(c["not"])
            value = source(c["source"])
            return (
                c["contains"] in value
                if "contains" in c
                else bool(search(c["regex"], value, c.get("flags", [])))
            )

        def execute(steps):
            for s in steps:
                op = s["op"]
                budget.stage = op
                budget.check()
                if op == "capture":
                    m = search(s["pattern"], source(s["source"]), s.get("flags", []))
                    if m:
                        for index, name in s["groups"].items():
                            budget.check()
                            if m[int(index)] is not None:
                                fields[name] = m[int(index)]
                elif op == "bracket_fields":
                    for name, aliases in s["fields"].items():
                        budget.check()
                        values = []
                        for alias in (
                            aliases if isinstance(aliases, list) else [aliases]
                        ):
                            budget.check()
                            pattern = (
                                r"(?<![\w])"
                                + regex.escape(alias)
                                + r"\s*:?\s*\[([^\]]*)\]"
                            )
                            for m in iterate(pattern, source(s["source"])):
                                if m[1].strip():
                                    values.append(m[1].strip())
                        if len(set(values)) > 1:
                            errors.append("conflicting_aliases:" + name)
                        elif values:
                            fields[name] = values[0]
                elif op == "constant":
                    fields.update(s["fields"])
                elif op == "normalize":
                    name = s["field"]
                    if name not in fields:
                        continue
                    try:
                        value = fields[name]
                        for step in s["steps"]:
                            budget.check()
                            if step == "trim":
                                value = str(value).strip()
                            elif step == "lower":
                                value = str(value).lower()
                            elif step == "remove_commas":
                                value = str(value).replace(",", "")
                            elif step == "int":
                                value = int(value)
                            elif step == "float":
                                value = float(value)
                            else:
                                v = step["regex_replace"]
                                value = search(
                                    v["pattern"], str(value), replace=v["replacement"]
                                )
                            if isinstance(value, str) and len(value) > MAX_RECORD_BYTES:
                                raise ValueError("Normalized field exceeds limit")
                        if isinstance(value, float) and not math.isfinite(value):
                            raise ValueError
                        fields[name] = value
                    except (
                        ValueError,
                        TypeError,
                        OverflowError,
                        IndexError,
                        regex.error,
                    ):
                        fields.pop(name, None)
                        errors.append("invalid:" + name)
                elif op == "choose":
                    for case in s["cases"]:
                        budget.check()
                        if matches(case["when"]):
                            execute(case["steps"])
                            break
                elif op == "collect_true_fields":
                    fields[s["field"]] = {
                        name: True
                        for name in s["names"]
                        if search(r"\b" + regex.escape(name) + r"\s*:\s*true\b", text)
                    }
                elif op == "exclude_values":
                    if (
                        fields.get(s["field"])
                        in self.instructions.data["lookups"][s["table"]]
                    ):
                        raise _Excluded
                elif op == "quantity_with_unit":
                    m = search(
                        r"^\s*([\d,]+(?:\.\d+)?)\s*([A-Za-z]+)\s*$", source(s["source"])
                    )
                    if m and m[2] in s["accepted_units"]:
                        fields[s["number_field"]] = float(m[1].replace(",", ""))
                        fields[s["unit_field"]] = m[2]
                elif op == "notification_payload":
                    m = search(
                        "^" + regex.escape(s["label"]) + r"\s*:\s*(.*)$",
                        context["notification.text"],
                        ["DOTALL"],
                    )
                    if m:
                        fields[s["field"]] = m[1].strip().removesuffix(":").rstrip()

        try:
            budget.stage = "notification"
            framing = self.instructions.data["framing"]
            m = search(framing["notification"], text, ["DOTALL"])
            self.last_record_kind = "notification" if m else "other"
            if m and m[1] is not None:
                if (
                    not m[0].endswith('"') or m.end(1) == m.end()
                ) and "incomplete_record" not in errors:
                    errors.append("incomplete_record")
                context["notification.text"] = (
                    m[1].replace("\\n", "\n").replace('\\"', '"').strip()
                )
                self.last_notification_complete = "incomplete_record" not in errors
            budget.stage = "ignore"
            if any(matches(c) for c in self.instructions.data["ignore_records"]):
                budget.check()
                self.last_disposition = "ignored"
                return None
            matched = []
            budget.stage = "match"
            for candidate in self._candidates(text, budget):
                budget.rule_id = candidate["id"]
                if matches(candidate["match"]):
                    matched.append(candidate)
            budget.check()
            if not matched:
                return (
                    Event(
                        "diagnostic",
                        errors=errors,
                        instruction_version=self.instructions.version,
                    )
                    if errors
                    else None
                )
            if len(matched) != 1:
                return Event(
                    "diagnostic",
                    errors=["ambiguous_rules"],
                    instruction_version=self.instructions.version,
                )
            rule = matched[0]
            budget.rule_id = rule["id"]
            execute(rule["read"])
            if self.instructions.data["engine_version"] == 1:
                budget.stage = "legacy"
                self._legacy_fields(rule["event"], fields, search, budget.check)
            budget.stage = "validate"
            for name in rule["required"]:
                budget.check()
                if fields.get(name) in (None, "", {}, []):
                    errors.append("missing:" + name)
            errors.extend(field_errors(fields, rule["event"]))
            budget.stage = "timestamp"
            m = search(framing["timestamp"], text)
            timestamp = None
            if m and m[1] is not None:
                try:
                    timestamp = datetime.fromisoformat(m[1])
                    if timestamp.tzinfo is None:
                        timestamp = None
                    else:
                        timestamp = timestamp.astimezone(UTC)
                except (ValueError, TypeError, OverflowError):
                    pass
            result = Event(
                rule["event"],
                fields,
                timestamp,
                errors,
                rule["id"],
                self.instructions.version,
                game_build in self.instructions.data["verified_game_builds"],
            )
            budget.stage = "return"
            budget.check()
            return result
        except _Excluded:
            self.last_disposition = "ignored"
            return None
        except TimeoutError as exc:
            reason = "regex_timeout"
            if isinstance(exc, _DeadlineExceeded):
                reason = "entry_deadline"
            elif isinstance(exc, _OperationDeadlineExceeded):
                reason = "operation_deadline"
            return Event(
                "diagnostic",
                fields={
                    "reason": reason,
                    "stage": budget.stage,
                    "rule_id": budget.rule_id[:128],
                },
                errors=["regex_budget_exceeded"],
                rule_id=budget.rule_id,
                instruction_version=self.instructions.version,
            )
        except (
            ValueError,
            TypeError,
            OverflowError,
            AttributeError,
            IndexError,
            KeyError,
        ):
            # Malformed input is an occurrence to reject, not a reason to retry
            # the same bytes forever. Never turn partial fields into state.
            return Event(
                "diagnostic",
                errors=["invalid_record_fields"],
                instruction_version=self.instructions.version,
            )

    def _legacy_fields(self, kind, fields, search, checkpoint):
        """Version-1 definitions are adapted here, never inside the state layer."""
        if kind == "channel_change" and isinstance(fields.get("channel_raw"), str):
            raw = fields["channel_raw"].strip()
            model, separator, owner = raw.rpartition(" : ")
            if not separator:
                model, owner = raw, ""
            model = model.strip().removeprefix("@vehicle_Name")
            lookups = self.instructions.data["lookups"]
            internal = False
            for prefix in lookups["ship_manufacturer_prefixes"]:
                checkpoint()
                if model.startswith(prefix) and len(model) > len(prefix):
                    internal = True
                    break
            display = False
            for name in lookups["ship_manufacturer_names"]:
                checkpoint()
                if model.startswith(name + " ") and model[len(name) :].strip():
                    display = True
                    break
            if internal or display:
                fields.update(
                    ship_name=model.replace("_", " ") if internal else model,
                    owner=owner.strip(),
                )
                if internal:
                    fields["ship_class"] = model
        elif kind == "fatal_collision" and isinstance(fields.get("vehicle"), str):
            fields["vehicle"] = search(r"_\d+$", fields["vehicle"], replace="")


@dataclass
class Record:
    text: str
    start: int
    end: int
    complete: bool = True


class RecordAssembler:
    """Incremental bytes -> physical lines -> complete quoted notification records.

    No state effects are permitted for incomplete records. Offsets count bytes.
    Call expire() while tailing, and finish() only at a fixed replay EOF.
    """

    def __init__(self, instructions=None, offset=0):
        d = (instructions or Instructions.load(bundled_bytes())).data["framing"]
        self.start_pattern = _pattern(d["record_start"])
        self.timestamp_pattern = _pattern(d["timestamp"])
        self.continuation_pattern = (
            _pattern(d["notification_continuation"])
            if "notification_continuation" in d
            else None
        )
        self.notification_pattern = _pattern(d["notification"], ["DOTALL"])
        self.buffer = b""
        self.offset = offset
        self.pending = None
        self.pending_at = None
        self.discard_line = False

    def _line(self, raw, start, end):
        text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        result = []
        if self.pending and self.start_pattern.search(
            text, timeout=REGEX_TIMEOUT_SECONDS
        ):
            first = self.timestamp_pattern.search(
                self.pending.text, timeout=REGEX_TIMEOUT_SECONDS
            )
            current = self.timestamp_pattern.search(text, timeout=REGEX_TIMEOUT_SECONDS)
            # Logging individual physical lines can advance the timestamp by a
            # millisecond. Bound the total gap, and still require explicit
            # continuation syntax: nearby timestamps alone never join records.
            nearby = False
            if first is not None and current is not None and first[1] and current[1]:
                try:
                    gap = (
                        datetime.fromisoformat(current[1].replace("Z", "+00:00"))
                        - datetime.fromisoformat(first[1].replace("Z", "+00:00"))
                    ).total_seconds()
                    nearby = 0 <= gap <= 0.25
                except (ValueError, TypeError):
                    pass
            continuation = (
                nearby
                and self.continuation_pattern is not None
                and self.continuation_pattern.search(
                    text[current.end() :], timeout=REGEX_TIMEOUT_SECONDS
                )
            )
            if continuation:
                text = text[current.end() :].lstrip()
            else:
                self.pending.complete = False
                result.append(self.pending)
                self.pending = None
                self.pending_at = None
        if self.pending:
            self.pending.text += "\n" + text
            self.pending.end = end
            record = self.pending
        else:
            record = Record(text, start, end)
        m = self.notification_pattern.search(record.text, timeout=REGEX_TIMEOUT_SECONDS)
        # Framing pattern captures through closing quote OR end of input.
        # Its match suffix is a quote only for a complete notification.
        opened = m is not None
        closed = opened and m[0].endswith('"') and m.end(1) < m.end()
        if opened and not closed:
            self.pending = record
            if self.pending_at is None:
                self.pending_at = time.monotonic()
        else:
            result.append(record)
            self.pending = None
            self.pending_at = None
        if self.pending and len(self.pending.text.encode("utf-8")) > MAX_RECORD_BYTES:
            self.pending.complete = False
            result.append(self.pending)
            self.pending = None
            self.pending_at = None
        return result

    def feed(self, chunk: bytes):
        output = []
        self.buffer += chunk
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            start = self.offset
            self.offset += len(line) + 1
            if not self.discard_line:
                try:
                    output.extend(self._line(line, start, self.offset))
                except TimeoutError:
                    output.append(Record("", start, self.offset, False))
                    self.pending = None
            self.discard_line = False
        if len(self.buffer) > MAX_RECORD_BYTES:
            output.append(
                Record("", self.offset, self.offset + len(self.buffer), False)
            )
            self.offset += len(self.buffer)
            self.buffer = b""
            self.discard_line = True
        return output

    def expire(self, now=None):
        if (
            self.pending
            and (now if now is not None else time.monotonic()) - self.pending_at > 5
        ):
            record = self.pending
            record.complete = False
            self.pending = None
            self.pending_at = None
            return [record]
        return []

    def finish(self):
        result = []
        if self.buffer:
            raw, self.buffer = self.buffer, b""
            start = self.offset
            self.offset += len(raw)
            if not self.discard_line:
                result.extend(self._line(raw, start, self.offset))
        if self.pending:
            self.pending.complete = False
            result.append(self.pending)
            self.pending = None
            self.pending_at = None
        return result
