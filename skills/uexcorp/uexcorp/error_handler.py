import time
from os import path
from helper import Helper


class ErrorHandler:
    def __init__(
        self,
        helper: Helper
    ):
        self.helper = helper
        self.file = path.join(self.helper.get_data_path(), "error.log")

    def get_error_file_path(self):
        return self.file

    def __get_error_header(self, function: str, arguments: list):
        timestamp = time.time()
        header  = f"\n\n======================================"
        header += f"\nTimestamp: {timestamp}"
        header += f"\nSkill version: {self.helper.get_version()}"
        header += f"\nCalled function: {function}"
        header += f"\nArguments: {arguments}"
        header += f"\n======================================"
        return header

    def write_error(self, function: str, arguments: list, error):
        with open(self.file, 'a') as f:
            f.write(self.__get_error_header(function, arguments))
            f.write(error)

    def read_debug(self):
        with open(self.file, 'r') as f:
            return f.read()
        