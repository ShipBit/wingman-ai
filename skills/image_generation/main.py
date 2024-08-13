from typing import TYPE_CHECKING
from api.enums import LogSource, LogType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class ImageGeneration(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        return errors

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        instant_response = ""
        function_response = "I can't generate an image, sorry. Try another provider."

        if tool_name == "generate_image":
            prompt = parameters["prompt"]
            if self.settings.debug_mode:
                await self.printr.print_async(f"Generate image with prompt: {prompt}.", color=LogType.INFO)
            image = await self.wingman.generate_image(prompt)
            await self.printr.print_async(
                        "",
                        color=LogType.INFO,
                        source=LogSource.WINGMAN,
                        source_name=self.wingman.name,
                        skill_name=self.name,
                        additional_data={"image_url": image},
                    )
            function_response = "Here is an image based on your prompt."
        return function_response, instant_response

    async def is_waiting_response_needed(self, tool_name: str) -> bool:
        return True

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "generate_image",
                {
                    "type": "function",
                    "function": {
                        "name": "generate_image",
                        "description": "Generate an image based on the users prompt.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "prompt": {"type": "string"},
                            },
                            "required": ["prompt"],
                        },
                    },
                },
            ),
        ]

        return tools
