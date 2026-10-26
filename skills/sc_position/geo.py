"""Coordinates for Star Citizen: from the game's global metres to a body,
latitude, longitude and height, and back.

`/showlocation` gives metres from the centre of the star system. Planets and
moons turn about their own axis, so a point on a surface wanders in those
numbers; a place is only fixed as latitude, longitude and height on its body,
together with the time of the measurement that turns one into the other.

The rotation model is the community's (Star-Citizen-Navigation, MIT, see
data/README.md): a body turns 0.1 / rotation_hours degrees per second,
counted from the first second of 2020 (UTC), plus an offset measured per
body. Checked against Port Tressler on 2026-10-26 with a current game build:
1.6 km off. The longitude sign follows that tool; which way is east has not
been checked in the game yet.

Pure functions. Only load_bodies reads a file.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROTATION_REFERENCE = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
"""Unix time the rotation model counts from."""
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
_LINE = re.compile(
    r"^\s*Coordinates:\s*x:\s*(-?\d+(?:\.\d+)?)\s+y:\s*(-?\d+(?:\.\d+)?)\s+z:\s*(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Poi:
    """A named place, body-fixed, in km."""

    name: str
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class Body:
    name: str
    x: float
    y: float
    z: float
    """Centre in global km."""
    radius_km: float
    om_radius_km: float
    reach_km: float
    """Up to this far from the centre a position counts as at this body."""
    rotation_hours: float
    rotation_adjust_deg: float
    pois: tuple = ()
    is_system: bool = False
    """The frame for open space: the origin, no rotation."""

    @property
    def rotates(self) -> bool:
        return self.rotation_hours > 0


@dataclass(frozen=True)
class Fix:
    """One measurement, resolved."""

    body: Body
    lat: float
    lon: float
    alt_km: float
    local_km: tuple
    """Body-fixed km."""
    global_m: tuple
    measured_at: float
    nearest: Optional[Poi]
    nearest_km: float


def parse_clipboard(text: str) -> tuple[float, float, float]:
    """x, y, z in metres from a `Coordinates: x:… y:… z:…` line.
    ValueError for anything else."""
    match = _LINE.match(text or "")
    if not match:
        raise ValueError("not a Coordinates line")
    x, y, z = (float(group) for group in match.groups())
    return x, y, z


def load_bodies(path) -> tuple[Body, ...]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    bodies = []
    for item in data["bodies"]:
        pois = tuple(Poi(p["name"], p["x"], p["y"], p["z"]) for p in item.get("pois", []))
        bodies.append(
            Body(
                name=item["name"],
                x=item["x"], y=item["y"], z=item["z"],
                radius_km=item.get("radius_km", 0.0),
                om_radius_km=item.get("om_radius_km", 0.0),
                reach_km=item.get("reach_km", 0.0),
                rotation_hours=item.get("rotation_hours", 0.0),
                rotation_adjust_deg=item.get("rotation_adjust_deg", 0.0),
                pois=pois,
                is_system=bool(item.get("system", False)),
            )
        )
    return tuple(bodies)


def rotation_deg(body: Body, t: float) -> float:
    """How far `body` has turned at Unix time `t`, in degrees."""
    if not body.rotates:
        return 0.0
    degrees_per_second = 0.1 / body.rotation_hours
    return (degrees_per_second * (t - ROTATION_REFERENCE) + body.rotation_adjust_deg) % 360.0


def resolve_body(bodies, x_km: float, y_km: float, z_km: float) -> Optional[Body]:
    """The body a global position belongs to: the nearest one within its
    reach, else the system frame, else None."""
    best = None
    for body in bodies:
        if body.is_system or body.reach_km <= 0:
            continue
        distance = math.dist((x_km, y_km, z_km), (body.x, body.y, body.z))
        if distance <= body.reach_km and (best is None or distance < best[0]):
            best = (distance, body)
    if best:
        return best[1]
    return next((body for body in bodies if body.is_system), None)


def to_body_fixed(body: Body, x_km: float, y_km: float, z_km: float, t: float) -> tuple:
    """Global km at time `t` into the body's own, rotating frame."""
    lx, ly, lz = x_km - body.x, y_km - body.y, z_km - body.z
    angle = math.radians(-rotation_deg(body, t))
    return (
        lx * math.cos(angle) - ly * math.sin(angle),
        lx * math.sin(angle) + ly * math.cos(angle),
        lz,
    )


def lat_lon_alt(body: Body, local: tuple) -> tuple[float, float, float]:
    """Latitude and longitude in degrees, height above the surface in km."""
    x, y, z = local
    r = math.sqrt(x * x + y * y + z * z)
    if r == 0:
        return 0.0, 0.0, -body.radius_km
    lat = math.degrees(math.asin(max(-1.0, min(1.0, z / r))))
    lon = -math.degrees(math.atan2(x, y))
    return lat, lon, r - body.radius_km


def body_fixed(body: Body, lat: float, lon: float, alt_km: float) -> tuple:
    """The inverse of lat_lon_alt."""
    r = body.radius_km + alt_km
    horizontal = r * math.cos(math.radians(lat))
    return (
        -horizontal * math.sin(math.radians(lon)),
        horizontal * math.cos(math.radians(lon)),
        r * math.sin(math.radians(lat)),
    )


def locate(bodies, x_m: float, y_m: float, z_m: float, t: float) -> Fix:
    """Resolve a measurement in global metres taken at Unix time `t`."""
    x, y, z = x_m / 1000, y_m / 1000, z_m / 1000
    body = resolve_body(bodies, x, y, z)
    if body is None:
        raise ValueError("no body data")
    local = to_body_fixed(body, x, y, z, t)
    lat, lon, alt = lat_lon_alt(body, local)
    nearest, nearest_km = None, math.inf
    for poi in body.pois:
        distance = math.dist(local, (poi.x, poi.y, poi.z))
        if distance < nearest_km:
            nearest, nearest_km = poi, distance
    return Fix(
        body=body, lat=lat, lon=lon, alt_km=alt, local_km=local,
        global_m=(x_m, y_m, z_m), measured_at=t,
        nearest=nearest, nearest_km=nearest_km if nearest else 0.0,
    )


def distance_km(a: tuple, b: tuple) -> float:
    return math.dist(a, b)


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from the first point to the second, 0 = north, 90 = east."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.cos(p2) * math.sin(dl)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(x, y)) % 360.0


def compass(bearing: float) -> str:
    return COMPASS[int(((bearing % 360.0) + 22.5) // 45) % 8]


def format_distance(km: float) -> str:
    metres = km * 1000
    if metres < 1000:
        return f"{metres:.0f} m"
    if km < 100:
        return f"{km:.1f} km"
    return f"{km:,.0f} km"
