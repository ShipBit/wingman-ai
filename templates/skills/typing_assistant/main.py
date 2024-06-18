import time
from typing import TYPE_CHECKING
from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from api.enums import LogType
from skills.skill_base import Skill
import keyboard.keyboard as keyboard

if TYPE_CHECKING:
    from wingmen.wingman import Wingman


class TypingAssistant(Skill):

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
                "assist_with_typing",
                {
                    "type": "function",
                    "function": {
                        "name": "assist_with_typing",
                        "description": "Identifies what the user wants the AI to type into an active application window.  This may be either transcribing exactly what the user says or typing something the user wants the AI to imagine and then type. Also identifies whether to end the typed content with a press of the Enter / Return key, common typically for typing a response to a chat message or form field.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "content_to_type": {
                                    "type": "string",
                                    "description": "The content the user wants the assistant to type.",
                                },
                                "end_by_pressing_enter": {
                                    "type": "boolean",
                                    "description": "Boolean True/False indicator of whether the typed content should end by pressing the enter key on the keyboard. Default False. Typically True when typing a response in a chat program.",
                                },
                            },
                            "required": ["content_to_type"],
                        },
                    },
                },
            ),
        ]
        return tools

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        function_response = "Error in typing. Can you please try your command again?"
        instant_response = ""

        if tool_name == "assist_with_typing":
            if self.settings.debug_mode:
                self.start_execution_benchmark()
                await self.printr.print_async(
                    f"Executing assist_with_typing function with parameters: {parameters}",
                    color=LogType.INFO,
                )

            content_to_type = parameters.get("content_to_type")
            press_enter = parameters.get("end_by_pressing_enter")

            keyboard.write(content_to_type)

            if press_enter is True:
                keyboard.press("enter")
                time.sleep(0.2)
                keyboard.release("enter")

            function_response = "Typed user request at active mouse cursor position."

            if self.settings.debug_mode:
                await self.print_execution_time()

        return function_response, instant_response
