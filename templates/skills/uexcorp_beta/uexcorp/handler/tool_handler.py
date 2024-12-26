import inspect
import traceback
from typing import TYPE_CHECKING
try:
    from skills.uexcorp_beta.uexcorp.tool.vehicle_information import VehicleInformation
    from skills.uexcorp_beta.uexcorp.tool.commodity_route import CommodityRoute
    from skills.uexcorp_beta.uexcorp.tool.commodity_information import CommodityInformation
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.tool.vehicle_information import VehicleInformation
    from uexcorp_beta.uexcorp.tool.commodity_route import CommodityRoute
    from uexcorp_beta.uexcorp.tool.commodity_information import CommodityInformation

if TYPE_CHECKING:
    try:
        from uexcorp_beta.uexcorp.helper import Helper
    except ModuleNotFoundError:
        from skills.uexcorp_beta.uexcorp.helper import Helper


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
            "uex_get_vehicle_information": VehicleInformation,
            "uex_get_trade_routes": CommodityRoute,
            "uex_get_commodity_information": CommodityInformation
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

                if not self.__helper.is_ready():
                    await self.__helper.get_handler_debug().write_async(
                        f"UEX skill is currently loading: Import is at {self.__helper.get_handler_import().get_imported_percent()}%. Please wait a moment.", True
                    )
                    function_response = (
                        f"UEX skill is currently loading: Import is at {self.__helper.get_handler_import().get_imported_percent()}%. Please wait a moment and try again."
                    )
                    self.__helper.set_request_while_not_loaded(True)
                    return function_response, instant_response

                self.__helper.start_timer(tool_name)
                tool = self.__functions[tool_name]()
                mandatory_fields = tool.get_mandatory_fields()
                optional_fields = tool.get_optional_fields()

                valid_parameters = {}
                invalid_parameters = {}
                for key, value in parameters.items():
                    if key not in mandatory_fields and key not in optional_fields:
                        invalid_parameters[key] = f"a parameter '{key}' is not valid for this function."
                        continue

                    if key in mandatory_fields:
                        validated_value = await mandatory_fields[key].validate(value)
                    else:
                        validated_value = await optional_fields[key].validate(value)

                    if validated_value is None:
                        invalid_parameters[key] = f"value '{value}' of parameter '{key}' could not be mapped to a known value."
                    else:
                        valid_parameters[key] = validated_value

                missing_parameters = []
                for key, value in mandatory_fields.items():
                    if key not in parameters:
                        missing_parameters.append(key)

                if invalid_parameters or missing_parameters:
                    function_response = f"The following errors occurred while validating the parameters for '{tool_name}':"
                    for key, value in invalid_parameters.items():
                        function_response += f"\n- {value}"
                    for key in missing_parameters:
                        function_response += f"\n- parameter '{key}' is mandatory, but missing."

                    self.__helper.get_handler_debug().write(function_response)
                    return function_response, instant_response

                self.__helper.get_handler_debug().write(
                    f"Executing '{tool_name}' with validated parameters: {valid_parameters}"
                )

                if inspect.iscoroutinefunction(tool.execute):
                    function_response, instant_response = await tool.execute(**valid_parameters)
                else:
                    function_response, instant_response = tool.execute(**valid_parameters)

                notes = self.get_notes(clear=True)
                if notes:
                    notes = '\n-'.join(notes)
                    function_response += f"\n\nImportant information for user:\n-{notes}"

                self.__helper.get_handler_debug().write(
                    f"Execution of '{tool_name}' took {self.__helper.end_timer(tool_name)} ms."
                )
                self.__helper.get_handler_debug().write(
                    f"Response of '{tool_name}': {function_response}"
                )
                self.__helper.get_handler_debug().write(
                    f"Instant response of '{tool_name}': {instant_response if instant_response else 'None'}"
                )

        except Exception as e:
            await self.__helper.get_handler_debug().write_async(
                f"Execution of '{tool_name}' resulted in an error: {str(e)}. Feel free to report this to JayMatthew on the ShipBit Discord server.",
                True,
            )
            self.__helper.get_handler_error().write(f"tool: {tool_name}", parameters, e, traceback.format_exc())
            function_response = f"Error while executing function '{tool_name}' with parameters: {parameters}."

        return str(function_response), str(instant_response)

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = []

        for tool_name, tool in self.__functions.items():
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
                            "optional": list(tool.get_optional_fields().keys()),
                        },
                    },
                }
            ))
        return tools

    def get_notes(self, clear: bool = False) -> list[str]:
        notes = self.__notes
        if clear:
            self.__notes = []
        return notes

    def add_note(self, note: str):
        self.__notes.append(note)
