from typing import TYPE_CHECKING
#from api.enums import LogSource, LogType
from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from skills.skill_base import Skill
from services.printr import Printr

if TYPE_CHECKING:
    from wingmen.wingman import Wingman

printr = Printr()


class XPlane(Skill):

    def __init__(
        self,
        config: SkillConfig,
        wingman_config: WingmanConfig,
        settings: SettingsConfig,
        wingman: "Wingman",
    ) -> None:
        super().__init__(
            config=config,
            wingman_config=wingman_config,
            settings=settings,
            wingman=wingman,
        )

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        return errors

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "read_aircraft_and_environment_data",
                {
                    "type": "function",
                    "function": {
                        "name": "read_aircraft_and_environment_data",
                        "description": "Reads the aircraft and environment data from the simulator.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "variable": {
                                    "type": "string",
                                    "description": "The variable to read from the simulator.",
                                    "enum": [
                                        "PLANE_ALTITUDE",
                                        "AIRSPEED_TRUE",
                                    ],
                                },
                            },
                            "required": ["variable"],
                        },
                    },
                },
            ),
            (
                "set_aircraft_and_environment_data",
                {
                    "type": "function",
                    "function": {
                        "name": "set_aircraft_and_environment_data",
                        "description": "Sets the aircraft and environment data from the simulator.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "variable": {
                                    "type": "string",
                                    "description": "The variable to set in the simulator.",
                                    "enum": [
                                        "PLANE_ALTITUDE",
                                        "AIRSPEED_TRUE",
                                    ],
                                },
                                "value": {
                                    "type": "integer",
                                    "description": "The value to set in the simulator.",
                                },
                            },
                            "required": ["variable"],
                        },
                    },
                },
            ),
        ]
        return tools

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        function_response = ""
        instant_response = ""

        if tool_name == "read_aircraft_and_environment_data":
            function_response = await self._read_aircraft_and_environment_data(**parameters)
        if tool_name == "set_aircraft_and_environment_data":
            function_response = await self._set_aircraft_and_environment_data(**parameters)

        return function_response, instant_response

    async def is_summarize_needed(self, tool_name: str) -> bool:
        """Returns whether a tool needs to be summarized."""
        return True

    async def is_waiting_response_needed(self, tool_name: str) -> bool:
        """Returns whether a tool probably takes long and a message should be printet in between."""
        return True

    async def _read_aircraft_and_environment_data(self, variable: str) -> str:
        pass

    async def _set_aircraft_and_environment_data(self, variable: str, value: int) -> str:
        pass
