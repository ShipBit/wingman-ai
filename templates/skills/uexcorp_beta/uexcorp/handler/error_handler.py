import threading
import time
from os import path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from skills.uexcorp_beta.uexcorp.helper import Helper
    except ModuleNotFoundError:
        from uexcorp_beta.uexcorp.helper import Helper


class ErrorHandler:
    def __init__(
        self,
        helper: "Helper",
    ):
        self.helper = helper
        self.file = path.join(self.helper.get_data_path(), "error.log")

    def get_error_file_path(self):
        return self.file

    def __get_error_header(self, function: str, arguments: list):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        header  = f"\n\n======================================"
        header += f"\nTimestamp: {timestamp}"
        header += f"\nSkill version: {self.helper.get_version_skill()}"
        header += f"\nThread: {threading.current_thread().name}"
        header += f"\nCalled function: {function}"
        header += f"\nArguments: {arguments}"
        header += f"\n======================================\n"
        return header

    def write(self, function: str, arguments: list|dict[str, any], error, traceback: str | None = None):
        with open(self.file, 'a') as f:
            f.write(self.__get_error_header(function, arguments))
            f.write(str(error))
            if traceback:
                f.write(traceback)

    def read(self):
        with open(self.file, 'r') as f:
            return f.read()
        