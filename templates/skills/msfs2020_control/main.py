import time
import random
import requests
from typing import TYPE_CHECKING
from SimConnect import *
from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanInitializationError,
)
from api.enums import LogType
from services.benchmark import Benchmark
from skills.skill_base import Skill

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
        self.autostart_data_monitoring_loop_mode = False
        self.data_monitoring_backstory = ""
        self.min_data_monitoring_seconds = 60
        self.max_data_monitoring_seconds = 360

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        self.autostart_data_monitoring_loop_mode = self.retrieve_custom_property_value(
            "autostart_data_monitoring_loop_mode", errors
        )
        self.data_monitoring_backstory = self.retrieve_custom_property_value(
            "data_monitoring_backstory", errors
        )
        # If not available or not set, use default wingman's backstory
        if (
            not self.data_monitoring_backstory
            or self.data_monitoring_backstory == ""
            or self.data_monitoring_backstory == " "
        ):
            self.data_monitoring_backstory = self.wingman.config.prompts.backstory

        self.min_data_monitoring_seconds = self.retrieve_custom_property_value(
            "min_data_monitoring_seconds", errors
        )

        self.max_data_monitoring_seconds = self.retrieve_custom_property_value(
            "max_data_monitoring_seconds", errors
        )

        return errors

    def get_tools(self) -> list[tuple[str, dict]]:
        return [
            (
                "get_data_from_sim",
                {
                    "type": "function",
                    "function": {
                        "name": "get_data_from_sim",
                        "description": "Retrieve data points from Microsoft Flight Simulator 2020 using the Python SimConnect module.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "data_point": {
                                    "type": "string",
                                    "description": "The data point to retrieve, such as 'PLANE_ALTITUDE', 'PLANE_HEADING_DEGREES_TRUE'.",
                                },
                            },
                            "required": ["data_point"],
                        },
                    },
                },
            ),
            (
                "set_data_or_perform_action_in_sim",
                {
                    "type": "function",
                    "function": {
                        "name": "set_data_or_perform_action_in_sim",
                        "description": "Set data points or perform actions in Microsoft Flight Simulator 2020 using the Python SimConnect module.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "description": "The action to perform or data point to set, such as 'TOGGLE_MASTER_BATTERY', 'THROTTLE_SET'.",
                                },
                                "argument": {
                                    "type": "number",
                                    "description": "The argument to pass for the action, if any. For actions like 'TOGGLE_MASTER_BATTERY', no argument is needed. For 'THROTTLE_SET', pass the throttle value.",
                                },
                            },
                            "required": ["action"],
                        },
                    },
                },
            ),
            (
                "start_or_activate_data_monitoring_loop",
                {
                    "type": "function",
                    "function": {
                        "name": "start_or_activate_data_monitoring_loop",
                        "description": "Begin data monitoring loop, which will check certain data points at designated intervals.  May be referred to as tour guide mode.",
                    },
                },
            ),
            (
                "end_or_stop_data_monitoring_loop",
                {
                    "type": "function",
                    "function": {
                        "name": "end_or_stop_data_monitoring_loop",
                        "description": "End or stop data monitoring loop, to stop automatically checking data points at designated intervals.  May be referred to as tour guide mode.",
                    },
                },
            ),
            (
                "get_information_about_current_location",
                {
                    "type": "function",
                    "function": {
                        "name": "get_information_about_current_location",
                        "description": "Used to provide more detailed information if the user asks a general question like 'where are we?', 'what city are we flying over?', or 'what country is down there?'",
                    },
                },
            ),
        ]

    # Using sample methods found here; allow AI to determine the appropriate variables and arguments, if any:
    # https://pypi.org/project/SimConnect/
    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any], benchmark: Benchmark
    ) -> tuple[str, str]:
        function_response = "Error in execution. Can you please try your command again?"
        instant_response = ""

        if tool_name in [
            "get_data_from_sim",
            "set_data_or_perform_action_in_sim",
            "start_or_activate_data_monitoring_loop",
            "end_or_stop_data_monitoring_loop",
            "get_information_about_current_location",
        ]:
            benchmark.start_snapshot(f"MSFS2020 Control: {tool_name}")
            if self.settings.debug_mode:
                message = f"MSFS2020: executing tool '{tool_name}'"
                if parameters:
                    message += f" with params: {parameters}"
                await self.printr.print_async(message, color=LogType.INFO)

            if tool_name == "get_data_from_sim":
                data_point = parameters.get("data_point")
                value = self.aq.get(data_point)
                function_response = f"{data_point} value is: {value}"

            elif tool_name == "set_data_or_perform_action_in_sim":
                action = parameters.get("action")
                argument = parameters.get("argument", None)
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
                    benchmark.finish_snapshot()
                    return function_response, instant_response

                function_response = (
                    f"Action '{action}' executed with argument '{argument}'"
                )

            elif tool_name == "start_or_activate_data_monitoring_loop":
                if self.data_monitoring_loop_running:
                    function_response = "Data monitoring loop is already running."
                    benchmark.finish_snapshot()
                    return function_response, instant_response

                if not self.already_initialized_simconnect:
                    function_response = "Cannot start data monitoring / tour guide mode because simconnect is not connected yet.  Check to make sure the game is running."
                    benchmark.finish_snapshot()
                    return function_response, instant_response

                if not self.data_monitoring_loop_running:
                    await self.initialize_data_monitoring_loop()

                function_response = "Started data monitoring loop/tour guide mode."

            elif tool_name == "end_or_stop_data_monitoring_loop":
                await self.stop_data_monitoring_loop()
                function_response = "Closed data monitoring / tour guide mode."

            elif tool_name == "get_information_about_current_location":
                place_info = await self.convert_lat_long_data_into_place_data()
                if place_info:
                    on_ground = self.aq.get("SIM_ON_GROUND")
                    on_ground_statement = "The plane is currently in the air."
                    if not on_ground:
                        on_ground_statement = "The plane is currently on the ground."
                    function_response = f"{on_ground_statement}  Detailed information regarding the location we are currently at or flying over: {place_info}"
                else:
                    function_response = "Unable to get more detailed information regarding the place based on the current latitude and longitude."

            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"MSFS2020: function_response: '{function_response}'",
                    color=LogType.INFO,
                )

            benchmark.finish_snapshot()

        return function_response, instant_response

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
                if self.autostart_data_monitoring_loop_mode:
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
                random_time = random.choice(
                    range(
                        self.min_data_monitoring_seconds,
                        self.max_data_monitoring_seconds,
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
        user_content = f"{on_ground_statement}  Information about the location: {data}"
        messages = [
            {
                "role": "system",
                "content": f"""
                    {self.data_monitoring_backstory}
                """,
            },
            {
                "role": "user",
                "content": user_content,
            },
        ]
        if self.settings.debug_mode:
            await self.printr.print_async(
                f"Attempting LLM call with parameters: {self.data_monitoring_backstory}, {user_content}.",
                color=LogType.INFO,
            )
        llm_response = await self.llm_call(messages)
        response = (
            llm_response.content
            if llm_response
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
        self.loaded = True
        self.threaded_execution(self.start_simconnect)

    async def unload(self) -> None:
        """Unload the skill."""
        await self.stop_data_monitoring_loop()
        self.loaded = False
        if self.sm:
            self.sm.exit()
