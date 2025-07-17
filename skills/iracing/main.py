import asyncio
import threading
import time
from typing import TYPE_CHECKING, Any, Dict, Tuple, Callable
from api.enums import LogType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from services.benchmark import Benchmark
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman

try:
    import irsdk
except ImportError:
    irsdk = None


class WatchdogEvent:
    """Represents a watchdog event that can be triggered based on telemetry data"""

    def __init__(
        self,
        name: str,
        check_interval: float,
        cooldown_period: float,
        threshold_func: Callable[[dict, dict], bool],
        prompt_template: str,
        enabled: bool = True,
    ):
        self.name = name
        self.check_interval = check_interval
        self.cooldown_period = cooldown_period
        self.threshold_func = threshold_func
        self.prompt_template = prompt_template
        self.enabled = enabled
        self.last_triggered = 0
        self.last_checked = 0
        self.state = {}  # Store previous values and state data


class IRacing(Skill):
    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        # Initialize telemetry data structures
        self.telemetry_data = {}
        self.session_data = {}
        self.is_connected = False
        self.watchdog_thread = None
        self.watchdog_running = False
        self.last_update = 0
        self._last_session_update = 0  # Track session data updates

        self.enable_watchdog = False
        self.watchdog_interval = 10.0
        self.telemetry_awareness = False
        self.watchdog_prompt = None
        if irsdk:
            self.ir = irsdk.IRSDK()

        # Start watchdog after validation
        self.watchdog_started = False

        # Initialize watchdog events system (will be populated after config loading)
        self.watchdog_events = []
        self.watchdog_event_configs = {}

        # Initialize telemetry dictionary structure once
        self._init_telemetry_structure()

    def _init_telemetry_structure(self):
        """Initialize telemetry dictionary structure once to avoid repeated allocation"""
        self.telemetry_data = {
            "Speed": 0,
            "RPM": 0,
            "Gear": 0,
            "FuelLevel": 0,
            "FuelUsePerHour": 0,
            "PlayerCarPosition": 1,
            "PlayerCarIdx": 0,
            "Lap": 0,
            "SessionTime": 0,
            "SessionTimeRemain": 0,
            "SessionFlags": 0,
            "SessionState": 0,
            "IsReplayPlaying": False,
            "LapLastLapTime": 0,
            "LapBestLapTime": 0,
            "LapCurrentLapTime": 0,
            # Delta timing and sector analysis data
            "LapDistPct": 0,
            "LapDeltaToBestLap": 0,
            "LapDeltaToBestLap_OK": False,
            "LapDeltaToOptimalLap": 0,
            "LapDeltaToOptimalLap_OK": False,
            "LapDeltaToSessionBestLap": 0,
            "LapDeltaToSessionBestLap_OK": False,
            "LapDeltaToSessionLastlLap": 0,
            "LapDeltaToSessionLastlLap_OK": False,
            "LFtempCM": [0, 0, 0],
            "RFtempCM": [0, 0, 0],
            "LRtempCM": [0, 0, 0],
            "RRtempCM": [0, 0, 0],
            "LFwearM": 0,
            "RFwearM": 0,
            "LRwearM": 0,
            "RRwearM": 0,
            "TrackTemp": 0,
            "AirTemp": 0,
            "RelativeHumidity": 0,
            "WindVel": 0,
            "PlayerCarMyIncidentCount": 0,
            "EngineWarnings": 0,
            "FuelPressureWarnings": 0,
            "WaterTempWarnings": 0,
            "OilTempWarnings": 0,
            "LFtempCL": 0,
            "RFtempCL": 0,
            "LRtempCL": 0,
            "RRtempCL": 0,
            "PitWindowOpen": False,
            "CarIdxPosition": [0],
            "dcBrakeBias": 0,
            # Enhanced competitor and proximity data
            "CarDistAhead": 0,
            "CarDistBehind": 0,
            # Additional setup and car state variables
            "LFpressure": 0,
            "RFpressure": 0,
            "LRpressure": 0,
            "RRpressure": 0,
        }

        # Initialize session data structure
        self.session_data = {
            "WeekendInfo": None,
            "SessionInfo": None,
            "CarSetup": None,
        }

    def _telemetry(self, key, default=None):
        """Safely get telemetry data with fallback"""
        try:
            if self.ir and self.ir.is_initialized and self.ir.is_connected:
                value = self.ir[key]
                return value if value is not None else default
            return default
        except (KeyError, AttributeError):
            return default

    def _update_telemetry_data(self):
        """Update telemetry data in-place to avoid memory allocation"""
        # Update telemetry data structure in-place
        self.telemetry_data.update(
            {
                "Speed": self._telemetry("Speed", 0),
                "RPM": self._telemetry("RPM", 0),
                "Gear": self._telemetry("Gear", 0),
                "FuelLevel": self._telemetry("FuelLevel", 0),
                "FuelUsePerHour": self._telemetry("FuelUsePerHour", 0),
                "PlayerCarPosition": self._telemetry("PlayerCarPosition", 1),
                "PlayerCarIdx": self._telemetry("PlayerCarIdx", 0),
                "Lap": self._telemetry("Lap", 0),
                "SessionTime": self._telemetry("SessionTime", 0),
                "SessionTimeRemain": self._telemetry("SessionTimeRemain", 0),
                "SessionFlags": self._telemetry("SessionFlags", 0),
                "SessionState": self._telemetry("SessionState", 0),
                "IsReplayPlaying": self._telemetry("IsReplayPlaying", False),
                "LapLastLapTime": self._telemetry("LapLastLapTime", 0),
                "LapBestLapTime": self._telemetry("LapBestLapTime", 0),
                "LapCurrentLapTime": self._telemetry("LapCurrentLapTime", 0),
                # Delta timing and sector analysis data
                "LapDistPct": self._telemetry("LapDistPct", 0),
                "LapDeltaToBestLap": self._telemetry("LapDeltaToBestLap", 0),
                "LapDeltaToBestLap_OK": self._telemetry("LapDeltaToBestLap_OK", False),
                "LapDeltaToOptimalLap": self._telemetry("LapDeltaToOptimalLap", 0),
                "LapDeltaToOptimalLap_OK": self._telemetry(
                    "LapDeltaToOptimalLap_OK", False
                ),
                "LapDeltaToSessionBestLap": self._telemetry(
                    "LapDeltaToSessionBestLap", 0
                ),
                "LapDeltaToSessionBestLap_OK": self._telemetry(
                    "LapDeltaToSessionBestLap_OK", False
                ),
                "LapDeltaToSessionLastlLap": self._telemetry(
                    "LapDeltaToSessionLastlLap", 0
                ),
                "LapDeltaToSessionLastlLap_OK": self._telemetry(
                    "LapDeltaToSessionLastlLap_OK", False
                ),
                "LFtempCM": self._telemetry("LFtempCM", [0, 0, 0]),
                "RFtempCM": self._telemetry("RFtempCM", [0, 0, 0]),
                "LRtempCM": self._telemetry("LRtempCM", [0, 0, 0]),
                "RRtempCM": self._telemetry("RRtempCM", [0, 0, 0]),
                "LFwearM": self._telemetry("LFwearM", 0),
                "RFwearM": self._telemetry("RFwearM", 0),
                "LRwearM": self._telemetry("LRwearM", 0),
                "RRwearM": self._telemetry("RRwearM", 0),
                "TrackTemp": self._telemetry("TrackTemp", 0),
                "AirTemp": self._telemetry("AirTemp", 0),
                "RelativeHumidity": self._telemetry("RelativeHumidity", 0),
                "WindVel": self._telemetry("WindVel", 0),
                "PlayerCarMyIncidentCount": self._telemetry(
                    "PlayerCarMyIncidentCount", 0
                ),
                "EngineWarnings": self._telemetry("EngineWarnings", 0),
                "FuelPressureWarnings": self._telemetry("FuelPressureWarnings", 0),
                "WaterTempWarnings": self._telemetry("WaterTempWarnings", 0),
                "OilTempWarnings": self._telemetry("OilTempWarnings", 0),
                "LFtempCL": self._telemetry("LFtempCL", 0),
                "RFtempCL": self._telemetry("RFtempCL", 0),
                "LRtempCL": self._telemetry("LRtempCL", 0),
                "RRtempCL": self._telemetry("RRtempCL", 0),
                "PitWindowOpen": self._telemetry("PitWindowOpen", False),
                "CarIdxPosition": self._telemetry("CarIdxPosition", [0]),
                "dcBrakeBias": self._telemetry("dcBrakeBias", 0),
                # Enhanced competitor and proximity data
                "CarDistAhead": self._telemetry("CarDistAhead", 0),
                "CarDistBehind": self._telemetry("CarDistBehind", 0),
                # Additional setup and car state variables
                "LFpressure": self._telemetry("LFpressure", 0),
                "RFpressure": self._telemetry("RFpressure", 0),
                "LRpressure": self._telemetry("LRpressure", 0),
                "RRpressure": self._telemetry("RRpressure", 0),
            }
        )

        # Update session data structure in-place
        self.session_data.update(
            {
                "WeekendInfo": self._telemetry("WeekendInfo"),
                "SessionInfo": self._telemetry("SessionInfo"),
                "CarSetup": self._telemetry("CarSetup"),
            }
        )

    def _init_watchdog_events(self):
        """Initialize watchdog events with their threshold functions"""
        self.watchdog_events = [
            # Critical Events - High Priority
            WatchdogEvent(
                name="damage_detection",
                check_interval=self.damage_alerts_interval,
                cooldown_period=self.alert_cooldown_period,
                threshold_func=self._check_damage_threshold,
                prompt_template="[WATCHDOG_EVENT] Vehicle damage detected - Engine warnings: {engine_warnings}",
                enabled=self.damage_alerts_enabled,
            ),
            WatchdogEvent(
                name="fuel_critical",
                check_interval=self.fuel_alerts_interval,
                cooldown_period=self.alert_cooldown_period,
                threshold_func=self._check_fuel_threshold,
                prompt_template="[WATCHDOG_EVENT] Fuel critical - Only {laps_remaining:.1f} laps of fuel remaining, need {laps_needed:.1f} to finish",
                enabled=self.fuel_alerts_enabled,
            ),
            WatchdogEvent(
                name="flag_change",
                check_interval=self.flag_alerts_interval,
                cooldown_period=self.alert_cooldown_period,
                threshold_func=self._check_flag_threshold,
                prompt_template="[WATCHDOG_EVENT] Flag status changed to: {flag_status}",
                enabled=self.flag_alerts_enabled,
            ),
            WatchdogEvent(
                name="tire_overheat",
                check_interval=self.tire_alerts_interval,
                cooldown_period=self.alert_cooldown_period,
                threshold_func=self._check_tire_temp_threshold,
                prompt_template="[WATCHDOG_EVENT] Tire overheating - {tire_position} at {temperature:.0f}°F",
                enabled=self.tire_alerts_enabled,
            ),
            WatchdogEvent(
                name="tire_pressure_loss",
                check_interval=self.tire_alerts_interval
                * 1.5,  # Check slightly less frequently
                cooldown_period=self.alert_cooldown_period,
                threshold_func=self._check_tire_pressure_threshold,
                prompt_template="[WATCHDOG_EVENT] Tire pressure issue - {tire_position} at {pressure:.1f} PSI, {change_type}",
                enabled=self.tire_alerts_enabled,
            ),
            WatchdogEvent(
                name="tire_wear_critical",
                check_interval=self.tire_alerts_interval
                * 2.0,  # Check less frequently as wear is gradual
                cooldown_period=self.alert_cooldown_period
                * 2,  # Longer cooldown for wear alerts
                threshold_func=self._check_tire_wear_threshold,
                prompt_template="[WATCHDOG_EVENT] Critical tire wear - {tire_position} at {wear_percent:.0f}% worn, consider pit stop",
                enabled=self.tire_alerts_enabled,
            ),
            # Strategic Events - Medium Priority
            WatchdogEvent(
                name="pit_window",
                check_interval=15.0,
                cooldown_period=self.alert_cooldown_period,
                threshold_func=self._check_pit_window_threshold,
                prompt_template="[WATCHDOG_EVENT] Pit window status - Fuel for approximately {laps_remaining} more laps",
                enabled=self.pit_window_alerts_enabled,
            ),
            WatchdogEvent(
                name="performance_drop",
                check_interval=self.performance_alerts_interval,
                cooldown_period=self.alert_cooldown_period,
                threshold_func=self._check_performance_delta_threshold,
                prompt_template="[WATCHDOG_EVENT] Performance drop detected - Delta to personal best: {delta:.2f}s consistently slow",
                enabled=self.performance_alerts_enabled,
            ),
            WatchdogEvent(
                name="incident_alert",
                check_interval=5.0,
                cooldown_period=self.alert_cooldown_period,
                threshold_func=self._check_incidents_threshold,
                prompt_template="[WATCHDOG_EVENT] Incident occurred - Count now: {incidents}x",
                enabled=self.incident_alerts_enabled,
            ),
            WatchdogEvent(
                name="position_change",
                check_interval=self.position_alerts_interval,
                cooldown_period=self.alert_cooldown_period,
                threshold_func=self._check_position_change_threshold,
                prompt_template="[WATCHDOG_EVENT] Position change - From P{old_pos} to P{new_pos}",
                enabled=self.position_alerts_enabled,
            ),
            WatchdogEvent(
                name="personal_best",
                check_interval=10.0,
                cooldown_period=self.alert_cooldown_period,
                threshold_func=self._check_personal_best_threshold,
                prompt_template="[WATCHDOG_EVENT] {improvement_message}{lap_context}",
                enabled=self.personal_best_alerts_enabled,
            ),
            WatchdogEvent(
                name="track_conditions",
                check_interval=30.0,
                cooldown_period=self.alert_cooldown_period,
                threshold_func=self._check_track_conditions_threshold,
                prompt_template="[WATCHDOG_EVENT] Track conditions changed - Track: {track_temp}°C, Air: {air_temp}°C",
                enabled=self.track_condition_alerts_enabled,
            ),
        ]

    def _check_damage_threshold(self, telemetry_data):
        """Check for damage threshold events"""
        if not telemetry_data:
            return False, {}

        # Check for damage increase
        engine_warn = telemetry_data.get("EngineWarnings", 0)
        fuel_pressure_warn = telemetry_data.get("FuelPressureWarnings", 0)
        water_temp_warn = telemetry_data.get("WaterTempWarnings", 0)
        oil_temp_warn = telemetry_data.get("OilTempWarnings", 0)

        warning_types = []
        if engine_warn > 0:
            warning_types.append("Engine")
        if fuel_pressure_warn > 0:
            warning_types.append("Fuel Pressure")
        if water_temp_warn > 0:
            warning_types.append("Water Temperature")
        if oil_temp_warn > 0:
            warning_types.append("Oil Temperature")

        if warning_types:
            return True, {"engine_warnings": ", ".join(warning_types)}

        return False, {}

    def _check_fuel_threshold(self, telemetry_data):
        """Check for fuel critical threshold events"""
        if not telemetry_data:
            return False, {}

        fuel_level = telemetry_data.get("FuelLevel", 0)
        fuel_use_per_hour = telemetry_data.get("FuelUsePerHour", 0)
        session_time = telemetry_data.get("SessionTime", 0)
        session_time_remain = telemetry_data.get("SessionTimeRemain", 0)
        lap_num = telemetry_data.get("Lap", 0)
        current_lap_time = telemetry_data.get("LapCurrentLapTime", 0)

        # Don't alert for fuel in very early stages of session
        # Wait until at least lap 5 and 10 minutes into session to get accurate consumption data
        if lap_num < 5 or session_time < 600:
            return False, {}

        # Only alert if we have meaningful fuel consumption data
        if fuel_use_per_hour <= 0 or fuel_level <= 0:
            return False, {}

        # Calculate more accurate laps remaining based on current consumption
        # Convert fuel use per hour to fuel use per second
        fuel_use_per_second = fuel_use_per_hour / 3600.0

        # Estimate lap time (use current lap time if available, otherwise estimate from session progress)
        if (
            current_lap_time > 0 and current_lap_time < 300
        ):  # Valid lap time (under 5 minutes)
            estimated_lap_time = current_lap_time
        elif lap_num > 0 and session_time > 0:
            # Estimate average lap time from session progress
            estimated_lap_time = session_time / lap_num
        else:
            # Fallback to typical lap time estimate
            estimated_lap_time = 90.0  # 1.5 minutes

        # Calculate fuel use per lap
        fuel_per_lap = fuel_use_per_second * estimated_lap_time

        if fuel_per_lap <= 0:
            return False, {}

        # Calculate laps remaining with current fuel
        laps_remaining = fuel_level / fuel_per_lap

        # Calculate laps needed to finish session
        if session_time_remain > 0 and estimated_lap_time > 0:
            laps_needed = session_time_remain / estimated_lap_time
        else:
            laps_needed = 0

        # Only alert if we're in a race scenario (session has significant time remaining)
        # and fuel is actually critically low
        if session_time_remain < 300:  # Less than 5 minutes remaining
            return False, {}  # Don't alert for very short remaining time

        # Much more conservative thresholds - only alert when driver MUST act
        if (
            session_time_remain > 1800
        ):  # More than 30 minutes remaining (endurance race)
            # For long races, alert when less than 3 laps of fuel remain
            fuel_threshold = 3.0
        elif session_time_remain > 900:  # 15-30 minutes remaining
            # For medium races, alert when less than 2 laps remain
            fuel_threshold = 2.0
        else:
            # For shorter races (5-15 min), alert when less than 1 lap remains
            fuel_threshold = 1.0

        # Additional check: only alert if we actually need more fuel to finish
        fuel_shortage = max(0, laps_needed - laps_remaining)

        if laps_remaining < fuel_threshold and fuel_shortage > 0.5:
            return True, {
                "fuel_level": fuel_level,
                "laps_remaining": laps_remaining,
                "laps_needed": laps_needed,
                "shortage": fuel_shortage,
            }

        return False, {}

    def _interpret_session_flags(self, flags):
        """Interpret iRacing session flags into readable format"""
        flag_meanings = {
            0x00000001: "Checkered",
            0x00000002: "White",
            0x00000004: "Green",
            0x00000008: "Yellow",
            0x00000010: "Red",
            0x00000020: "Blue",
            0x00000040: "Debris",
            0x00000080: "Crossed",
            0x00000100: "YellowWaving",
            0x00000200: "OneLapToGreen",
            0x00000400: "GreenHeld",
            0x00000800: "TenToGo",
            0x00001000: "FiveToGo",
            0x00002000: "RandomWaving",
            0x00004000: "Caution",
            0x00008000: "CautionWaving",
        }

        active_flags = []
        for flag_bit, flag_name in flag_meanings.items():
            if flags & flag_bit:
                active_flags.append(flag_name)

        if not active_flags:
            return "Green"
        return ", ".join(active_flags)

    def _check_flag_threshold(self, telemetry_data):
        """Check for flag change threshold events"""
        if not telemetry_data:
            return False, {}

        current_flags = telemetry_data.get("SessionFlags", 0)
        if not hasattr(self, "_last_flags"):
            self._last_flags = current_flags
            return False, {}

        # Check for flag changes
        if current_flags != self._last_flags:
            old_flags = self._last_flags
            self._last_flags = current_flags
            flag_status = self._interpret_session_flags(current_flags)

            # Ignore green flag events as they are normal race start conditions
            # Only alert for significant flag changes (yellow, red, checkered, etc.)
            if flag_status == "Green":
                return False, {}

            return True, {"flag_status": flag_status}

        return False, {}

    def _check_tire_temp_threshold(self, telemetry_data):
        """Check for tire temperature threshold events"""
        if not telemetry_data:
            return False, {}

        # Check tire temperatures (optimal range varies by compound)
        tire_temps = {
            "LF": telemetry_data.get("LFtempCL", 0),
            "RF": telemetry_data.get("RFtempCL", 0),
            "LR": telemetry_data.get("LRtempCL", 0),
            "RR": telemetry_data.get("RRtempCL", 0),
        }

        # Find overheating tires (above 105°C is concerning)
        overheating_tires = []
        for tire_pos, temp in tire_temps.items():
            if temp > 105:
                overheating_tires.append((tire_pos, temp))

        if overheating_tires:
            # Report the hottest tire
            hottest_tire, max_temp = max(overheating_tires, key=lambda x: x[1])
            # Convert to Fahrenheit for American racing context
            temp_f = (max_temp * 9 / 5) + 32
            return True, {
                "tire_position": hottest_tire,
                "temperature": temp_f,
                "tire_count": len(overheating_tires),
            }

        return False, {}

    def _check_tire_pressure_threshold(self, telemetry_data):
        """Check for tire pressure threshold events"""
        if not telemetry_data:
            return False, {}

        # Get current tire pressures
        current_pressures = {
            "LF": telemetry_data.get("LFpressure", 0),
            "RF": telemetry_data.get("RFpressure", 0),
            "LR": telemetry_data.get("LRpressure", 0),
            "RR": telemetry_data.get("RRpressure", 0),
        }

        # Initialize baseline pressures if not set
        if not hasattr(self, "_baseline_pressures"):
            # Only set baseline if we have valid pressure data
            if any(p > 0 for p in current_pressures.values()):
                self._baseline_pressures = current_pressures.copy()
            return False, {}

        # Check for significant pressure changes or abnormal values
        pressure_issues = []

        for tire_pos, current_pressure in current_pressures.items():
            if current_pressure <= 0:
                continue  # Skip invalid readings

            baseline_pressure = self._baseline_pressures.get(tire_pos, 0)
            if baseline_pressure <= 0:
                continue  # Skip if no baseline

            pressure_change = current_pressure - baseline_pressure
            pressure_change_pct = (pressure_change / baseline_pressure) * 100

            # Check for significant pressure loss (>15% drop)
            if pressure_change_pct < -15:
                pressure_issues.append(
                    (tire_pos, current_pressure, "significant pressure loss")
                )

            # Check for pressure gain (overheating or setup issue, >20% increase)
            elif pressure_change_pct > 20:
                pressure_issues.append((tire_pos, current_pressure, "pressure spike"))

            # Check for abnormally low pressure (under 20 PSI for most cars)
            elif current_pressure < 20:
                pressure_issues.append(
                    (tire_pos, current_pressure, "critically low pressure")
                )

            # Check for abnormally high pressure (over 45 PSI for most cars)
            elif current_pressure > 45:
                pressure_issues.append(
                    (tire_pos, current_pressure, "critically high pressure")
                )

        if pressure_issues:
            # Report the most critical issue (lowest or highest pressure)
            critical_issue = min(
                pressure_issues, key=lambda x: abs(x[1] - 30)
            )  # 30 PSI as target
            tire_pos, pressure, change_type = critical_issue

            return True, {
                "tire_position": tire_pos,
                "pressure": pressure,
                "change_type": change_type,
            }

        return False, {}

    def _check_tire_wear_threshold(self, telemetry_data):
        """Check for tire wear threshold events"""
        if not telemetry_data:
            return False, {}

        # Get tire wear levels (0.0 = new, 1.0 = completely worn)
        tire_wear = {
            "LF": telemetry_data.get("LFwearM", 0),
            "RF": telemetry_data.get("RFwearM", 0),
            "LR": telemetry_data.get("LRwearM", 0),
            "RR": telemetry_data.get("RRwearM", 0),
        }

        # Track wear progression to avoid repeat alerts
        if not hasattr(self, "_last_wear_alert_level"):
            self._last_wear_alert_level = {}

        critical_wear_tires = []

        for tire_pos, wear_level in tire_wear.items():
            if wear_level <= 0:
                continue  # Skip invalid readings

            wear_percent = wear_level * 100
            last_alert_level = self._last_wear_alert_level.get(tire_pos, 0)

            # Alert at 70%, 85%, and 95% wear levels
            if wear_percent >= 95 and last_alert_level < 95:
                critical_wear_tires.append((tire_pos, wear_percent, "CRITICAL"))
                self._last_wear_alert_level[tire_pos] = 95
            elif wear_percent >= 85 and last_alert_level < 85:
                critical_wear_tires.append((tire_pos, wear_percent, "HIGH"))
                self._last_wear_alert_level[tire_pos] = 85
            elif wear_percent >= 70 and last_alert_level < 70:
                critical_wear_tires.append((tire_pos, wear_percent, "MODERATE"))
                self._last_wear_alert_level[tire_pos] = 70

        if critical_wear_tires:
            # Report the most worn tire
            most_worn = max(critical_wear_tires, key=lambda x: x[1])
            tire_pos, wear_percent, severity = most_worn

            return True, {
                "tire_position": tire_pos,
                "wear_percent": wear_percent,
                "severity": severity,
                "tire_count": len(critical_wear_tires),
            }

        return False, {}

    def _check_pit_window_threshold(self, telemetry_data):
        """Check for pit window threshold events"""
        if not telemetry_data:
            return False, {}

        # Check if pit window is opening/closing
        pit_window_open = telemetry_data.get("PitWindowOpen", False)
        if not hasattr(self, "_last_pit_window"):
            self._last_pit_window = pit_window_open
            return False, {}

        if pit_window_open != self._last_pit_window:
            self._last_pit_window = pit_window_open
            return True, {"pit_window_open": pit_window_open}

        return False, {}

    def _check_performance_delta_threshold(self, telemetry_data):
        """Check for performance delta threshold events"""
        if not telemetry_data:
            return False, {}

        lap_delta = telemetry_data.get("LapDeltaToBestLap", 0)

        # Alert if significantly off pace (more than 2 seconds slower)
        if lap_delta > 2.0:
            return True, {"delta": lap_delta}

        return False, {}

    def _check_incidents_threshold(self, telemetry_data):
        """Check for incidents threshold events"""
        if not telemetry_data:
            return False, {}

        current_incidents = telemetry_data.get("PlayerCarMyIncidentCount", 0)
        if not hasattr(self, "_last_incidents"):
            self._last_incidents = current_incidents
            return False, {}

        if current_incidents > self._last_incidents:
            self._last_incidents = current_incidents
            return True, {"incidents": current_incidents}

        return False, {}

    def _check_position_change_threshold(self, telemetry_data):
        """Check for position change threshold events"""
        if not telemetry_data:
            return False, {}

        current_pos = telemetry_data.get("CarIdxPosition", [0])[0]  # Player position
        if not hasattr(self, "_last_position"):
            self._last_position = current_pos
            return False, {}

        if current_pos != self._last_position:
            old_pos = self._last_position
            self._last_position = current_pos
            return True, {"old_pos": old_pos, "new_pos": current_pos}

        return False, {}

    def _check_personal_best_threshold(self, telemetry_data):
        """Check for personal best threshold events"""
        if not telemetry_data:
            return False, {}

        current_best = telemetry_data.get("LapBestLapTime", 0)
        last_lap_time = telemetry_data.get("LapLastLapTime", 0)

        if not hasattr(self, "_last_best_lap"):
            self._last_best_lap = current_best
            return False, {}

        # Check if we have a new personal best (faster time)
        if current_best > 0 and (
            self._last_best_lap == 0 or current_best < self._last_best_lap
        ):
            old_best = self._last_best_lap
            self._last_best_lap = current_best

            # Calculate time improvement delta
            time_delta = old_best - current_best if old_best > 0 else 0

            # Determine if this new best was the lap just completed
            was_last_lap = abs(last_lap_time - current_best) < 0.01 if last_lap_time > 0 else False

            # Create appropriate improvement message
            if old_best == 0:
                # First personal best of the session
                improvement_message = f"Personal best set - {current_best:.3f}s"
            else:
                # Improved existing personal best
                improvement_message = f"Personal best achieved - {current_best:.3f}s (improved by {time_delta:.3f}s from {old_best:.3f}s)"

            # Create contextual lap information
            if was_last_lap and last_lap_time > 0:
                lap_context = f" - Last lap was {last_lap_time:.3f}s"
            elif last_lap_time > 0:
                lap_context = f" - Last lap: {last_lap_time:.3f}s, Best: {current_best:.3f}s"
            else:
                lap_context = ""

            return True, {
                "old_best": old_best,
                "new_best": current_best,
                "time_delta": time_delta,
                "last_lap_time": last_lap_time,
                "was_last_lap": was_last_lap,
                "improvement_message": improvement_message,
                "lap_context": lap_context
            }

        return False, {}

    def _check_track_conditions_threshold(self, telemetry_data):
        """Check for track conditions threshold events"""
        if not telemetry_data:
            return False, {}

        track_temp = telemetry_data.get("TrackTemp", 0)
        air_temp = telemetry_data.get("AirTemp", 0)

        # Store initial conditions
        if not hasattr(self, "_initial_track_temp"):
            self._initial_track_temp = track_temp
            self._initial_air_temp = air_temp
            return False, {}

        # Check for significant temperature changes (>10°C)
        track_delta = abs(track_temp - self._initial_track_temp)
        air_delta = abs(air_temp - self._initial_air_temp)

        if track_delta > 10 or air_delta > 10:
            return True, {
                "track_temp": track_temp,
                "air_temp": air_temp,
                "track_delta": track_delta,
                "air_delta": air_delta,
            }

        return False, {}

    def _refresh_telemetry_data(self):
        """Refresh telemetry data on-demand when watchdog is disabled"""
        if (
            not self.enable_watchdog
            and self.ir
            and self.ir.startup()
            and self.ir.is_initialized
            and self.ir.is_connected
        ):
            try:
                # Freeze buffer for consistent data access
                self.ir.freeze_var_buffer_latest()

                # Update telemetry data
                self.telemetry_data = {
                    "Speed": self._telemetry("Speed", 0),
                    "RPM": self._telemetry("RPM", 0),
                    "Gear": self._telemetry("Gear", 0),
                    "FuelLevel": self._telemetry("FuelLevel", 0),
                    "FuelUsePerHour": self._telemetry("FuelUsePerHour", 0),
                    "PlayerCarPosition": self._telemetry("PlayerCarPosition", 1),
                    "PlayerCarIdx": self._telemetry("PlayerCarIdx", 0),
                    "Lap": self._telemetry("Lap", 0),
                    "SessionTime": self._telemetry("SessionTime", 0),
                    "SessionTimeRemain": self._telemetry("SessionTimeRemain", 0),
                    "SessionFlags": self._telemetry("SessionFlags", 0),
                    "SessionState": self._telemetry("SessionState", 0),
                    "IsReplayPlaying": self._telemetry("IsReplayPlaying", False),
                    "LapLastLapTime": self._telemetry("LapLastLapTime", 0),
                    "LapBestLapTime": self._telemetry("LapBestLapTime", 0),
                    "LapCurrentLapTime": self._telemetry("LapCurrentLapTime", 0),
                    # Delta timing and sector analysis data
                    "LapDistPct": self._telemetry("LapDistPct", 0),
                    "LapDeltaToBestLap": self._telemetry("LapDeltaToBestLap", 0),
                    "LapDeltaToBestLap_OK": self._telemetry(
                        "LapDeltaToBestLap_OK", False
                    ),
                    "LapDeltaToOptimalLap": self._telemetry("LapDeltaToOptimalLap", 0),
                    "LapDeltaToOptimalLap_OK": self._telemetry(
                        "LapDeltaToOptimalLap_OK", False
                    ),
                    "LapDeltaToSessionBestLap": self._telemetry(
                        "LapDeltaToSessionBestLap", 0
                    ),
                    "LapDeltaToSessionBestLap_OK": self._telemetry(
                        "LapDeltaToSessionBestLap_OK", False
                    ),
                    "LapDeltaToSessionLastlLap": self._telemetry(
                        "LapDeltaToSessionLastlLap", 0
                    ),
                    "LapDeltaToSessionLastlLap_OK": self._telemetry(
                        "LapDeltaToSessionLastlLap_OK", False
                    ),
                    "LFtempCM": self._telemetry("LFtempCM", [0, 0, 0]),
                    "RFtempCM": self._telemetry("RFtempCM", [0, 0, 0]),
                    "LRtempCM": self._telemetry("LRtempCM", [0, 0, 0]),
                    "RRtempCM": self._telemetry("RRtempCM", [0, 0, 0]),
                    "LFwearM": self._telemetry("LFwearM", 0),
                    "RFwearM": self._telemetry("RFwearM", 0),
                    "LRwearM": self._telemetry("LRwearM", 0),
                    "RRwearM": self._telemetry("RRwearM", 0),
                    "TrackTemp": self._telemetry("TrackTemp", 0),
                    "AirTemp": self._telemetry("AirTemp", 0),
                    "RelativeHumidity": self._telemetry("RelativeHumidity", 0),
                    "WindVel": self._telemetry("WindVel", 0),
                    "PlayerCarMyIncidentCount": self._telemetry(
                        "PlayerCarMyIncidentCount", 0
                    ),
                    "EngineWarnings": self._telemetry("EngineWarnings", 0),
                    "dcBrakeBias": self._telemetry("dcBrakeBias", 0),
                    # Enhanced competitor and proximity data
                    "CarDistAhead": self._telemetry("CarDistAhead", 0),
                    "CarDistBehind": self._telemetry("CarDistBehind", 0),
                    # Additional setup and car state variables
                    "LFpressure": self._telemetry("LFpressure", 0),
                    "RFpressure": self._telemetry("RFpressure", 0),
                    "LRpressure": self._telemetry("LRpressure", 0),
                    "RRpressure": self._telemetry("RRpressure", 0),
                }

                self.is_connected = True
                self.last_update = time.time()
            except Exception:
                self.is_connected = False

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        if not irsdk:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.name,
                    message="iRacing skill requires the 'irsdk' library.",
                )
            )

        # Read configuration values (following ATS telemetry pattern)
        self.enable_watchdog = self.retrieve_custom_property_value(
            "enable_watchdog", errors
        )
        self.watchdog_interval = float(
            self.retrieve_custom_property_value("watchdog_interval", errors)
        )

        # Read watchdog event configuration
        self.damage_alerts_enabled = self.retrieve_custom_property_value(
            "damage_alerts_enabled", errors
        )
        self.damage_alerts_interval = float(
            self.retrieve_custom_property_value("damage_alerts_interval", errors)
        )
        self.fuel_alerts_enabled = self.retrieve_custom_property_value(
            "fuel_alerts_enabled", errors
        )
        self.fuel_alerts_interval = float(
            self.retrieve_custom_property_value("fuel_alerts_interval", errors)
        )
        self.flag_alerts_enabled = self.retrieve_custom_property_value(
            "flag_alerts_enabled", errors
        )
        self.flag_alerts_interval = float(
            self.retrieve_custom_property_value("flag_alerts_interval", errors)
        )
        self.tire_alerts_enabled = self.retrieve_custom_property_value(
            "tire_alerts_enabled", errors
        )
        self.tire_alerts_interval = float(
            self.retrieve_custom_property_value("tire_alerts_interval", errors)
        )
        self.position_alerts_enabled = self.retrieve_custom_property_value(
            "position_alerts_enabled", errors
        )
        self.position_alerts_interval = float(
            self.retrieve_custom_property_value("position_alerts_interval", errors)
        )
        self.performance_alerts_enabled = self.retrieve_custom_property_value(
            "performance_alerts_enabled", errors
        )
        self.performance_alerts_interval = float(
            self.retrieve_custom_property_value("performance_alerts_interval", errors)
        )
        self.incident_alerts_enabled = self.retrieve_custom_property_value(
            "incident_alerts_enabled", errors
        )
        self.personal_best_alerts_enabled = self.retrieve_custom_property_value(
            "personal_best_alerts_enabled", errors
        )
        self.pit_window_alerts_enabled = self.retrieve_custom_property_value(
            "pit_window_alerts_enabled", errors
        )
        self.track_condition_alerts_enabled = self.retrieve_custom_property_value(
            "track_condition_alerts_enabled", errors
        )
        self.alert_cooldown_period = float(
            self.retrieve_custom_property_value("alert_cooldown_period", errors)
        )
        self.telemetry_awareness = self.retrieve_custom_property_value(
            "telemetry_awareness", errors
        )
        # Handle optional watchdog_prompt - don't add error if missing or empty
        watchdog_prompt_property = next(
            (prop for prop in self.config.custom_properties if prop.id == "watchdog_prompt"),
            None,
        )
        self.watchdog_prompt = watchdog_prompt_property.value if watchdog_prompt_property and watchdog_prompt_property.value else None

        # Initialize watchdog events now that configuration is loaded
        self._init_watchdog_events()

        # Start watchdog if enabled and not already started
        if self.enable_watchdog and not self.watchdog_started:
            self._start_watchdog()
            self.watchdog_started = True

        return errors

    def _start_watchdog(self):
        """Start the watchdog thread to monitor iRacing telemetry"""
        if not self.watchdog_running:
            self.watchdog_running = True
            self.watchdog_thread = threading.Thread(
                target=self._watchdog_loop, daemon=True
            )
            self.watchdog_thread.start()

    def _watchdog_loop(self):
        """Main watchdog loop that monitors iRacing connection and updates telemetry"""
        while self.watchdog_running:
            try:
                if (
                    self.ir
                    and self.ir.startup()
                    and self.ir.is_initialized
                    and self.ir.is_connected
                ):
                    if not self.is_connected:
                        self.is_connected = True
                        if self.settings.debug_mode:
                            asyncio.run(
                                self.printr.print_async(
                                    text="iRacing: Connected to simulator",
                                    color=LogType.INFO,
                                )
                            )

                    # Freeze buffer for consistent data access
                    self.ir.freeze_var_buffer_latest()

                    # Update telemetry data in-place to avoid memory allocation
                    self._update_telemetry_data()

                    self.last_update = time.time()

                    # Process watchdog events for proactive alerts
                    if self.enable_watchdog:
                        asyncio.run(self._process_watchdog_events())

                    time.sleep(self.watchdog_interval)  # Use configurable interval
                else:
                    if self.is_connected:
                        self.is_connected = False
                        if self.settings.debug_mode:
                            asyncio.run(
                                self.printr.print_async(
                                    text="iRacing: Disconnected from simulator",
                                    color=LogType.WARNING,
                                )
                            )
                    time.sleep(
                        self.watchdog_interval
                    )  # Use configurable interval when disconnected too

            except Exception as e:
                # Only log watchdog errors in debug mode to avoid disturbing streamers
                if self.settings.debug_mode:
                    asyncio.run(
                        self.printr.print_async(
                            text=f"iRacing watchdog error: {str(e)}",
                            color=LogType.ERROR,
                        )
                    )
                time.sleep(1)

    def _is_in_active_session(self) -> bool:
        """Check if the user is in an active racing session where watchdog alerts should be triggered"""
        try:
            # Check if we have valid telemetry data
            if not self.telemetry_data:
                return False

            # Check session state - only trigger during active racing sessions
            session_state = self._telemetry("SessionState", 0)
            # SessionState values: 0=invalid, 1=get_in_car, 2=warmup, 3=parade_laps, 4=racing, 5=checkered, 6=cool_down
            # We want alerts during: warmup(2), parade_laps(3), racing(4), checkered(5)
            if session_state < 2 or session_state > 5:
                return False

            # Check if we're in a replay - don't trigger alerts during replay playback
            is_replay_playing = self._telemetry("IsReplayPlaying", False)
            if is_replay_playing:
                return False

            # Check if we're actually on track (speed > 0 or in gear)
            speed = self.telemetry_data.get("Speed", 0)
            gear = self.telemetry_data.get("Gear", 0)
            # Allow alerts even at zero speed (pit stops, grid starts, etc.)
            # but require a valid gear state or recent activity
            if speed == 0 and gear == 0:
                # Check if we have recent lap activity
                current_lap = self.telemetry_data.get("Lap", 0)
                if current_lap == 0:
                    return False

            return True

        except Exception:
            # If we can't determine session state, err on the side of caution
            return False

    async def _process_watchdog_events(self):
        """Process watchdog events and trigger proactive alerts"""
        if not self.telemetry_data:
            return

        # Check if we're in an active racing session before processing events
        if not self._is_in_active_session():
            return

        current_time = time.time()

        for event in self.watchdog_events:
            if not event.enabled:
                continue

            # Check if enough time has passed since last check
            if current_time - event.last_checked < event.check_interval:
                continue

            # Check if cooldown period has passed since last trigger
            if current_time - event.last_triggered < event.cooldown_period:
                continue

            # Update last check time
            event.last_checked = current_time

            try:
                # Call the threshold function
                triggered, context = event.threshold_func(self.telemetry_data)

                if triggered:
                    # Update last trigger time
                    event.last_triggered = current_time

                    # Generate event prompt for LLM processing
                    prompt = event.prompt_template.format(**context)

                    # Generate race engineer response using LLM
                    try:
                        # Create messages for LLM call with minimal context for efficiency
                        # Use custom watchdog prompt or fallback to default
                        system_prompt = (
                            self.watchdog_prompt
                            or """You are a professional race engineer providing urgent telemetry alerts during an iRacing session.

GUIDELINES:
- Messages starting with "[WATCHDOG_EVENT]" are automatic telemetry notifications
- Generate brief, urgent responses (under 15 words) as a race engineer would
- Use racing terminology and provide actionable advice when possible
- Always round numerical values - avoid excessive decimal places
- Use natural language for very small values (e.g., "less than a lap remaining" instead of "0.234 laps remaining")
- Be confident, direct, and results-oriented
- For personal best achievements, acknowledge the improvement delta and celebrate meaningful progress
- Examples: "Box this lap for fuel!" or "Yellow flag out, prepare to bunch up!" or "Half a lap of fuel left!" or "Great lap! Three tenths faster!"

Stay focused on the immediate racing situation and provide clear, actionable guidance."""
                        )

                        messages = [
                            {
                                "role": "system",
                                "content": system_prompt,
                            },
                            {"role": "user", "content": prompt},
                        ]

                        # Call LLM to generate appropriate race engineer response
                        response = await self.wingman.actual_llm_call(
                            messages=messages,
                            tools=[],  # No tools needed for event responses
                        )

                        if response and response.choices and len(response.choices) > 0:
                            response_text = response.choices[0].message.content
                            if response_text:
                                # Play the response to user
                                self.threaded_execution(
                                    self.wingman.play_to_user, response_text, True
                                )

                                # Add to conversation history only if telemetry awareness is enabled
                                if self.telemetry_awareness:
                                    await self.wingman.add_assistant_message(
                                        f"Telemetry alert: {response_text}"
                                    )

                        else:
                            # No response generated, use fallback
                            raise Exception("No response content generated")

                    except Exception as llm_error:
                        # Fallback to direct message if LLM fails
                        if self.settings.debug_mode:
                            await self.printr.print_async(
                                text=f"LLM error for event {event.name}, using fallback: {str(llm_error)}",
                                color=LogType.WARNING,
                            )
                        # Use a simplified version of the prompt as fallback
                        fallback_text = prompt.replace("[WATCHDOG_EVENT] ", "")
                        self.threaded_execution(
                            self.wingman.play_to_user, fallback_text, True
                        )

                        # Add to conversation history only if telemetry awareness is enabled
                        if self.telemetry_awareness:
                            await self.wingman.add_assistant_message(
                                f"Telemetry alert: {fallback_text}"
                            )

                    if self.settings.debug_mode:
                        await self.printr.print_async(
                            text=f"iRacing watchdog triggered: {event.name}",
                            color=LogType.INFO,
                        )

            except Exception as e:
                # Only log watchdog errors in debug mode to avoid disturbing streamers
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        text=f"iRacing watchdog event error ({event.name}): {str(e)}",
                        color=LogType.ERROR,
                    )

    def get_tools(self) -> list[Tuple[str, Dict[str, Any]]]:
        return [
            (
                "get_current_vehicle_status_and_telemetry",
                {
                    "type": "function",
                    "function": {
                        "name": "get_current_vehicle_status_and_telemetry",
                        "description": "Get current vehicle status including speed, RPM, gear, fuel level, and consumption rate",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                },
            ),
            (
                "get_session_info_and_race_position",
                {
                    "type": "function",
                    "function": {
                        "name": "get_session_info_and_race_position",
                        "description": "Get current race session information including position, lap number, session time, and flag status",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                },
            ),
            (
                "get_lap_times_and_performance_analysis",
                {
                    "type": "function",
                    "function": {
                        "name": "get_lap_times_and_performance_analysis",
                        "description": "Get lap time analysis including last lap, best lap, current lap, and real-time delta timing to various references",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                },
            ),
            (
                "get_sector_times_and_track_position_analysis",
                {
                    "type": "function",
                    "function": {
                        "name": "get_sector_times_and_track_position_analysis",
                        "description": "Get detailed sector analysis including current track position, delta timing to best/optimal laps, and performance in different track sections",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                },
            ),
            (
                "get_tire_condition_and_temperature_data",
                {
                    "type": "function",
                    "function": {
                        "name": "get_tire_condition_and_temperature_data",
                        "description": "Get detailed tire information including temperatures, pressures, wear levels, and grip status",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                },
            ),
            (
                "get_track_conditions_and_weather_info",
                {
                    "type": "function",
                    "function": {
                        "name": "get_track_conditions_and_weather_info",
                        "description": "Get current track and weather conditions including temperature, grip levels, and weather forecast",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                },
            ),
            (
                "get_competitor_gaps_and_relative_positions",
                {
                    "type": "function",
                    "function": {
                        "name": "get_competitor_gaps_and_relative_positions",
                        "description": "Get information about nearby competitors including gaps, relative speeds, and positions",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                },
            ),
            (
                "calculate_pit_strategy_and_fuel_requirements",
                {
                    "type": "function",
                    "function": {
                        "name": "calculate_pit_strategy_and_fuel_requirements",
                        "description": "Calculate optimal pit strategy including fuel requirements, tire strategy, and pit window timing",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                },
            ),
            (
                "get_incident_count_and_penalty_status",
                {
                    "type": "function",
                    "function": {
                        "name": "get_incident_count_and_penalty_status",
                        "description": "Get current incident points, penalties, and safety rating information",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                },
            ),
            (
                "get_vehicle_damage_assessment",
                {
                    "type": "function",
                    "function": {
                        "name": "get_vehicle_damage_assessment",
                        "description": "Get detailed vehicle damage report and performance impact assessment",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                },
            ),
            (
                "get_current_car_setup_information",
                {
                    "type": "function",
                    "function": {
                        "name": "get_current_car_setup_information",
                        "description": "Get current car setup parameters including brake bias, differential settings, and suspension",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                },
            ),
        ]

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any], benchmark: Benchmark
    ) -> tuple[str, str]:
        instant_response = ""
        function_response = "iRacing not connected or tool unavailable."

        if not self.is_connected:
            return (
                "iRacing simulator is not running or not connected.",
                instant_response,
            )

        tool_methods = [
            "get_current_vehicle_status_and_telemetry",
            "get_session_info_and_race_position",
            "get_lap_times_and_performance_analysis",
            "get_sector_times_and_track_position_analysis",
            "get_tire_condition_and_temperature_data",
            "get_track_conditions_and_weather_info",
            "get_competitor_gaps_and_relative_positions",
            "calculate_pit_strategy_and_fuel_requirements",
            "get_incident_count_and_penalty_status",
            "get_vehicle_damage_assessment",
            "get_current_car_setup_information",
        ]

        if tool_name in tool_methods:
            benchmark.start_snapshot(f"iRacing: {tool_name}")

            if self.settings.debug_mode:
                message = f"iRacing: executing tool '{tool_name}'"
                if parameters:
                    message += f" with params: {parameters}"
                await self.printr.print_async(text=message, color=LogType.INFO)

            try:
                function = getattr(self, tool_name)
                function_response = function()
            except Exception as e:
                function_response = f"Error executing iRacing tool: {str(e)}"
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        text=f"iRacing tool error: {str(e)}", color=LogType.ERROR
                    )

            benchmark.finish_snapshot()

        return function_response, instant_response

    def get_current_vehicle_status_and_telemetry(self) -> str:
        """Get current vehicle status and telemetry data"""
        # Refresh data if watchdog is disabled
        if not self.enable_watchdog:
            self._refresh_telemetry_data()

        if not self.telemetry_data:
            return "No telemetry data available."

        try:
            speed = self.telemetry_data.get("Speed", 0) * 2.237  # m/s to mph
            rpm = self.telemetry_data.get("RPM", 0)
            gear = self.telemetry_data.get("Gear", 0)
            fuel_level = self.telemetry_data.get("FuelLevel", 0)
            fuel_use_per_hour = self.telemetry_data.get("FuelUsePerHour", 0)

            # Calculate estimated laps remaining based on fuel consumption
            if fuel_use_per_hour > 0:
                hours_remaining = fuel_level / fuel_use_per_hour
                # Rough estimate - would need lap time for accuracy
                laps_remaining = int(hours_remaining * 30)  # Assuming ~2min laps
            else:
                laps_remaining = "Unknown"

            gear_text = (
                "Neutral" if gear == 0 else ("Reverse" if gear == -1 else f"{gear}")
            )

            return (
                f"Currently doing {speed:.0f} mph in {gear_text} gear, "
                f"engine at {rpm:.0f} RPM. Fuel level: {fuel_level:.1f} gallons, "
                f"estimated {laps_remaining} laps remaining."
            )
        except Exception as e:
            return f"Error reading vehicle status: {str(e)}"

    def get_session_info_and_race_position(self) -> str:
        """Get current session information and race position"""
        # Refresh data if watchdog is disabled
        if not self.enable_watchdog:
            self._refresh_telemetry_data()

        if not self.telemetry_data:
            return "No session data available."

        try:
            # Get player's position directly
            position = self.telemetry_data.get("PlayerCarPosition", 1)
            lap_current = self.telemetry_data.get("Lap", 0)
            session_time = self.telemetry_data.get("SessionTime", 0)
            session_time_remain = self.telemetry_data.get("SessionTimeRemain", 0)

            # Convert time to readable format
            time_remaining = (
                f"{session_time_remain // 60:.0f}:{session_time_remain % 60:02.0f}"
            )

            # Get flag status
            session_flags = self.telemetry_data.get("SessionFlags", 0)
            flag_status = "Green flag"
            if session_flags & 0x00000001:  # Checkered
                flag_status = "Checkered flag"
            elif session_flags & 0x00000002:  # White
                flag_status = "White flag"
            elif session_flags & 0x00000004:  # Green
                flag_status = "Green flag"
            elif session_flags & 0x00000008:  # Yellow
                flag_status = "Yellow flag"

            return (
                f"Currently P{position} on lap {lap_current}. "
                f"Session time remaining: {time_remaining}. "
                f"Flag status: {flag_status}."
            )
        except Exception as e:
            return f"Error reading session info: {str(e)}"

    def get_lap_times_and_performance_analysis(self) -> str:
        """Get lap time analysis and performance data with delta timing"""
        # Refresh data if watchdog is disabled
        if not self.enable_watchdog:
            self._refresh_telemetry_data()

        if not self.telemetry_data:
            return "No lap time data available."

        try:
            last_lap_time = self.telemetry_data.get("LapLastLapTime", 0)
            best_lap_time = self.telemetry_data.get("LapBestLapTime", 0)
            current_lap_time = self.telemetry_data.get("LapCurrentLapTime", 0)

            # Get delta timing data
            delta_to_best = self.telemetry_data.get("LapDeltaToBestLap", 0)
            delta_to_best_ok = self.telemetry_data.get("LapDeltaToBestLap_OK", False)
            delta_to_optimal = self.telemetry_data.get("LapDeltaToOptimalLap", 0)
            delta_to_optimal_ok = self.telemetry_data.get(
                "LapDeltaToOptimalLap_OK", False
            )
            delta_to_session_best = self.telemetry_data.get(
                "LapDeltaToSessionBestLap", 0
            )
            delta_to_session_best_ok = self.telemetry_data.get(
                "LapDeltaToSessionBestLap_OK", False
            )

            # Convert times to readable format
            def format_time(seconds):
                if seconds <= 0:
                    return "N/A"
                minutes = int(seconds // 60)
                seconds = seconds % 60
                return f"{minutes}:{seconds:06.3f}"

            def format_delta(delta_seconds, is_valid=True):
                if not is_valid or delta_seconds == 0:
                    return "N/A"
                return f"{delta_seconds:+.3f}s"

            last_lap = format_time(last_lap_time)
            best_lap = format_time(best_lap_time)
            current_lap = format_time(current_lap_time)

            # Calculate delta to personal best for last lap
            personal_delta = ""
            if last_lap_time > 0 and best_lap_time > 0:
                diff = last_lap_time - best_lap_time
                personal_delta = f", {diff:+.3f}s from personal best"

            # Build response with current delta timing
            response_parts = [
                f"Last lap: {last_lap}{personal_delta}",
                f"Personal best: {best_lap}",
                f"Current lap: {current_lap}",
            ]

            # Add real-time delta information
            if delta_to_best_ok:
                response_parts.append(
                    f"Delta to PB: {format_delta(delta_to_best, delta_to_best_ok)}"
                )

            if delta_to_session_best_ok:
                response_parts.append(
                    f"Delta to session best: {format_delta(delta_to_session_best, delta_to_session_best_ok)}"
                )

            if delta_to_optimal_ok:
                response_parts.append(
                    f"Delta to optimal: {format_delta(delta_to_optimal, delta_to_optimal_ok)}"
                )

            return ". ".join(response_parts) + "."

        except Exception as e:
            return f"Error reading lap times: {str(e)}"

    def get_sector_times_and_track_position_analysis(self) -> str:
        """Get detailed sector analysis and track position data"""
        # Refresh data if watchdog is disabled
        if not self.enable_watchdog:
            self._refresh_telemetry_data()

        if not self.telemetry_data:
            return "No sector data available."

        try:
            # Get track position data
            lap_dist_pct = self.telemetry_data.get("LapDistPct", 0)

            # Get delta timing data
            delta_to_best = self.telemetry_data.get("LapDeltaToBestLap", 0)
            delta_to_best_ok = self.telemetry_data.get("LapDeltaToBestLap_OK", False)
            delta_to_optimal = self.telemetry_data.get("LapDeltaToOptimalLap", 0)
            delta_to_optimal_ok = self.telemetry_data.get(
                "LapDeltaToOptimalLap_OK", False
            )
            delta_to_session_best = self.telemetry_data.get(
                "LapDeltaToSessionBestLap", 0
            )
            delta_to_session_best_ok = self.telemetry_data.get(
                "LapDeltaToSessionBestLap_OK", False
            )
            delta_to_last_lap = self.telemetry_data.get("LapDeltaToSessionLastlLap", 0)
            delta_to_last_lap_ok = self.telemetry_data.get(
                "LapDeltaToSessionLastlLap_OK", False
            )

            # Determine current sector based on track position
            def get_sector_info(pct):
                if pct < 33.33:
                    return "Sector 1", 1
                elif pct < 66.67:
                    return "Sector 2", 2
                else:
                    return "Sector 3", 3

            def format_delta(delta_seconds, is_valid=True):
                if not is_valid or delta_seconds == 0:
                    return "N/A"
                return f"{delta_seconds:+.3f}s"

            # Get current sector
            sector_name, sector_num = get_sector_info(lap_dist_pct)

            # Build response
            response_parts = [
                f"Currently in {sector_name} ({lap_dist_pct:.1f}% around track)"
            ]

            # Add delta timing information
            if delta_to_best_ok:
                delta_str = format_delta(delta_to_best, delta_to_best_ok)
                response_parts.append(f"Delta to personal best: {delta_str}")

            if delta_to_session_best_ok:
                delta_str = format_delta(
                    delta_to_session_best, delta_to_session_best_ok
                )
                response_parts.append(f"Delta to session best: {delta_str}")

            if delta_to_optimal_ok:
                delta_str = format_delta(delta_to_optimal, delta_to_optimal_ok)
                response_parts.append(f"Delta to optimal: {delta_str}")

            # Performance analysis based on delta trends
            if delta_to_best_ok and delta_to_best != 0:
                if delta_to_best > 0.5:
                    response_parts.append("Currently losing significant time")
                elif delta_to_best > 0.1:
                    response_parts.append("Currently losing time")
                elif delta_to_best < -0.1:
                    response_parts.append("Currently gaining time")
                else:
                    response_parts.append("Currently matching personal best pace")

            # Sector-specific advice
            if sector_num == 1:
                response_parts.append("Focus on exit speed for the upcoming turns")
            elif sector_num == 2:
                response_parts.append("Mid-sector performance critical for lap time")
            else:
                response_parts.append(
                    "Final sector - maintain consistency to finish line"
                )

            return ". ".join(response_parts) + "."

        except Exception as e:
            return f"Error reading sector data: {str(e)}"

    def get_tire_condition_and_temperature_data(self) -> str:
        """Get tire temperature, pressure, and condition data"""
        # Refresh data if watchdog is disabled
        if not self.enable_watchdog:
            self._refresh_telemetry_data()

        if not self.telemetry_data:
            return "No tire data available."

        try:
            # Get tire temperatures (left, right, middle for each tire) in Celsius
            lf_temp = self.telemetry_data.get("LFtempCM", [0, 0, 0])
            rf_temp = self.telemetry_data.get("RFtempCM", [0, 0, 0])
            lr_temp = self.telemetry_data.get("LRtempCM", [0, 0, 0])
            rr_temp = self.telemetry_data.get("RRtempCM", [0, 0, 0])

            # Get core/center line temperatures
            lf_core = self.telemetry_data.get("LFtempCL", 0)
            rf_core = self.telemetry_data.get("RFtempCL", 0)
            lr_core = self.telemetry_data.get("LRtempCL", 0)
            rr_core = self.telemetry_data.get("RRtempCL", 0)

            # Get tire pressures in PSI
            lf_pressure = self.telemetry_data.get("LFpressure", 0)
            rf_pressure = self.telemetry_data.get("RFpressure", 0)
            lr_pressure = self.telemetry_data.get("LRpressure", 0)
            rr_pressure = self.telemetry_data.get("RRpressure", 0)

            # Get tire wear (0.0 = new, 1.0 = worn out)
            lf_wear = self.telemetry_data.get("LFwearM", 0)
            rf_wear = self.telemetry_data.get("RFwearM", 0)
            lr_wear = self.telemetry_data.get("LRwearM", 0)
            rr_wear = self.telemetry_data.get("RRwearM", 0)

            # Calculate average temperatures and convert to Fahrenheit
            lf_avg = sum(lf_temp) / 3 if lf_temp and any(lf_temp) else lf_core
            rf_avg = sum(rf_temp) / 3 if rf_temp and any(rf_temp) else rf_core
            lr_avg = sum(lr_temp) / 3 if lr_temp and any(lr_temp) else lr_core
            rr_avg = sum(rr_temp) / 3 if rr_temp and any(rr_temp) else rr_core

            lf_f = (lf_avg * 9 / 5) + 32 if lf_avg > 0 else 0
            rf_f = (rf_avg * 9 / 5) + 32 if rf_avg > 0 else 0
            lr_f = (lr_avg * 9 / 5) + 32 if lr_avg > 0 else 0
            rr_f = (rr_avg * 9 / 5) + 32 if rr_avg > 0 else 0

            # Analyze tire wear condition
            max_wear = max(lf_wear, rf_wear, lr_wear, rr_wear)
            if max_wear < 0.3:
                wear_status = "excellent"
            elif max_wear < 0.6:
                wear_status = "good"
            elif max_wear < 0.8:
                wear_status = "worn"
            else:
                wear_status = "critical"

            # Build response with temperature, pressure, and wear data
            response_parts = []

            # Temperatures
            if any(temp > 0 for temp in [lf_f, rf_f, lr_f, rr_f]):
                response_parts.append(
                    f"Temps: LF {lf_f:.0f}°F, RF {rf_f:.0f}°F, LR {lr_f:.0f}°F, RR {rr_f:.0f}°F"
                )

            # Pressures
            if any(
                pressure > 0
                for pressure in [lf_pressure, rf_pressure, lr_pressure, rr_pressure]
            ):
                response_parts.append(
                    f"Pressures: LF {lf_pressure:.1f}, RF {rf_pressure:.1f}, LR {lr_pressure:.1f}, RR {rr_pressure:.1f} PSI"
                )

            # Wear status with more detailed analysis
            if max_wear > 0.85:
                response_parts.append(
                    f"Tire wear: {wear_status} - Consider pit stop soon!"
                )
            elif max_wear > 0.70:
                response_parts.append(f"Tire wear: {wear_status} - Monitor closely")
            else:
                response_parts.append(f"Tire wear: {wear_status}")

            # Pressure analysis
            avg_pressure = sum(
                p for p in [lf_pressure, rf_pressure, lr_pressure, rr_pressure] if p > 0
            )
            pressure_count = sum(
                1 for p in [lf_pressure, rf_pressure, lr_pressure, rr_pressure] if p > 0
            )

            if pressure_count > 0:
                avg_pressure = avg_pressure / pressure_count

                # Check for pressure imbalances
                pressure_issues = []
                for pos, pressure in [
                    ("LF", lf_pressure),
                    ("RF", rf_pressure),
                    ("LR", lr_pressure),
                    ("RR", rr_pressure),
                ]:
                    if pressure > 0:
                        diff_from_avg = abs(pressure - avg_pressure)
                        if diff_from_avg > 5:  # More than 5 PSI difference
                            pressure_issues.append(f"{pos} {pressure:.1f}")

                if pressure_issues:
                    response_parts.append(
                        f"Pressure imbalance: {', '.join(pressure_issues)} PSI"
                    )

            # Temperature analysis and warnings
            hot_tires = []
            cold_tires = []
            for pos, temp in [("LF", lf_f), ("RF", rf_f), ("LR", lr_f), ("RR", rr_f)]:
                if temp > 220:  # Overheating
                    hot_tires.append(pos)
                elif temp > 0 and temp < 160:  # Under-temperature (not generating grip)
                    cold_tires.append(pos)

            if hot_tires:
                response_parts.append(f"WARNING: {', '.join(hot_tires)} overheating!")
            if cold_tires:
                response_parts.append(
                    f"Cold tires: {', '.join(cold_tires)} - Need more heat"
                )

            # Overall tire strategy advice
            if max_wear > 0.85 or hot_tires:
                response_parts.append("Recommend pit stop consideration")
            elif max_wear > 0.70:
                response_parts.append("Monitor tire degradation closely")

            return (
                ". ".join(response_parts) + "."
                if response_parts
                else "Tire data not available during current session."
            )

        except Exception as e:
            return f"Error reading tire data: {str(e)}"

    def get_track_conditions_and_weather_info(self) -> str:
        """Get track conditions and weather information"""
        # Refresh data if watchdog is disabled
        if not self.enable_watchdog:
            self._refresh_telemetry_data()

        if not self.telemetry_data:
            return "No track condition data available."

        try:
            track_temp = self.telemetry_data.get("TrackTemp", 0)
            air_temp = self.telemetry_data.get("AirTemp", 0)
            humidity = self.telemetry_data.get("RelativeHumidity", 0)
            wind_speed = self.telemetry_data.get("WindVel", 0)

            # Convert to Fahrenheit
            track_temp_f = (track_temp * 9 / 5) + 32
            air_temp_f = (air_temp * 9 / 5) + 32

            return (
                f"Track temp: {track_temp_f:.0f}°F, "
                f"Air temp: {air_temp_f:.0f}°F, "
                f"Humidity: {humidity:.0f}%, "
                f"Wind: {wind_speed:.1f} mph."
            )
        except Exception as e:
            return f"Error reading track conditions: {str(e)}"

    def get_competitor_gaps_and_relative_positions(self) -> str:
        """Get information about nearby competitors"""
        # Refresh data if watchdog is disabled
        if not self.enable_watchdog:
            self._refresh_telemetry_data()

        if not self.telemetry_data:
            return "No competitor data available."

        try:
            # Get player's position and car index
            position = self.telemetry_data.get("PlayerCarPosition", 1)
            player_car_idx = self.telemetry_data.get("PlayerCarIdx", 0)

            # Get gaps to cars ahead and behind
            car_ahead_dist = self._telemetry("CarDistAhead", 0)
            car_behind_dist = self._telemetry("CarDistBehind", 0)

            response_parts = [f"Currently P{position}"]

            if car_ahead_dist > 0:
                if car_ahead_dist < 1000:  # Within 1km
                    response_parts.append(f"Car ahead: {car_ahead_dist:.1f}m")
                else:
                    response_parts.append("Car ahead: >1km")

            if car_behind_dist > 0:
                if car_behind_dist < 1000:  # Within 1km
                    response_parts.append(f"Car behind: {car_behind_dist:.1f}m")
                else:
                    response_parts.append("Car behind: >1km")

            # Get relative positions from CarIdx arrays if available
            try:
                # These would need to be cached in watchdog for better performance
                positions_data = []
                for i in range(max(1, player_car_idx - 2), min(64, player_car_idx + 3)):
                    car_position = self._telemetry(f"CarIdxPosition", None)
                    if car_position and car_position != position:
                        lap_pct = self._telemetry(f"CarIdxLapDistPct", None)
                        if lap_pct is not None:
                            positions_data.append((car_position, lap_pct))

                if positions_data:
                    response_parts.append("Nearby cars analyzed")

            except Exception:
                pass  # Fall back to basic gap data

            return ". ".join(response_parts) + "."

        except Exception as e:
            return f"Error reading competitor data: {str(e)}"

    def calculate_pit_strategy_and_fuel_requirements(self) -> str:
        """Calculate pit strategy and fuel requirements"""
        # Refresh data if watchdog is disabled
        if not self.enable_watchdog:
            self._refresh_telemetry_data()

        if not self.telemetry_data:
            return "No data available for pit strategy calculation."

        try:
            fuel_level = self.telemetry_data.get("FuelLevel", 0)
            fuel_use_per_hour = self.telemetry_data.get("FuelUsePerHour", 0)
            session_time_remain = self.telemetry_data.get("SessionTimeRemain", 0)

            if fuel_use_per_hour > 0:
                hours_remaining = fuel_level / fuel_use_per_hour
                fuel_needed = (session_time_remain / 3600) * fuel_use_per_hour

                if fuel_level > fuel_needed:
                    return f"Fuel looks good! Current: {fuel_level:.1f} gallons, need {fuel_needed:.1f} for the session."
                else:
                    shortage = fuel_needed - fuel_level
                    return f"Pit stop recommended! Need {shortage:.1f} more gallons to finish the session."
            else:
                return (
                    "Unable to calculate fuel strategy - no consumption data available."
                )
        except Exception as e:
            return f"Error calculating pit strategy: {str(e)}"

    def get_incident_count_and_penalty_status(self) -> str:
        """Get incident and penalty information"""
        # Refresh data if watchdog is disabled
        if not self.enable_watchdog:
            self._refresh_telemetry_data()

        if not self.telemetry_data:
            return "No incident data available."

        try:
            # These values might need adjustment based on actual iRacing API
            incidents = self.telemetry_data.get("PlayerCarMyIncidentCount", 0)

            if incidents == 0:
                return "Clean driving! No incidents recorded."
            else:
                return f"Current incident count: {incidents}x. Drive carefully!"
        except Exception as e:
            return f"Error reading incident data: {str(e)}"

    def get_vehicle_damage_assessment(self) -> str:
        """Get vehicle damage assessment"""
        # Refresh data if watchdog is disabled
        if not self.enable_watchdog:
            self._refresh_telemetry_data()

        if not self.telemetry_data:
            return "No damage data available."

        try:
            # Engine and system warnings
            engine_warnings = self.telemetry_data.get("EngineWarnings", 0)

            # Get additional damage indicators from available SDK variables
            fuel_level = self.telemetry_data.get("FuelLevel", 0)
            rpm = self.telemetry_data.get("RPM", 0)
            speed = self.telemetry_data.get("Speed", 0)

            # Analyze potential damage indicators
            damage_indicators = []

            if engine_warnings > 0:
                damage_indicators.append(f"Engine warnings: {engine_warnings}")

            # Check for performance anomalies that might indicate damage
            gear = self.telemetry_data.get("Gear", 0)
            if (
                gear > 0 and rpm > 1000 and speed < 5
            ):  # High RPM, low speed might indicate damage
                damage_indicators.append("Possible drivetrain issues detected")

            # Check tire wear as damage indicator
            tire_wear_values = [
                self.telemetry_data.get("LFwearM", 0),
                self.telemetry_data.get("RFwearM", 0),
                self.telemetry_data.get("LRwearM", 0),
                self.telemetry_data.get("RRwearM", 0),
            ]
            max_wear = max(tire_wear_values) if tire_wear_values else 0
            if max_wear > 0.8:
                damage_indicators.append("Excessive tire wear detected")

            # Additional checks that could be added with more specific damage variables:
            # - Body damage from CarIdxDamage arrays
            # - Suspension damage indicators
            # - Aerodynamic damage effects

            if not damage_indicators:
                return "No damage detected. Car systems nominal."
            else:
                return f"Damage assessment: {'; '.join(damage_indicators)}. Recommend careful driving or pit stop."

        except Exception as e:
            return f"Error reading damage data: {str(e)}"

    def get_current_car_setup_information(self) -> str:
        """Get current car setup information"""
        # Refresh data if watchdog is disabled
        if not self.enable_watchdog:
            self._refresh_telemetry_data()

        if not self.telemetry_data:
            return "No setup data available."

        try:
            setup_info = []

            # Basic setup info available from telemetry
            brake_bias = self.telemetry_data.get("dcBrakeBias", 0)
            if brake_bias > 0:
                setup_info.append(f"Brake bias: {brake_bias:.1f}%")

            # Get additional setup-related telemetry
            try:
                # These variables might be available depending on the car
                wing_front = self._telemetry("dcAeroFront", None)
                wing_rear = self._telemetry("dcAeroRear", None)
                if wing_front is not None:
                    setup_info.append(f"Front wing: {wing_front}")
                if wing_rear is not None:
                    setup_info.append(f"Rear wing: {wing_rear}")

                # Differential settings (if available)
                diff_entry = self._telemetry("dcDiffEntry", None)
                diff_middle = self._telemetry("dcDiffMiddle", None)
                diff_exit = self._telemetry("dcDiffExit", None)

                if any(x is not None for x in [diff_entry, diff_middle, diff_exit]):
                    diff_parts = []
                    if diff_entry is not None:
                        diff_parts.append(f"Entry: {diff_entry}")
                    if diff_middle is not None:
                        diff_parts.append(f"Middle: {diff_middle}")
                    if diff_exit is not None:
                        diff_parts.append(f"Exit: {diff_exit}")
                    setup_info.append(f"Differential - {', '.join(diff_parts)}")

                # Tire pressure (basic setup indicator)
                tire_pressures = [
                    self._telemetry("LFpressure", None),
                    self._telemetry("RFpressure", None),
                    self._telemetry("LRpressure", None),
                    self._telemetry("RRpressure", None),
                ]

                if any(p is not None for p in tire_pressures):
                    valid_pressures = [p for p in tire_pressures if p is not None]
                    if valid_pressures:
                        avg_pressure = sum(valid_pressures) / len(valid_pressures)
                        setup_info.append(f"Avg tire pressure: {avg_pressure:.1f} psi")

            except Exception:
                pass  # Skip advanced setup data if not available

            if setup_info:
                return f"Setup: {'; '.join(setup_info)}. Access garage for detailed adjustments."
            else:
                return "Basic setup data available. Access garage for detailed setup information."

        except Exception as e:
            return f"Error reading setup data: {str(e)}"

    def __del__(self):
        """Cleanup when the skill is destroyed"""
        # Use the proper cleanup method
        asyncio.run(self.unload())

    async def unload(self) -> None:
        """Unload the skill - stop all background tasks and cleanup resources"""
        # Call parent cleanup first
        await super().unload()

        # Stop watchdog thread safely
        if hasattr(self, "watchdog_running") and self.watchdog_running:
            self.watchdog_running = False

            # Wait for thread to finish (with timeout to prevent hanging)
            if (
                hasattr(self, "watchdog_thread")
                and self.watchdog_thread
                and self.watchdog_thread.is_alive()
            ):
                self.watchdog_thread.join(timeout=2.0)  # 2 second timeout

                if self.watchdog_thread.is_alive():
                    # Log warning if thread doesn't stop gracefully
                    if hasattr(self, "settings") and self.settings.debug_mode:
                        await self.printr.print_async(
                            text="iRacing: Watchdog thread did not stop gracefully - forcing cleanup",
                            color=LogType.WARNING,
                        )

        # Clean up iRacing SDK connection
        if hasattr(self, "ir") and self.ir:
            try:
                self.ir.shutdown()
            except Exception as e:
                # Log error but don't fail cleanup
                if hasattr(self, "settings") and self.settings.debug_mode:
                    await self.printr.print_async(
                        text=f"iRacing: Error during SDK shutdown: {str(e)}",
                        color=LogType.ERROR,
                    )
            finally:
                self.ir = None

        # Clear all telemetry data
        if hasattr(self, "telemetry_data"):
            self.telemetry_data.clear()
        if hasattr(self, "session_data"):
            self.session_data.clear()
        if hasattr(self, "watchdog_events"):
            self.watchdog_events.clear()

        # Reset connection state
        self.is_connected = False
        self.watchdog_started = False

        if hasattr(self, "settings") and self.settings.debug_mode:
            await self.printr.print_async(
                text="iRacing: Skill unloaded successfully",
                color=LogType.INFO,
            )
