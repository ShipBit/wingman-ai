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
from services.file import get_writable_dir

if TYPE_CHECKING:
    from wingmen.wingman import Wingman

DEFAULT_MAX_TEXT_SIZE = 10000
DEFAULT_FILE_EXTENSIONS = [
    "txt",
    "md",
    "log",
    "yaml",
    "py",
    "json",
    "csv",
    "html",
    "htm",
    "xml",
    "ini",
    "toml",
    "Rmd",
    "tex",
    "sql",
]


class FileManager(Skill):

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
        self.allowed_file_extensions = DEFAULT_FILE_EXTENSIONS
        self.default_file_extension = "txt"
        self.max_text_size = DEFAULT_MAX_TEXT_SIZE
        self.default_directory = ""  # Set in validate
        self.allow_overwrite_existing = False

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        self.default_directory = self.retrieve_custom_property_value(
            "default_directory", errors
        )
        if not self.default_directory or self.default_directory == "":
            self.default_directory = self.get_default_directory()
        self.allow_overwrite_existing = self.retrieve_custom_property_value(
            "allow_overwrite_existing", errors
        )
        return errors

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "load_text_from_file",
                {
                    "type": "function",
                    "function": {
                        "name": "load_text_from_file",
                        "description": "Loads the content of a specified text file.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "file_name": {
                                    "type": "string",
                                    "description": "The name of the file to load, including the file extension.",
                                },
                                "directory_path": {
                                    "type": "string",
                                    "description": "The directory from where the file should be loaded. Defaults to the configured directory.",
                                },
                            },
                            "required": ["file_name"],
                        },
                    },
                },
            ),
            (
                "save_text_to_file",
                {
                    "type": "function",
                    "function": {
                        "name": "save_text_to_file",
                        "description": "Saves the provided text to a file.",
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
                                "directory_path": {
                                    "type": "string",
                                    "description": "The directory where the file should be saved. Defaults to the configured directory.",
                                },
                            },
                            "required": ["file_name", "text_content"],
                        },
                    },
                },
            ),
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
                                    "description": "The path of the directory where the folder should be created. Defaults to the configured directory.",
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
        function_response = "Operation not completed."
        instant_response = ""

        if tool_name == "load_text_from_file":
            if self.settings.debug_mode:
                self.start_execution_benchmark()
                await self.printr.print_async(
                    f"Executing load_text_from_file with parameters: {parameters}",
                    color=LogType.INFO,
                )
            file_name = parameters.get("file_name")
            directory = parameters.get("directory_path", self.default_directory)

            if not file_name:
                function_response = "File name not provided."
            else:
                file_extension = file_name.split(".")[-1]
                if file_extension not in self.allowed_file_extensions:
                    function_response = f"Unsupported file extension: {file_extension}"
                else:
                    file_path = os.path.join(directory, file_name)
                    try:
                        with open(file_path, "r", encoding="utf-8") as file:
                            file_content = file.read()
                            if len(file_content) > self.max_text_size:
                                function_response = (
                                    "File content exceeds the maximum allowed size."
                                )
                            else:
                                function_response = f"File content loaded from {file_path}:\n{file_content}"
                    except FileNotFoundError:
                        function_response = (
                            f"File '{file_name}' not found in '{directory}'."
                        )
                    except Exception as e:
                        function_response = (
                            f"Failed to read file '{file_name}': {str(e)}"
                        )

        elif tool_name == "save_text_to_file":
            if self.settings.debug_mode:
                self.start_execution_benchmark()
                await self.printr.print_async(
                    f"Executing save_text_to_file with parameters: {parameters}",
                    color=LogType.INFO,
                )
            file_name = parameters.get("file_name")
            text_content = parameters.get("text_content")
            directory = parameters.get("directory_path", self.default_directory)

            if not file_name or not text_content:
                function_response = "File name or text content not provided."
            else:
                file_extension = file_name.split(".")[-1]
                if file_extension not in self.allowed_file_extensions:
                    file_name += f".{self.default_file_extension}"
                if len(text_content) > self.max_text_size:
                    function_response = "Text content exceeds the maximum allowed size."
                else:
                    if file_extension == "json":
                        try:
                            json_content = json.loads(text_content)
                            text_content = json.dumps(json_content, indent=4)
                        except json.JSONDecodeError as e:
                            function_response = f"Invalid JSON content: {str(e)}"
                            return function_response, instant_response
                    os.makedirs(directory, exist_ok=True)
                    file_path = os.path.join(directory, file_name)

                    if os.path.isfile(file_path) and not self.allow_overwrite_existing:
                        function_response = f"File '{file_name}' already exists at {directory} and overwrite is not allowed."
                    else:
                        try:
                            with open(file_path, "w", encoding="utf-8") as file:
                                file.write(text_content)
                            function_response = f"Text saved to {file_path}."
                        except Exception as e:
                            function_response = (
                                f"Failed to save text to {file_path}: {str(e)}"
                            )

        elif tool_name == "create_folder":
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
                    function_response = (
                        f"Folder '{folder_name}' created at '{directory_path}'."
                    )
                except Exception as e:
                    function_response = (
                        f"Failed to create folder '{folder_name}': {str(e)}"
                    )

        if self.settings.debug_mode:
            await self.printr.print_async(
                f"Finished calling {tool_name} tool and returned function response: {function_response}",
                color=LogType.INFO,
            )
        return function_response, instant_response

    def get_default_directory(self) -> str:
        return get_writable_dir("files")
