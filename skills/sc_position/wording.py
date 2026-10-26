"""What a measurement says, for the model and for the HUD.

A place in the data is one point; a station or a city is kilometres across,
and the rotation model leaves a kilometre or two even after calibration. So
within `place_km` of a place the pilot is *at* it, and the text says so
without a distance, or the model hedges ("1.4 km away, so probably at Port
Tressler"). Up to NEAR_FACTOR times that radius the pilot is *near* it, with
the distance. Beyond that the nearest place is named as a reference.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from skills.sc_position import geo
from skills.sc_position.waypoints import Waypoint

NEAR_FACTOR = 5
"""'Near' a place reaches this many place radii."""
ON_SURFACE_KM = 1.0
"""Below this height the pilot is on the body, not above it."""


def describe(
    fix: geo.Fix, waypoint: Optional[Waypoint], *, calibrated: bool, place_km: float
) -> tuple[str, str]:
    """The sentence for the model, and the short HUD line."""
    when = datetime.fromtimestamp(fix.measured_at, timezone.utc).strftime("%H:%M:%S UTC")
    if fix.body.is_system:
        away = geo.format_distance(geo.distance_km(fix.local_km, (0.0, 0.0, 0.0)))
        where = f"open space, {away} from the centre of {fix.body.name}"
        hud = f"{fix.body.name} · open space"
    else:
        height = geo.format_distance(max(0.0, fix.alt_km))
        if fix.alt_km < ON_SURFACE_KM:
            body, body_hud = f"on {fix.body.name}", f"{fix.body.name} surface"
        else:
            body, body_hud = f"{height} above {fix.body.name}", f"{fix.body.name} {height} up"
        if fix.nearest and fix.nearest_km <= place_km:
            where = f"at {fix.nearest.name} ({body})"
            hud = f"{fix.nearest.name} · {body_hud}"
        elif fix.nearest and fix.nearest_km <= place_km * NEAR_FACTOR:
            near = geo.format_distance(fix.nearest_km)
            where = f"near {fix.nearest.name}, {near} from it, {body}"
            hud = f"near {fix.nearest.name} {near} · {body_hud}"
        else:
            where = f"{body}, lat {fix.lat:.2f}, lon {fix.lon:.2f}"
            hud = body_hud
            if fix.nearest:
                near = geo.format_distance(fix.nearest_km)
                where += f"; nearest known place {fix.nearest.name} ({near})"
                hud += f" · {fix.nearest.name} {near}"
    text = f"Position at {when}: {where}."
    if fix.body.rotates and not calibrated:
        text += (
            f" The rotation of {fix.body.name} is not calibrated yet, so places and "
            "waypoints on it can be off by several km; the user can say where they "
            "are to calibrate it."
        )
    if waypoint is None:
        return text, hud
    if waypoint.body != fix.body.name:
        text += f" Waypoint '{waypoint.name}' is on {waypoint.body}, not here."
        hud += f" · {waypoint.name}: on {waypoint.body}"
        return text, hud
    target = geo.body_fixed(fix.body, waypoint.lat, waypoint.lon, waypoint.alt_m / 1000)
    distance = geo.distance_km(fix.local_km, target)
    bearing = geo.bearing_deg(fix.lat, fix.lon, waypoint.lat, waypoint.lon)
    point = geo.compass(bearing)
    if distance * 1000 <= waypoint.tolerance_m:
        text += f" Waypoint '{waypoint.name}': arrived, within its {geo.format_distance(waypoint.tolerance_m / 1000)}."
        hud += f" · {waypoint.name} ✓"
    else:
        text += (
            f" Waypoint '{waypoint.name}': {geo.format_distance(distance)} away, "
            f"bearing {bearing:.0f}° ({point}); counts as arrived within "
            f"{geo.format_distance(waypoint.tolerance_m / 1000)}."
        )
        hud += f" · → {waypoint.name} {geo.format_distance(distance)} {point}"
    return text, hud
