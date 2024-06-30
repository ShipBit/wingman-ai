from typing import TYPE_CHECKING
from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from api.enums import LogType
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.wingman import Wingman


class AINPC(Skill):

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
                "change_voice_settings",
                {
                    "type": "function",
                    "function": {
                        "name": "change_voice_settings",
                        "description": "Change the voice settings. For example: Change the gender of the voice.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "gender": {
                                    "type": "string",
                                    "description": "The gender of the voice.",
                                    "enum": [
                                        "woman",
                                        "man",
                                    ],
                                },
                            },
                            "required": ["gender"],
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

        if tool_name == "change_voice_settings":
            if self.settings.debug_mode:
                self.start_execution_benchmark()
                await self.printr.print_async(
                    f"Executing change_voice_settings with parameters: {parameters}",
                    color=LogType.INFO,
                )

            gender = parameters.get("gender")

            function_response = "Settings changed."

            if self.settings.debug_mode:
                await self.print_execution_time()

        return function_response, instant_response
