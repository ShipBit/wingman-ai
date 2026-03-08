import os
import time
import random
import requests
import sys
from typing import TYPE_CHECKING
from SimConnect import *
from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanInitializationError,
)
from api.enums import LogType
from services.benchmark import Benchmark
from skills.skill_base import Skill, tool


# add skill to sys path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import msfs2020 command processer helper
from skills.msfs2020_control.command_matcher.command_matcher import CommandMatcher

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class Msfs2020Control(Skill):

    def __init__(
        self, config: SkillConfig, settings: SettingsConfig, wingman: "OpenAiWingman"
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        self.already_initialized_simconnect = False
        self.loaded = False
        self.sm = None  # Needs to be set once MSFS2020 is actually connected
        self.aq = None  # Same
        self.ae = None  # Same
        self.data_monitoring_loop_running = False
        self.command_matcher = CommandMatcher()

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        # Validate properties exist (don't cache values)
        self.retrieve_custom_property_value(
            "autostart_data_monitoring_loop_mode", errors
        )
        self.retrieve_custom_property_value("data_monitoring_backstory", errors)
        self.retrieve_custom_property_value("min_data_monitoring_seconds", errors)
        self.retrieve_custom_property_value("max_data_monitoring_seconds", errors)
        return errors

    def _get_data_monitoring_backstory(self) -> str:
        """Retrieve fresh data monitoring backstory at runtime."""
        errors: list[WingmanInitializationError] = []
        backstory = self.retrieve_custom_property_value(
            "data_monitoring_backstory", errors
        )
        # If not available or not set, use default wingman's backstory
        if not backstory or backstory.strip() == "":
            return self.wingman.config.prompts.backstory
        return backstory

    def _get_min_data_monitoring_seconds(self) -> int:
        """Retrieve fresh min data monitoring seconds at runtime."""
        errors: list[WingmanInitializationError] = []
        seconds = self.retrieve_custom_property_value(
            "min_data_monitoring_seconds", errors
        )
        return seconds if seconds else 60

    def _get_max_data_monitoring_seconds(self) -> int:
        """Retrieve fresh max data monitoring seconds at runtime."""
        errors: list[WingmanInitializationError] = []
        seconds = self.retrieve_custom_property_value(
            "max_data_monitoring_seconds", errors
        )
        return seconds if seconds else 360

    def _get_autostart_data_monitoring_loop_mode(self) -> bool:
        """Retrieve fresh autostart mode at runtime."""
        errors: list[WingmanInitializationError] = []
        return (
            self.retrieve_custom_property_value(
                "autostart_data_monitoring_loop_mode", errors
            )
            or False
        )

    @tool(
        description="Retrieve the list of potential matching SimConnect commands (events) or data points (SimVars) to accomplish the user's intent."
    )
    async def get_potential_matching_commands(self, user_intent: str) -> str:
        """
        Retrieve the list of potential matching SimConnect commands (events) or data points (SimVars) to accomplish the user's intent. For use in get_data_from_sim and set_data_or_perform_action_in_sim.
        Automatically use if there is a problem fetching data or accomplishing an action in the Sim to ensure the proper Event or SimVar is used.
        Args:
            user_intent: The user's intent expressed as a brief string, e.g., "set the heading to 270 degrees", "turn on autopilot", "set full throttle".
        """
        
        matches = self.command_matcher.find_matches(user_intent)
        matches_string = self.command_matcher.matches_as_string(matches)
        if self.settings.debug_mode:
            await self.printr.print_async(
                f"Found potential matching commands for intent {user_intent}: {matches_string}",
                color=LogType.INFO,
            )
        return matches_string

    @tool(
        description="Retrieve data from MSFS2020 via SimConnect SimVars. Examples: PLANE_ALTITUDE, AIRSPEED_INDICATED, FUEL_TOTAL_QUANTITY, GEAR_HANDLE_POSITION. Use :index suffix for multi-engine (e.g., GENERAL_ENG_RPM:1)."
    )
    async def get_data_from_sim(self, data_point: str) -> str:
        """
        Retrieve data points from Microsoft Flight Simulator 2020 using the Python SimConnect module.

        Args:
            data_point: The data point to retrieve, such as 'PLANE_ALTITUDE', 'PLANE_HEADING_DEGREES_TRUE'.
        """
        
        value = self.aq.get(data_point)
        if self.settings.debug_mode:
            await self.printr.print_async(
                f"Retrieving data point from sim: {data_point}; value returned: {value}",
                color=LogType.INFO,
            )
        return f"{data_point} value is: {value}"

    @tool(
        description="Control MSFS2020 aircraft via SimConnect Events. Examples: THROTTLE_FULL, FLAPS_UP, GEAR_TOGGLE, AP_MASTER, TOGGLE_BEACON_LIGHTS. Use TOGGLE_ prefix for switches, _INCR/_DECR for adjustments. Pass argument for SET commands (0-16383)."
    )
    async def set_data_or_perform_action_in_sim(
        self, action: str, argument: float = None
    ) -> str:
        """
        Set data points or perform actions in Microsoft Flight Simulator 2020 using the Python SimConnect module.

        Args:
            action: The action to perform or data point to set, such as 'TOGGLE_MASTER_BATTERY', 'THROTTLE_SET'.
            argument: The argument to pass for the action, if any.
        """
        if self.settings.debug_mode:
            await self.printr.print_async(
                f"Attempting to perform action/set data in sim: {action} with argument: {argument}",
                color=LogType.INFO,
            )
        try:
            if argument is not None:
                self.aq.set(action, argument)
            else:
                event_to_trigger = self.ae.find(action)
                event_to_trigger()
        except Exception:
            await self.printr.print_async(
                f"Tried to perform action {action} with argument {argument} using aq.set, now going to try ae.event_to_trigger.",
                color=LogType.INFO,
            )

        try:
            if argument is not None:
                event_to_trigger = self.ae.find(action)
                event_to_trigger(argument)
        except Exception:
            await self.printr.print_async(
                f"Neither aq.set nor ae.event_to_trigger worked with {action} and {argument}.  Command failed.",
                color=LogType.INFO,
            )
            return "Error: Command failed."

        return f"Action '{action}' executed with argument '{argument}'"

    @tool(
        description="Begin flight data monitoring loop (tour guide mode). Periodically checks flight data and provides commentary. Use for immersive AI co-pilot experience."
    )
    async def start_or_activate_data_monitoring_loop(self) -> str:
        """Begin data monitoring loop, which will check certain data points at designated intervals."""
        if self.data_monitoring_loop_running:
            return "Data monitoring loop is already running."

        if not self.already_initialized_simconnect:
            return "Cannot start data monitoring / tour guide mode because simconnect is not connected yet.  Check to make sure the game is running."

        if not self.data_monitoring_loop_running:
            await self.initialize_data_monitoring_loop()

        return "Started data monitoring loop/tour guide mode."

    @tool(description="End or stop data monitoring loop (tour guide mode).")
    async def end_or_stop_data_monitoring_loop(self) -> str:
        """End or stop data monitoring loop."""
        await self.stop_data_monitoring_loop()
        return "Closed data monitoring / tour guide mode."

    @tool(description="Get detailed information about the current location.")
    async def get_information_about_current_location(self) -> str:
        """Used to provide more detailed information if the user asks a general question like 'where are we?'."""
        place_info = await self.convert_lat_long_data_into_place_data()
        if place_info:
            on_ground = self.aq.get("SIM_ON_GROUND")
            on_ground_statement = "The plane is currently in the air."
            if not on_ground:
                on_ground_statement = "The plane is currently on the ground."
            return f"{on_ground_statement}  Detailed information regarding the location we are currently at or flying over: {place_info}"
        else:
            return "Unable to get more detailed information regarding the place based on the current latitude and longitude."

    # Search for MSFS2020 sim running and then connect
    async def start_simconnect(self):
        while self.loaded and not self.already_initialized_simconnect:
            try:
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        "Attempting to find MSFS2020....",
                        color=LogType.INFO,
                    )
                self.sm = SimConnect()
                self.aq = AircraftRequests(self.sm, _time=2000)
                self.ae = AircraftEvents(self.sm)
                self.already_initialized_simconnect = True
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        "Initialized SimConnect with MSFS2020.",
                        color=LogType.INFO,
                    )
                if self._get_autostart_data_monitoring_loop_mode():
                    await self.initialize_data_monitoring_loop()
            except Exception:
                # Wait 30 seconds between connect attempts
                time.sleep(30)

    async def initialize_data_monitoring_loop(self):
        if self.data_monitoring_loop_running:
            return

        if self.settings.debug_mode:
            await self.printr.print_async(
                "Starting threaded data monitoring loop",
                color=LogType.INFO,
            )

        self.threaded_execution(self.start_data_monitoring_loop)

    async def start_data_monitoring_loop(self):
        if not self.data_monitoring_loop_running:
            self.data_monitoring_loop_running = True

            while self.data_monitoring_loop_running:
                min_seconds = self._get_min_data_monitoring_seconds()
                max_seconds = self._get_max_data_monitoring_seconds()
                random_time = random.choice(
                    range(
                        min_seconds,
                        max_seconds,
                        15,
                    )
                )  # Gets random number from min to max in increments of 15
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        "Attempting looped monitoring check.",
                        color=LogType.INFO,
                    )
                try:
                    place_data = await self.convert_lat_long_data_into_place_data()
                    if place_data:
                        await self.initiate_llm_call_with_plane_data(place_data)
                except Exception as e:
                    if self.settings.debug_mode:
                        await self.printr.print_async(
                            f"Something failed in looped monitoring check.  Could not return data or send to llm: {e}.",
                            color=LogType.INFO,
                        )
                time.sleep(random_time)

    async def stop_data_monitoring_loop(self):
        self.data_monitoring_loop_running = False

        if self.settings.debug_mode:
            await self.printr.print_async(
                "Stopping data monitoring loop",
                color=LogType.INFO,
            )

    async def convert_lat_long_data_into_place_data(
        self, latitude=None, longitude=None, altitude=None
    ):
        if not self.already_initialized_simconnect or not self.sm or not self.aq:
            return None
        ground_altitude = 0
        # If all parameters are already provided, just run the request
        if latitude and longitude and altitude:
            ground_altitude = self.aq.get("GROUND_ALTITUDE")
        # If only latitude and longitude, grab altitude so a reasonable "zoom level" can be set for place data
        elif latitude and longitude:
            altitude = self.aq.get("PLANE_ALTITUDE")
            ground_altitude = self.aq.get("GROUND_ALTITUDE")
        # Otherwise grab all data components
        else:
            latitude = self.aq.get("PLANE_LATITUDE")
            longitude = self.aq.get("PLANE_LONGITUDE")
            altitude = self.aq.get("PLANE_ALTITUDE")
            ground_altitude = self.aq.get("GROUND_ALTITUDE")

        # If no values still, for instance, when connection is made but no data yet, return None
        if not latitude or not longitude or not altitude or not ground_altitude:
            return None

        # Set zoom level based on altitude, see zoom documentation at https://nominatim.org/release-docs/develop/api/Reverse/
        zoom = 18
        distance_above_ground = altitude - ground_altitude
        if distance_above_ground <= 1500:
            zoom = 18
        elif distance_above_ground <= 3500:
            zoom = 17
        elif distance_above_ground <= 5000:
            zoom = 15
        elif distance_above_ground <= 10000:
            zoom = 13
        elif distance_above_ground <= 20000:
            zoom = 10
        else:
            zoom = 8

        if self.settings.debug_mode:
            await self.printr.print_async(
                f"Attempting query of OpenStreetMap Nominatum with parameters: {latitude}, {longitude}, {altitude}, zoom level: {zoom}",
                color=LogType.INFO,
            )

        # Request data from openstreetmap nominatum api for reverse geocoding
        url = f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={latitude}&lon={longitude}&zoom={zoom}&accept-language=en&extratags=1"
        headers = {"User-Agent": f"msfs2020control_skill wingmanai {self.wingman.name}"}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"API request failed to {url}, status code: {response.status_code}.",
                    color=LogType.INFO,
                )
            return None

    # Get LLM to provide a verbal response to the user, without requiring the user to initiate a communication with the LLM
    async def initiate_llm_call_with_plane_data(self, data):
        on_ground = self.aq.get("SIM_ON_GROUND")
        on_ground_statement = "The plane is currently in the air."
        if on_ground:
            on_ground_statement = "The plane is currently on the ground."
        backstory = self._get_data_monitoring_backstory()
        user_content = f"{on_ground_statement}  Information about the location: {data}"
        messages = [
            {
                "role": "system",
                "content": f"""
                    {backstory}
                """,
            },
            {
                "role": "user",
                "content": user_content,
            },
        ]
        if self.settings.debug_mode:
            await self.printr.print_async(
                f"Attempting LLM call with parameters: {backstory}, {user_content}.",
                color=LogType.INFO,
            )
        completion = await self.llm_call(messages)
        response = (
            completion.choices[0].message.content
            if completion and completion.choices
            else ""
        )

        if not response:
            if self.settings.debug_mode:
                await self.printr.print_async(
                    "LLM call returned no response.",
                    color=LogType.INFO,
                )
            return

        await self.printr.print_async(
            text=f"Data monitoring response: {response}",
            color=LogType.INFO,
            source_name=self.wingman.name,
        )

        self.threaded_execution(self.wingman.play_to_user, response, True)
        await self.wingman.add_assistant_message(response)

    async def is_waiting_response_needed(self, tool_name: str) -> bool:
        return True

    async def prepare(self) -> None:
        """Load the skill by trying to connect to the sim"""
        await super().prepare()
        self.loaded = True
        self.threaded_execution(self.start_simconnect)

    async def unload(self) -> None:
        """Unload the skill."""
        await super().unload()
        await self.stop_data_monitoring_loop()
        self.loaded = False
        if self.sm:
            self.sm.exit()
