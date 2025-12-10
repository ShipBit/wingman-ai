import os
import time
from datetime import datetime
from typing import TYPE_CHECKING
from mss import mss
import pygetwindow as gw
from PIL import Image
from api.enums import LogType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class AutoScreenshot(Skill):
    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
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
        """Get default_directory property value just-in-time."""
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
        """Get display property value just-in-time."""
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
            await self.printr.print_async(
                f"AutoScreenshot: taking screenshot for reason: {reason}",
                color=LogType.INFO,
            )

        try:
            focused_window = gw.getActiveWindow()

            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Taking screenshot because: {reason}. Focused window: {focused_window}",
                    color=LogType.INFO,
                )

            window_bbox = {
                "top": focused_window.top,
                "left": focused_window.left,
                "width": focused_window.width,
                "height": focused_window.height,
            }

            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"{focused_window} bbox detected as: {window_bbox}",
                    color=LogType.INFO,
                )

        except Exception as e:
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Failed to get focused window or window bbox using pygetwindow: {e}. Defaulting to full screen capture.",
                    color=LogType.ERROR,
                )
            window_bbox = None

        with mss() as sct:
            if window_bbox:
                screenshot = sct.grab(window_bbox)
            else:
                main_display = sct.monitors[self._get_display()]
                screenshot = sct.grab(main_display)

            image = Image.frombytes(
                "RGB", screenshot.size, screenshot.bgra, "raw", "BGRX"
            )

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_file = os.path.join(
                self._get_default_directory(), f"{self.wingman.name}_{timestamp}.png"
            )
            image.save(screenshot_file)

            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Screenshot saved at: {screenshot_file}",
                    color=LogType.INFO,
                )

        return f"Screenshot saved to: {screenshot_file}"
