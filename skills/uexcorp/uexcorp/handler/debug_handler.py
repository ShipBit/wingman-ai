import os
import threading
import time
import datetime
from os import path
from services.printr import Printr
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from skills.uexcorp.uexcorp.helper import Helper

printr = Printr()

class DebugHandler:
    SOURCE_NAME = "UEXCorp"

    def __init__(
        self,
        helper: "Helper",
    ):
        self.helper = helper
        self.file = path.join(self.helper.get_data_path(), "debug.log")

    def get_debug_file_path(self):
        return self.file

    def __get_debug_header(self):
        timestamp = datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')
        thread_note = "" if threading.get_ident() == self.helper.get_default_thread_ident() else f" | Thread: {threading.current_thread().name}"
        return f"\n{timestamp} (Ver: {self.helper.get_version_skill_short()}{thread_note})"

    # One old file is kept: the log never grows past about twice this size
    MAX_SIZE = 5 * 1024 * 1024

    def write(self, content: str, print_to_console: bool = False):
        if not self.helper.is_debug():
            return
        if print_to_console:
            printr.print(content, source_name=self.SOURCE_NAME)
        self.__append(content)

    async def write_async(self, content: str, print_to_console: bool = False):
        if not self.helper.is_debug():
            return
        if print_to_console:
            await printr.print_async(content, source_name=self.SOURCE_NAME)
        self.__append(content)

    def __append(self, content: str):
        # UTF-8: game names like "Yāi" crash the cp1252 default on Windows
        try:
            if path.getsize(self.file) > self.MAX_SIZE:
                os.replace(self.file, self.file + ".1")
        except OSError:
            pass
        with open(self.file, "a", encoding="utf-8") as f:
            f.write(f"{self.__get_debug_header()}: {content}")

    def read(self):
        with open(self.file, "r", encoding="utf-8") as f:
            return f.read()
