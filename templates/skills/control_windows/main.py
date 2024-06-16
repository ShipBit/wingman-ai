import os
import time
from pathlib import Path
import pygetwindow as gw
from typing import TYPE_CHECKING
from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from api.enums import LogType
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.wingman import Wingman

class ControlWindows(Skill):

    # Paths to Start Menu directories
    start_menu_paths: list[Path] = [
        Path(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs"),
        Path(
            os.environ["PROGRAMDATA"], "Microsoft", "Windows", "Start Menu", "Programs"
        ),
    ]

    def __init__(
        self,
        config: SkillConfig,
        wingman_config: WingmanConfig,
        settings: SettingsConfig,
        wingman: "Wingman",
    ) -> None:
        super().__init__(
            config=config, wingman_config=wingman_config, settings=settings, wingman=wingman
        )

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        return errors

    # Function to recursively list files in a directory
    def list_files(self, directory, extension=""):
        for item in directory.iterdir():
            if item.is_dir():
                yield from self.list_files(item, extension)
            elif item.is_file() and item.suffix == extension:
                yield item

    # Microsoft does odd things with its tab titles, see https://github.com/asweigart/PyGetWindow/issues/54, so use this function to try to find matching windows to app name and if match not found try adding unicode special character
    def get_and_check_windows(self, app_name):
        windows = gw.getWindowsWithTitle(app_name)
        if not windows and "Microsoft Edge".lower() in app_name.lower():
            app_name = app_name.replace("Microsoft Edge", "Microsoft\u200b Edge")
            app_name = app_name.replace("microsoft edge", "Microsoft\u200b Edge")
            windows = gw.getWindowsWithTitle(app_name)
            if not windows:
                return None
        return windows


    # Function to search and start an application
    def search_and_start(self, app_name):
        for start_menu_path in self.start_menu_paths:
            if start_menu_path.exists():
                for file_path in self.list_files(start_menu_path, ".lnk"):
                    if app_name.lower() in file_path.stem.lower():
                        # Attempt to start the application
                        try:
                            os.startfile(str(file_path))
                        # subprocess.Popen([str(file_path)])
                        except:
                            return False

                        return True

        return False

    def close_application(self, app_name):
        windows = self.get_and_check_windows(app_name)
        if windows and len(windows) > 0:
            for window in windows:
                try:
                    window.close()
                except:
                    return False

            return True

        return False

    def execute_ui_command(self, app_name: str, command: str):
        windows = self.get_and_check_windows(app_name)
        if windows and len(windows) > 0:
            for window in windows:
                try:
                    getattr(window, command)()
                except AttributeError:
                    pass

            return True

        return False

    def activate_application(self, app_name: str):
        windows = self.get_and_check_windows(app_name)
        if windows and len(windows) > 0:
            for window in windows:
                # See https://github.com/asweigart/PyGetWindow/issues/36#issuecomment-919332733 for why just regular "activate" may not work
                try:
                    window.minimize()
                    window.restore()
                    window.activate()
                except:
                    return False

            return True

        return False

    async def move_application(self, app_name: str, command: str):
        windows = self.get_and_check_windows(app_name)

        if self.settings.debug_mode:
            await self.printr.print_async(
                f"Windows found in move_application function matching {app_name}: {windows}",
                color=LogType.INFO,
            )

        if windows and len(windows) > 0:
            for window in windows:
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        f"Executing move_application command for: {window.title}",
                        color=LogType.INFO,
                    )
                # Make sure application is active before moving it
                try:
                    window.minimize()
                    window.restore()
                    # Temporarily maximize it, let windows do the work of what maximize means based on the user's setup 
                    window.maximize()
                    time.sleep(0.5)
                except:
                    pass
                # Assume that maximize is a proxy for the appropriate full size of a window in this setup, use that to calculate resize
                monitor_width, monitor_height = window.size
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        f"Before resize and move, {window.title} is {window.size} and is located at {window.topleft}.",
                        color=LogType.INFO,
                    )

                try:
                    if "left" in command:
                        window.resizeTo(int(monitor_width * 0.5) , int(monitor_height))
                        window.moveTo(0, 0)
                    if "right" in command:
                        window.resizeTo(int(monitor_width * 0.5) , int(monitor_height))
                        window.moveTo(int(monitor_width * 0.5), 0)
                    if "top" in command:
                        window.resizeTo(int(monitor_width), int(monitor_height * 0.5))
                        window.moveTo(0, 0)
                    if "bottom" in command:
                        window.resizeTo(int(monitor_width), int(monitor_height * 0.5))
                        window.moveTo(0, int(monitor_height * 0.5))
                    if self.settings.debug_mode:
                        await self.printr.print_async(
                            f"Executed move_application command {command}; {window.title} is now {window.size} and is located at {window.topleft}.",
                            color=LogType.INFO,
                        )
                    # Check if resize and move command really worked, if not return false so wingmanai does not tell user command was successful when it was not
                    if (monitor_width, monitor_height) == window.size:
                        return False
                    return True

                # If any errors in trying to move and resize windows, return false as well
                except:
                    return False

        # If no windows found, return false
        return False

    async def list_applications(self):
        window_titles = gw.getAllTitles()
        if window_titles:
            titles_as_string = ", ".join(window_titles)
            response = f"List of all application window titles found: {titles_as_string}."
            if self.settings.debug_mode:
                self.start_execution_benchmark()
                await self.printr.print_async(
                    f"list_applications command found these applications: {titles_as_string}",
                    color=LogType.INFO,
                )
            return response
        return False

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "control_windows_functions",
                {
                    "type": "function",
                    "function": {
                        "name": "control_windows_functions",
                        "description": "Control Windows Functions, like opening, closing, listing, and moving applications.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "description": "The command to execute",
                                    "enum": [
                                        "open",
                                        "close",
                                        "minimize",
                                        "maximize",
                                        "restore",
                                        "activate",
                                        "snap_left",
                                        "snap_right",
                                        "snap_top",
                                        "snap_bottom",
                                        "list_applications",
                                    ],
                                },
                                "parameter": {
                                    "type": "string",
                                    "description": "The parameter for the command. For example, the application name to open, close, or move. Or the information to get.",
                                },
                            },
                            "required": ["command"],
                        },
                    },
                },
            ),
        ]
        return tools

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        function_response = "Error: Application not found."
        instant_response = ""

        if tool_name == "control_windows_functions":
            if self.settings.debug_mode:
                self.start_execution_benchmark()
                await self.printr.print_async(
                    f"Executing control_windows_functions with parameters: {parameters}",
                    color=LogType.INFO,
                )

            parameter = parameters.get("parameter")

            if parameters["command"] == "open":
                app_started = self.search_and_start(parameter)
                if app_started:
                    function_response = "Application started."

            elif parameters["command"] == "close":
                app_closed = self.close_application(parameter)
                if app_closed:
                    function_response = "Application closed."

            elif parameters["command"] == "activate":
                app_activated = self.activate_application(parameter)
                if app_activated:
                    function_response = "Application activated."

            elif any(word in parameters["command"].lower() for word in ["left", "right", "top", "bottom"]):
                command = parameters["command"].lower()
                app_moved = await self.move_application(parameter, command)
                if app_moved:
                    function_response = "Application moved"
                else:
                    function_response = "There was a problem moving that application. The application may not support moving it through automation."

            elif "list" in parameters["command"].lower():
                apps_listed = await self.list_applications()
                if apps_listed:
                    function_response = apps_listed
                else:
                    function_response = "There was a problem getting your list of applications."
            else:
                command = parameters["command"]
                app_minimize = self.execute_ui_command(parameter, command)
                if app_minimize:
                    function_response = f"Application {command}."

            if self.settings.debug_mode:
                await self.print_execution_time()

        return function_response, instant_response
