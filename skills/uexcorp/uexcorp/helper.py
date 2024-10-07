from os import path
from services.file import get_writable_dir
from skills.uexcorp.uexcorp.config import Config
from skills.uexcorp.uexcorp.dataaccess.dataaccess import DataAccess
from skills.uexcorp.uexcorp.debug_handler import DebugHandler
from skills.uexcorp.uexcorp.error_handler import ErrorHandler


class Helper:
    def __init__(self):
        self.data_path: str = get_writable_dir(path.join("skills", "uexcorp", "data"))
        self.data_access: DataAccess = DataAccess(self)
        self.handler_debug: DebugHandler = DebugHandler(self)
        self.handler_error: ErrorHandler = ErrorHandler(self)
        self.config: Config = Config(self)
        self.version_file_path: str = 'version'
        self.version: str = None
        self.debug: bool = False

    def get_data_path(self):
        return self.data_path

    def get_data_access(self):
        return self.data_access

    def get_handler_debug(self):
        return self.handler_debug

    def get_handler_error(self):
        return self.handler_error

    def get_config(self):
        return self.config

    def get_version(self):
        if not self.version:
            with open(self.version_file_path, 'r') as f:
                self.version = f.read()
        return self.version

    def is_debug(self):
        return self.debug