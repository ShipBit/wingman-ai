"""Star Citizen Position: where the pilot is, in numbers.

Star Citizen's Game.log names places but logs no coordinates. The game does
have a chat command, `/showlocation`, that puts the position on the clipboard
as `Coordinates: x:… y:… z:…` (metres from the centre of the star system).
This skill sends that command for the user, reads the clipboard, and turns
the numbers into what a pilot can use: the body (planet, moon, station),
height above its surface, the nearest known place, and distance and bearing
to a saved waypoint.

Planets and moons turn, so a fixed point on a surface wanders in global
coordinates. Waypoints are stored body-fixed: latitude, longitude and height
on a body, with the time of the measurement. The body data and the rotation
model come from the community tool Star-Citizen-Navigation (MIT), see
data/README.md. Stanton only, so far. The model's rotation offsets drift, so
the user calibrates a body once by saying where they are (calibrate_position).

The command is pasted into the chat, never typed, and only on request: a tool
call or the "Read position" command. See reader.py for why, and for why the
user has to say whether their chat is hidden.
"""

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from api.interface import SettingsConfig, SkillConfig
from skills.sc_position import geo
from skills.sc_position.calibration import Calibration, CalibrationStore
from skills.sc_position.reader import PositionReader, ReadError
from skills.sc_position.waypoints import Waypoint, WaypointStore
from skills.skill_base import Skill, command_action, tool

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext

BODIES_FILE = Path(__file__).parent / "data" / "bodies.json"
DEFAULT_KEYS = {"chat_input_key": "enter", "chat_toggle_key": "f12", "paste_key": "ctrl+v"}
DELAY_MS = (50, 150, 1000)
"""Minimum, default and maximum of "key_delay_ms"."""
DEFAULT_TOLERANCE_M = 1000.0
HUD_SECONDS = 15
LISTED = 10


def _utc(t: float) -> datetime:
    return datetime.fromtimestamp(t, timezone.utc)


class ScPosition(Skill):
    def __init__(
        self, config: SkillConfig, settings: SettingsConfig, wingman: "WingmanContext"
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        self._bodies: tuple = ()

    # --- settings, read fresh -------------------------------------------------

    def _key(self, name: str) -> str:
        value = self.retrieve_custom_property_value(name, [])
        return str(value).strip().lower() if value else DEFAULT_KEYS[name]

    def _chat_hidden(self) -> bool:
        value = self.retrieve_custom_property_value("chat_hidden", [])
        return True if value is None else bool(value)

    def _delay(self) -> float:
        low, default, high = DELAY_MS
        try:
            ms = float(self.retrieve_custom_property_value("key_delay_ms", []))
        except (TypeError, ValueError):
            ms = default
        return min(high, max(low, ms)) / 1000

    def _default_tolerance(self) -> float:
        try:
            metres = float(self.retrieve_custom_property_value("tolerance_m", []))
        except (TypeError, ValueError):
            metres = DEFAULT_TOLERANCE_M
        return max(10.0, metres)

    def _show_in_hud(self) -> bool:
        return bool(self.retrieve_custom_property_value("show_in_hud", []))

    # --- data ---------------------------------------------------------------------

    def _files(self) -> Path:
        return Path(self.get_generated_files_dir())

    def _waypoints(self) -> WaypointStore:
        return WaypointStore(self._files() / "waypoints.json")

    def _calibration(self) -> CalibrationStore:
        return CalibrationStore(self._files() / "calibration.json")

    def _get_bodies(self) -> tuple:
        if not self._bodies:
            self._bodies = geo.load_bodies(BODIES_FILE)
        return self._bodies

    # --- measuring ----------------------------------------------------------------

    async def _press(self, key: str) -> None:
        try:
            import keyboard.keyboard as keyboard
        except Exception as error:  # no keyboard access on this system
            raise ReadError(f"Key presses are not available here: {error}") from error
        try:
            await asyncio.to_thread(keyboard.send, key)
        except Exception as error:
            raise ReadError(f"Could not press {key}: {error}") from error

    async def _measure(self) -> geo.Fix:
        reader = PositionReader(
            press=self._press,
            read_clipboard=self.wingman.clipboard.read,
            write_clipboard=self.wingman.clipboard.write,
            sleep=asyncio.sleep,
            now=time.time,
            chat_hidden=self._chat_hidden(),
            chat_input_key=self._key("chat_input_key"),
            chat_toggle_key=self._key("chat_toggle_key"),
            paste_key=self._key("paste_key"),
            delay=self._delay(),
        )
        reading = await reader.read()
        x, y, z = geo.parse_clipboard(reading.text)
        return geo.locate(
            self._get_bodies(), x, y, z, reading.measured_at, self._calibration().deltas()
        )

    # --- wording --------------------------------------------------------------------

    def _describe(self, fix: geo.Fix, waypoint: "Waypoint | None") -> tuple[str, str]:
        """What to tell the model, and the short HUD line."""
        when = _utc(fix.measured_at).strftime("%H:%M:%S UTC")
        if fix.body.is_system:
            away = geo.format_distance(geo.distance_km(fix.local_km, (0.0, 0.0, 0.0)))
            where = f"open space, {away} from the centre of {fix.body.name}"
            hud = f"{fix.body.name} · open space"
        else:
            height = geo.format_distance(max(0.0, fix.alt_km))
            where = f"{height} above {fix.body.name}, lat {fix.lat:.2f}, lon {fix.lon:.2f}"
            hud = f"{fix.body.name} · {height} up"
        if fix.nearest:
            near = geo.format_distance(fix.nearest_km)
            where += f"; nearest known place {fix.nearest.name} ({near})"
            hud += f" · {fix.nearest.name} {near}"
        text = f"Position at {when}: {where}."
        if fix.body.rotates and self._calibration().get(fix.body.name) is None:
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
        arrived = distance * 1000 <= waypoint.tolerance_m
        text += f" Waypoint '{waypoint.name}': {geo.format_distance(distance)} away, bearing {bearing:.0f}° ({point})."
        text += " Arrived (within tolerance)." if arrived else f" Not yet within {geo.format_distance(waypoint.tolerance_m / 1000)}."
        hud += f" · → {waypoint.name} {geo.format_distance(distance)} {point}" + (" ✓" if arrived else "")
        return text, hud

    async def _show(self, line: str) -> None:
        if self._show_in_hud():
            await self.wingman.hud.show_message(self.wingman.name, line, duration=HUD_SECONDS)

    @staticmethod
    def _listed(store: WaypointStore) -> str:
        names = [w.name for w in store.all()]
        if not names:
            return ""
        more = f" (and {len(names) - LISTED} more)" if len(names) > LISTED else ""
        return f" Saved waypoints: {', '.join(names[:LISTED])}{more}."

    # --- tools --------------------------------------------------------------------------

    @tool(
        description=(
            "Measure the current position in Star Citizen and save it as a waypoint. "
            "Use when the user says 'save this place as …', 'mark this spot' or "
            "'remember where I am'."
        )
    )
    async def save_waypoint(self, name: str, tolerance_m: int = 0) -> str:
        """Args:
        name: The waypoint's name.
        tolerance_m: Radius in metres that counts as arrived. 0 uses the skill's default.
        """
        name = (name or "").strip()
        if not name:
            return "A waypoint needs a name."
        try:
            fix = await self._measure()
        except (RuntimeError, ValueError) as error:
            return f"Could not read the position: {error}"
        tolerance = float(tolerance_m) if tolerance_m and tolerance_m > 0 else self._default_tolerance()
        waypoint = Waypoint(
            name=name, body=fix.body.name, lat=fix.lat, lon=fix.lon, alt_m=fix.alt_km * 1000,
            tolerance_m=tolerance, measured_at=_utc(fix.measured_at).isoformat(timespec="seconds"),
            global_m=list(fix.global_m),
        )
        self._waypoints().add(waypoint)
        text, hud = self._describe(fix, None)
        await self._show(f"Saved {name} · {hud}")
        return f"Saved waypoint '{name}' on {fix.body.name}, tolerance {geo.format_distance(tolerance / 1000)}. {text}"

    @tool(
        description=(
            "Measure the current position in Star Citizen: body, height above the surface, "
            "nearest known place, and distance and bearing to a waypoint (the active one when "
            "none is named). Use for 'where am I', 'how far to …', 'am I there yet' and "
            "'which waypoints do I have'."
        )
    )
    async def check_position(self, waypoint: str = "") -> str:
        """Args:
        waypoint: A saved waypoint to measure against. Empty uses the active one, if any.
        """
        store = self._waypoints()
        if waypoint and waypoint.strip():
            target = store.find(waypoint)
            if target is None:
                listed = self._listed(store)
                return f"No waypoint named '{waypoint.strip()}'." + (listed or " No waypoints saved yet.")
            store.activate(target.name)
        else:
            target = store.active()
        try:
            fix = await self._measure()
        except (RuntimeError, ValueError) as error:
            return f"Could not read the position: {error}"
        text, hud = self._describe(fix, target)
        await self._show(hud)
        return text if target else text + self._listed(store)

    @tool(
        description=(
            "Calibrate the rotation of the body the user is on: the user names the known "
            "place they are at right now, e.g. 'I am at Port Tressler'. Use when a reported "
            "distance to the place the user is at is clearly wrong, or when a body is "
            "reported as not calibrated."
        )
    )
    async def calibrate_position(self, place: str) -> str:
        """Args:
        place: The known place the user is at right now, as the game names it.
        """
        place = (place or "").strip()
        if not place:
            return "Which place is the user at?"
        try:
            fix = await self._measure()
        except (RuntimeError, ValueError) as error:
            return f"Could not read the position: {error}"
        if not fix.body.rotates:
            return f"{fix.body.name} does not rotate; there is nothing to calibrate here."
        poi = geo.find_poi(fix.body, place)
        if poi is None:
            near = ", ".join(p.name for p, _ in geo.nearest_pois(fix.body, fix.local_km, LISTED))
            return f"'{place}' is not a known place on {fix.body.name}. Known places nearby: {near}."
        delta = geo.calibration_delta(fix.local_km, poi)
        total = (fix.correction_deg + delta + 180.0) % 360.0 - 180.0
        corrected = geo.to_body_fixed(
            fix.body, fix.global_m[0] / 1000, fix.global_m[1] / 1000, fix.global_m[2] / 1000,
            fix.measured_at, total,
        )
        residual_km = geo.distance_km(corrected, (poi.x, poi.y, poi.z))
        minutes = abs(delta) / (0.1 / fix.body.rotation_hours) / 60
        self._calibration().set(
            Calibration(
                body=fix.body.name, delta_deg=total, place=poi.name,
                calibrated_at=_utc(fix.measured_at).isoformat(timespec="seconds"),
                residual_m=residual_km * 1000,
            )
        )
        await self._show(f"Calibrated {fix.body.name} at {poi.name} · {delta:+.2f}°")
        return (
            f"Calibrated {fix.body.name} at {poi.name}: rotation corrected by {delta:+.2f}° "
            f"(the model was {minutes:.1f} minutes {'behind' if delta > 0 else 'ahead'}); "
            f"remaining offset to the place {geo.format_distance(residual_km)}. "
            f"Waypoints saved on {fix.body.name} before this calibration are in the old "
            "frame and should be saved again."
        )

    @command_action(
        label="Read position",
        description=(
            "Reads the position from Star Citizen and reports the body, height, nearest "
            "place and the way to the active waypoint."
        ),
        respond="ai",
    )
    async def read_position(self) -> str:
        store = self._waypoints()
        try:
            fix = await self._measure()
        except (RuntimeError, ValueError) as error:
            return f"Could not read the position: {error}"
        text, hud = self._describe(fix, store.active())
        await self._show(hud)
        return text
