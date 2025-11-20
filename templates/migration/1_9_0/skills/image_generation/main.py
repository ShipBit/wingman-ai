from os import path
import datetime
import requests
from typing import TYPE_CHECKING
from api.enums import LogSource, LogType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from services.benchmark import Benchmark
from skills.skill_base import Skill
from services.file import get_writable_dir

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
        self.image_path = get_writable_dir(
            path.join("skills", "image_generation", "generated_images")
        )

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        self.save_images = self.retrieve_custom_property_value("save_images", errors)

        return errors

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any], benchmark: Benchmark
    ) -> tuple[str, str]:
        instant_response = ""
        function_response = "Unable to generate an image. Please try another provider."

        if tool_name == "generate_image":
            benchmark.start_snapshot(f"Image Generation: {tool_name}")

            if self.settings.debug_mode:
                message = f"Image Generation: executing tool '{tool_name}'"
                if parameters:
                    message += f" with params: {parameters}"
                await self.printr.print_async(text=message, color=LogType.INFO)

            prompt = parameters["prompt"]
            await self.generate_image(prompt)

            function_response = "Here is an image based on your prompt."
            benchmark.finish_snapshot()

        return function_response, instant_response

    async def generate_image(self, prompt: str) -> str:
        if self.settings.debug_mode:
            await self.printr.print_async(
                f"Generate image with prompt: {prompt}.", color=LogType.INFO
            )

        image = await self.wingman.generate_image(prompt)
        await self.printr.print_async(
            "",
            color=LogType.INFO,
            source=LogSource.WINGMAN,
            source_name=self.wingman.name,
            skill_name=self.name,
            additional_data={"image_url": image},
        )
        if image:
            function_response = "Here is an image based on your prompt."

            if self.save_images:
                image_path = path.join(
                    self.image_path,
                    f"{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{prompt[:40]}.png",
                )
                image_response = requests.get(image)

                if image_response.status_code == 200:
                    with open(image_path, "wb") as file:
                        file.write(image_response.content)

                    function_response += (
                        f" The image has also been stored to {image_path}."
                    )
                    if self.settings.debug_mode:
                        await self.printr.print_async(
                            f"Image displayed and saved at {image_path}.",
                            color=LogType.INFO,
                        )

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
