import os
import shutil
import truck_telemetry
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
            "onJob",
            "jobFinished",
            "jobCancelled",
            "jobDelivered",
            "jobDeliveredDeliveryTime",
            "jobStartingTime",
            "jobFinishedTime",
            "jobIncome",
            "jobCancelledPenalty",
            "jobDeliveredRevenue",
            "jobDeliveredCargoDamage",
            "jobDeliveredDistanceKm",
            "jobDeliveredAutoparkUsed",
            "jobDeliveredAutoloadUsed",
            "isCargoLoaded",
            "cargoDamage",
            "specialJob",
            "jobMarket",
            "routeDistance",
            "routeTime",
            "fined",
            "fineAmount",
            "fineOffence",
            "refuelPayed",
            "refuelAmount",
            "truckBrand",
            "truckName",
            "cargo",
            "cargoMass",
            "cityDst",
            "compDst",
            "citySrc",
            "compSrc",
            "truckLicensePlate",
            "truckLicensePlateCountry",
        ]
        self.telemetry_loop_running = False
        self.ats_install_directory = ""
        self.ets_install_directory = ""
        self.dispatcher_backstory = ""
        self.autostart_dispatch_mode = False
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
            self.telemetry_loop_cached_data = truck_telemetry.get_data()
            while self.telemetry_loop_running:
                changed_data = await self.query_and_compare_data(self.telemetry_loop_data_points)
                if changed_data:
                    keywords = {"job", "fine", "refuel", "cargo"}
                    if any(keyword in changed_data.lower() for keyword in keywords): # Hack to make sure its not just route time and distance that has changed, since those change constantly
                        await self.initiate_llm_call_with_changed_data(changed_data)
                time.sleep(loop_time)

    # Compare new telemetry data in monitored fields and react if there are changes
    async def query_and_compare_data(self, data_points: list):
        try:
            default = "The following key data changed: "
            data_changed = default
            data = truck_telemetry.get_data()
            if self.settings.debug_mode:
                await self.printr.print_async(
                    "Querying and comparing telemetry data",
                    color=LogType.INFO,
                )
            for point in data_points:
                current_data = data.get(point)
                if current_data and current_data != self.telemetry_loop_cached_data.get(point):
                    # Prevent relatively small data changes in float values from triggering new alerts, such as when cargo damage, route distance or route time change by very small values
                    if isinstance(current_data, float) and abs((current_data - self.telemetry_loop_cached_data.get(point)) / current_data) <= 0.25:
                        pass
                    else:
                        data_changed = data_changed + f"{point}:{current_data}, last value was {point}:{self.telemetry_loop_cached_data.get(point)},"
            self.telemetry_loop_cached_data = data
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
            units_phrase = "Use the metric system like meters, kilometers, kilometers per hour, and kilograms in your responses.  All currency is in euros."
        user_content = f"{self.dispatcher_backstory} {changed_data}"
        messages = [
            {
                'role': 'system',
                'content': f"""
                    You are a big rig truck dispatcher.  Act in character at all times.  
                    Important background information: route distance is provided to you in meters, times are provided in seconds, mass is provided in kilograms.
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
                self.already_initalized_telemetry = await self.initialize_telemetry()
                # If initialization of telemetry object fails because another instance is already running, try just checking getting the data as a fail safe; if still cannot get the data, trigger error
                if not self.already_initialized_telemetry:
                    try:
                        test = truck_telemetry.get_data()
                        self.already_initalized_telemetry = True
                    except:
                        function_response = "Error trying to access truck telemetry data.  It appears there is a problem with the module.  Check to see if the game is running, and that you have installed the SDK in the proper location."
                        return function_response, instant_response

            self.start_execution_benchmark()
            await self.printr.print_async(
                f"Executing get_game_state function with parameters: {parameters}",
                color=LogType.INFO,
            )

            data = truck_telemetry.get_data()
            await self.printr.print_async(
                f"Printout of all data received from telemetry: {data}",
                color=LogType.INFO,
            )
            variable = parameters.get("variable")
            if variable in data:
                value = data[variable]
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
            self.start_execution_benchmark()
            await self.printr.print_async(
                f"Executing start_or_activate_dispatch_telemetry_loop",
                color=LogType.INFO,
            )

            if not self.already_initialized_telemetry:
                self.already_initialized_telemetry = await self.initialize_telemetry()
                # If initialization of telemetry object fails because another instance is already running, try just checking getting the data as a fail safe; if still cannot get the data, trigger error
                if not self.already_initialized_telemetry:
                    try:
                        test = truck_telemetry.get_data()
                        self.already_initalized_telemetry = True
                    except:
                        function_response = "Error trying to access truck telemetry data.  It appears there is a problem with the module.  Check to see if the game is running, and that you have installed the SDK in the proper location."
                        return function_response, instant_response

            if not self.telemetry_loop_running:
                await self.initialize_telemetry_cache_loop(10)

            if self.settings.debug_mode:
                await self.print_execution_time()

            function_response = "Opened dispatch communications."

        elif tool_name == "end_or_stop_dispatch_telemetry_loop":
            self.start_execution_benchmark()
            await self.printr.print_async(
                f"Executing end_or_stop_dispatch_telemetry_loop",
                color=LogType.INFO,
            )

            await self.stop_telemetry_loop()

            if self.settings.debug_mode:
                await self.print_execution_time()

            function_response = "Closed dispatch communications."

        return function_response, instant_response

    # Function to autostart dispatch mode
    async def autostart_dispatcher_mode(self):
        telemetry_started = False
        while not telemetry_started and self.loaded == True:
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
        if self.loaded == True:
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