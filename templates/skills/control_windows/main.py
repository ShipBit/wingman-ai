import os
from pathlib import Path
import pygetwindow as gw
from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from api.enums import LogType
from skills.skill_base import Skill


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
    ) -> None:
        super().__init__(
            config=config, wingman_config=wingman_config, settings=settings
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

    # Function to search and start an application
    def search_and_start(self, app_name):
        for start_menu_path in self.start_menu_paths:
            if start_menu_path.exists():
                for file_path in self.list_files(start_menu_path, ".lnk"):
                    if app_name.lower() in file_path.stem.lower():
                        # Attempt to start the application
                        os.startfile(str(file_path))
                        # subprocess.Popen([str(file_path)])
                        return True
        return False

    def close_application(self, app_name):
        windows = gw.getWindowsWithTitle(app_name)
        if windows and len(windows) > 0:
            for window in windows:
                window.close()

            return True

        return False

    def execute_ui_command(self, app_name: str, command: str):
        windows = gw.getWindowsWithTitle(app_name)
        if windows and len(windows) > 0:
            for window in windows:
                try:
                    getattr(window, command)()
                except AttributeError:
                    pass

            return True

        return False

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "control_windows_functions",
                {
                    "type": "function",
                    "function": {
                        "name": "control_windows_functions",
                        "description": "Control Windows Functions, like opening and closing applications.",
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
                                    ],
                                },
                                "parameter": {
                                    "type": "string",
                                    "description": "The parameter for the command. For example, the application name to open or close. Or the information to get.",
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
        function_response = "Application not found."
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

            else:
                command = parameters["command"]
                app_minimize = self.execute_ui_command(parameter, command)
                if app_minimize:
                    function_response = f"Application {command}."

            if self.settings.debug_mode:
                await self.print_execution_time()

        return function_response, instant_response
