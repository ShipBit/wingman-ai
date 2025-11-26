from os import path
import datetime
import requests
from typing import TYPE_CHECKING
from api.enums import LogSource, LogType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill, tool
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

    @tool(
        name="generate_image",
        description="""Generates an image using DALL-E 3 based on a text description.

        WHEN TO USE:
        - User requests image creation: 'Generate an image of...', 'Create a picture of...'
        - User wants visual content created from a description
        - Any request for AI-generated artwork or illustrations

        Produces high-quality, detailed images matching user specifications.""",
        wait_response=True,
    )
    async def generate_image(self, prompt: str) -> str:
        """
        Args:
            prompt: The image generation prompt describing what to create.
        """
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

        function_response = "Unable to generate an image. Please try another provider."

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

        return function_response
