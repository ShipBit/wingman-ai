import asyncio
import os
from datetime import datetime
from typing import TYPE_CHECKING
from mss import mss
from PIL import Image

try:
    import pygetwindow as gw
except (ImportError, NotImplementedError):
    gw = None

from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill, tool

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
            if gw is None:
                raise RuntimeError("pygetwindow not available on this platform")
            focused_window = await asyncio.to_thread(gw.getActiveWindow)

            if focused_window:
                window_bbox = {
                    "top": focused_window.top,
                    "left": focused_window.left,
                    "width": focused_window.width,
                    "height": focused_window.height,
                }

            if self.settings.debug_mode:
                self.log.info(
                    f"Focused window {focused_window} bbox: {window_bbox}",
                    server_only=True,
                )

        except Exception as e:
            self.log.warning(
                f"Window detection unavailable ({e}), using full screen capture.",
                server_only=True,
            )

        screenshot_file = os.path.join(
            self._get_default_directory(),
            f"{self.wingman.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
        )
        await asyncio.to_thread(
            self._grab_and_save, window_bbox, self._get_display(), screenshot_file
        )

        if self.settings.debug_mode:
            self.log.info(f"Screenshot saved at: {screenshot_file}", server_only=True)

        return f"Screenshot saved to: {screenshot_file}"

    @staticmethod
    def _grab_and_save(window_bbox, display, screenshot_file: str) -> None:
        with mss() as sct:
            if window_bbox:
                screenshot = sct.grab(window_bbox)
            else:
                try:
                    display = int(display)
                except (TypeError, ValueError):
                    display = -1
                if not 0 <= display < len(sct.monitors):
                    display = 1 if len(sct.monitors) > 1 else 0
                screenshot = sct.grab(sct.monitors[display])
            image = Image.frombytes(
                "RGB", screenshot.size, screenshot.bgra, "raw", "BGRX"
            )
            image.save(screenshot_file)
