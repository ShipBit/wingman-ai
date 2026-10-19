import asyncio
import datetime
import threading
import time
from typing import TYPE_CHECKING
from os import path
from services.file import get_writable_dir
from services.printr import Printr

from skills.uexcorp.uexcorp.handler.config_handler import ConfigHandler
from skills.uexcorp.uexcorp.database.database import Database
from skills.uexcorp.uexcorp.handler.import_handler import ImportHandler
from skills.uexcorp.uexcorp.handler.debug_handler import DebugHandler
from skills.uexcorp.uexcorp.handler.error_handler import ErrorHandler
from skills.uexcorp.uexcorp.api.llm import Llm

if TYPE_CHECKING:
    from skills.uexcorp.uexcorp.handler.tool_handler import ToolHandler
    from wingmen.wingman_context import WingmanContext

printr = Printr()

class Helper:

    _instance = None

    @classmethod
    def get_instance(cls) -> "Helper":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def destroy_instance(cls):
        if cls._instance is not None:
            cls._instance.stop()
            if cls._instance.get_handler_import():
                cls._instance.get_handler_import().destroy()
            if cls._instance.get_database():
                cls._instance.get_database().destroy()
        cls._instance = None

    def stop(self):
        """Ends waits of the background loop at once (unload)."""
        self.__stop_event.set()

    def __init__(self):
        self.__is_loaded = None
        self.__data_path: str = get_writable_dir(path.join("skills", "uexcorp", "data"))
        self.__version_skill: str = 'v3.0.0-20261018'
        self.__version_uex: str | None = None
        self.__debug: bool = True
        self.__default_thread = threading.get_ident()
        self.__handler_debug: DebugHandler = DebugHandler(self)
        self.__handler_debug.write(
            "===================================== INIT ====================================="
        )
        self.__handler_error: ErrorHandler = ErrorHandler(self)
        self.__handler_config: ConfigHandler = ConfigHandler(self)
        self.__handler_tool = None
        self.__handler_import: ImportHandler | None = None
        self.__database: Database | None = None
        self.__llm: Llm | None = None
        self.__timers = {}
        self.__additional_context = []
        self.__threaded_execution: callable | None = None
        self.__is_ready = False
        self.__request_while_not_ready = False
        self.__data_pool_recreated = False
        self.__wingman = None
        self.__owner: str | None = None  # name of the Wingman that activated the skill
        self.__stop_event = threading.Event()

    def prepare(self, threaded_execution: callable, wingman: "WingmanContext"):
        from skills.uexcorp.uexcorp.handler.tool_handler import ToolHandler

        self.__wingman = wingman
        self.get_handler_config().set_wingman(self.__wingman)
        self.__threaded_execution = threaded_execution
        self.__database: Database = Database(
            self.__data_path, self.get_version_skill(), self
        )
        self.__handler_import: ImportHandler = ImportHandler(self)
        self.__handler_tool: ToolHandler = ToolHandler(self)
        self.__llm: Llm = Llm(self)

    def is_prepared(self) -> bool:
        return self.__handler_import is not None

    def get_owner(self) -> str | None:
        return self.__owner

    def claim(self, wingman: "WingmanContext"):
        """The Wingman that activated the skill owns it: its context (HUD, System One) is used."""
        self.__owner = wingman.name
        self.__wingman = wingman
        self.get_handler_config().set_wingman(wingman)

    def ensure_version_parity(self, force_check: bool = False):
        if force_check:
            self.__handler_debug.write("Forced version parity check ...")

        old_version_skill = self.__version_skill
        old_version_uex = self.get_version_uex()

        if (
            old_version_skill != self.get_version_skill()
            or old_version_uex != self.get_version_uex(force_check)
        ):
            self.__handler_debug.write(f"UEX/Skill version parity lost.", True)
            self.__handler_debug.write(
                f"UEX functions will be unavailable for a moment. Recreating data pool ...",
                True,
            )
            self.__handler_debug.write(
                f"Versions: Skill: {old_version_skill} -> {self.__version_skill} | UEX: {old_version_uex} -> {self.__version_uex}"
            )
            self.set_ready(False)
            self.get_database().recreate_database()
            self.__data_pool_recreated = True
        elif force_check:
            self.__handler_debug.write(
                f"Version parity is still given. Skill: {old_version_skill} | UEX: {old_version_uex}"
            )

    def on_import_completed(self, imported_rows_count: int):
        # Only called with data (ImportHandler.import_data)
        self.get_handler_config().sync_blacklists()
        self.__version_uex = self.get_handler_import().get_version_uex()
        self.set_ready(True)
        # Location names are matched on almost every call: embed them now, not on the first voice request
        self.run_in_thread(self.__warm_up_location_embeddings)
        if self.__data_pool_recreated:
            self.__data_pool_recreated = False
            self.__handler_debug.write(
                f"UEX/Skill version parity restored. UEX functions are available again.",
                True,
            )

    def __warm_up_location_embeddings(self):
        from skills.uexcorp.uexcorp.tool.validator import Validator

        if self.__stop_event.is_set():
            return
        try:
            self.start_timer("embeddings")
            names = set(Validator.location_names(True)) | set(Validator.location_names(False))
            if self.get_llm().embed_names(names):
                self.__handler_debug.write(f"Location names embedded: {len(names)} in {self.end_timer('embeddings')}s")
            else:
                self.__handler_debug.write("No embedding model available, location names are matched without it.")
        except Exception as e:
            # After an unload the database is closed: nothing to tell the user
            self.__handler_debug.write(f"Embedding location names failed: {e}", not self.__stop_event.is_set())

    def wait(self, seconds: float) -> bool:
        """Blocking wait, for worker threads only. True when the skill was unloaded meanwhile."""
        return self.__stop_event.wait(seconds)

    async def wait_async(self, seconds: float):
        await asyncio.sleep(seconds)

    def is_ready(self) -> bool:
        return self.__is_ready

    def set_ready(self, ready: bool = True):
        self.__is_ready = ready
        # The import already told the user the data is back ("reachable again"): no second notice
        if ready and self.get_request_while_not_ready():
            self.set_request_while_not_loaded(False)

    def is_loaded(self) -> bool:
        return self.__is_loaded

    def set_loaded(self, loaded: bool = True):  #
        if loaded:
            self.__handler_debug.write(
                "===================================== LOAD ====================================="
            )
        else:
            self.__handler_debug.write(
                "===================================== UNLOAD ====================================="
            )
        self.__is_loaded = loaded

    def set_request_while_not_loaded(self, request: bool):
        self.__request_while_not_ready = request

    def get_request_while_not_ready(self) -> bool:
        return self.__request_while_not_ready

    def start_timer(self, id: str = "default"):
        self.__timers[id] = self.get_timestamp()

    def end_timer(self, id: str = "default") -> int:
        if id not in self.__timers:
            self.get_handler_debug().write(
                f"Tried to end a non existent timer with id '{id}'"
            )
            return 0
        duration = self.get_timestamp() - self.__timers[id]
        del self.__timers[id]
        return duration

    def get_data_path(self) -> str:
        return self.__data_path

    def get_database(self) -> Database:
        return self.__database

    def get_handler_import(self) -> ImportHandler:
        return self.__handler_import

    def get_handler_debug(self) -> DebugHandler:
        return self.__handler_debug

    def get_handler_error(self) -> ErrorHandler:
        return self.__handler_error

    def get_handler_config(self) -> ConfigHandler:
        return self.__handler_config

    def get_handler_tool(self) -> "ToolHandler":
        return self.__handler_tool

    def is_debug(self) -> bool:
        return self.__debug

    def get_version_skill(self, force_check: bool = False) -> str:
        return self.__version_skill

    def get_version_skill_short(self):
        return self.get_version_skill().split("-")[0]

    def get_version_uex(self, force_check: bool = False):
        from skills.uexcorp.uexcorp.model.game_version import GameVersion

        if force_check:
            self.__version_uex = self.__handler_import.get_version_uex(force_check)
        elif not self.__version_uex:
            self.__version_uex = GameVersion(load=True).get_live()
        return self.__version_uex

    def get_timestamp(self) -> int:
        return int(datetime.datetime.now().timestamp())

    MAX_CONTEXT_NOTES = 10

    def add_context(self, context: str):
        # Name hints ("Use 'X' instead of 'Y'") go into every prompt: only the latest few, no repeats
        if context in self.__additional_context:
            self.__additional_context.remove(context)
        self.__additional_context.append(context)
        del self.__additional_context[:-self.MAX_CONTEXT_NOTES]
        self.get_handler_debug().write(f"Added context: {context}")

    def get_context(self) -> str:
        context = ""
        if self.get_handler_tool().get_tool_help_prompt():
            context += "\n\n" + self.get_handler_tool().get_tool_help_prompt()
        if self.__additional_context:
            context += "\n\n" + "\n".join(self.__additional_context)
        return context

    def run_in_thread(self, function, *args) -> threading.Thread:
        if not self.__threaded_execution:
            raise Exception("Threaded execution not prepared")
        return self.__threaded_execution(function, *args)

    def get_llm(self) -> Llm:
        return self.__llm

    def get_default_thread_ident(self) -> int:
        return self.__default_thread

    def get_wingmen(self) -> "WingmanContext":
        return self.__wingman

    def toast(self, message: str):
        printr.toast_info(message)
