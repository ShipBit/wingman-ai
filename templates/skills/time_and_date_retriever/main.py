import datetime
from typing import TYPE_CHECKING
from api.interface import SettingsConfig, SkillConfig
from api.enums import LogType
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class TimeAndDateRetriever(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config, settings, wingman)

    def get_tools(self) -> list[tuple[str, dict]]:
        return [
            (
                "get_current_time_and_date",
                {
                    "type": "function",
                    "function": {
                        "name": "get_current_time_and_date",
                        "description": "Retrieves the current date and time for the user.",
                        "parameters": {}
                    }
                }
            )
        ]

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        function_response = ""
        instant_response = ""
        
        if tool_name == "get_current_time_and_date":
            if self.settings.debug_mode:
                self.start_execution_benchmark()
                await self.printr.print_async(
                    f"Executing get_current_time_and_date function.",
                    color=LogType.INFO,
                )

            now = datetime.datetime.now()
            function_response = now.strftime("%Y-%m-%d %H:%M:%S")

            if self.settings.debug_mode:
                await self.print_execution_time()

        return function_response, instant_response