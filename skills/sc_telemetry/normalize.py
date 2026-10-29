"""One telemetry frame (protobuf JSON dict, field names as in the schema) -> a plain, complete state dict.

Missing fields read as their defaults (false, 0), because the stream leaves out default values. Values the game never
fills (doors, presets, quantum fuel, manufacturer) are not reported as if they worked. Rules: the field-test report §4.
"""
from __future__ import annotations

NO_PLANET_ALTITUDE = 1e30
"""Altitude above this (the game sends 3.4028235e38) means: not inside a planet's frame."""

POWER_FLAGS = ("powerplants", "engines", "weapons", "coolers", "life_support", "gravity_generators", "sensors",
               "shield_generators", "shield_emitters")
LIGHTS = ("pwr", "wpn", "thr", "shld", "cool", "qdrv", "radr", "prox", "hit", "misl")
SETTINGS = ("ifcs_coupled", "ifcs_esp", "ifcs_gravity_compensation", "ifcs_g_safe", "ifcs_cruise_mode",
            "ifcs_speed_limiter", "ifcs_proximity_assist", "ifcs_proximity_assist_landing", "ifcs_stability",
            "ifcs_core", "ifcs_wind_compensation", "ifcs_command_behaviour")
FLAG_SETTINGS = ("ifcs_spacebreak_enables_boost", "advanced_hud_enabled_scm", "advanced_hud_enabled_nav",
                 "advanced_hud_labels", "course_prediction", "ifcs_g_safe_disabled_by_boost",
                 "flight_light_amplification")
MANUFACTURERS = {
    "AEGS": "Aegis", "ANVL": "Anvil", "ARGO": "Argo", "BANU": "Banu", "CNOU": "Consolidated Outland",
    "CRUS": "Crusader", "DRAK": "Drake", "ESPR": "Esperia", "GAMA": "Gatac", "GRIN": "Greycat", "KRIG": "Kruger",
    "MISC": "MISC", "MRAI": "Mirai", "ORIG": "Origin", "RSI": "RSI", "TMBL": "Tumbril", "XIAN": "Aopoa",
    "XNAA": "Aopoa", "VNCL": "Vanduul",
}


def _enum(value: str | None, prefix: str) -> str:
    """'ACTOR_LOCOMOTION_STATE_ON_FOOT' -> 'on_foot'; missing -> 'unspecified'."""
    if not value:
        return "unspecified"
    return value.removeprefix(prefix).lower()


def _gauge(gauge: dict | None) -> tuple[float, float]:
    gauge = gauge or {}
    return float(gauge.get("current", 0.0)), float(gauge.get("max", 0.0))


def _fraction(current: float, maximum: float) -> float:
    return current / maximum if maximum > 0 else 0.0


def _player(actor: dict | None) -> dict | None:
    if actor is None:
        return None
    state = actor.get("state", {})
    vitals = actor.get("vitals", {})
    env = actor.get("environment")
    gauges = {}
    for key in ("health", "oxygen", "hunger", "thirst", "body_temperature"):
        current, maximum = _gauge(vitals.get(key))
        gauges[key] = current
        gauges[f"{key}_max"] = maximum
        gauges[f"{key}_fraction"] = _fraction(current, maximum)
    return {
        "locomotion": _enum(state.get("locomotion"), "ACTOR_LOCOMOTION_STATE_"),
        "seat": state.get("seat_name", ""),
        "crew_role": _enum(state.get("crew_role"), "ACTOR_CREW_ROLE_"),
        "uec_balance": int(state.get("uec_balance", 0)),
        **gauges,
        "heart_rate": float(vitals.get("heart_rate", 0.0)),
        "gravity": float(vitals.get("gravity", 0.0)),
        "pressure": float(vitals.get("pressure", 0.0)),
        "intoxication": int(vitals.get("intoxication_level", 0)),
        "environment_known": env is not None,
        "outside_temperature": float((env or {}).get("external_temperature", 0.0)),
        "radiation": float((env or {}).get("ambient_radiation_rate", 0.0)),
        "breathable": bool((env or {}).get("breathable_atmosphere", False)),
    }


def _instance(name: str) -> tuple[str, str]:
    """'DRAK_Cutter_907038284543' -> ('DRAK_Cutter', '907038284543')."""
    head, _, tail = name.rpartition("_")
    return (head, tail) if head and tail.isdigit() else (name, "")


def _vehicle(vehicle: dict | None) -> dict | None:
    state = (vehicle or {}).get("state")
    if state is None:
        return None
    name = state.get("name", "")
    class_name = state.get("class_name") or _instance(name)[0]
    flight = state.get("flight", {})
    instruments = flight.get("instruments", {})
    boost = instruments.get("boost", {})
    g_current, g_max = _gauge(instruments.get("g_meter"))
    flight_state = flight.get("state", {})
    settings = flight.get("settings", {})
    lights = state.get("annunciators", {})
    return {
        "name": name,
        "instance_id": _instance(name)[1],
        "class_name": class_name,
        "manufacturer": MANUFACTURERS.get(class_name.split("_", 1)[0], ""),
        "type": _enum(state.get("type"), "VEHICLE_TYPE_"),
        "lights_on": bool(state.get("lights_enabled", False)),
        "landed": bool(flight_state.get("is_landed", False)),
        "gear": _enum(flight_state.get("gear"), "VEHICLE_COMPONENT_DEPLOYMENT_STATE_"),
        "vtol": _enum(flight_state.get("vtol"), "VEHICLE_COMPONENT_DEPLOYMENT_STATE_"),
        "instruments": {
            "speed": float(instruments.get("speed", 0.0)),
            "heading": float(instruments.get("heading", 0.0)),
            "altitude": float(instruments.get("altitude", 0.0)),
            "radar_altitude": float(instruments.get("radar_altitude", 0.0)),
            "vertical_speed": float(instruments.get("vertical_speed_indicator", 0.0)),
            "atmospheric_density": float(instruments.get("atmospheric_density", 0.0)),
            "g": g_current,
            "g_max": g_max,
            "hydrogen_fuel": float(instruments.get("hydrogen_fuel", 0.0)),
            "boost_engaged": bool(boost.get("engaged", False)),
            "boost_output": float(boost.get("output", 0.0)),
            "boost_reserves": float(boost.get("reserves", 0.0)),
            "boost_critical": bool(boost.get("critical", False)),
            "altitude_sent": "altitude" in instruments,
        },
        "settings": {key: {"enabled": bool(settings.get(key, {}).get("enabled", False)),
                           "active": bool(settings.get(key, {}).get("active", False))} for key in SETTINGS}
        | {key: bool(settings.get(key, False)) for key in FLAG_SETTINGS},
        "power": {flag: bool(state.get("power", {}).get(flag, False)) for flag in POWER_FLAGS},
        "lights": {light: _enum(lights.get(light), "ANNUNCIATOR_STATE_") for light in LIGHTS},
    }


def _weapons(weapons: dict | None) -> dict | None:
    if weapons is None:
        return None
    counts = {"decoy": 0, "noise": 0}
    for cm in weapons.get("countermeasures", []):
        kind = _enum(cm.get("type"), "COUNTERMEASURE_TYPE_")
        if kind in counts:
            counts[kind] = int(cm.get("amount", 0))
    return {
        # The id tells weapon instances apart: an Ironclad pilot seat lists the pilot's guns, the turret seats their own.
        "weapons": [{"name": _instance(w.get("name", ""))[0], "id": _instance(w.get("name", ""))[1],
                     "powered": bool(w.get("is_powered", False)), "ready": bool(w.get("ready_to_fire", False))}
                    for w in weapons.get("weapons", [])],
        "gimbals_locked": bool(weapons.get("settings", {}).get("gimbals_locked", False)),
        "countermeasures": counts,
    }


def normalize(frame: dict) -> dict:
    """The full state of one frame, with the derived flags that need only this frame."""
    vehicle = _vehicle(frame.get("vehicle"))
    instruments = vehicle["instruments"] if vehicle else {}
    altitude = instruments.get("altitude", 0.0)
    # Inside a planet's frame the game sends a real altitude; outside it sends 3.4e38. An instrument block
    # without any altitude (e.g. a frozen Ironclad) is not trusted either.
    in_planet = bool(instruments.get("altitude_sent")) and altitude < NO_PLANET_ALTITUDE
    return {
        "player": _player(frame.get("actor")),
        "vehicle": vehicle,
        "weapons": _weapons(frame.get("weapons")),
        "turret": {"light_amplification": bool(frame["turret"].get("light_amplification", False))}
        if "turret" in frame else None,
        "game_events": [_enum(e.get("type"), "GAME_EVENT_TYPE_") for e in frame.get("events", {}).get("events", [])],
        "derived": {
            "in_planet_frame": in_planet,
            "heading_valid": in_planet,
            "radar_valid": bool(vehicle) and instruments.get("radar_altitude") != altitude,
            "in_quantum_mode": bool(vehicle) and vehicle["lights"]["qdrv"] == "nominal",
        },
    }
