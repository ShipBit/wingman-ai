import os
import json
import zipfile
from typing import TYPE_CHECKING
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from api.enums import LogType
from skills.skill_base import Skill
from services.file import get_writable_dir
from showinfm import show_in_file_manager
from pdfminer.high_level import extract_text
if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman

DEFAULT_MAX_TEXT_SIZE = 24000
SUPPORTED_FILE_EXTENSIONS = [
    "adoc",
    "android",
    "asc",
    "ascii",
    "bat",
    "bib",
    "cfg",
    "cmake",
    "cmd",
    "conf",
    "cpp",
    "c",
    "cs",
    "csproj",
    "css",
    "csv",
    "dockerfile",
    "dot",
    "env",
    "fo",
    "gd",
    "gemspec",
    "gitconfig",
    "gitignore",
    "go",
    "gradle",
    "graphql",
    "h",
    "htaccess",
    "html",
    "http",
    "in",
    "ini",
    "ipynb",
    "java",
    "json",
    "jsonl",
    "js",
    "lua",
    "log",
    "m3u",
    "map",
    "md",
    "mk",
    "pdf",
    "pyd",
    "plist",
    "pl",
    "po",
    "properties",
    "ps1",
    "pxd",
    "py",
    "rb",
    "resx",
    "rpy",
    "rs",
    "rst",
    "rtf",
    "srt",
    "sh",
    "sql",
    "svg",
    "swift",
    "ts",
    "tscn",
    "tcl",
    "tex",
    "tmpl",
    "toml",
    "tpl",
    "tres",
    "tsv",
    "txt",
    "vtt",
    "wsdl",
    "wsgi",
    "xlf",
    "xml",
    "yml",
    "yaml",
]


class FileManager(Skill):

    def __init__(self, config: SkillConfig, settings: SettingsConfig, wingman: "OpenAiWingman") -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        self.allowed_file_extensions = SUPPORTED_FILE_EXTENSIONS
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

    def get_text_from_file(self, file_path: str, file_extension: str, pdf_page_number: int = None) -> str:
        try:
            if file_extension.lower() == "pdf":
                return extract_text(file_path, page_numbers=[pdf_page_number-1]) if pdf_page_number else extract_text(file_path)
            else:
                with open(file_path, "r", encoding="utf-8") as file:
                    return file.read()
        except Exception as e:
            return None

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
                                    "description": "The path of the directory from where the file should be loaded. Defaults to the configured directory.",
                                },
                                "pdf_page_number_to_load": {
                                    "type": "number",
                                    "description": "The page number of a pdf to load, if expressly specified by the user.",
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
                                    "description": "The path of the directory where the file should be saved. Defaults to the configured directory.",
                                },
                                "add_to_existing_file": {
                                    "type": "boolean",
                                    "description": "Boolean True/False indicator of whether the user wants to add text to an already existing file. Defaults to False unless user expresses clear intent to add to existing file.",
                                },
                            },
                            "required": [
                                "file_name",
                                "text_content",
                                "add_to_existing_file",
                            ],
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
            (
                "open_folder",
                {
                    "type": "function",
                    "function": {
                        "name": "open_folder",
                        "description": "Opens a specified directory in the GUI.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "folder_name": {
                                    "type": "string",
                                    "description": "The name of the folder to open.",
                                },
                                "directory_path": {
                                    "type": "string",
                                    "description": "The path of the directory where the folder to open is located. Defaults to the configured directory.",
                                },
                            },
                            "required": ["folder_name"],
                        },
                    },
                },
            ),
            (
                "read_file_or_text_content_aloud",
                {
                    "type": "function",
                    "function": {
                        "name": "read_file_or_text_content_aloud",
                        "description": "Reads aloud the content of a specified text file or or other text content provided by the user.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "file_name": {
                                    "type": "string",
                                    "description": "The name of the file to read aloud, including the file extension.",
                                },
                                "directory_path": {
                                    "type": "string",
                                    "description": "The path of the directory from where the file should be loaded. Defaults to the configured directory.",
                                },
                                "pdf_page_number_to_load": {
                                    "type": "number",
                                    "description": "The page number of a PDF to read aloud, if specified.",
                                },
                                "text_content": {
                                    "type": "string",
                                    "description": "The content to read aloud, if specified"
                                }
                            },
                        },
                    },
                },
            ),
            (
                "load_folder_contents",
                {
                    "type": "function",
                    "function": {
                        "name": "load_folder_contents",
                        "description": "Reads the contents of supported files in a folder and loads it into memory.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "folder_path": {
                                    "type": "string",
                                    "description": "The absolute path of the folder to read contents from.",
                                },
                            },
                            "required": ["folder_path"],
                        },
                    },
                },
            ),
            (
                "create_zip_file",
                {
                    "type": "function",
                    "function": {
                        "name": "create_zip_file",
                        "description": "Combines and compresses specified folders or files into a .zip file.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "zip_file_name": {
                                    "type": "string",
                                    "description": "The name of the zip file to create.",
                                },
                                "directory_path": {
                                    "type": "string",
                                    "description": "The path of the directory where the zip file should be created. Defaults to the configured directory.",
                                },
                                "files_to_compress": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "List of absolute file or folder paths to compress into the zip.",
                                },
                            },
                            "required": ["zip_file_name", "files_to_compress"],
                        },
                    },
                },
            ),
            (
                "add_to_zip_file",
                {
                    "type": "function",
                    "function": {
                        "name": "add_to_zip_file",
                        "description": "Adds more files to an existing .zip file.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "zip_file_name": {
                                    "type": "string",
                                    "description": "The name of the zip file to add files to.",
                                },
                                "directory_path": {
                                    "type": "string",
                                    "description": "The path of the directory where the zip file is located. Defaults to the configured directory.",
                                },
                                "files_to_add": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "List of files to add to the existing zip.",
                                },
                            },
                            "required": ["zip_file_name", "files_to_add"],
                        },
                    },
                },
            ),
            (
                "extract_zip",
                {
                    "type": "function",
                    "function": {
                        "name": "extract_zip",
                        "description": "Extracts all files contained in a specified .zip file to the specified target directory",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "zip_file_path": {
                                    "type": "string",
                                    "description": "The absolute path (including full name) of the zip file to extract.",
                                },
                                "target_directory": {
                                    "type": "string",
                                    "description": "The absolute path of the target directory to extract the contents to.",
                                },
                            },
                            "required": ["zip_file_path", "target_directory"],
                        },
                    },
                },
            )
        ]
        return tools
        
    async def execute_tool(self, tool_name: str, parameters: dict[str, any]) -> tuple[str, str]:
        function_response = "Operation not completed."
        instant_response = ""

        if self.settings.debug_mode and tool_name in ["load_text_from_file", "save_text_to_file", "create_folder", "open_folder", "read_file_aloud", "load_folder_contents", "create_zip_file", "add_to_zip_file", "extract_zip"]:
            self.start_execution_benchmark()
            await self.printr.print_async(
                f"Executing {tool_name} with parameters: {parameters}",
                color=LogType.INFO,
            )

        # Get all possible parameters once to avoid duplicate work
        file_name = parameters.get("file_name")
        directory_path = parameters.get("directory_path", self.default_directory)
        if directory_path == "" or directory_path == ".":
            directory_path = self.default_directory
        pdf_page_number = parameters.get("pdf_page_number_to_load")
        text_content = parameters.get("text_content")
        add_to_existing_file = parameters.get("add_to_existing_file")
        folder_name = parameters.get("folder_name")
        folder_path = parameters.get("folder_path")
        zip_file_name = parameters.get("zip_file_name")
        files_to_add = parameters.get("files_to_add")
        zip_file_path = parameters.get("zip_file_path")
        target_directory = parameters.get("target_directory")
        files_to_compress = parameters.get("files_to_compress")
        
        if tool_name == "load_text_from_file":
            if not file_name or file_name == "":
                function_response = "File name not provided."
            else:
                file_extension = file_name.split(".")[-1]
                if file_extension.lower() not in self.allowed_file_extensions:
                    function_response = f"Unsupported file extension: {file_extension}"
                else:
                    file_path = os.path.join(directory_path, file_name)
                    try:
                        # if PDF, use pdfminer.six's extract text to read (optionally passing the specific page to read - zero-indexed so subtract 1), otherwise open and parse file
                        file_content = self.get_text_from_file(file_path, file_extension, pdf_page_number)
                        if len(file_content) < 3 or not file_content:
                            function_response = f"File at {file_path} appears not to have any content. If file is a .pdf it may be an image format that cannot be read."
                        elif len(file_content) > self.max_text_size:
                            function_response = f"File content at {file_path} exceeds the maximum allowed size."
                        else:
                            function_response = f"File content loaded from {file_path}:\n{file_content}"
                    except FileNotFoundError:
                        function_response = f"File '{file_name}' not found in '{directory_path}'."
                    except Exception as e:
                        function_response = f"Failed to read file '{file_name}': {str(e)}"

        elif tool_name == "save_text_to_file":
            if not file_name or not text_content or file_name == "":
                function_response = "File name or text content not provided."
            else:
                file_extension = file_name.split(".")[-1]
                if file_extension.lower() not in self.allowed_file_extensions:
                    file_name += f".{self.default_file_extension}"
                if len(text_content) > self.max_text_size:
                    function_response = "Text content exceeds the maximum allowed size."
                else:
                    if file_extension.lower() == "json":
                        try:
                            json_content = json.loads(text_content)
                            text_content = json.dumps(json_content, indent=4)
                        except json.JSONDecodeError as e:
                            function_response = f"Invalid JSON content: {str(e)}"
                            return function_response, instant_response
                    os.makedirs(directory_path, exist_ok=True)
                    file_path = os.path.join(directory_path, file_name)
                    # If file already exists, and user does not have overwrite option on, and LLM did not detect an intent to add to the existing file, stop
                    if (
                        os.path.isfile(file_path)
                        and not self.allow_overwrite_existing
                        and not add_to_existing_file
                    ):
                        function_response = f"File '{file_name}' already exists at {directory_path} and overwrite is not allowed."
                    # Otherwise, if file exists but LLM detected user wanted to add to existing file, do that.
                    elif os.path.isfile(file_path) and add_to_existing_file:
                        try:
                            with open(file_path, "a", encoding="utf-8") as file:
                                file.write(text_content)
                            function_response = (
                                f"Text added to existing file at {file_path}."
                            )
                        except Exception as e:
                            function_response = (
                                f"Failed to append text to {file_path}: {str(e)}"
                            )
                    # We are either fine with completely overwriting the file or it does not exist already
                    else:
                        try:
                            with open(file_path, "w", encoding="utf-8") as file:
                                file.write(text_content)
                            function_response = f"Text saved to {file_path}."
                        except Exception as e:
                            function_response = f"Failed to save text to {file_path}: {str(e)}"

        elif tool_name == "create_folder":
            if not folder_name or folder_name == "":
                function_response = "Folder name not provided."
            else:
                full_path = os.path.join(directory_path, folder_name)
                try:
                    os.makedirs(full_path, exist_ok=True)
                    function_response = f"Folder '{folder_name}' created at '{directory_path}'."
                except Exception as e:
                    function_response = (
                        f"Failed to create folder '{folder_name}': {str(e)}"
                    )

        elif tool_name == "open_folder":
            if not folder_name or folder_name == "":
                function_response = "Folder name not provided."
            else:
                full_path = os.path.join(directory_path, folder_name)
                try:
                    show_in_file_manager(full_path)
                    function_response = (
                        f"Folder '{folder_name}' opened in '{directory_path}'."
                    )
                except Exception as e:
                    function_response = (
                        f"Failed to open folder '{folder_name}': {str(e)}"
                    )

        elif tool_name == "read_file_or_text_content_aloud":
            # First check if there's text content, if so, just play that as the user just wants the AI to say something in its TTS voice
            if text_content:
                await self.wingman.play_to_user(text_content)
                function_response = "Provided text read aloud."
            # Otherwise, check to see if a valid file has been passed, if so, read its text as long as it does not exceed max content length
            # If not a valid file location, double check whether the AI accidentally put text content in file name and play that
            else:
                if not file_name:
                    function_response = "File name not provided."
                else:
                    file_path = os.path.join(directory_path, file_name)
                    if not os.path.isfile(file_path):
                        await self.wingman.play_to_user(file_path)
                        function_response = "Provided text read aloud."
                    else:
                        file_extension = file_name.split(".")[-1]
                        if file_extension.lower() not in self.allowed_file_extensions:
                            function_response = f"Unsupported file extension: {file_extension}"
                        else:
                            try:
                                file_content = self.get_text_from_file(file_path, file_extension, pdf_page_number)
                                if len(file_content) < 3 or not file_content:
                                    function_response = f"File at {file_path} appears not to have any content so could not read it aloud. If file is a .pdf it may be an image format that cannot be read."
                                elif len(file_content) > self.max_text_size:
                                    function_response = f"File content at {file_path} exceeds the maximum allowed size so could not read it aloud."
                                else:
                                    await self.wingman.play_to_user(file_content)
                                    function_response = f"File content from {file_path} read aloud."
                            except Exception as e:
                                function_response = f"There was an error trying to read aloud '{file_name}' in '{directory_path}'.  The error was {str(e)}."
                        
        elif tool_name == "load_folder_contents":
            skipped_files = []
            try:
                absolute_paths = []
                contents_of_files = ""

                for root, _, files in os.walk(folder_path):
                    for file in files:
                        absolute_path = os.path.abspath(os.path.join(root, file))
                        absolute_paths.append(absolute_path)

                for file_path in absolute_paths:
                    file_extension = file_path.split(".")[-1]
                    if file_extension.lower() not in self.allowed_file_extensions:
                        skipped_files.append(f"Unsupported file extension: {file_path}")
                    else:
                        file_contents = self.get_text_from_file(file_path, file_extension)
                        if len(file_contents) > self.max_text_size:
                            skipped_files.append(f"File content exceeds max size: {file_path}")
                        else:
                            contents_of_files += f"\n\n##File path: {file_path}##\n{file_contents}\n\n"

                if skipped_files:
                    function_response = f"Some files were skipped: {', '.join(skipped_files)}\nLoaded content: {contents_of_files}"
                else:
                    function_response = f"Loaded content: {contents_of_files}"

            except Exception as e:
                function_response = f"Error in reading folder contents in '{folder_path}': {str(e)}"

        elif tool_name == "create_zip_file":
            full_zip_path = os.path.join(directory_path, zip_file_name)
            try:
                if not isinstance(files_to_compress, list):
                    files_to_compress = [files_to_compress]
                
                with zipfile.ZipFile(full_zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_ref:
                    for file in files_to_compress:
                        if os.path.isdir(file):
                            for root, dirs, files in os.walk(file):
                                for filename in files:
                                    file_path = os.path.join(root, filename)
                                    arcname = os.path.relpath(file_path, start=os.path.dirname(file))
                                    zip_ref.write(file_path, arcname=arcname)
                        elif os.path.isfile(file):
                            arcname = os.path.basename(file)
                            zip_ref.write(file, arcname=arcname)
                        else:
                            raise ValueError(f"Invalid path: {file}")
                
                function_response = f"Created zip file '{full_zip_path}' with specified files."
            except Exception as e:
                function_response = f"Failed to create zip file '{zip_file_name}': {str(e)}"

        elif tool_name == "add_to_zip_file":
            full_zip_path = os.path.join(directory_path, zip_file_name)
            try:
                if not isinstance(files_to_add, list):
                    files_to_add = [files_to_add]

                with zipfile.ZipFile(full_zip_path, 'a', zipfile.ZIP_DEFLATED) as zip_ref:
                    for file in files_to_add:
                        if os.path.isdir(file):
                            for root, dirs, files in os.walk(file):
                                for filename in files:
                                    file_path = os.path.join(root, filename)
                                    arcname = os.path.relpath(file_path, start=os.path.dirname(file))
                                    zip_ref.write(file_path, arcname=arcname)
                        elif os.path.isfile(file):
                            arcname = os.path.basename(file)
                            zip_ref.write(file, arcname=arcname)
                        else:
                            raise ValueError(f"Invalid path: {file}")

                function_response = f"Added specified files to zip file '{full_zip_path}'."
            except Exception as e:
                function_response = f"Failed to add files to zip file '{full_zip_path}': {str(e)}"


        elif tool_name == "extract_zip":
            try:
                with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                    zip_ref.extractall(path=target_directory)
                    function_response = f"Extracted {zip_file_path} contents to {target_directory}"

            except Exception as e:
                function_response = f"Failed to extract contents of {zip_file_path}, error was {e}."

        if self.settings.debug_mode:
            await self.printr.print_async(
                f"Finished calling {tool_name} tool and returned function response: {function_response}",
                color=LogType.INFO,
            )
            await self.print_execution_time()

        return function_response, instant_response

    def get_default_directory(self) -> str:
        return get_writable_dir("files")