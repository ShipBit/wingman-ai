import asyncio
import base64
import io
from typing import TYPE_CHECKING
from mss import mss
from PIL import Image
from api.enums import LogSource, LogType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext


class VisionAI(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "WingmanContext",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        # Validate properties exist (don't cache values)
        self.retrieve_custom_property_value("display", errors)
        self.retrieve_custom_property_value("show_screenshots", errors)
        return errors

    def _get_display(self) -> int:
        """Retrieve fresh display number at runtime."""
        errors: list[WingmanInitializationError] = []
        display = self.retrieve_custom_property_value("display", errors)
        return display if display else 1

    def _get_show_screenshots(self) -> bool:
        """Retrieve fresh show_screenshots setting at runtime."""
        errors: list[WingmanInitializationError] = []
        return self.retrieve_custom_property_value("show_screenshots", errors) or False

    @tool(
        name="analyse_what_you_or_user_sees",
        description="""Captures and analyzes the user's screen to answer questions about visual content.

        WHEN TO USE:
        - User asks 'What is on my screen?' or 'What do you see?'
        - User wants analysis of currently displayed content
        - User asks to look at something or check something out
        - User asks specific questions about visual elements, text, or objects on screen

        Immediately captures and analyzes the current screen content.
        Provides detailed descriptions of visual content including text, UI elements, and objects.""",
        wait_response=True,
    )
    async def analyse_what_you_or_user_sees(self, question: str) -> str:
        """
        Args:
            question: The question to answer about the image.
        """
        return await self.analyse_screen(question)

    async def analyse_screen(self, prompt: str, desired_image_width: int = 1000):
        function_response = ""

        # Take a screenshot (blocking work runs in a thread)
        png_base64 = await asyncio.to_thread(
            self._capture_screen_base64, self._get_display(), desired_image_width
        )

        if self._get_show_screenshots():
            await self.printr.print_async(
                "Analyzing this image",
                color=LogType.INFO,
                source=LogSource.WINGMAN,
                source_name=self.wingman.name,
                skill_name=self.name,
                additional_data={"image_base64": png_base64},
            )

        response_text = await self.wingman.ai.generate(
            prompt,
            system="You are a helpful ai assistant.",
            image=f"data:image/png;base64,{png_base64}",
        )
        function_response = response_text or ""

        return function_response

    def _capture_screen_base64(self, display: int, desired_image_width: int) -> str:
        with mss() as sct:
            try:
                display = int(display)
            except (TypeError, ValueError):
                display = 1
            if not 1 <= display < len(sct.monitors):
                display = 1
            screenshot = sct.grab(sct.monitors[display])

            # Create a PIL image from array
            image = Image.frombytes(
                "RGB", screenshot.size, screenshot.bgra, "raw", "BGRX"
            )

        aspect_ratio = image.height / image.width
        new_height = int(desired_image_width * aspect_ratio)
        resized_image = image.resize((desired_image_width, new_height))
        return self.pil_image_to_base64(resized_image)

    def pil_image_to_base64(self, pil_image):
        """
        Convert a PIL image to a base64 encoded string.

        :param pil_image: PIL Image object
        :return: Base64 encoded string of the image
        """
        # Create a bytes buffer to hold the image data
        buffer = io.BytesIO()
        # Save the PIL image to the bytes buffer in PNG format
        pil_image.save(buffer, format="PNG")
        # Get the byte data from the buffer

        # Encode the byte data to Base64
        base64_encoded_data = base64.b64encode(buffer.getvalue())
        # Convert the base64 bytes to a string
        base64_string = base64_encoded_data.decode("utf-8")

        return base64_string

    def convert_png_to_base64(self, png_data):
        """
        Convert raw PNG data to a base64 encoded string.

        :param png_data: A bytes object containing the raw PNG data
        :return: A base64 encoded string.
        """
        # Encode the PNG data to base64
        base64_encoded_data = base64.b64encode(png_data)
        # Convert the base64 bytes to a string
        base64_string = base64_encoded_data.decode("utf-8")
        return base64_string
