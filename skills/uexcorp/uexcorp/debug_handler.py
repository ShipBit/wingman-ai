import time
from os import path
from helper import Helper


class DebugHandler:
    def __init__(
        self,
        helper: Helper,
    ):
        self.helper = helper
        self.file = path.join(self.helper.get_data_path(), "debug.log")

    def get_debug_file_path(self):
        return self.file

    def __get_debug_header(self):
        timestamp = time.time()
        return f"\n{timestamp} ({self.helper.get_version()})"

    def write_debug(self, content: str):
        if not self.helper.is_debug():
            return
        with open(self.file, 'a') as f:
            f.write(f"{self.__get_debug_header()}: {content}")

    def read_debug(self):
        with open(self.file, 'r') as f:
            return f.read()
