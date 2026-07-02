import inspect
from typing import TYPE_CHECKING
from skills.uexcorp.uexcorp.tool.vehicle_information import VehicleInformation
from skills.uexcorp.uexcorp.tool.commodity_route import CommodityRoute
from skills.uexcorp.uexcorp.tool.commodity_information import CommodityInformation
from skills.uexcorp.uexcorp.tool.location_information import LocationInformation
from skills.uexcorp.uexcorp.tool.item_information import ItemInformation
from skills.uexcorp.uexcorp.tool.profit_calculation import ProfitCalculation

if TYPE_CHECKING:
    from skills.uexcorp.uexcorp.helper import Helper


class ToolHandler:

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
            ProfitCalculation.TOOL_NAME: ProfitCalculation,
        }
        self.__notes = []

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        function_response = ""
        instant_response = ""

        try:
            if tool_name in self.__functions:
                self.__helper.get_handler_debug().write(
                    f"LLM called for '{tool_name}' with parameters: {parameters}"
                )

                if self.__helper.get_handler_import().get_imported_percent() not in [100, 0]:
                    await self.__helper.get_handler_debug().write_async(
                        f"UEX skill is currently loading: Import is at {self.__helper.get_handler_import().get_imported_percent()}%. Giving it 5 more seconds ..", True
                    )
                    self.__helper.wait(5)
                    if self.__helper.get_handler_import().get_imported_percent() not in [100, 0]:
                        await self.__helper.get_handler_debug().write_async(
                            f"UEX skill is still loading after 5s: Import is at {self.__helper.get_handler_import().get_imported_percent()}%. Deciding to retry later.",
                            True
                        )
                        function_response = (
                            f"UEX data is still loading ({self.__helper.get_handler_import().get_imported_percent()}%). Ask the user to retry in a moment."
                        )
                        self.__helper.set_request_while_not_loaded(True)
                        return function_response, instant_response
                    else:
                        self.__helper.set_request_while_not_loaded(False)

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
                        validated_value = await optional_fields[key].validate(value)

                    if validated_value is None or validated_value == (None, None):
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
                    function_response, instant_response = tool.execute(**valid_parameters)

                function_response_pretty = function_response
                try:
                    import json
                    function_response_pretty = json.dumps(json.loads(function_response), indent=4)
                except Exception:
                    pass

                notes = self.get_notes(clear=True)
                if notes:
                    notes = '\n-'.join(dict.fromkeys(notes))
                    function_response = str(function_response) + f"\n\nRelay to user:\n-{notes}"
                    function_response_pretty = str(function_response_pretty) + f"\n\nRelay to user:\n-{notes}"

                self.__helper.get_handler_debug().write(
                    f"Execution of '{tool_name}' took {self.__helper.end_timer(tool_name)} ms."
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
        prompt += "Note on uex function responses: omitted fields mean \"unknown / not available\", not zero. Prices and profits are in aUEC, margins and inventory statuses in percent. A response may start with a \"keys\" object mapping shortened keys to full field names for the \"data\" part.\n"
        prompt += "Trade direction - every buy/sell field is from the PLAYER's perspective: buy_* = the player buys FROM the terminal, sell_* = the player sells TO the terminal. In answers, never present the terminal as the actor (no 'terminal X buys/sells') - phrase it as 'you can buy <commodity> at <terminal> for <buy price>' / 'you can sell <commodity> at <terminal> for <sell price>'. Buy options report the terminal's stock (more stock = better to buy), sell options report the terminal's demand (more demand = better to sell); relay these statuses as given.\n"
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
