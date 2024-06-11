import os
import json
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

class SaveTextToFile(Skill):

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
        # Define any necessary settings for the skill
        self.allowed_file_extensions = ['txt', 'md', 'log', 'yaml', 'py', 'json']
        self.default_file_extension = 'txt'
        self.max_text_size = 10000  # Reasonable limit for the text size, this is roughly 1500-2500 words
        # Will be set in validate, default directory to save files to
        self.default_directory = ""
        self.overwrite_existing = False

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        custom_path = self.retrieve_custom_property_value("create_file_default_path", errors)
        if custom_path and custom_path != "":
            self.default_directory = custom_path
        else:
            self.default_directory = self.get_default_directory()
        self.overwrite_existing = self.retrieve_custom_property_value("overwrite_existing", errors)
        return errors

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "save_text_to_file",
                {
                    "type": "function",
                    "function": {
                        "name": "save_text_to_file",
                        "description": "Saves the provided text to a file specified by the user.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "file_name": {
                                    "type": "string",
                                    "description": "The name of the file where the text should be saved, including the file extension.",
                                },
                                "text_content": {
                                    "type": "string",
                                    "description": "The text content to save to the file.",
                                },
                                "directory": {
                                    "type": "string",
                                    "description": "The directory where the file should be saved. Defaults to the WingmanAI config directory.",
                                },
                            },
                            "required": ["file_name", "text_content"],
                        },
                    },
                },
            ),
        ]
        return tools

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        function_response = "File not saved or save operation failed."
        instant_response = ""

        if tool_name == "save_text_to_file":
            if self.settings.debug_mode:
                self.start_execution_benchmark()
                await self.printr.print_async(
                    f"Executing save_text_to_file with parameters: {parameters}",
                    color=LogType.INFO,
                )

            file_name = parameters.get("file_name")
            text_content = parameters.get("text_content")
            directory = parameters.get("directory", self.default_directory)

            if not directory or directory == "":
                directory = self.get_default_directory()

            if not file_name or not text_content:
                function_response = "File name or text content not provided."
            else:
                # Validate and add file extension if missing or unsupported
                file_extension = file_name.split('.')[-1]
                if file_extension not in self.allowed_file_extensions:
                    file_name += f".{self.default_file_extension}"

                if len(text_content) > self.max_text_size:
                    function_response = "Text content exceeds the maximum allowed size."
                else:
                    # Handle JSON content validation
                    if file_extension == 'json':
                        try:
                            # Try to parse the content as JSON
                            json_content = json.loads(text_content)
                            # Reformat it to ensure it's valid JSON
                            text_content = json.dumps(json_content, indent=4)
                        except json.JSONDecodeError as e:
                            function_response = f"Invalid JSON content: {str(e)}"
                            if self.settings.debug_mode:
                                await self.printr.print_async(
                                    f"JSON validation error: {str(e)}",
                                    color=LogType.ERROR,
                                )
                            return function_response, instant_response
                    # Ensure the directory exists
                    os.makedirs(directory, exist_ok=True)
                    file_path = os.path.join(directory, file_name)

                    if os.path.isfile(file_path) and not self.overwrite_existing:
                        function_response = f"File '{file_name}' already exists at '{directory}' and overwrite is not allowed."
                    else:
                        try:
                            with open(file_path, "w", encoding="utf-8") as file:
                                file.write(text_content)
                            function_response = f"Text successfully saved to {file_path}."
                        except Exception as e:
                            function_response = f"Failed to save text to {file_path}: {str(e)}"
                            if self.settings.debug_mode:
                                await self.printr.print_async(
                                    f"Error occurred while saving text to {file_path}: {str(e)}",
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
