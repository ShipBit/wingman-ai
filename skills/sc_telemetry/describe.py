"""Short plain-text answers for the two AI tools, built from the Handler's state. Kept small: they go into the
conversation on every tool call (Wingman's token rules)."""
from __future__ import annotations

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
