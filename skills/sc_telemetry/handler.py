"""The Handler: turns the stream of normalised frames into a smoothed state and debounced events.

It applies the quirk rules from the field-test report §4 once, so the Orchestrator and other skills never repeat them:
heading only inside a planet frame and outside jumps, EVA flicker smoothed, settings and lights debounced, death
from health alone, countermeasure burst size learnt, a new vehicle starts a fresh silent baseline.
"""
from __future__ import annotations

import copy
from collections import deque
from dataclasses import dataclass, field

from skills.sc_telemetry.events import BY_ID, render
from skills.sc_telemetry.normalize import normalize

EVA_STABLE_S = 1.5
JUMP_ON_S = 1.5
JUMP_OFF_S = 8.0
"""THR drops to NOMINAL for several seconds in the middle of a jump (seen on the Vulture)."""
UEC_QUIET_S = 5.0
"""Purchases arrive one item every ~2 s; report the total once the balance has settled."""
EXHAUSTED_BPM = 170.0
"""The HUD turns the heart rate red here (user, 2026-10-27)."""
EXHAUSTED_SPIKES = 2
EXHAUSTED_WINDOW_S = 10.0
"""Measured sprint (2026-10-27): 170+ spikes about every 6 s (17:39:13, :19, :25, :31)."""
RECOVERED_BPM = 150.0
RESPAWN_HEALTH = 0.9
GROUND_VEHICLE_AFTER_S = 12.0
"""Seated without a vehicle frame this long = a ground vehicle (they send none). In ships the vehicle frame arrives
6-9 s after sitting down, so a shorter wait would mistake every boarding for a ground vehicle."""


@dataclass(frozen=True)
class Thresholds:
    health_low: float = 0.30
    oxygen_low: float = 0.20
    hunger_low: float = 0.25
    thirst_low: float = 0.25
    countermeasure_bursts: int = 3
    """'Low' means this many bursts or fewer are left."""
    hydrogen_low: float = 0.15


@dataclass(frozen=True)
class TelemetryEvent:
    id: str
    group: str
    text: str
    t: float
    data: dict = field(default_factory=dict)


class _Hold:
    """A boolean that only counts as changed after it has held the new value for a while."""

    def __init__(self, on_s: float, off_s: float = 0.0) -> None:
        self.on_s, self.off_s = on_s, off_s
        self.value = False
        self._pending: bool | None = None
        self._since = 0.0

    def reset(self, value: bool) -> None:
        self.value, self._pending = value, None

    def update(self, raw: bool, t: float) -> bool | None:
        """The confirmed new value when it just changed, otherwise None."""
        if raw == self.value:
            self._pending = None
            return None
        if self._pending != raw:
            self._pending, self._since = raw, t
        if t - self._since >= (self.on_s if raw else self.off_s):
            self.value, self._pending = raw, None
            return raw
        return None


class Handler:
    def __init__(self) -> None:
        self._state: dict | None = None
        self._last_fired: dict[str, float] = {}
        self._locomotion = "unspecified"
        self._locomotion_pending: tuple[str, float] | None = None
        self._vehicle_key: str | None = None
        """The vehicle of the current seat; None while not in one, so re-entering takes a fresh baseline."""
        self._last_vehicle_name: str | None = None
        """The last vehicle seen at all, for 'vehicle_changed'."""
        self._holds = self._ship_holds()
        self._player_holds = {"down": _Hold(1.0), "breathless": _Hold(2.0, 2.0)}
        self._player_seen = False
        self._first_frame_t: float | None = None
        self._seat_without_vehicle: tuple[str, float] | None = None
        """(seat, since) while seated with no vehicle frame."""
        self._ground_vehicle: str | None = None
        self._spikes: deque[tuple[float, str]] = deque()
        self._dead = False
        """Health reached 0 and stayed there; only a return to RESPAWN_HEALTH clears it."""
        self.last_unfiltered: list[TelemetryEvent] = []
        """Every event of the last update, before the cooldowns: the feed for other skills wants all of them."""
        self._armed: dict[str, bool] = {}
        self._gear = self._vtol = None
        self._cm: dict[str, dict] = {}
        self._uec: int | None = None
        self._uec_pending: tuple[int, float] | None = None
        """(balance before the change, time of the latest change)"""

    @staticmethod
    def _ship_holds() -> dict[str, _Hold]:
        return {
            "powerplant": _Hold(1.0, 1.0), "engines_off": _Hold(1.0), "engines_damaged": _Hold(1.0),
            "shields_down": _Hold(1.5, 3.0), "weapons_major": _Hold(1.0),
            "boost_critical": _Hold(0.3), "landed": _Hold(1.0, 1.0), "quantum": _Hold(1.0, 1.0),
            "jump": _Hold(JUMP_ON_S, JUMP_OFF_S), "prox": _Hold(0.2), "hit": _Hold(0.0), "lock": _Hold(1.0),
        }

    @property
    def state(self) -> dict:
        """The latest smoothed state (a copy: callers may keep it)."""
        return copy.deepcopy(self._state) if self._state else {}

    # --- per frame --------------------------------------------------------------------------------------------

    def update(self, frame: dict, t: float, thresholds: Thresholds) -> list[TelemetryEvent]:
        state = normalize(frame)
        fired: list[TelemetryEvent] = []
        player = state["player"]
        if player is not None:
            player["locomotion"] = self._smooth_locomotion(player["locomotion"], t)
            fired += self._player_events(player, t, thresholds)
        if self._first_frame_t is None:
            self._first_frame_t = t
        if state["vehicle"] is not None:
            fired += self._vehicle_events(state, t, thresholds)
            self._seat_without_vehicle = None
            self._ground_vehicle = None
        else:
            self._vehicle_key = None
            fired += self._ground_vehicle_events(player, t)
        if state["weapons"] is not None:
            fired += self._countermeasure_events(state["weapons"], t, thresholds)
        state["derived"]["in_jump"] = self._holds["jump"].value if state["vehicle"] else False
        state["derived"]["heading_valid"] = state["derived"]["heading_valid"] and not state["derived"]["in_jump"]
        state["derived"]["player_down"] = self._dead
        if state["weapons"] is not None:
            state["weapons"]["countermeasures"] = {
                kind: {"count": count, "burst": self._cm.get(kind, {}).get("burst", 0)}
                for kind, count in state["weapons"]["countermeasures"].items()
            }
        self._state = state
        self.last_unfiltered = fired
        return [event for event in fired if self._past_cooldown(event)]

    def _past_cooldown(self, event: TelemetryEvent) -> bool:
        spec = BY_ID[event.id]
        last = self._last_fired.get(event.id)
        if last is not None and event.t - last < spec.cooldown_s:
            return False
        self._last_fired[event.id] = event.t
        return True

    @staticmethod
    def _event(event_id: str, t: float, **data) -> TelemetryEvent:
        spec = BY_ID[event_id]
        return TelemetryEvent(event_id, spec.group, render(spec, data), t, data)

    # --- player -------------------------------------------------------------------------------------------------

    def _smooth_locomotion(self, raw: str, t: float) -> str:
        """On foot <-> EVA flickers many times a second at a ship's door; other changes are taken at once."""
        if raw == self._locomotion:
            self._locomotion_pending = None
            return raw
        if {raw, self._locomotion} <= {"on_foot", "eva"}:
            if self._locomotion_pending is None or self._locomotion_pending[0] != raw:
                self._locomotion_pending = (raw, t)
            if t - self._locomotion_pending[1] < EVA_STABLE_S:
                return self._locomotion
        self._locomotion, self._locomotion_pending = raw, None
        return raw

    def _crossed_below(self, key: str, value: float, limit: float) -> bool:
        """True once when value drops below limit; re-armed when it is back above."""
        armed = self._armed.get(key, value >= limit)
        if value >= limit:
            self._armed[key] = True
            return False
        self._armed[key] = False
        return armed

    def _player_events(self, player: dict, t: float, thresholds: Thresholds) -> list[TelemetryEvent]:
        fired = []
        if not self._player_seen:
            # The first frame (start, or reconnecting mid-session) is the baseline: no event for a state that
            # was already there.
            self._player_seen = True
            self._player_holds["breathless"].reset(player["environment_known"] and not player["breathable"])
            self._armed["exhausted"] = player["heart_rate"] < RECOVERED_BPM
        health = player["health_fraction"] if player["health_max"] > 0 else None
        if health is not None:
            if self._player_holds["down"].update(health <= 0.0, t):
                self._dead = True
                fired.append(self._event("player_down", t))
            if self._dead and health >= RESPAWN_HEALTH:
                # Not tied to the 'down' hold: health may pass through other values on the way back.
                self._dead = False
                self._player_holds["down"].reset(False)
                self._armed["health"] = True
                fired.append(self._event("respawned", t))
            if health > 0 and self._crossed_below("health", health, thresholds.health_low):
                fired.append(self._event("health_low", t, percent=round(health * 100)))
        for key, limit, event_id in (("oxygen", thresholds.oxygen_low, "oxygen_low"),
                                     ("hunger", thresholds.hunger_low, "hunger_low"),
                                     ("thirst", thresholds.thirst_low, "thirst_low")):
            if player[f"{key}_max"] > 0 and self._crossed_below(key, player[f"{key}_fraction"], limit):
                fired.append(self._event(event_id, t, percent=round(player[f"{key}_fraction"] * 100)))
        if player["environment_known"] and self._player_holds["breathless"].update(not player["breathable"], t):
            fired.append(self._event("not_breathable", t))
        fired += self._exhaustion_events(player["heart_rate"], t)
        if player["intoxication"] > 0 and self._armed.get("sober", True):
            self._armed["sober"] = False
            fired.append(self._event("intoxicated", t))
        elif player["intoxication"] == 0:
            self._armed["sober"] = True
        fired += self._uec_events(player["uec_balance"], t)
        return fired

    def _exhaustion_events(self, rate: float, t: float) -> list[TelemetryEvent]:
        """The heart rate only touches 170+ in spikes of ~0.3 s while sprinting flat out (measured), so
        'exhausted' is EXHAUSTED_SPIKES spikes within EXHAUSTED_WINDOW_S, re-armed once it drops below 150."""
        if rate < RECOVERED_BPM:
            self._spikes.clear()
            self._armed["exhausted"] = True
            return []
        if rate >= EXHAUSTED_BPM and (not self._spikes or self._spikes[-1][1] != "high"):
            self._spikes.append((t, "high"))
        elif rate < EXHAUSTED_BPM and self._spikes and self._spikes[-1][1] == "high":
            self._spikes.append((t, "low"))
        while self._spikes and t - self._spikes[0][0] > EXHAUSTED_WINDOW_S:
            self._spikes.popleft()
        spikes = sum(1 for _, kind in self._spikes if kind == "high")
        if spikes >= EXHAUSTED_SPIKES and self._armed.get("exhausted", True):
            self._armed["exhausted"] = False
            return [self._event("exhausted", t)]
        return []

    def _uec_events(self, balance: int, t: float) -> list[TelemetryEvent]:
        if self._uec is None:
            self._uec = balance
            return []
        if balance != self._uec:
            before = self._uec_pending[0] if self._uec_pending else self._uec
            self._uec_pending = (before, t)
            self._uec = balance
            return []
        if self._uec_pending and t - self._uec_pending[1] >= UEC_QUIET_S:
            before, _ = self._uec_pending
            self._uec_pending = None
            if balance != before:
                return [self._event("uec_changed", t, delta=f"{balance - before:+,}", balance=f"{balance:,}")]
        return []

    # --- vehicle ------------------------------------------------------------------------------------------------

    def _ground_vehicle_events(self, player: dict | None, t: float) -> list[TelemetryEvent]:
        """Ground vehicles send no vehicle frame; only the seat says which vehicle it is
        ('RSI_Ursa_Rover_SCItem_Seat_Pilot_...')."""
        seat = player["seat"] if player and player["locomotion"] == "seated" else ""
        if not seat or "_SCItem" not in seat:
            self._seat_without_vehicle = None
            self._ground_vehicle = None
            return []
        if self._seat_without_vehicle is None or self._seat_without_vehicle[0] != seat:
            self._seat_without_vehicle = (seat, t)
        since = self._seat_without_vehicle[1]
        vehicle = seat.split("_SCItem", 1)[0]
        if t - since < GROUND_VEHICLE_AFTER_S or vehicle == self._ground_vehicle:
            return []
        self._ground_vehicle = vehicle
        if since == self._first_frame_t:  # already seated when the stream started: baseline, no event
            return []
        return [self._event("ground_vehicle_entered", t, vehicle=vehicle.replace("_", " "))]

    def _vehicle_events(self, state: dict, t: float, thresholds: Thresholds) -> list[TelemetryEvent]:
        vehicle = state["vehicle"]
        key = vehicle["name"]
        fired = []
        if key != self._vehicle_key:
            if self._last_vehicle_name is not None and key != self._last_vehicle_name:
                fired.append(self._event("vehicle_changed", t, vehicle=vehicle["class_name"]))
            self._vehicle_key = self._last_vehicle_name = key
            self._baseline(vehicle)
            return fired
        lights, power, instr = vehicle["lights"], vehicle["power"], vehicle["instruments"]
        holds = self._holds
        changes = {
            "powerplant": holds["powerplant"].update(power["powerplants"], t),
            "engines_off": holds["engines_off"].update(power["powerplants"] and not power["engines"], t),
            "engines_damaged": holds["engines_damaged"].update(lights["thr"] == "minor_on", t),
            "shields_down": holds["shields_down"].update(lights["shld"] == "major_on", t),
            # WPN MAJOR only (no power). MINOR also stays on while landed or after quantum mode with the guns firing
            # normally (live test 2026-10-29), so it says too little for an event.
            "weapons_major": holds["weapons_major"].update(lights["wpn"] == "major_on", t),
            "boost_critical": holds["boost_critical"].update(instr["boost_critical"], t),
            "landed": holds["landed"].update(vehicle["landed"], t),
            "quantum": holds["quantum"].update(lights["qdrv"] == "nominal", t),
            "jump": holds["jump"].update(
                lights["thr"] == "major_on" and instr["g"] == 0.0 and not vehicle["landed"], t),
            "prox": holds["prox"].update(lights["prox"] == "major_on", t),
            "hit": holds["hit"].update(lights["hit"] in ("major_flashing", "major_on", "minor_flashing",
                                                         "minor_on"), t),
            "lock": holds["lock"].update(lights["radr"] == "major_on", t),
        }
        on_off = {
            "powerplant": ("powerplant_online", "powerplant_offline"),
            "engines_off": ("engines_offline", None), "engines_damaged": ("engines_damaged", None),
            "shields_down": ("shields_down", "shields_restored"), "weapons_major": ("weapons_unavailable", None),
            "boost_critical": ("boost_depleted", None),
            "landed": ("landed", "took_off"), "quantum": ("quantum_mode_on", "quantum_mode_off"),
            "jump": ("jump_started", "jump_finished"), "prox": ("proximity_warning", None),
            "hit": ("under_fire", None), "lock": ("locked_on", None),
        }
        for name, change in changes.items():
            if change is None:
                continue
            event_id = on_off[name][0 if change else 1]
            if event_id and not (name == "engines_off" and changes["powerplant"] is False):
                fired.append(self._event(event_id, t))
        fired += self._deployment_events(vehicle, t)
        hydrogen = instr["hydrogen_fuel"]
        if hydrogen > 0 and self._crossed_below("hydrogen", hydrogen, thresholds.hydrogen_low):
            fired.append(self._event("hydrogen_low", t, percent=round(hydrogen * 100)))
        return fired

    def _baseline(self, vehicle: dict) -> None:
        """A new vehicle: take its current values silently, so entering a ship is not a burst of events."""
        self._holds = self._ship_holds()
        lights, power, instr = vehicle["lights"], vehicle["power"], vehicle["instruments"]
        self._holds["powerplant"].reset(power["powerplants"])
        self._holds["engines_off"].reset(power["powerplants"] and not power["engines"])
        self._holds["engines_damaged"].reset(lights["thr"] == "minor_on")
        self._holds["shields_down"].reset(lights["shld"] == "major_on")
        self._holds["weapons_major"].reset(lights["wpn"] == "major_on")
        self._holds["boost_critical"].reset(instr["boost_critical"])
        self._holds["landed"].reset(vehicle["landed"])
        self._holds["quantum"].reset(lights["qdrv"] == "nominal")
        self._holds["lock"].reset(lights["radr"] == "major_on")
        self._holds["prox"].reset(lights["prox"] == "major_on")
        self._holds["hit"].reset(lights["hit"] in ("major_flashing", "major_on", "minor_flashing", "minor_on"))
        self._holds["jump"].reset(lights["thr"] == "major_on" and instr["g"] == 0.0 and not vehicle["landed"])
        self._gear, self._vtol = vehicle["gear"], vehicle["vtol"]
        self._cm = {}
        self._armed.pop("hydrogen", None)  # a new ship's fuel level is its baseline

    def _deployment_events(self, vehicle: dict, t: float) -> list[TelemetryEvent]:
        fired = []
        gear = vehicle["gear"]
        if gear != self._gear and gear in ("deployed", "retracted") and self._gear is not None:
            fired.append(self._event("gear_deployed" if gear == "deployed" else "gear_retracted", t))
        self._gear = gear
        self._vtol = vehicle["vtol"]
        return fired

    # --- countermeasures ------------------------------------------------------------------------------------

    def _countermeasure_events(self, weapons: dict, t: float, thresholds: Thresholds) -> list[TelemetryEvent]:
        fired = []
        for kind, count in weapons["countermeasures"].items():
            known = self._cm.get(kind)
            if known is None:
                self._cm[kind] = {"count": count, "burst": 0}
                continue
            previous = known["count"]
            if count < previous:
                known["burst"] = previous - count
                limit = known["burst"] * thresholds.countermeasure_bursts
                if count == 0:
                    fired.append(self._event("countermeasures_empty", t, kind=kind.capitalize()))
                elif count <= limit < previous:
                    fired.append(self._event("countermeasures_low", t, kind=kind.capitalize(), count=count))
            known["count"] = count
        return fired
