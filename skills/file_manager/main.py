import os
import json
import zipfile
from typing import TYPE_CHECKING
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from api.enums import LogType
from services.benchmark import Benchmark
from skills.skill_base import Skill, tool
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

    def __init__(
        self, config: SkillConfig, settings: SettingsConfig, wingman: "OpenAiWingman"
    ) -> None:
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

    def get_text_from_file(
        self, file_path: str, file_extension: str, pdf_page_number: int = None
    ) -> str:
        try:
            if file_extension.lower() == "pdf":
                return (
                    extract_text(file_path, page_numbers=[pdf_page_number - 1])
                    if pdf_page_number
                    else extract_text(file_path)
                )
            else:
                with open(file_path, "r", encoding="utf-8") as file:
                    return file.read()
        except Exception as e:
            return None

    @tool(description="Load the content of a specified text file.")
    async def load_text_from_file(
        self,
        file_name: str,
        directory_path: str = None,
        pdf_page_number_to_load: int = None,
    ) -> str:
        """
        Load the content of a specified text file.

        Args:
            file_name: The name of the file to load.
            directory_path: The path of the directory. Defaults to configured directory.
            pdf_page_number_to_load: The page number of a pdf to load.
        """
        directory_path = directory_path or self.default_directory
        if directory_path == "" or directory_path == ".":
            directory_path = self.default_directory

        if not file_name or file_name == "":
            return "File name not provided."

        file_extension = file_name.split(".")[-1]
        if file_extension.lower() not in self.allowed_file_extensions:
            return f"Unsupported file extension: {file_extension}"

        file_path = os.path.join(directory_path, file_name)
        try:
            file_content = self.get_text_from_file(
                file_path, file_extension, pdf_page_number_to_load
            )
            if len(file_content) < 3 or not file_content:
                return f"File at {file_path} appears not to have any content. If file is a .pdf it may be an image format that cannot be read."
            elif len(file_content) > self.max_text_size:
                return f"File content at {file_path} exceeds the maximum allowed size."
            else:
                return f"File content loaded from {file_path}:\n{file_content}"
        except FileNotFoundError:
            return f"File '{file_name}' not found in '{directory_path}'."
        except Exception as e:
            return f"Failed to read file '{file_name}': {str(e)}"

    @tool(
        description="Save text content to a file. Use when user wants to save, write, create a document, or export text. Can append to existing files or create new ones."
    )
    async def save_text_to_file(
        self,
        file_name: str,
        text_content: str,
        directory_path: str = None,
        add_to_existing_file: bool = False,
    ) -> str:
        """
        Save the provided text to a file.

        Args:
            file_name: The name of the file.
            text_content: The text content to save.
            directory_path: The path of the directory. Defaults to configured directory.
            add_to_existing_file: Whether to add to an existing file.
        """
        directory_path = directory_path or self.default_directory
        if directory_path == "" or directory_path == ".":
            directory_path = self.default_directory

        if not file_name or not text_content or file_name == "":
            return "File name or text content not provided."

        file_extension = file_name.split(".")[-1]
        if file_extension.lower() not in self.allowed_file_extensions:
            file_name += f".{self.default_file_extension}"
            file_extension = self.default_file_extension

        if len(text_content) > self.max_text_size:
            return "Text content exceeds the maximum allowed size."

        if file_extension.lower() == "json":
            try:
                json_content = json.loads(text_content)
                text_content = json.dumps(json_content, indent=4)
            except json.JSONDecodeError as e:
                return f"Invalid JSON content: {str(e)}"

        os.makedirs(directory_path, exist_ok=True)
        file_path = os.path.join(directory_path, file_name)

        # If file already exists, and user does not have overwrite option on, and LLM did not detect an intent to add to the existing file, stop
        if (
            os.path.isfile(file_path)
            and not self.allow_overwrite_existing
            and not add_to_existing_file
        ):
            return f"File '{file_name}' already exists at {directory_path} and overwrite is not allowed."

        # Otherwise, if file exists but LLM detected user wanted to add to existing file, do that.
        elif os.path.isfile(file_path) and add_to_existing_file:
            try:
                with open(file_path, "a", encoding="utf-8") as file:
                    file.write(text_content)
                return f"Text added to existing file at {file_path}."
            except Exception as e:
                return f"Failed to append text to {file_path}: {str(e)}"
        # We are either fine with completely overwriting the file or it does not exist already
        else:
            try:
                with open(file_path, "w", encoding="utf-8") as file:
                    file.write(text_content)
                return f"Text saved to {file_path}."
            except Exception as e:
                return f"Failed to save text to {file_path}: {str(e)}"

    @tool(description="Create a folder in the specified directory.")
    async def create_folder(self, folder_name: str, directory_path: str = None) -> str:
        """
        Create a folder in the specified directory.

        Args:
            folder_name: The name of the folder to create.
            directory_path: The path of the directory. Defaults to configured directory.
        """
        directory_path = directory_path or self.default_directory
        if directory_path == "" or directory_path == ".":
            directory_path = self.default_directory

        if not folder_name or folder_name == "":
            return "Folder name not provided."

        full_path = os.path.join(directory_path, folder_name)
        try:
            os.makedirs(full_path, exist_ok=True)
            return f"Folder '{folder_name}' created at '{directory_path}'."
        except Exception as e:
            return f"Failed to create folder '{folder_name}': {str(e)}"

    @tool(description="Open a specified directory in the GUI.")
    async def open_folder(self, folder_name: str, directory_path: str = None) -> str:
        """
        Open a specified directory in the GUI.

        Args:
            folder_name: The name of the folder to open.
            directory_path: The path of the directory. Defaults to configured directory.
        """
        directory_path = directory_path or self.default_directory
        if directory_path == "" or directory_path == ".":
            directory_path = self.default_directory

        if not folder_name or folder_name == "":
            return "Folder name not provided."

        full_path = os.path.join(directory_path, folder_name)
        try:
            show_in_file_manager(full_path)
            return f"Folder '{folder_name}' opened in '{directory_path}'."
        except Exception as e:
            return f"Failed to open folder '{folder_name}': {str(e)}"

    @tool(
        description="Read aloud the content of a specified text file or provided text. Use when user wants to hear file contents spoken, for accessibility, or text-to-speech of documents."
    )
    async def read_file_or_text_content_aloud(
        self,
        file_name: str = None,
        directory_path: str = None,
        pdf_page_number_to_load: int = None,
        text_content: str = None,
    ) -> str:
        """
        Read aloud the content of a specified text file or provided text.

        Args:
            file_name: The name of the file to read aloud.
            directory_path: The path of the directory. Defaults to configured directory.
            pdf_page_number_to_load: The page number of a PDF to read aloud.
            text_content: The content to read aloud.
        """
        directory_path = directory_path or self.default_directory
        if directory_path == "" or directory_path == ".":
            directory_path = self.default_directory

        # First check if there's text content, if so, just play that as the user just wants the AI to say something in its TTS voice
        if text_content:
            await self.wingman.play_to_user(text_content)
            return "Provided text read aloud."
        # Otherwise, check to see if a valid file has been passed, if so, read its text as long as it does not exceed max content length
        # If not a valid file location, double check whether the AI accidentally put text content in file name and play that
        else:
            if not file_name:
                return "File name not provided."
            else:
                file_path = os.path.join(directory_path, file_name)
                if not os.path.isfile(file_path):
                    await self.wingman.play_to_user(file_path)
                    return "Provided text read aloud."
                else:
                    file_extension = file_name.split(".")[-1]
                    if file_extension.lower() not in self.allowed_file_extensions:
                        return f"Unsupported file extension: {file_extension}"
                    else:
                        try:
                            file_content = self.get_text_from_file(
                                file_path, file_extension, pdf_page_number_to_load
                            )
                            if len(file_content) < 3 or not file_content:
                                return f"File at {file_path} appears not to have any content so could not read it aloud. If file is a .pdf it may be an image format that cannot be read."
                            elif len(file_content) > self.max_text_size:
                                return f"File content at {file_path} exceeds the maximum allowed size so could not read it aloud."
                            else:
                                await self.wingman.play_to_user(file_content)
                                return f"File content from {file_path} read aloud."
                        except Exception as e:
                            return f"There was an error trying to read aloud '{file_name}' in '{directory_path}'.  The error was {str(e)}."

    @tool(description="Read the contents of supported files in a folder.")
    async def load_folder_contents(self, folder_path: str) -> str:
        """
        Read the contents of supported files in a folder and load it into memory.

        Args:
            folder_path: The absolute path of the folder to read contents from.
        """
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
                        skipped_files.append(
                            f"File content exceeds max size: {file_path}"
                        )
                    else:
                        contents_of_files += (
                            f"\n\n##File path: {file_path}##\n{file_contents}\n\n"
                        )

            if skipped_files:
                return f"Some files were skipped: {', '.join(skipped_files)}\nLoaded content: {contents_of_files}"
            else:
                return f"Loaded content: {contents_of_files}"

        except Exception as e:
            return f"Error in reading folder contents in '{folder_path}': {str(e)}"

    @tool(
        description="Combine and compress specified folders or files into a .zip file. Use when user wants to compress, archive, or bundle files for sharing or backup."
    )
    async def create_zip_file(
        self,
        zip_file_name: str,
        files_to_compress: list[str],
        directory_path: str = None,
    ) -> str:
        """
        Combine and compress specified folders or files into a .zip file.

        Args:
            zip_file_name: The name of the zip file to create.
            files_to_compress: List of absolute file or folder paths to compress.
            directory_path: The path of the directory where the zip file should be created.
        """
        directory_path = directory_path or self.default_directory
        if directory_path == "" or directory_path == ".":
            directory_path = self.default_directory

        full_zip_path = os.path.join(directory_path, zip_file_name)
        try:
            if not isinstance(files_to_compress, list):
                files_to_compress = [files_to_compress]

            with zipfile.ZipFile(full_zip_path, "w", zipfile.ZIP_DEFLATED) as zip_ref:
                for file in files_to_compress:
                    if os.path.isdir(file):
                        for root, dirs, files in os.walk(file):
                            for filename in files:
                                file_path = os.path.join(root, filename)
                                arcname = os.path.relpath(
                                    file_path, start=os.path.dirname(file)
                                )
                                zip_ref.write(file_path, arcname=arcname)
                    elif os.path.isfile(file):
                        arcname = os.path.basename(file)
                        zip_ref.write(file, arcname=arcname)
                    else:
                        raise ValueError(f"Invalid path: {file}")

            return f"Created zip file '{full_zip_path}' with specified files."
        except Exception as e:
            return f"Failed to create zip file '{zip_file_name}': {str(e)}"

    @tool(description="Add more files to an existing .zip file.")
    async def add_to_zip_file(
        self,
        zip_file_name: str,
        files_to_add: list[str],
        directory_path: str = None,
    ) -> str:
        """
        Add more files to an existing .zip file.

        Args:
            zip_file_name: The name of the zip file to add files to.
            files_to_add: List of files to add to the existing zip.
            directory_path: The path of the directory where the zip file is located.
        """
        directory_path = directory_path or self.default_directory
        if directory_path == "" or directory_path == ".":
            directory_path = self.default_directory

        full_zip_path = os.path.join(directory_path, zip_file_name)
        try:
            if not isinstance(files_to_add, list):
                files_to_add = [files_to_add]

            with zipfile.ZipFile(full_zip_path, "a", zipfile.ZIP_DEFLATED) as zip_ref:
                for file in files_to_add:
                    if os.path.isdir(file):
                        for root, dirs, files in os.walk(file):
                            for filename in files:
                                file_path = os.path.join(root, filename)
                                arcname = os.path.relpath(
                                    file_path, start=os.path.dirname(file)
                                )
                                zip_ref.write(file_path, arcname=arcname)
                    elif os.path.isfile(file):
                        arcname = os.path.basename(file)
                        zip_ref.write(file, arcname=arcname)
                    else:
                        raise ValueError(f"Invalid path: {file}")

            return f"Added specified files to zip file '{full_zip_path}'."
        except Exception as e:
            return f"Failed to add files to zip file '{full_zip_path}': {str(e)}"

    @tool(description="Extract all files contained in a specified .zip file.")
    async def extract_zip(self, zip_file_path: str, target_directory: str) -> str:
        """
        Extract all files contained in a specified .zip file to the specified target directory.

        Args:
            zip_file_path: The absolute path of the zip file to extract.
            target_directory: The absolute path of the target directory.
        """
        try:
            with zipfile.ZipFile(zip_file_path, "r") as zip_ref:
                zip_ref.extractall(path=target_directory)
                return f"Extracted {zip_file_path} contents to {target_directory}"

        except Exception as e:
            return f"Failed to extract contents of {zip_file_path}, error was {e}."

    def get_default_directory(self) -> str:
        return get_writable_dir("files")
