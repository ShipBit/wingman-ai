import asyncio
from typing import TYPE_CHECKING
from api.enums import LogSource, LogType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from services.image_generation import screenshot_base64
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

    async def analyse_screen(self, prompt: str):
        function_response = ""

        # The screen through Core: under Wayland the desktop takes the shot
        try:
            display = int(self._get_display())
        except (TypeError, ValueError):
            display = 1
        try:
            image = await self.wingman.screen.capture(max(1, display))
        except RuntimeError as e:
            return f"Could not see the screen: {e}"
        jpeg_base64 = await asyncio.to_thread(screenshot_base64, image)

        if self._get_show_screenshots():
            await self.printr.print_async(
                "Analyzing this image",
                color=LogType.INFO,
                source=LogSource.WINGMAN,
                source_name=self.wingman.name,
                skill_name=self.name,
                additional_data={"image_base64": jpeg_base64},
            )

        response_text = await self.wingman.ai.generate(
            prompt,
            system="You are a helpful ai assistant.",
            image=f"data:image/jpeg;base64,{jpeg_base64}",
        )
        function_response = response_text or ""

        return function_response
