from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from api.enums import LogType
from skills.skill_base import Skill


class VisionAI(Skill):

    def __init__(
        self,
        config: SkillConfig,
        wingman_config: WingmanConfig,
        settings: SettingsConfig,
    ) -> None:
        super().__init__(
            config=config, wingman_config=wingman_config, settings=settings
        )

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        return errors

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "analyse_what_user_sees",
                {
                    "type": "function",
                    "function": {
                        "name": "analyse_what_user_sees",
                        "description": "Analyse what the user sees and answer questions about it.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                            },
                            "required": [],
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

        if tool_name == "analyse_what_user_sees":
            pass

        return function_response, instant_response
