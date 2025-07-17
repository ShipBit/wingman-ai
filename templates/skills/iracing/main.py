import asyncio
import threading
import time
from typing import TYPE_CHECKING, Any, Dict, Tuple
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


class IRacing(Skill):
    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        self.ir = None
        self.telemetry_data = {}
        self.session_data = {}
        self.is_connected = False
        self.watchdog_thread = None
        self.watchdog_running = False
        self.last_update = 0

        self.enable_watchdog = False
        self.watchdog_interval = 10.0
        if irsdk:
            self.ir = irsdk.IRSDK()

        # Start watchdog after validation
        self.watchdog_started = False

    def _telemetry(self, key, default=None):
        """Safely get telemetry data with fallback"""
        try:
            if self.ir and self.ir.is_initialized and self.ir.is_connected:
                value = self.ir[key]
                return value if value is not None else default
            return default
        except (KeyError, AttributeError):
            return default

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

                    # Cache commonly used data for performance
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
                        "LapLastLapTime": self._telemetry("LapLastLapTime", 0),
                        "LapBestLapTime": self._telemetry("LapBestLapTime", 0),
                        "LapCurrentLapTime": self._telemetry("LapCurrentLapTime", 0),
                        # Delta timing and sector analysis data
                        "LapDistPct": self._telemetry("LapDistPct", 0),
                        "LapDeltaToBestLap": self._telemetry("LapDeltaToBestLap", 0),
                        "LapDeltaToBestLap_OK": self._telemetry(
                            "LapDeltaToBestLap_OK", False
                        ),
                        "LapDeltaToOptimalLap": self._telemetry(
                            "LapDeltaToOptimalLap", 0
                        ),
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

                    # Get session info
                    self.session_data = {
                        "WeekendInfo": self._telemetry("WeekendInfo"),
                        "SessionInfo": self._telemetry("SessionInfo"),
                        "CarSetup": self._telemetry("CarSetup"),
                    }

                    self.last_update = time.time()
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
                if self.settings.debug_mode:
                    asyncio.run(
                        self.printr.print_async(
                            text=f"iRacing watchdog error: {str(e)}",
                            color=LogType.ERROR,
                        )
                    )
                time.sleep(1)

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
        """Get tire temperature and condition data"""
        # Refresh data if watchdog is disabled
        if not self.enable_watchdog:
            self._refresh_telemetry_data()

        if not self.telemetry_data:
            return "No tire data available."

        try:
            # Get tire temperatures (left, right, middle for each tire)
            lf_temp = self.telemetry_data.get("LFtempCM", [0, 0, 0])
            rf_temp = self.telemetry_data.get("RFtempCM", [0, 0, 0])
            lr_temp = self.telemetry_data.get("LRtempCM", [0, 0, 0])
            rr_temp = self.telemetry_data.get("RRtempCM", [0, 0, 0])

            # Get tire wear
            lf_wear = self.telemetry_data.get("LFwearM", 0)
            rf_wear = self.telemetry_data.get("RFwearM", 0)
            lr_wear = self.telemetry_data.get("LRwearM", 0)
            rr_wear = self.telemetry_data.get("RRwearM", 0)

            # Calculate average temperatures
            lf_avg = sum(lf_temp) / 3 if lf_temp else 0
            rf_avg = sum(rf_temp) / 3 if rf_temp else 0
            lr_avg = sum(lr_temp) / 3 if lr_temp else 0
            rr_avg = sum(rr_temp) / 3 if rr_temp else 0

            # Convert to Fahrenheit and format
            lf_f = (lf_avg * 9 / 5) + 32
            rf_f = (rf_avg * 9 / 5) + 32
            lr_f = (lr_avg * 9 / 5) + 32
            rr_f = (rr_avg * 9 / 5) + 32

            return (
                f"Tire temps: LF {lf_f:.0f}°F, RF {rf_f:.0f}°F, "
                f"LR {lr_f:.0f}°F, RR {rr_f:.0f}°F. "
                f"Wear levels looking {'good' if max(lf_wear, rf_wear, lr_wear, rr_wear) < 0.5 else 'concerning'}."
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
        if hasattr(self, "watchdog_running"):
            self.watchdog_running = False
        if hasattr(self, "ir") and self.ir:
            self.ir.shutdown()
