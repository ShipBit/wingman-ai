"""Saved places, body-fixed, in one JSON file in the skill's files folder."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Waypoint:
    name: str
    body: str
    lat: float
    lon: float
    alt_m: float
    tolerance_m: float
    measured_at: str
    """ISO 8601, UTC."""
    global_m: list
    """The raw measurement, for the record."""


class WaypointStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._active: Optional[str] = None
        self._waypoints: list[Waypoint] = []
        self._loaded = False

    # --- reading --------------------------------------------------------------

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        self._active = data.get("active") or None
        for item in data.get("waypoints", []):
            try:
                self._waypoints.append(Waypoint(**item))
            except TypeError:
                continue  # a field from another version; the rest still loads

    def all(self) -> list[Waypoint]:
        self._load()
        return list(self._waypoints)

    def find(self, name: str) -> Optional[Waypoint]:
        """The waypoint called `name`: the same name first, then one that
        starts with it, then one that contains it. Case does not matter."""
        self._load()
        wanted = (name or "").strip().lower()
        if not wanted:
            return None
        for match in (
            lambda n: n == wanted,
            lambda n: n.startswith(wanted),
            lambda n: wanted in n,
        ):
            for waypoint in self._waypoints:
                if match(waypoint.name.lower()):
                    return waypoint
        return None

    def active(self) -> Optional[Waypoint]:
        self._load()
        return self.find(self._active) if self._active else None

    # --- writing --------------------------------------------------------------

    def add(self, waypoint: Waypoint, activate: bool = True) -> None:
        """Save a waypoint; one with the same name is replaced."""
        self._load()
        self._waypoints = [w for w in self._waypoints if w.name.lower() != waypoint.name.lower()]
        self._waypoints.append(waypoint)
        if activate:
            self._active = waypoint.name
        self._save()

    def activate(self, name: str) -> None:
        self._load()
        self._active = name
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"active": self._active, "waypoints": [asdict(w) for w in self._waypoints]},
            indent=1, ensure_ascii=False,
        )
        fd, temporary = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
