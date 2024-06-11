import os
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

class LoadTextFromFile(Skill):

    def __init__(
        self,
        config: SkillConfig,
        wingman_config: WingmanConfig,
        settings: SettingsConfig,
        wingman: "Wingman",
    ) -> None:
        super().__init__(
            config=config,
            wingman_config=wingman_config,
            settings=settings,
            wingman=wingman,
        )
        # Define necessary settings for the skill
        self.allowed_file_extensions = ['txt', 'md', 'log', 'yaml', 'py', 'json']
        self.default_file_extension = 'txt'
        self.max_text_size = 10000  # Reasonable limit for the text size, this is roughly 1500-2500 words
        # Will be set in validate, default directory to load files from
        self.default_directory = ""

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        custom_path = self.retrieve_custom_property_value("load_file_default_path", errors)
        if custom_path and custom_path != "":
            self.default_directory = custom_path
        else:
            self.default_directory = self.get_default_directory()
        return errors

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "load_text_from_file",
                {
                    "type": "function",
                    "function": {
                        "name": "load_text_from_file",
                        "description": "Loads the content of a specified text file into the current AI conversation.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "file_name": {
                                    "type": "string",
                                    "description": "The name of the file to load, including the file extension.",
                                },
                                "directory": {
                                    "type": "string",
                                    "description": "The directory from where the file should be loaded.  Defaults to the WingmanAI config directory.",
                                },
                            },
                            "required": ["file_name"],
                        },
                    },
                },
            ),
        ]
        return tools

    async def execute_tool(
        self, tool_name:str, parameters:dict[str,any]
    ) -> tuple[str, str]:
        function_response = "File not loaded or load operation failed."
        instant_response = ""

        if tool_name == "load_text_from_file":
            if self.settings.debug_mode:
                self.start_execution_benchmark()
                await self.printr.print_async(
                    f"Executing load_text_from_file with parameters: {parameters}",
                    color=LogType.INFO,
                )

            file_name = parameters.get("file_name")
            directory = parameters.get("directory", self.default_directory)

            if not directory or directory == "":
                directory = self.get_default_directory()

            if not file_name or file_name == "":
                function_response = "File name not provided."
            else:
                # Validate and add file extension if missing or unsupported
                file_extension = file_name.split('.')[-1]
                if file_extension not in self.allowed_file_extensions:
                    function_response = f"Unsupported file extension: {file_extension}"

                else:
                    file_path = os.path.join(directory, file_name)
                    try:
                        with open(file_path, "r", encoding="utf-8") as file:
                            file_content = file.read()
                            if len(file_content) > self.max_text_size:
                                function_response = "File content exceeds the maximum allowed size."
                            else:
                                function_response = f"File content loaded from {directory} successfully:\n{file_content}"
                    except FileNotFoundError:
                        function_response = f"File '{file_name}' not found at '{directory}'."
                    except Exception as e:
                        function_response = f"Failed to read file '{file_name}' in {directory}: {str(e)}"
                        if self.settings.debug_mode:
                            await self.printr.print_async(
                                f"Error occurred while reading file: {str(e)}",
                                color=LogType.ERROR,
                            )

            if self.settings.debug_mode:
                await self.print_execution_time()

        return function_response, instant_response

    def get_default_directory(self) -> str:
        # If no custom property value is set or an error occurred, fallback to dynamic default WingmanAI config directory
        if os.name == 'nt':  # Windows
            return os.path.join(os.path.expandvars(r"%APPDATA%"),
                "ShipBit",
                "WingmanAI",
            )
        elif os.name == 'posix':
            if sys.platform == 'darwin':  # macOS
                return os.path.join(os.path.expanduser("~/Library/Application Support"),
                "ShipBit",
                "WingmanAI",
            )
            else:  # Linux and other Unix-like systems
                return os.path.join(os.path.expanduser("~/.config"),
                "ShipBit",
                "WingmanAI",
            )
        else:
            return os.getcwd()  # Fallback to current working directory