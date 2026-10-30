"""Star Citizen telemetry in the Star Citizen Events skill: which switch speaks for which event, which source speaks
when the game log and the telemetry see the same moment, and the short answers about the ship and the pilot.

Core reads the telemetry (services/sc_telemetry) and the skill gets it through `self.wingman.sc_telemetry`. The
answers are kept small: they go into the conversation on every tool call (Wingman's token rules).
"""
from __future__ import annotations

SHIP_MASTER = "telemetry_ship"
PILOT_MASTER = "telemetry_pilot"
SWITCHES: dict[str, tuple[str, tuple[str, ...]]] = {
    # react_<switch>: (the master it sits under, the telemetry events it speaks for)
    "tm_shields": (SHIP_MASTER, ("shields_down", "shields_restored")),
    "tm_under_fire": (SHIP_MASTER, ("under_fire",)),
    "tm_locked_on": (SHIP_MASTER, ("locked_on",)),
    "tm_countermeasures": (SHIP_MASTER, ("countermeasures_low", "countermeasures_empty")),
    "tm_power": (SHIP_MASTER, ("powerplant_offline", "powerplant_online")),
    "tm_engines": (SHIP_MASTER, ("engines_damaged", "engines_offline")),
    "tm_weapons": (SHIP_MASTER, ("weapons_unavailable",)),
    "tm_boost": (SHIP_MASTER, ("boost_depleted",)),
    "tm_proximity": (SHIP_MASTER, ("proximity_warning",)),
    "tm_landing": (SHIP_MASTER, ("landed", "took_off")),
    "tm_jump": (SHIP_MASTER, ("jump_started", "jump_finished")),
    "tm_vehicle": (SHIP_MASTER, ("vehicle_changed", "ground_vehicle_entered")),
    "tm_hydrogen": (SHIP_MASTER, ("hydrogen_low",)),
    "tm_gear": (SHIP_MASTER, ("gear_deployed", "gear_retracted")),
    "tm_quantum_mode": (SHIP_MASTER, ("quantum_mode_on", "quantum_mode_off")),
    "tm_health": (PILOT_MASTER, ("health_low",)),
    "tm_down": (PILOT_MASTER, ("player_down", "respawned")),
    "tm_oxygen": (PILOT_MASTER, ("oxygen_low", "not_breathable")),
    "tm_exhausted": (PILOT_MASTER, ("exhausted",)),
    "tm_hunger_thirst": (PILOT_MASTER, ("hunger_low", "thirst_low")),
    "tm_intoxicated": (PILOT_MASTER, ("intoxicated",)),
    "tm_wallet": (PILOT_MASTER, ("uec_changed",)),
}
"""Off by default (default_config.yaml): landing gear and quantum mode, which come on every flight."""

LOG = "log"
TELEMETRY = "telemetry"
SOURCES: dict[str, tuple[str, frozenset[str], frozenset[str]]] = {
    # source_<topic>: (the better one by default, the game log's events, the telemetry's events)
    # The log names the item and the amount; the telemetry only sees the balance move.
    "source_money": (LOG, frozenset({
        "shop_buy", "shop_sell", "commodity_buy", "commodity_sell", "reward_earned", "fined", "money_sent",
        "transaction_complete",
    }), frozenset({"uec_changed"})),
    # The log names the ship on every boarding; the telemetry only notices a different ship.
    "source_boarding": (LOG, frozenset({"ship_entered", "ship_exited"}),
                        frozenset({"vehicle_changed", "ground_vehicle_entered"})),
    # The game's own warning; hydrogen low was never seen live in the field test.
    "source_fuel": (LOG, frozenset({"fuel_low"}), frozenset({"hydrogen_low"})),
    # The telemetry sees the jump start and end to the second; the log only the arrival.
    "source_quantum_arrival": (TELEMETRY, frozenset({"qt_arrived"}), frozenset({"jump_started", "jump_finished"})),
    # The telemetry sees going down and the respawn, both tested live.
    "source_down": (TELEMETRY, frozenset({"incapacitated"}), frozenset({"player_down"})),
}
NOT_LIVE = {
    "waiting": "The game sends no telemetry: it is not running, or it was started before telemetry was switched on.",
    "game_without_telemetry": "Star Citizen runs without telemetry. Quit the RSI Launcher completely, tray icon "
                              "too, start it again and restart the game.",
    "connected": "Connected to Star Citizen, but no data yet: the pilot is in a menu or loading.",
    "incompatible": "Star Citizen answers in a way Wingman does not know. A game patch probably changed the "
                    "telemetry; a Wingman update will follow.",
    "unavailable": "This Wingman cannot read Star Citizen telemetry. Please report it.",
}


def not_live(state: str) -> str:
    """Why there is nothing to tell, by the telemetry status."""
    return NOT_LIVE.get(state, "No telemetry from Star Citizen right now.")


ROUTINE_GROUPS = {
    # Every flight: paced like the log's routine lines (routine_gap_minutes).
    "gear_deployed": "flight",
    "gear_retracted": "flight",
    "quantum_mode_on": "flight",
    "quantum_mode_off": "flight",
}

LIGHT_MEANINGS = {
    "qdrv": {"nominal": "quantum mode active"},
    "thr": {"off": "engines off", "minor_on": "engines damaged", "major_on": "engines starting, failing or in a jump"},
    "shld": {"off": "shields off", "major_on": "shields down or recharging"},
    "prox": {"minor_on": "close to something", "major_on": "collision danger"},
    "wpn": {"minor_on": "weapons limited", "major_on": "weapons unavailable"},
    "hit": {"major_flashing": "taking hits", "major_on": "taking hits"},
    "radr": {"major_on": "being locked on", "off": "radar off"},
}
SETTING_NAMES = {"ifcs_coupled": "coupled", "ifcs_esp": "ESP", "ifcs_g_safe": "G-safe",
                 "ifcs_speed_limiter": "speed limiter", "ifcs_cruise_mode": "cruise",
                 "ifcs_gravity_compensation": "gravity compensation"}


def _warnings(lights: dict) -> list[str]:
    return [meaning for light, meanings in LIGHT_MEANINGS.items()
            if (meaning := meanings.get(lights.get(light, "")))]


def ship_summary(state: dict) -> str:
    vehicle = state.get("vehicle")
    player = state.get("player") or {}
    if vehicle is None:
        if player.get("locomotion") == "seated":
            return "Seated, but this vehicle sends no ship telemetry (ground vehicles don't)."
        return "Not in a ship's seat, so there is no ship telemetry."
    instr, derived = vehicle["instruments"], state["derived"]
    name = vehicle["class_name"].replace("_", " ")
    lines = [f"Ship: {name}" + (f" ({vehicle['manufacturer']})" if vehicle["manufacturer"] else "")]
    if derived.get("in_jump"):
        lines.append("In a quantum jump.")
    elif vehicle["landed"]:
        lines.append("Landed.")
    else:
        lines.append(f"Speed {instr['speed']:.0f} m/s.")
    if derived.get("in_planet_frame"):
        flight = [f"altitude {instr['altitude']:,.0f} m"]
        if derived.get("radar_valid"):
            flight.append(f"{instr['radar_altitude']:,.0f} m above ground")
        if derived.get("heading_valid"):
            flight.append(f"heading {instr['heading']:.0f}°")
        flight.append(f"vertical {instr['vertical_speed']:+.0f} m/s")
        lines.append(", ".join(flight).capitalize() + ".")
    else:
        lines.append("In space (no planet altitude or heading).")
    lines.append(f"Hydrogen {instr['hydrogen_fuel'] * 100:.0f}%, boost {instr['boost_reserves'] * 100:.0f}%"
                 + (" (low)" if instr["boost_critical"] else "") + f", g {instr['g']:.1f}.")
    on = [label for key, label in SETTING_NAMES.items() if vehicle["settings"][key]["active"]]
    lines.append("Active: " + (", ".join(on) if on else "none") + f"; gear {vehicle['gear']}"
                 + ("; lights on" if vehicle["lights_on"] else "") + ".")
    off = [flag.replace("_", " ") for flag, value in vehicle["power"].items()
           if not value and flag != "gravity_generators"]
    lines.append("Power: " + ("all on" if not off else "off: " + ", ".join(off)) + ".")
    warnings = _warnings(vehicle["lights"])
    lines.append("Warnings: " + (", ".join(warnings) if warnings else "none") + ".")
    weapons = state.get("weapons")
    if weapons:
        ready = sum(1 for w in weapons["weapons"] if w["ready"])
        cms = weapons["countermeasures"]
        lines.append(f"Weapons ready {ready}/{len(weapons['weapons'])}"
                     + (", gimbals locked" if weapons["gimbals_locked"] else "")
                     + f"; decoys {cms['decoy']['count']}, noise {cms['noise']['count']}.")
    return "\n".join(lines)


def player_summary(state: dict) -> str:
    player = state.get("player")
    if not player:
        return "No player telemetry yet (it starts once the player has spawned)."
    derived = state.get("derived", {})
    where = {"on_foot": "on foot", "eva": "in EVA", "seated": "seated"}.get(player["locomotion"], "unknown")
    lines = [f"Player {where}" + (f", role {player['crew_role']}" if player["crew_role"] != "unspecified" else "")
             + "."]
    if derived.get("player_down"):
        lines.append("Down or dead (health 0).")
    else:
        lines.append(f"Health {player['health_fraction'] * 100:.0f}%, heart rate {player['heart_rate']:.0f} bpm.")
    lines.append(f"Hunger {player['hunger_fraction'] * 100:.0f}%, thirst {player['thirst_fraction'] * 100:.0f}%, "
                 f"oxygen {player['oxygen_fraction'] * 100:.0f}%"
                 + (f", intoxication {player['intoxication']}" if player["intoxication"] else "") + ".")
    if player["environment_known"]:
        lines.append(f"Outside {player['outside_temperature']:.0f} °C, air "
                     + ("breathable" if player["breathable"] else "NOT breathable")
                     + f", gravity {player['gravity']:.1f} g.")
    lines.append(f"Wallet {player['uec_balance']:,} aUEC.")
    return "\n".join(lines)
