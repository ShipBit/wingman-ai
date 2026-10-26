"""Per-body corrections to the rotation model, measured by the user.

The community data give each body a rotation offset from 2022. The offsets
drift: on 2026-10-26 microTech was about four degrees off, which is 56 km at
Port Tressler. A clock error looks the same. One measurement at a known
place fixes a body: the correction is the angle between where the model puts
the measurement and where the place is, about the body's axis.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from skills.sc_position.store import read_json, write_json


@dataclass
class Calibration:
    body: str
    delta_deg: float
    """Added to the body's rotation offset."""
    place: str
    calibrated_at: str
    """ISO 8601, UTC."""
    residual_m: float
    """How far the measurement still was from the place after the correction."""


class CalibrationStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._bodies: Optional[dict[str, Calibration]] = None

    def _load(self) -> dict[str, Calibration]:
        if self._bodies is None:
            self._bodies = {}
            data = read_json(self.path)
            for body, item in ((data or {}).get("bodies") or {}).items():
                try:
                    self._bodies[body] = Calibration(**item)
                except TypeError:
                    continue
        return self._bodies

    def get(self, body: str) -> Optional[Calibration]:
        return self._load().get(body)

    def deltas(self) -> dict[str, float]:
        """Body name to correction in degrees, for geo.locate."""
        return {body: c.delta_deg for body, c in self._load().items()}

    def set(self, calibration: Calibration) -> None:
        self._load()[calibration.body] = calibration
        write_json(self.path, {"bodies": {b: asdict(c) for b, c in self._load().items()}})
