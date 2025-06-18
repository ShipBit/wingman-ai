import datetime
import threading
import time
from typing import TYPE_CHECKING
from os import path
from services.file import get_writable_dir
from services.printr import Printr
from services.secret_keeper import SecretKeeper

try:
    from skills.uexcorp.uexcorp.handler.config_handler import ConfigHandler
    from skills.uexcorp.uexcorp.database.database import Database
    from skills.uexcorp.uexcorp.handler.import_handler import ImportHandler
    from skills.uexcorp.uexcorp.handler.debug_handler import DebugHandler
    from skills.uexcorp.uexcorp.handler.error_handler import ErrorHandler
    from skills.uexcorp.uexcorp.api.llm import Llm
except ModuleNotFoundError:
    from uexcorp.uexcorp.handler.config_handler import ConfigHandler
    from uexcorp.uexcorp.database.database import Database
    from uexcorp.uexcorp.handler.import_handler import ImportHandler
    from uexcorp.uexcorp.handler.debug_handler import DebugHandler
    from uexcorp.uexcorp.handler.error_handler import ErrorHandler
    from uexcorp.uexcorp.api.llm import Llm

if TYPE_CHECKING:
    try:
        from skills.uexcorp.uexcorp.handler.tool_handler import ToolHandler
    except ModuleNotFoundError:
        from uexcorp.uexcorp.handler.tool_handler import ToolHandler
    from wingmen.open_ai_wingman import OpenAiWingman

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
            cls._instance.get_handler_import().destroy()
            cls._instance.get_database().destroy()
            cls._instance.sync_fasterwhisper_hotwords(unload=True)
        cls._instance = None

    def __init__(self):
        self.__is_loaded = None
        self.__data_path: str = get_writable_dir(path.join("skills", "uexcorp", "data"))
        self.__version_file_path: str = get_writable_dir(path.join("skills", "uexcorp"))
        self.__version_file_name: str = "version"
        self.__version_skill: str | None = None
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
        self.__secret_keeper = SecretKeeper()
        self.__secret_keeper.secret_events.subscribe(
            "secrets_saved", self.on_secret_changed
        )
        self.__request_while_not_ready = False
        self.__wingman = None

    def prepare(self, threaded_execution: callable, wingman: "OpenAiWingman"):
        try:
            from skills.uexcorp.uexcorp.handler.tool_handler import ToolHandler
        except ModuleNotFoundError:
            from uexcorp.uexcorp.handler.tool_handler import ToolHandler

        self.__wingman = wingman
        self.__threaded_execution = threaded_execution
        self.__database: Database = Database(
            self.__data_path, self.get_version_skill(), self
        )
        self.__handler_import: ImportHandler = ImportHandler(self)
        self.__handler_tool: ToolHandler = ToolHandler(self)
        self.__llm: Llm = Llm(self)

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
            self.set_ready(True)
            self.get_database().recreate_database()
        elif force_check:
            self.__handler_debug.write(
                f"Version parity is still given. Skill: {old_version_skill} | UEX: {old_version_uex}"
            )

    def on_secret_changed(self, secrets: dict[str, any]):
        if "uex" in secrets:
            self.__handler_config.handle_secret_change(secrets["uex"])

    def on_import_completed(self, imported_rows_count: int):
        self.get_handler_config().sync_blacklists()
        self.__version_uex = self.get_handler_import().get_version_uex()
        self.set_ready(True)

    def sync_fasterwhisper_hotwords(self, unload: bool = False):
        if not self.get_handler_config().get_behavior_use_fasterwhisper_hotwords():
            return

        self.__handler_debug.write(
            f"{'Unloading' if unload else 'Syncing'} UEX unique names with FasterWhisper hotword list..."
        )
        try:
            from skills.uexcorp.uexcorp.data_access.city_data_access import (
                CityDataAccess,
            )
            from skills.uexcorp.uexcorp.data_access.commodity_data_access import (
                CommodityDataAccess,
            )
            from skills.uexcorp.uexcorp.data_access.company_data_access import (
                CompanyDataAccess,
            )
            from skills.uexcorp.uexcorp.data_access.item_data_acceess import (
                ItemDataAccess,
            )
            from skills.uexcorp.uexcorp.data_access.moon_data_access import (
                MoonDataAccess,
            )
            from skills.uexcorp.uexcorp.data_access.outpost_data_access import (
                OutpostDataAccess,
            )
            from skills.uexcorp.uexcorp.data_access.planet_data_access import (
                PlanetDataAccess,
            )
            from skills.uexcorp.uexcorp.data_access.poi_data_access import PoiDataAccess
            from skills.uexcorp.uexcorp.data_access.space_station_data_access import (
                SpaceStationDataAccess,
            )
            from skills.uexcorp.uexcorp.data_access.star_system_data_access import (
                StarSystemDataAccess,
            )
            from skills.uexcorp.uexcorp.data_access.terminal_data_access import (
                TerminalDataAccess,
            )
            from skills.uexcorp.uexcorp.data_access.vehicle_data_access import (
                VehicleDataAccess,
            )
        except ModuleNotFoundError:
            from uexcorp.uexcorp.data_access.city_data_access import CityDataAccess
            from uexcorp.uexcorp.data_access.commodity_data_access import (
                CommodityDataAccess,
            )
            from uexcorp.uexcorp.data_access.company_data_access import (
                CompanyDataAccess,
            )
            from uexcorp.uexcorp.data_access.item_data_acceess import ItemDataAccess
            from uexcorp.uexcorp.data_access.moon_data_access import MoonDataAccess
            from uexcorp.uexcorp.data_access.outpost_data_access import (
                OutpostDataAccess,
            )
            from uexcorp.uexcorp.data_access.planet_data_access import PlanetDataAccess
            from uexcorp.uexcorp.data_access.poi_data_access import PoiDataAccess
            from uexcorp.uexcorp.data_access.space_station_data_access import (
                SpaceStationDataAccess,
            )
            from uexcorp.uexcorp.data_access.star_system_data_access import (
                StarSystemDataAccess,
            )
            from uexcorp.uexcorp.data_access.terminal_data_access import (
                TerminalDataAccess,
            )
            from uexcorp.uexcorp.data_access.vehicle_data_access import (
                VehicleDataAccess,
            )

        data_access_instances = [
            CityDataAccess(),
            CommodityDataAccess(),
            # CompanyDataAccess(),
            # ItemDataAccess(),
            MoonDataAccess(),
            # OutpostDataAccess(),
            PlanetDataAccess(),
            # PoiDataAccess(),
            SpaceStationDataAccess(),
            StarSystemDataAccess(),
            # TerminalDataAccess(),
            VehicleDataAccess(),
        ]

        wingman = self.get_wingmen()
        wingman_hotwords = wingman.config.fasterwhisper.additional_hotwords or []
        original_hotwords_count = len(wingman_hotwords)

        uex_hotwords = ["UEX"]
        for data_access in data_access_instances:
            data = data_access.load()
            for item in data:
                item_name = str(item).strip()
                if item_name:
                    uex_hotwords.append(item_name)
        uex_hotwords = list(set(uex_hotwords)) # remove duplicates

        if unload:
            wingman_hotwords = [word for word in wingman_hotwords if word not in uex_hotwords]
        else:
            wingman_hotwords.extend(uex_hotwords)
            wingman_hotwords = list(set(wingman_hotwords))

        self.get_wingmen().config.fasterwhisper.additional_hotwords = wingman_hotwords
        hotword_change = len(wingman_hotwords) - original_hotwords_count
        if hotword_change < 0:
            self.__handler_debug.write(
                f"Removed {abs(hotword_change)} hotwords from FasterWhisper."
            )
        elif hotword_change > 0:
            self.__handler_debug.write(
                f"Synced {hotword_change} new hotwords with FasterWhisper."
            )
        else:
            self.__handler_debug.write(
                "No new hotwords synced with FasterWhisper."
            )

    def wait(self, seconds: int):
        time.sleep(seconds)

    def is_ready(self) -> bool:
        return self.__is_ready

    def set_ready(self, ready: bool = True):
        self.__is_ready = ready

        async def add_loaded_message():
            await self.get_wingmen().add_assistant_message(
                "UEX skill is now loaded and ready to use."
            )

        if ready and self.get_request_while_not_ready():
            self.__handler_debug.write("UEX functions are available now.", True)
            self.threaded_execution(add_loaded_message)
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

    def get_handler_secret(self) -> SecretKeeper:
        return self.__secret_keeper

    def is_debug(self) -> bool:
        return self.__debug

    def get_version_skill(self, force_check: bool = False) -> str:
        if not self.__version_skill or force_check:
            with open(
                path.join(self.__version_file_path, self.__version_file_name), "r"
            ) as f:
                self.__version_skill = f"{f.read()}"
        return self.__version_skill

    def get_version_skill_short(self):
        return self.get_version_skill().split("-")[0]

    def get_version_uex(self, force_check: bool = False):
        try:
            from skills.uexcorp.uexcorp.model.game_version import GameVersion
        except ModuleNotFoundError:
            from uexcorp.uexcorp.model.game_version import GameVersion

        if force_check:
            self.__version_uex = self.__handler_import.get_version_uex(force_check)
        elif not self.__version_uex:
            self.__version_uex = GameVersion(load=True).get_live()
        return self.__version_uex

    def get_timestamp(self) -> int:
        return int(datetime.datetime.now().timestamp())

    def add_context(self, context: str):
        self.__additional_context.append(context)
        self.get_handler_debug().write(f"Added context: {context}")

    def get_context(self) -> str:
        context = ""
        if self.get_handler_tool().get_tool_help_prompt():
            context += "\n\n" + self.get_handler_tool().get_tool_help_prompt()
        if self.__additional_context:
            context += "\n\n" + "\n".join(self.__additional_context)
        return context

    def threaded_execution(self, function, *args) -> threading.Thread:
        if not self.__threaded_execution:
            raise Exception("Threaded execution not prepared")
        return self.__threaded_execution(function, args)

    def get_llm(self) -> Llm:
        return self.__llm

    def get_default_thread_ident(self) -> int:
        return self.__default_thread

    def get_wingmen(self) -> "OpenAiWingman":
        return self.__wingman

    def toast(self, message: str):
        printr.toast_info(message)
