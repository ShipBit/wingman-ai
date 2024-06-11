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


class CreateFolder(Skill):

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
        # Will be set in validate, default directory to save files to
        self.default_directory = ""

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        custom_path = self.retrieve_custom_property_value("create_folder_default_path", errors)
        if custom_path and custom_path != "":
            self.default_directory = custom_path
        else:
            self.default_directory = self.get_default_directory()
        return errors

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "create_folder",
                {
                    "type": "function",
                    "function": {
                        "name": "create_folder",
                        "description": "Creates a folder in the specified directory.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "folder_name": {
                                    "type": "string",
                                    "description": "The name of the folder to create.",
                                },
                                "directory_path": {
                                    "type": "string",
                                    "description": "The path of the directory where the folder should be created. If not provided, a default will be used.",
                                    "default": self.default_directory,
                                },
                            },
                            "required": ["folder_name"],
                        },
                    },
                },
            ),
        ]
        return tools

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        function_response = "Folder not created or create operation failed."
        instant_response = ""

        if tool_name == "create_folder":
            if self.settings.debug_mode:
                self.start_execution_benchmark()
                await self.printr.print_async(
                    f"Executing create_folder with parameters: {parameters}",
                    color=LogType.INFO,
                )

            folder_name = parameters.get("folder_name")
            directory_path = parameters.get("directory_path", self.default_directory)

            if not folder_name:
                function_response = "Folder name not provided."
            else:
                full_path = os.path.join(directory_path, folder_name)
                try:
                    os.makedirs(full_path, exist_ok=True)
                    function_response = f"Folder '{folder_name}' successfully created at '{directory_path}'."
                except Exception as e:
                    function_response = f"Failed to create folder '{folder_name}' at '{directory_path}': {str(e)}"
                    if self.settings.debug_mode:
                        await self.printr.print_async(
                            f"Error occurred while creating folder at {directory_path}: {str(e)}",
                            color=LogType.ERROR,
                        )

            if self.settings.debug_mode:
                await self.print_execution_time()

        return function_response, instant_response

    def get_default_directory(self) -> str:
        # If no custom property value is set or an error occurred, fallback to dynamic default
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
            return os.getcwd()  # Fallback to current working directory.