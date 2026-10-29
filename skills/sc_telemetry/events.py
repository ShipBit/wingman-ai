"""The events sc_telemetry derives from the stream, with their group and wording.

Every event is reported; the only switch is "Enable Proactive Notifications" (user, 2026-10-29: show just the two
main settings). The wording is the report the support model turns into an in-character line; it is plain, short and states only
what the telemetry shows.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EventSpec:
    id: str
    group: str
    name: str
    """Name in the settings hint."""
    text: str
    """Report wording; `{...}` placeholders are filled from the event's data."""
    cooldown_s: float = 0.0
    """The same event is not reported again sooner than this."""

    @property
    def tested(self) -> bool:
        """Seen working live in the field tests (the field-test report). Untested ones say so in their label."""
        return self.id not in UNTESTED


UNTESTED = frozenset({"intoxicated", "oxygen_low", "hydrogen_low", "ground_vehicle_entered", "not_breathable"})
"""Built, but never seen working live: intoxication stayed 0 (no alcohol yet), oxygen stayed 1.0 even in EVA,
hydrogen never ran low, the ground-vehicle event is new (checked on recordings only), and the not-breathable event
never fired live. Move an id out of here once a field test confirms it."""

GROUP_PREFIX = {"ship": "Ship", "vehicle": "Vehicle", "on_foot": "On foot", "wallet": "Wallet"}


GROUPS = tuple(GROUP_PREFIX)
"""Where the player is (user, 2026-10-28); the settings hint lists the reactions per group."""

EVENTS: tuple[EventSpec, ...] = (
    EventSpec("powerplant_offline", "ship", "Powerplant Offline", "The ship's powerplant went offline.", 30),
    EventSpec("powerplant_online", "ship", "Powerplant Online", "The ship's powerplant is back online.", 30),
    EventSpec("engines_damaged", "ship", "Engines Damaged", "The engines are damaged.", 120),
    EventSpec("engines_offline", "ship", "Engines Offline", "The engines are offline.", 60),
    EventSpec("shields_down", "ship", "Shields Down", "The shields are down.", 60),
    EventSpec("shields_restored", "ship", "Shields Restored", "The shields are back up.", 60),
    EventSpec("weapons_unavailable", "ship", "Weapons Unpowered", "The weapons have no power.", 60),
    EventSpec("boost_depleted", "ship", "Boost Depleted", "Boost is nearly empty.", 60),
    EventSpec("hydrogen_low", "ship", "Hydrogen Low", "Hydrogen fuel is low: {percent} percent.", 300),
    EventSpec("landed", "ship", "Landed", "The ship has landed.", 30),
    EventSpec("took_off", "ship", "Took Off", "The ship took off.", 30),
    EventSpec("gear_deployed", "ship", "Landing Gear Down", "The landing gear is down.", 20),
    EventSpec("gear_retracted", "ship", "Landing Gear Up", "The landing gear is up.", 20),
    EventSpec("quantum_mode_on", "ship", "Quantum Mode On", "Switched to quantum mode.", 20),
    EventSpec("quantum_mode_off", "ship", "Quantum Mode Off", "Left quantum mode.", 20),
    EventSpec("jump_started", "ship", "Quantum Jump Started", "The quantum jump has started.", 30),
    EventSpec("jump_finished", "ship", "Quantum Jump Finished", "The quantum jump is over.", 30),
    EventSpec("proximity_warning", "ship", "Proximity Warning", "Collision warning: very close to something.",
              30),
    EventSpec("vehicle_changed", "ship", "New Ship", "Now in {vehicle}.", 10),
    EventSpec("under_fire", "ship", "Under Fire", "The ship is taking hits.", 90),
    EventSpec("locked_on", "ship", "Being Locked On", "Something has a lock on the ship.", 90),
    EventSpec("countermeasures_low", "ship", "Countermeasures Low",
              "{kind} countermeasures are running low: {count} left.", 120),
    EventSpec("countermeasures_empty", "ship", "Countermeasures Empty",
              "{kind} countermeasures are used up.", 120),
    EventSpec("ground_vehicle_entered", "vehicle", "Boarded a Ground Vehicle", "Now in {vehicle}.", 10),
    EventSpec("health_low", "on_foot", "Health Low", "The pilot's health is low: {percent} percent.", 60),
    EventSpec("player_down", "on_foot", "Player Down", "The pilot is down.", 60),
    EventSpec("respawned", "on_foot", "Respawned", "The pilot has respawned.", 60),
    EventSpec("oxygen_low", "on_foot", "Oxygen Low", "Oxygen is low: {percent} percent.", 60),
    EventSpec("not_breathable", "on_foot", "Air Not Breathable", "The air here is not breathable.", 120),
    EventSpec("exhausted", "on_foot", "Exhausted", "The pilot is out of breath.", 120),
    EventSpec("hunger_low", "on_foot", "Hunger Low", "The pilot is getting hungry.", 600),
    EventSpec("thirst_low", "on_foot", "Thirst Low", "The pilot is getting thirsty.", 600),
    EventSpec("intoxicated", "on_foot", "Intoxicated", "The pilot is getting drunk.", 600),
    EventSpec("uec_changed", "wallet", "UEC Balance Changed",
              "The wallet changed by {delta} aUEC, now {balance} aUEC.", 30),
)

BY_ID: dict[str, EventSpec] = {spec.id: spec for spec in EVENTS}


def render(spec: EventSpec, data: dict) -> str:
    """The report wording with its placeholders filled; a missing value reads as 'unknown'."""

    class _Default(dict):
        def __missing__(self, key: str) -> str:
            return "unknown"

    return spec.text.format_map(_Default(data))
