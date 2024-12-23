import threading
import time
import datetime
from os import path
from services.printr import Printr
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from skills.uexcorp_beta.uexcorp.helper import Helper
    except ModuleNotFoundError:
        from uexcorp_beta.uexcorp.helper import Helper

printr = Printr()

class DebugHandler:
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

    def write(self, content: str, print_to_console: bool = False):
        if not self.helper.is_debug():
            return
        if print_to_console:
            printr.print(content)
        with open(self.file, 'a') as f:
            f.write(f"{self.__get_debug_header()}: {content}")

    async def write_async(self, content: str, print_to_console: bool = False):
        if not self.helper.is_debug():
            return
        if print_to_console:
            await printr.print_async(content)
        with open(self.file, 'a') as f:
            f.write(f"{self.__get_debug_header()}: {content}")

    def read(self):
        with open(self.file, 'r') as f:
            return f.read()
