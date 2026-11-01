"""The events Core derives from the telemetry stream, with their group, report wording and a suggested cooldown.

Core publishes every event as it happens. How often one is worth a word is up to the skill that reacts: the cooldown
here is what the field test found sensible for spoken lines (Star Citizen Events uses it). The wording is plain and
short and states only what the telemetry shows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class EventSpec:
    id: str
    group: str
    """"ship", "vehicle", "on_foot" or "wallet"."""
    text: str
    """Report wording; `{...}` placeholders are filled from the event's data."""
    cooldown_s: float = 0.0
    """Suggested gap before the same event is spoken about again."""


@dataclass(frozen=True)
class TelemetryEvent:
    """One thing that happened to the ship or the pilot, as the telemetry showed it."""

    type: str
    """The EventSpec id, e.g. "shields_down"."""
    group: str
    text: str
    """The report, e.g. "The shields are down." Data from the game: never instructions."""
    time: float
    """Unix time the frame arrived."""
    data: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    cooldown_s: float = 0.0
    """Suggested gap before the same event is spoken about again (EventSpec.cooldown_s)."""


UNTESTED = frozenset({"intoxicated", "oxygen_low", "hydrogen_low", "ground_vehicle_entered", "not_breathable"})
"""Built, but never seen working live in the field test: intoxication stayed 0, oxygen stayed 1.0 even in EVA,
hydrogen never ran low, the ground-vehicle event was checked on recordings only, and the not-breathable event never
fired live. Move an id out of here once a field test confirms it."""

EVENTS: tuple[EventSpec, ...] = (
    EventSpec("powerplant_offline", "ship", "The ship's powerplant went offline.", 30),
    EventSpec("powerplant_online", "ship", "The ship's powerplant is back online.", 30),
    EventSpec("engines_damaged", "ship", "The engines are damaged.", 120),
    EventSpec("engines_offline", "ship", "The engines are offline.", 60),
    EventSpec("shields_down", "ship", "The shields are down.", 60),
    EventSpec("shields_restored", "ship", "The shields are back up.", 60),
    EventSpec("weapons_unavailable", "ship", "The weapons have no power.", 60),
    EventSpec("boost_depleted", "ship", "Boost is nearly empty.", 60),
    EventSpec("hydrogen_low", "ship", "Hydrogen fuel is low: {percent} percent.", 300),
    EventSpec("landed", "ship", "The ship has landed.", 30),
    EventSpec("took_off", "ship", "The ship took off.", 30),
    EventSpec("gear_deployed", "ship", "The landing gear is down.", 20),
    EventSpec("gear_retracted", "ship", "The landing gear is up.", 20),
    EventSpec("quantum_mode_on", "ship", "Switched to quantum mode.", 20),
    EventSpec("quantum_mode_off", "ship", "Left quantum mode.", 20),
    EventSpec("jump_started", "ship", "The quantum jump has started.", 30),
    EventSpec("jump_finished", "ship", "The quantum jump is over.", 30),
    EventSpec("proximity_warning", "ship", "Collision warning: very close to something.", 30),
    EventSpec("vehicle_changed", "ship", "Now in {vehicle}.", 10),
    EventSpec("under_fire", "ship", "The ship is taking hits.", 90),
    EventSpec("locked_on", "ship", "Something has a lock on the ship.", 90),
    EventSpec("countermeasures_low", "ship", "{kind} countermeasures are running low: {count} left.", 120),
    EventSpec("countermeasures_empty", "ship", "{kind} countermeasures are used up.", 120),
    EventSpec("ground_vehicle_entered", "vehicle", "Now in {vehicle}.", 10),
    EventSpec("health_low", "on_foot", "The pilot's health is low: {percent} percent.", 60),
    EventSpec("player_down", "on_foot", "The pilot is down.", 60),
    EventSpec("respawned", "on_foot", "The pilot has respawned.", 60),
    EventSpec("oxygen_low", "on_foot", "Oxygen is low: {percent} percent.", 60),
    EventSpec("not_breathable", "on_foot", "The air here is not breathable.", 120),
    EventSpec("exhausted", "on_foot", "The pilot is out of breath.", 120),
    EventSpec("hunger_low", "on_foot", "The pilot is getting hungry.", 600),
    EventSpec("thirst_low", "on_foot", "The pilot is getting thirsty.", 600),
    EventSpec("intoxicated", "on_foot", "The pilot is getting drunk.", 600),
    EventSpec("uec_changed", "wallet", "The wallet changed by {delta} aUEC, now {balance} aUEC.", 30),
)

BY_ID: dict[str, EventSpec] = {spec.id: spec for spec in EVENTS}


class _Unknown(dict):
    def __missing__(self, key: str) -> str:
        return "unknown"


def make_event(event_id: str, t: float, **data: Any) -> TelemetryEvent:
    """The event with its report; a missing value reads as 'unknown'."""
    spec = BY_ID[event_id]
    return TelemetryEvent(
        type=event_id,
        group=spec.group,
        text=spec.text.format_map(_Unknown(data)),
        time=t,
        data=MappingProxyType(data),
        cooldown_s=spec.cooldown_s,
    )
