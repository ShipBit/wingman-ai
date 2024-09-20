import os
import shutil
import math
import copy
from datetime import datetime, timedelta
import requests
import truck_telemetry
from pyproj import Proj, transform
import time
from typing import TYPE_CHECKING
from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanInitializationError,
)
from api.enums import LogType
from skills.skill_base import Skill
from services.file import get_writable_dir


if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman

class ATSTelemetry(Skill):

    def __init__(self, config: SkillConfig, settings: SettingsConfig, wingman: "OpenAiWingman") -> None:
        self.already_initialized_telemetry = False
        self.use_metric_system = False
        self.telemetry_loop_cached_data = {}
        self.telemetry_loop_data_points = [
            'onJob',
            'plannedDistance',
            'jobFinished',
            'jobCancelled',
            'jobDelivered',
            'jobStartingTime',
            'jobFinishedTime',
            'jobIncome',
            'jobCancelledPenalty',
            'jobDeliveredRevenue',
            'jobDeliveredEarnedXp',
            'jobDeliveredCargoDamage',
            'jobDeliveredDistance',
            'jobDeliveredAutoparkUsed',
            'jobDeliveredAutoloadUsed',
            'isCargoLoaded',
            'specialJob',
            'jobMarket',
            'fined',
            'tollgate',
            'ferry',
            'train',
            'refuel',
            'refuelPayed',
            'refuelAmount',
            'cargoDamage',
            'truckBrand',
            'truckName',
            'cargo',
            'cityDst',
            'compDst',
            'citySrc',
            'compSrc',
            'truckLicensePlate',
            'truckLicensePlateCountry',
            'fineOffence',
            'fineAmount',
            'isWorldOfTrucksContract',
            'gameTimeLapsedToCompleteJob',
            'realLifeTimeToCompleteWorldofTrucksJob',
            'cargoMassInTons',
            'cargoMass',
        ]
        self.telemetry_loop_running = False
        self.ats_install_directory = ""
        self.ets_install_directory = ""
        self.dispatcher_backstory = ""
        self.autostart_dispatch_mode = False
        # Define the ATS (American Truck Simulator) projection for use in converting in-game coordinates to real life
        self.ats_proj = Proj(
            proj='lcc', lat_1=33, lat_2=45, lat_0=39, lon_0=-96, units='m', k_0=0.05088, ellps='sphere'
        )
        # Define the ETS2 (Euro Truck Simulator 2) projection and the UK projection for use in converting in-game coordinates to real life
        ets2_scale = 1 / 19.35
        uk_scale = ets2_scale / 0.75

        self.ets2_proj = Proj(
            proj='lcc', lat_1=37, lat_2=65, lat_0=50, lon_0=15, units='m', k_0=ets2_scale, ellps='sphere'
        )
        self.uk_proj = Proj(
            proj='lcc', lat_1=37, lat_2=65, lat_0=50, lon_0=15, units='m', k_0=uk_scale, ellps='sphere'
        )
        super().__init__(config=config, settings=settings, wingman=wingman)

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        self.use_metric_system = self.retrieve_custom_property_value(
            "use_metric_system", errors
        )
        self.ats_install_directory = self.retrieve_custom_property_value(
            "ats_install_directory", errors
        )
        self.ets_install_directory = self.retrieve_custom_property_value(
            "ets_install_directory", errors
        )
        self.dispatcher_backstory = self.retrieve_custom_property_value(
            "dispatcher_backstory", errors
        )
        # Default back to wingman backstory
        if self.dispatcher_backstory == "" or self.dispatcher_backstory == " " or not self.dispatcher_backstory:
            self.dispatcher_backstory = self.wingman.config.prompts.backstory
        
        self.autostart_dispatch_mode = self.retrieve_custom_property_value(
            "autostart_dispatch_mode", errors
        )
        await self.check_and_install_telemetry_dlls()
        return errors

    # Try to find existing telemetry dlls, if not found, attempt to install
    async def check_and_install_telemetry_dlls(self):
        skills_filepath = get_writable_dir("skills")
        ats_telemetry_skill_filepath = os.path.join(skills_filepath, "ats_telemetry")
        sdk_dll_filepath = os.path.join(ats_telemetry_skill_filepath, "scs-telemetry.dll")
        ats_plugins_dir = os.path.join(self.ats_install_directory, "bin\\win_x64\\plugins")
        ets_plugins_dir = os.path.join(self.ets_install_directory, "bin\\win_x64\\plugins")
        # Check and copy dll for ATS if applicable
        if os.path.exists(self.ats_install_directory):
            ats_dll_path = os.path.join(ats_plugins_dir, "scs-telemetry.dll")
            if not os.path.exists(ats_dll_path):
                try:
                    if not os.path.exists(ats_plugins_dir):
                        os.makedirs(ats_plugins_dir)
                    shutil.copy2(sdk_dll_filepath, ats_plugins_dir)
                except Exception as e:
                    if self.settings.debug_mode:
                        await self.printr.print_async(
                            f"Could not install scs telemetry dll to {ats_plugins_dir}.",
                            color=LogType.INFO,
                        )
        # Check and copy dll for ETS if applicable
        if os.path.exists(self.ets_install_directory):
            ets_dll_path = os.path.join(ets_plugins_dir, "scs-telemetry.dll")
            if not os.path.exists(ets_dll_path):
                try:
                    if not os.path.exists(ets_plugins_dir):
                        os.makedirs(ets_plugins_dir)
                    shutil.copy2(sdk_dll_filepath, ets_plugins_dir)
                except Exception as e:
                    if self.settings.debug_mode:
                        await self.printr.print_async(
                            f"Could not install scs telemetry dll to {ets_plugins_dir}.",
                            color=LogType.INFO,
                        )

    # Start telemetry module connection with in-game telemetry SDK
    async def initialize_telemetry(self) -> bool:
        if self.settings.debug_mode:
            await self.printr.print_async(
                "Starting ATS / ETS telemetry module",
                color=LogType.INFO,
            )
        # truck_telemetry.init() requires the user to have installed the proper SDK DLL from https://github.com/RenCloud/scs-sdk-plugin/releases/tag/V.1.12.1 
        # into the proper folder of their truck sim install (https://github.com/RenCloud/scs-sdk-plugin#installation), if they do not this step will fail, so need to catch the error.
        try:
            truck_telemetry.init()
            return True
        except:
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Initialize ATSTelemetry function failed.",
                    color=LogType.INFO,
                )
            return False

    # Initiate separate thread for constant checking of changes to key telemetry data points
    async def initialize_telemetry_cache_loop(self, loop_time : int = 10):
        if self.telemetry_loop_running:
            return

        if self.settings.debug_mode:
            await self.printr.print_async(
                "Starting ATS / ETS telemetry cache loop",
                color=LogType.INFO,
            )
        self.threaded_execution(self.start_telemetry_loop, loop_time)

    # Loop every designated number of seconds to retrieve telemetry data and run query function to determine if any tracked data points have changed
    async def start_telemetry_loop(self, loop_time: int):
        if not self.telemetry_loop_running:
            self.telemetry_loop_running = True
            data = truck_telemetry.get_data()
            filtered_data = await self.filter_data(data)
            self.telemetry_loop_cached_data = copy.deepcopy(filtered_data)
            while self.telemetry_loop_running:
                changed_data = await self.query_and_compare_data(self.telemetry_loop_data_points)
                if changed_data:
                    await self.initiate_llm_call_with_changed_data(changed_data)
                time.sleep(loop_time)

    # Compare new telemetry data in monitored fields and react if there are changes
    async def query_and_compare_data(self, data_points: list):
        try:
            default = "The following data changed: "
            data_changed = default
            data = truck_telemetry.get_data()
            filtered_data = await self.filter_data(data)
            if self.settings.debug_mode:
                await self.printr.print_async(
                    "Querying and comparing telemetry data",
                    color=LogType.INFO,
                )
            for point in data_points:
                current_data = filtered_data.get(point)
                if current_data and current_data != self.telemetry_loop_cached_data.get(point):
                    # Prevent relatively small data changes in float values from triggering new alerts, such as when cargo damage, route distance or route time change by very small values
                    if isinstance(current_data, float) and abs((current_data - self.telemetry_loop_cached_data.get(point)) / current_data) <= 0.25:
                        pass
                    else:
                        data_changed = data_changed + f"{point}:{current_data}, last value was {point}:{self.telemetry_loop_cached_data.get(point)},"
            self.telemetry_loop_cached_data = copy.deepcopy(filtered_data)
            if data_changed == default:
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        "No changed telemetry data found.",
                        color=LogType.INFO,
                    )
                return None
            else:
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        data_changed,
                        color=LogType.INFO,
                    )
                return data_changed

        except Exception as e:
            return None

    # Stop ongoing call for updated telemetry data
    async def stop_telemetry_loop(self):
        self.telemetry_loop_running = False
        self.telemetry_loop_cached_data = {}
        if self.settings.debug_mode:
            await self.printr.print_async(
                "Stopping ATS / ETS telemetry cache loop",
                color=LogType.INFO,
            )

    # If telemetry data changed, get LLM to provide a verbal response to the user, without requiring the user to initiate a communication with the LLM
    async def initiate_llm_call_with_changed_data(self, changed_data):
        units_phrase = "You are located in the US, so use US Customary Units, like feet, yards, miles, and pounds in your responses, and convert metric or imperial formats to these units.  All currency is in dollars."
        if self.use_metric_system:
            units_phrase = "Use the metric system like meters, kilometers, kilometers per hour, and kilograms in your responses."
        user_content = f"{changed_data}"
        messages = [
            {
                'role': 'system',
                'content': f"""
                    {self.dispatcher_backstory}
                    Acting in character at all times, react to the following changed information.
                    {units_phrase}
                """,
            },
            {
                'role': 'user',
                'content': user_content,
            },
        ]
        completion = await self.llm_call(messages)
        response = completion.choices[0].message.content if completion and completion.choices else ""

        if not response:
            return

        await self.printr.print_async(
                text=f"Dispatch: {response}",
                color=LogType.INFO,
                source_name=self.wingman.name
            )

        self.threaded_execution(self.wingman.play_to_user, response, True)
        await self.wingman.add_assistant_message(response)

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "get_game_state",
                {
                    "type": "function",
                    "function": {
                        "name": "get_game_state",
                        "description": "Retrieve the current game state variable from American Truck Simulator.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "variable": {
                                    "type": "string",
                                    "description": "The game state variable to retrieve (e.g., 'speed').",
                                }
                            },
                            "required": ["variable"],
                        },
                    },
                },
            ),
            (
                "get_information_about_current_location",
                {
                    "type": "function",
                    "function": {
                        "name": "get_information_about_current_location",
                        "description": "Used to provide more detailed information if the user asks a general question like 'where are we?', or 'what city are we in?'",
                    },
                },
            ),
            (
                "start_or_activate_dispatch_telemetry_loop",
                {
                    "type": "function",
                    "function": {
                        "name": "start_or_activate_dispatch_telemetry_loop",
                        "description": "Begin dispatch function, which will check telemetry at designated intervals.",
                    },
                },
            ),
            (
                "end_or_stop_dispatch_telemetry_loop",
                {
                    "type": "function",
                    "function": {
                        "name": "end_or_stop_dispatch_telemetry_loop",
                        "description": "End or stop dispatch function, to stop automatically checking telemetry at designated intervals.",
                    },
                },
            ),
        ]
        return tools

    async def execute_tool(self, tool_name: str, parameters: dict[str, any]) -> tuple[str, str]:
        function_response = ""
        instant_response = ""

        if tool_name == "get_game_state":
            if not self.already_initialized_telemetry:
                self.already_initialized_telemetry = await self.initialize_telemetry()
                # If initialization of telemetry object fails because another instance is already running, try just checking getting the data as a fail safe; if still cannot get the data, trigger error
                if not self.already_initialized_telemetry:
                    try:
                        test = truck_telemetry.get_data()
                        self.already_initialized_telemetry = True
                    except:
                        function_response = "Error trying to access truck telemetry data.  It appears there is a problem with the module.  Check to see if the game is running, and that you have installed the SDK in the proper location."
                        return function_response, instant_response

            if self.settings.debug_mode:
                self.start_execution_benchmark()
                await self.printr.print_async(
                    f"Executing get_game_state function with parameters: {parameters}",
                    color=LogType.INFO,
                )

            data = truck_telemetry.get_data()
            filtered_data = await self.filter_data(data)

            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Printout of all data received from telemetry: {filtered_data}",
                    color=LogType.INFO,
                )

            variable = parameters.get("variable")
            if variable in filtered_data:
                value = filtered_data[variable]
                try:
                    string_value = str(value)
                except:
                    string_value = "value could not be found."
                function_response = f"The current value of '{variable}' is {string_value}."
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        f"Found variable result in telemetry for {variable}, {string_value}",
                        color=LogType.INFO,
                    )
            else:
                function_response = f"Variable '{variable}' not found."
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        f"Could not locate variable result in telemetry for {variable}.",
                        color=LogType.INFO,
                    )

            if self.settings.debug_mode:
                await self.print_execution_time()

        elif tool_name == "start_or_activate_dispatch_telemetry_loop":
            if self.settings.debug_mode:
                self.start_execution_benchmark()
                await self.printr.print_async(
                    f"Executing start_or_activate_dispatch_telemetry_loop",
                    color=LogType.INFO,
                )

            if self.telemetry_loop_running:
                function_response = "Dispatch communications already open."
                if self.settings.debug_mode:
                    await self.print_execution_time()
                    await self.printr.print_async(
                    f"Attempted to start dispatch communications loop but loop is already running",
                    color=LogType.INFO,
                )

                return function_response, instant_response

            if not self.already_initialized_telemetry:
                self.already_initialized_telemetry = await self.initialize_telemetry()
                # If initialization of telemetry object fails because another instance is already running, try just checking getting the data as a fail safe; if still cannot get the data, trigger error
                if not self.already_initialized_telemetry:
                    try:
                        test = truck_telemetry.get_data()
                        self.already_initialized_telemetry = True
                    except:
                        function_response = "Error trying to access truck telemetry data.  It appears there is a problem with the module.  Check to see if the game is running, and that you have installed the SDK in the proper location."
                        return function_response, instant_response

            if not self.telemetry_loop_running:
                await self.initialize_telemetry_cache_loop(10)

            if self.settings.debug_mode:
                await self.print_execution_time()

            function_response = "Opened dispatch communications."

        elif tool_name == "end_or_stop_dispatch_telemetry_loop":
            if self.settings.debug_mode:
                self.start_execution_benchmark()
                await self.printr.print_async(
                    f"Executing end_or_stop_dispatch_telemetry_loop",
                    color=LogType.INFO,
                )

            await self.stop_telemetry_loop()

            if self.settings.debug_mode:
                await self.print_execution_time()

            function_response = "Closed dispatch communications."

        elif tool_name == "get_information_about_current_location":
            if not self.already_initialized_telemetry:
                self.already_initalized_telemetry = await self.initialize_telemetry()
                # If initialization of telemetry object fails because another instance is already running, try just checking getting the data as a fail safe; if still cannot get the data, trigger error
                if not self.already_initialized_telemetry:
                    try:
                        test = truck_telemetry.get_data()
                        self.already_initialized_telemetry = True
                    except:
                        function_response = "Error trying to access truck telemetry data.  It appears there is a problem with the module.  Check to see if the game is running, and that you have installed the SDK in the proper location."
                        return function_response, instant_response

            if self.settings.debug_mode:
                self.start_execution_benchmark()

            data = truck_telemetry.get_data()
            # Pull x, y coordinates from truck sim, note that there are x, y, z, so here z pertains to 2d y, and y pertains to altitude
            x = data["coordinateX"]
            y = data["coordinateZ"]

            # Convert to world latitude and longitude
            longitude, latitude = await self.from_ats_coords_to_wgs84(data["coordinateX"], data["coordinateZ"])
            
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Executing get_information_about_current_location function with coordinateX as {x} and coordinateZ as {y}, latitude returned was {latitude}, longitude returned was {longitude}.",
                    color=LogType.INFO,
                )

            place_info = await self.convert_lat_long_data_into_place_data(latitude, longitude)

            if self.settings.debug_mode:
                await self.print_execution_time()

            if place_info:
                function_response = f"Information regarding the approximate location we are near: {place_info}"
            else:
                function_response = "Unable to get more detailed information regarding the place based on the current truck coordinates."

        return function_response, instant_response

    # Function to autostart dispatch mode
    async def autostart_dispatcher_mode(self):
        telemetry_started = False
        while not telemetry_started and self.loaded:
            telemetry_started = await self.initialize_telemetry()
            # Init could fail if truck telemetry module already started elsewhere, so make sure we cannot just query truck telemetry data yet to be sure it's not initialized
            if not telemetry_started:
                try:
                    test = truck_telemetry.get_data()
                    telemetry_started = True
                except:
                    telemetry_started = False
            # Try again in ten seconds; maybe user has not loaded up Truck Simulator yet
            time.sleep(10)
        if self.loaded:
            await self.initialize_telemetry_cache_loop(10)

    # Autostart dispatch mode if option turned on in config
    async def prepare(self) -> None:
        self.loaded = True
        if self.autostart_dispatch_mode:
            self.threaded_execution(self.autostart_dispatcher_mode)

    # Unload telemetry module and stop any ongoing loop when config / program unloads
    async def unload(self) -> None:
        self.loaded = False
        await self.stop_telemetry_loop()
        truck_telemetry.deinit()

# Helper Data Functions for Enhancing Telemetry Data Before Sending to LLM
# Adapted, revised from https://github.com/mike-koch/ets2-mobile-route-advisor/blob/master/dashboard.js
    async def filter_data(self, data):
        try:
            # Set enhanced data to copy of all values of data
            enhanced_data = copy.deepcopy(data)

            enhanced_data['isEts2'] = (data['game'] == 1)
            enhanced_data['isAts'] = not enhanced_data['isEts2']

            # Deal with speed variables, create new ones specific to MPH and KPH
            truck_speed_mph = data['speed'] * 2.23694
            truck_speed_kph = data['speed'] * 3.6

            if self.use_metric_system:
                enhanced_data['truckSpeed'] = str(abs(round(truck_speed_kph))) + ' kilometers per hour'
                enhanced_data['cruiseControlSpeed'] = str(round(data['cruiseControlSpeed'] * 3.6)) + ' kilometers per hour'
                enhanced_data['speedLimit'] = str(round(data['speedLimit'] * 3.6)) + ' kilometers per hour'
            else:
                enhanced_data['truckSpeed'] = str(abs(round(truck_speed_mph))) + ' miles per hour'
                enhanced_data['cruiseControlSpeed'] = str(round(data['cruiseControlSpeed'] * 2.23694)) + ' miles per hour'
                enhanced_data['speedLimit'] = str(round(data['speedLimit'] * 2.23694)) + ' miles per hour'

            # Deal with shifter type, use more readable format
            if data['shifterType'] in ['automatic', 'arcade']:
                enhanced_data['gear'] = 'A' + str(data['gearDashboard']) if data['gearDashboard'] > 0 else ('R' + str(abs(data['gearDashboard'])) if data['gearDashboard'] < 0 else 'N')
            else:
                enhanced_data['gear'] = str(data['gearDashboard']) if data['gearDashboard'] > 0 else ('R' + str(abs(data['gearDashboard'])) if data['gearDashboard'] < 0 else 'N')
            
            # Convert percentages
            enhanced_data['currentFuelPercentage'] = str(round((data['fuel'] / data['fuelCapacity']) * 100)) + ' percent of fuel remaining.'
            enhanced_data['currentAdbluePercentage'] = str(round((data['adblue'] / data['adblueCapacity']) * 100)) + ' percent of adblue remaining.'
            scs_truck_damage = await self.getDamagePercentage(data)
            enhanced_data['truckDamageRounded'] = str(math.floor(scs_truck_damage)) + ' percent truck damage'
            scs_trailer_one_damage = await self.getDamagePercentageTrailer(data)
            enhanced_data['wearTrailerRounded'] = str(math.floor(scs_trailer_one_damage)) + ' percent trailer damage'

            # Convert times
            days_hours_and_minutes = await self.convert_minutes_to_days_hours_minutes(data['time_abs'])
            if self.use_metric_system:
                enhanced_data['gameTime'] = await self.convert_to_clock_time(days_hours_and_minutes, 24)
            else:
                enhanced_data['gameTime'] = await self.convert_to_clock_time(days_hours_and_minutes, 12)

            job_start_days_hours_and_minutes = await self.convert_minutes_to_days_hours_minutes(data['jobStartingTime'])
            if self.use_metric_system:
                enhanced_data['jobStartingTime'] = await self.convert_to_clock_time(job_start_days_hours_and_minutes, 24)
            else:
                enhanced_data['jobStartingTime'] = await self.convert_to_clock_time(job_start_days_hours_and_minutes, 12)

            job_finish_days_hours_and_minutes = await self.convert_minutes_to_days_hours_minutes(data['jobFinishedTime'])
            if self.use_metric_system:
                enhanced_data['jobFinishedTime'] = await self.convert_to_clock_time(job_finish_days_hours_and_minutes, 24)
            else:
                enhanced_data['jobFinishedTime'] = await self.convert_to_clock_time(job_finish_days_hours_and_minutes, 12)

            next_rest_stop_time_array = await self.convert_minutes_to_days_hours_minutes(data['restStop']) 
            enhanced_data['nextRestStopTime'] = await self.processTimeDifferenceArray(next_rest_stop_time_array)

            route_time_in_days_hours_minutes = await self.convert_seconds_to_days_hours_minutes(data['routeTime'])
            enhanced_data['routeTime'] = await self.processTimeDifferenceArray(route_time_in_days_hours_minutes)
            route_expiration = await self.convert_minutes_to_days_hours_minutes(data['time_abs_delivery'] - data['time_abs'])
            enhanced_data['jobExpirationTimeInDaysHoursMinutes'] = await self.processTimeDifferenceArray(route_expiration)
            enhanced_data['isWorldOfTrucksContract'] = await self.isWorldOfTrucksContract(data)

            if enhanced_data['isWorldOfTrucksContract']:
                job_ended_time = await self.getDaysHoursMinutesAndSeconds(data['jobFinishedTime'])
                job_started_time = await self.getDaysHoursMinutesAndSeconds(data['jobStartingTime'])
                time_to_complete_route_array = await self.convert_minutes_to_days_hours_minutes(data['jobFinishedTime'] - data['jobStartingTime'])
                real_life_time_to_complete_route = await self.convert_minutes_to_days_hours_minutes(data['jobDeliveredDeliveryTime'])
                enhanced_data['realLifeTimeToCompleteWorldofTrucksJob'] = await self.processTimeDifferenceArray(real_life_time_to_complete_route)
            else:
                time_to_complete_route_array = await self.convert_minutes_to_days_hours_minutes(data['jobDeliveredDeliveryTime'])
            enhanced_data['gameTimeLapsedToCompleteJob'] = await self.processTimeDifferenceArray(time_to_complete_route_array)

            # Convert weights
            tons = (data['cargoMass'] / 1000.0)
            enhanced_data['cargoMassInTons'] = str(tons) + ' t' if data['trailer'][0]['attached'] else ''
            if self.use_metric_system:
                enhanced_data['cargoMass'] = str(round(data['cargoMass'])) + ' kg' if data['trailer'][0]['attached'] else ''
            else:
                enhanced_data['cargoMass'] = str(round(data['cargoMass'] * 2.20462)) + ' lb' if data['trailer'][0]['attached'] else ''

            # Convert distances
            route_distance_km = data['routeDistance'] / 1000
            route_distance_miles = route_distance_km * 0.621371

            if self.use_metric_system:
                enhanced_data['routeDistance'] = str(math.floor(route_distance_km)) + ' kilometers'
                enhanced_data['truckOdometer'] = str(round(data['truckOdometer'])) + ' kilometers'
                enhanced_data['truckFuelRange'] = str(round(data['fuelRange'])) + ' kilometers'
                enhanced_data['plannedDistance'] = str(round(data['plannedDistanceKm'])) + ' kilometers'
                enhanced_data['jobDeliveredDistance'] = str(round(data['jobDeliveredDistanceKm'])) + ' kilometers'
            else:
                enhanced_data['routeDistance'] = str(math.floor(route_distance_miles)) + ' miles'
                enhanced_data['truckOdometer'] = str(round(data['truckOdometer'] * 0.621371)) + ' miles'
                enhanced_data['truckFuelRange'] = str(round(data['fuelRange'] * 0.621371)) + ' miles'
                enhanced_data['plannedDistance'] = str(round(data['plannedDistanceKm'] * 0.621371)) + ' miles'
                enhanced_data['jobDeliveredDistance'] = str(round(data['jobDeliveredDistanceKm'] * 0.621371)) + ' miles'

            # Add currency symbol to income, fines, payments
            enhanced_data['jobIncome'] = await self.getCurrency(data['jobIncome'])
            enhanced_data['fineAmount'] = await self.getCurrency(data['fineAmount'])
            enhanced_data['tollgatePayAmount'] = await self.getCurrency(data['tollgatePayAmount'])
            enhanced_data['ferryPayAmount'] = await self.getCurrency(data['ferryPayAmount'])
            enhanced_data['trainPayAmount'] = await self.getCurrency(data['trainPayAmount'])
            enhanced_data['jobDeliveredRevenue'] = await self.getCurrency(data['jobDeliveredRevenue'])
            enhanced_data['jobCancelledPenalty'] = await self.getCurrency(data['jobCancelledPenalty'])


            # Convert temperatures
            if self.use_metric_system:
                enhanced_data['brakeTemperature'] = str(round(data['brakeTemperature'])) + ' degrees Celsius'
                enhanced_data['oilTemperature'] = str(round(data['oilTemperature'])) + ' degrees Celsius'
                enhanced_data['waterTemperature'] = str(round(data['waterTemperature'])) + ' degrees Celsius'
            else:
                enhanced_data['brakeTemperature'] = str(round(data['brakeTemperature'] * 1.8 + 32)) + ' degrees Fahrenheit'
                enhanced_data['oilTemperature'] = str(round(data['oilTemperature'] * 1.8 + 32)) + ' degrees Fahrenheit'
                enhanced_data['waterTemperature'] = str(round(data['waterTemperature'] * 1.8 + 32)) + ' degrees Fahrenheit'
            
            # Convert volumes
            if self.use_metric_system:
                enhanced_data['fuelTankSize'] = 'Fuel tank can hold ' + str(round(data['fuelCapacity'])) + ' liters'
                enhanced_data['fuelRemaining'] = str(round(data['fuel'])) + ' liters of fuel remaining'
                enhanced_data['fuelConsumption'] = str(data['fuelAvgConsumption']) + ' liters per kilometer'
                enhanced_data['adblueTankSize'] = 'Adblue tank can hold ' + str(round(data['adblueCapacity'])) + ' liters'
                enhanced_data['adblueRemaining'] = str(round(data['adblue'])) + ' liters of adblue remaining'
                enhanced_data['refuelAmount'] = str(round(data['refuelAmount'])) + ' liters'
            else:
                enhanced_data['fuelTankSize'] = 'Fuel tank can hold ' + str(round(data['fuelCapacity'] * 0.26417205)) + ' gallons'
                enhanced_data['fuelRemaining'] = str(round(data['fuel'] * 0.26417205)) + ' gallons of fuel remaining'
                enhanced_data['fuelConsumption'] = str(round(data['fuelAvgConsumption'] * 2.35214583)) + ' miles per gallon'
                enhanced_data['adblueTankSize'] = 'Adblue tank can hold ' + str(round(data['adblueCapacity'] * 0.26417205)) + ' gallons'
                enhanced_data['adblueRemaining'] = str(round(data['adblue'] * 0.26417205)) + ' gallons of adblue remaining'
                enhanced_data['refuelAmount'] = str(round(data['refuelAmount'] * 0.26417205)) + ' gallons'
            
            return enhanced_data

        except Exception as e:
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f'There was a problem with the filter_data function: {e}. Returning original data.',
                    color=LogType.INFO,
                )
            return data

    # Convert an array of days, hours, minutes into clock time
    async def convert_to_clock_time(self, timeArray, clockHours):
        days = math.floor(timeArray[0])
        hours = math.floor(timeArray[1])
        minutes = math.floor(timeArray[2])
        if len(timeArray) > 3:
            seconds = math.floor(timeArray[3])
        else:
            seconds = 0

        date = days % 7  # Get the remainder after dividing by 7
        days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day = days_of_week[date]

        if clockHours == 12:
            period = "AM"
            if hours >= 12:
                period = "PM"
                if hours > 12:
                    hours -= 12
            elif hours == 0:
                hours = 12  # Midnight case

            return f"{day}, {hours:02}:{minutes:02} {period}"
        elif clockHours == 24:
            return f"{day}, {hours:02}:{minutes:02}"

    # Can be used for values that are in seconds like routeTime
    async def convert_seconds_to_days_hours_minutes(self, seconds):
        # Constants
        seconds_per_day = 86400
        seconds_per_hour = 3600
        seconds_per_minute = 60

        # Calculate the number of in-game days
        days = seconds // seconds_per_day

        # Calculate the remaining seconds in the current in-game day
        remaining_seconds = seconds % seconds_per_day

        # Calculate the current in-game hours
        hours = remaining_seconds // seconds_per_hour
        remaining_seconds %= seconds_per_hour

        # Calculate the current in-game minutes
        minutes = remaining_seconds // seconds_per_minute

        # Calculate the remaining seconds
        seconds = remaining_seconds % seconds_per_minute

        return [days, hours, minutes, seconds]

    # Can be used for values like time_abs that are in game minutes since beginning of game mode
    async def convert_minutes_to_days_hours_minutes(self, minutes):
        # Constants
        minutes_per_day = 1440

        # Calculate the number of in-game days
        days = minutes // minutes_per_day

        # Calculate the remaining minutes in the current in-game day
        remaining_minutes = minutes % minutes_per_day

        # Calculate the current in-game hours and minutes
        hours = remaining_minutes // 60
        final_minutes = remaining_minutes % 60

        return [days, hours, final_minutes]

    # Can be used for timestamps like time, simulatedTime, renderTime, should be converted to clock times
    async def getDaysHoursMinutesAndSeconds(self, time):
        dateTime = datetime.utcfromtimestamp(time)
        return [dateTime.day, dateTime.hour, dateTime.minute, dateTime.second]

    async def addTime(self, time, days, hours, minutes, seconds):
        dateTime = datetime.utcfromtimestamp(time)
        return dateTime + timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)

    async def getTime(self, gameTime, timeUnits):
        currentTime = datetime.utcfromtimestamp(gameTime)
        formattedTime = currentTime.strftime('%a %I:%M %p' if timeUnits == 12 else '%a %H:%M')
        return formattedTime

    async def getDamagePercentage(self, data):
        return max(data['wearEngine'],
                   data['wearTransmission'],
                   data['wearCabin'],
                   data['wearChassis'],
                   data['wearWheels']) * 100
                   
    async def getDamagePercentageTrailer(self, data):
        return max(data['trailer'][0]['wearChassis'], data['trailer'][0]['wearWheels'], data['trailer'][0]['wearBody']) * 100

    async def processTimeDifferenceArray(self, timeArray): # To do, account for when calculation means person is late, like when its negative
        final_time_string = ""
        days = math.floor(timeArray[0])
        hours = math.floor(timeArray[1])
        minutes = math.floor(timeArray[2])
        if len(timeArray) > 3:
            seconds = math.floor(timeArray[3])
        else:
            seconds = 0

        if days == 1:
            final_time_string += f"{days} day "
        elif days > 1:
            final_time_string += f"{days} days "

        if hours == 1:
            final_time_string += f"{hours} hour "
        elif hours > 1:
            final_time_string += f"{hours} hours "

        if minutes == 1:
            final_time_string += f"{minutes} minute "
        elif minutes > 1:
            final_time_string += f"{minutes} minutes "

        if seconds == 1:
            final_time_string += f"{seconds} second "
        elif seconds > 1:
            final_time_string += f"{seconds} seconds "
        
        return final_time_string

    async def isWorldOfTrucksContract(self, data):
        return "external" in data['jobMarket'] # If external in job type means world of trucks contract

    async def getCurrency(self, money):
        currencyCode = 'EUR' if self.use_metric_system else 'USD'

        if currencyCode == 'EUR':
            return f"€{money}"
        elif currencyCode == 'USD':
            return f"${money}"


######## CODE TO CONVERT GAME COORDINATES TO REAL LIFE LAT / LONG #####
# Adapted and modified from https://github.com/truckermudgeon/maps/blob/main/packages/libs/map/projections.ts and https://github.com/truckermudgeon/maps/blob/main/packages/apis/navigation/index.ts 
# Should be passed coordinateX as X and coordinateZ as Y for use


    async def from_ats_coords_to_wgs84(self, x, y):
        # ATS coords are like LCC coords, except Y grows southward (its sign is reversed)
        lcc_coords = (x, -y)
        lon, lat = self.ats_proj(*lcc_coords, inverse=True)
        return lon, lat

    async def from_ets2_coords_to_wgs84(self, x, y):
        # Calais coordinates for UK detection
        calais = (-31140, -5505)
        is_uk = x < calais[0] and y < calais[1] - 100
        converter = self.uk_proj if is_uk else self.ets2_proj

        # Apply map offsets
        x -= 16660
        y -= 4150

        # Additional offsets for UK coordinates
        if is_uk:
            x -= 16650
            y -= 2700

        # ETS2 coords are like LCC coords, except Y grows southward (its sign is reversed)
        lcc_coords = (x, -y)
        lon, lat = converter(*lcc_coords, inverse=True)
        return lon, lat


    async def convert_lat_long_data_into_place_data(self, latitude=None, longitude=None):

        # If no values still, for instance, when connection is made but no data yet, return None
        if not latitude or not longitude:
            return None

        # Set zoom level, see zoom documentation at https://nominatim.org/release-docs/develop/api/Reverse/
        zoom = 15


        if self.settings.debug_mode:
            await self.printr.print_async(
                f"Attempting query of OpenStreetMap Nominatum with parameters: {latitude}, {longitude}, zoom level: {zoom}",
                color=LogType.INFO,
            )

        # Request data from openstreetmap nominatum api for reverse geocoding
        url = f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={latitude}&lon={longitude}&zoom={zoom}&accept-language=en&extratags=1"
        headers = {
            'User-Agent': f'ats_telemetry_skill {self.wingman.name}'
        }
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            if self.settings.debug_mode:
                await self.printr.print_async(f"API request failed to {url}, status code: {response.status_code}.", color=LogType.INFO)
            return None