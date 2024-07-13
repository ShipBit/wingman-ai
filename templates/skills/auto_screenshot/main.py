import os
import time
from datetime import datetime
from typing import TYPE_CHECKING
from mss import mss
import pygetwindow as gw
from PIL import Image
from api.enums import LogType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill
from services.file import get_writable_dir

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
        self.default_directory = ""
        self.display = 1

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        self.default_directory = self.retrieve_custom_property_value(
            "default_directory", errors
        )
        if not self.default_directory or self.default_directory == "" or not os.path.isdir(self.default_directory):
            self.default_directory = self.get_default_directory()
            if self.settings.debug_mode:
                await self.printr.print_async(
                    "User either did not enter default directory or entered directory is invalid.  Defaulting to wingman config directory / screenshots",
                    color=LogType.INFO,
                )


        self.display = self.retrieve_custom_property_value("display", errors)

        return errors

    def get_default_directory(self) -> str:
        return get_writable_dir("screenshots")

    async def take_screenshot(self, reason: str) -> None:
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
                main_display = sct.monitors[self.display]
                screenshot = sct.grab(main_display)

            image = Image.frombytes(
                "RGB", screenshot.size, screenshot.bgra, "raw", "BGRX"
            )

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_file = os.path.join(self.default_directory, f'{self.wingman.name}_{timestamp}.png')
            image.save(screenshot_file)

            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Screenshot saved at: {screenshot_file}",
                    color=LogType.INFO,
                )

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "take_screenshot",
                {
                    "type": "function",
                    "function": {
                        "name": "take_screenshot",
                        "description": "Takes a screenshot of the currently focused game window and saves it in the default directory.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "reason": {
                                    "type": "string",
                                    "description": "The reason for taking a screenshot.",
                                },
                            },
                            "required": ["reason"],
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

        if tool_name == "take_screenshot":
            if self.settings.debug_mode:
                self.start_execution_benchmark()
            reason = parameters.get("reason", "unspecified reason")
            await self.take_screenshot(reason)
            function_response = "Screenshot taken successfully."
            
            if self.settings.debug_mode:
                await self.print_execution_time()

        return function_response, instant_response