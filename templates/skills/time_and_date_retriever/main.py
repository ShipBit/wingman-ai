import datetime
from typing import TYPE_CHECKING
from api.interface import SettingsConfig, SkillConfig
from api.enums import LogType
from services.benchmark import Benchmark
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
                        "parameters": {},
                    },
                },
            )
        ]

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any], benchmark: Benchmark
    ) -> tuple[str, str]:
        function_response = ""
        instant_response = ""

        if tool_name == "get_current_time_and_date":
            benchmark.start_snapshot(f"DateTime Retriever: {tool_name}")

            if self.settings.debug_mode:
                message = f"DateTime Retriever: executing tool '{tool_name}'"
                if parameters:
                    message += f" with params: {parameters}"
                await self.printr.print_async(text=message, color=LogType.INFO)

            now = datetime.datetime.now()
            function_response = now.strftime("%Y-%m-%d %H:%M:%S")

            benchmark.finish_snapshot()

        return function_response, instant_response
