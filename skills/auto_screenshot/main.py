import asyncio
import os
from datetime import datetime
from typing import TYPE_CHECKING

from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill, tool
from skills.auto_screenshot.active_window import active_window_bbox

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext


class AutoScreenshot(Skill):
    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "WingmanContext",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        self.retrieve_custom_property_value("default_directory", errors)
        self.retrieve_custom_property_value("display", errors)

        return errors

    def get_default_directory(self) -> str:
        return self.get_generated_files_dir()

    def _get_default_directory(self) -> str:
        errors = []
        default_directory = self.retrieve_custom_property_value(
            "default_directory", errors
        )
        if (
            not default_directory
            or default_directory == ""
            or not os.path.isdir(default_directory)
        ):
            return self.get_default_directory()
        return default_directory

    def _get_display(self) -> int:
        errors = []
        return self.retrieve_custom_property_value("display", errors)

    @tool(
        name="take_screenshot",
        description="""Captures a screenshot of the focused window and saves it.

        WHEN TO USE:
        - User explicitly requests: 'Take a screenshot', 'Capture my screen'
        - User expresses excitement/surprise: 'Oh wow!', 'This is crazy!', 'Amazing!'
        - Memorable gaming moments or achievements

        IMPORTANT: Do NOT use for 'look at screen' requests - those need VisionAI for analysis, not capture.""",
    )
    async def take_screenshot(self, reason: str) -> str:
        """
        Args:
            reason: The reason for taking a screenshot.
        """
        if self.settings.debug_mode:
            self.log.info(
                f"Taking screenshot for reason: {reason}", server_only=True
            )

        window_bbox = None
        try:
            window_bbox = await asyncio.to_thread(active_window_bbox)
            if self.settings.debug_mode:
                self.log.info(f"Active window bbox: {window_bbox}", server_only=True)
        except Exception as e:
            self.log.warning(
                f"Window detection unavailable ({e}), using full screen capture.",
                server_only=True,
            )

        screenshot_file = os.path.join(
            self._get_default_directory(),
            f"{self.wingman.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
        )
        try:
            display = int(self._get_display())
        except (TypeError, ValueError):
            display = 1
        try:
            image = await self.wingman.screen.capture(display, window_bbox)
        except RuntimeError as e:
            return f"Could not take a screenshot: {e}"
        await asyncio.to_thread(image.save, screenshot_file)

        if self.settings.debug_mode:
            self.log.info(f"Screenshot saved at: {screenshot_file}", server_only=True)

        return f"Screenshot saved to: {screenshot_file}"
