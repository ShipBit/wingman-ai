import asyncio
import inspect
import time
from typing import TYPE_CHECKING
from skills.uexcorp.uexcorp.tool.vehicle_information import VehicleInformation
from skills.uexcorp.uexcorp.tool.commodity_route import CommodityRoute
from skills.uexcorp.uexcorp.tool.active_trade_route import ActiveTradeRoute
from skills.uexcorp.uexcorp.tool.commodity_information import CommodityInformation
from skills.uexcorp.uexcorp.tool.location_information import LocationInformation
from skills.uexcorp.uexcorp.tool.item_information import ItemInformation
from skills.uexcorp.uexcorp.tool.profit_calculation import ProfitCalculation

if TYPE_CHECKING:
    from skills.uexcorp.uexcorp.helper import Helper


class ToolHandler:
    # Tools that work without UEX data (own route file, plain arithmetic)
    NO_DATA_NEEDED = (ActiveTradeRoute.TOOL_NAME, ProfitCalculation.TOOL_NAME)
    FIRST_IMPORT_WAIT = 10  # seconds
    # Prices normally refresh every ~2 hours: older ones mean the data source is unreachable
    STALE_PRICES_HOURS = 4

    @staticmethod
    def __price_age_hours() -> int | None:
        from skills.uexcorp.uexcorp.model.import_data import ImportData

        try:
            imported = ImportData("relay_short", load=True).get_date_imported()
        except Exception:
            return None
        return int((time.time() - imported) // 3600) if imported else None

    def __init__(
        self,
        helper: "Helper",
    ):
        self.__helper = helper
        self.__asked_while_not_ready = False
        self.__needs_tools_reload = False
        self.__cache_parameters = {}
        self.__functions = {
            VehicleInformation.TOOL_NAME: VehicleInformation,
            CommodityInformation.TOOL_NAME: CommodityInformation,
            LocationInformation.TOOL_NAME: LocationInformation,
            ItemInformation.TOOL_NAME: ItemInformation,
            CommodityRoute.TOOL_NAME: CommodityRoute,
            ActiveTradeRoute.TOOL_NAME: ActiveTradeRoute,
            ProfitCalculation.TOOL_NAME: ProfitCalculation,
        }
        self.__notes = []
        self.__lock = asyncio.Lock()

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        # One call at a time: notes, timers and the parameter cache are shared
        async with self.__lock:
            return await self.__execute_tool(tool_name, parameters)

    async def __execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        function_response = ""
        instant_response = ""

        try:
            if tool_name in self.__functions:
                self.__helper.get_handler_debug().write(
                    f"LLM called for '{tool_name}' with parameters: {parameters}"
                )

                # Without data every name looks unknown: say so instead of blaming the user's words.
                # A refresh never blocks: tables are swapped in one transaction.
                if tool_name not in self.NO_DATA_NEEDED:
                    importer = self.__helper.get_handler_import()
                    has_data = await asyncio.to_thread(importer.has_data)
                    waited = 0
                    # A first import (fresh install, rebuilt database) takes a few seconds
                    while not has_data and importer.is_running() and waited < self.FIRST_IMPORT_WAIT:
                        await self.__helper.wait_async(1)
                        waited += 1
                        has_data = await asyncio.to_thread(importer.has_data)
                    if not has_data:
                        self.__helper.set_request_while_not_loaded(True)
                        reason = importer.get_last_error() or "it is still being downloaded"
                        function_response = (
                            f"UEX data is not available right now ({reason}). It is retried in the background every minute. "
                            "Tell the user that trade, price and location data are unavailable for now. Do not guess "
                            "them, and do not say the names the user gave are wrong."
                        )
                        self.__helper.get_handler_debug().write(function_response)
                        return function_response, instant_response

                self.__helper.start_timer(tool_name)
                tool = self.__functions[tool_name]()
                mandatory_fields = tool.get_mandatory_fields()
                optional_fields = tool.get_optional_fields()

                valid_parameters = {}
                invalid_parameters = {}
                for key, value in parameters.items():
                    if key not in mandatory_fields and key not in optional_fields:
                        invalid_parameters[key] = f"unknown parameter '{key}'"
                        continue

                    if key in mandatory_fields:
                        validated_value = await mandatory_fields[key].validate(value)
                    else:
                        # LLMs often send null or [] for optional parameters they don't want to use
                        if value is None or value == []:
                            continue
                        validated_value = await optional_fields[key].validate(value)

                    if validated_value is None:
                        invalid_parameters[key] = f"'{key}': value '{value}' not recognized, see notes"
                    else:
                        valid_parameters[key] = validated_value

                missing_parameters = []
                for key, value in mandatory_fields.items():
                    if key not in parameters:
                        missing_parameters.append(key)

                if invalid_parameters or missing_parameters:
                    function_response = f"Parameter errors for '{tool_name}':"
                    for key, value in invalid_parameters.items():
                        function_response += f"\n- {value}"
                    for key in missing_parameters:
                        function_response += f"\n- '{key}' is mandatory, but missing"

                    notes = self.get_notes(clear=True)
                    if notes:
                        function_response += "\n\nNotes:\n-" + '\n-'.join(dict.fromkeys(notes))

                    self.__helper.get_handler_debug().write(function_response)
                    return function_response, instant_response

                self.__helper.get_handler_debug().write(
                    f"Executing '{tool_name}' with validated parameters: {valid_parameters}"
                )

                if inspect.iscoroutinefunction(tool.execute):
                    function_response, instant_response = await tool.execute(**valid_parameters)
                else:
                    # Off Core's event loop: a route search can take seconds (audio and mic run on the loop)
                    function_response, instant_response = await asyncio.to_thread(tool.execute, **valid_parameters)

                function_response_pretty = function_response
                try:
                    import json
                    function_response_pretty = json.dumps(json.loads(function_response), indent=4)
                except Exception:
                    pass

                # Old prices alone may only mean Core was off: the refresh after a start is running
                if tool_name not in self.NO_DATA_NEEDED and self.__helper.get_handler_import().get_last_error():
                    age = await asyncio.to_thread(self.__price_age_hours)
                    if age is not None and age >= self.STALE_PRICES_HOURS:
                        self.add_note(
                            f"Prices are about {age} hours old: the UEX data source can't be reached right now. "
                            "Say so when giving prices."
                        )

                notes = self.get_notes(clear=True)
                if notes:
                    notes = '\n-'.join(dict.fromkeys(notes))
                    function_response = str(function_response) + f"\n\nRelay to user:\n-{notes}"
                    function_response_pretty = str(function_response_pretty) + f"\n\nRelay to user:\n-{notes}"

                self.__helper.get_handler_debug().write(
                    f"Execution of '{tool_name}' took {self.__helper.end_timer(tool_name)} s."
                )
                self.__helper.get_handler_debug().write(
                    f"Response of '{tool_name}': {function_response_pretty}"
                )
                self.__helper.get_handler_debug().write(
                    f"Instant response of '{tool_name}': {instant_response if instant_response else 'None'}"
                )

        except Exception as e:
            await self.__helper.get_handler_debug().write_async(
                f"Execution of '{tool_name}' resulted in an error: {str(e)}. Feel free to report this to JayMatthew on the ShipBit Discord server.",
                True,
            )
            self.__helper.get_handler_error().write(f"tool: {tool_name}", parameters, e)
            function_response = f"Error while executing function '{tool_name}' with parameters: {parameters}."

        return str(function_response), str(instant_response)

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = []

        for tool_name, tool in self.__functions.items():
            if self.__helper.get_handler_config().is_tool_enabled(tool_name):
                tool = tool()
                tools.append((
                    tool_name,
                    {
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "description": tool.get_description(),
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    **{
                                        key: validator.get_llm_definition()
                                        for key, validator in {**tool.get_mandatory_fields(), **tool.get_optional_fields()}.items()
                                    }
                                },
                                "required": list(tool.get_mandatory_fields().keys()),
                            },
                        },
                    }
                ))
        return tools

    def get_tool_help_prompt(self) -> str:
        tool_prompts = []
        for tool_name, tool in self.__functions.items():
            tool = tool()
            if self.__helper.get_handler_config().is_tool_enabled(tool_name):
                tool_prompts.append(f"- {tool.TOOL_NAME}: {tool.get_prompt()}")
            else:
                # No full prompt for disabled tools - it would cost tokens on
                # every request for a function the LLM must not use anyway.
                tool_prompts.append(f"- {tool.TOOL_NAME}: DISABLED BY USER")

        if not tool_prompts:
            return ""

        prompt = "=== UEX functions ===\n"
        prompt += "Note on uex function responses: omitted fields mean \"unknown / not available\", not zero. Prices and profits are in aUEC, margins, returns on investment and inventory statuses in percent. A response may start with a \"keys\" object mapping shortened keys to full field names for the \"data\" part.\n"
        prompt += "Trade direction - every buy/sell field is from the PLAYER's perspective: buy_* = the player buys FROM the terminal, sell_* = the player sells TO the terminal. In answers, never present the terminal as the actor (no 'terminal X buys/sells') - phrase it as 'you can buy <commodity> at <terminal> for <buy price>' / 'you can sell <commodity> at <terminal> for <sell price>'. Buy options report the terminal's stock (more stock = better to buy), sell options report the terminal's demand (more demand = better to sell); relay these statuses as given.\n"
        prompt += "Locations: every jump point has a gateway station in both star systems, so always name a gateway with the system it is in, e.g. 'Nyx Gateway (Stanton)' is in Stanton and leads to Nyx. If that system is unknown, ask the user. Never assume which star system a place is in: the 'location' fields in results say it.\n"
        prompt += "\n".join(tool_prompts)
        prompt += "\n=== End of UEX functions ==="
        return prompt

    def get_notes(self, clear: bool = False) -> list[str]:
        notes = self.__notes
        if clear:
            self.__notes = []
        return notes

    def add_note(self, note: str):
        self.__notes.append(note)
