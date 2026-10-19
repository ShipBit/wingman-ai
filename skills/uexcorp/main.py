import asyncio
import time
import uuid

from services.benchmark import Benchmark

from typing import TYPE_CHECKING
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill
from skills.uexcorp.uexcorp.helper import Helper

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext


class UEXCorp(Skill):
    """Wingman AI Skill to utilize uexcorp api for bidirectional information transmission"""

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "WingmanContext",
    ) -> None:
        self.random_seed = uuid.uuid4()
        super().__init__(config=config, settings=settings, wingman=wingman)
        self.__helper: Helper = Helper.get_instance()
        # Data, trade run and HUD panel are shared, so one Wingman owns the skill: the one that
        # activates it (validate), not the first one created. Created early, the download starts.
        if not self.__helper.is_prepared():
            self.__helper.prepare(self.wingman.run_in_thread, self.wingman)
            wingman.run_in_thread(self.threaded_prepare, True)
        self.__invalid_session = False

    def __claim(self) -> bool:
        """Takes the shared helper for this Wingman. False while another Wingman owns it."""
        if Helper.get_instance() is not self.__helper:
            # The owner unloaded and ended it: a new one takes its place
            self.__helper = Helper.get_instance()
        if not self.__helper.is_prepared():
            self.__helper.prepare(self.wingman.run_in_thread, self.wingman)
        owner = self.__helper.get_owner()
        if owner is not None and owner != self.wingman.name:
            return False
        self.__helper.claim(self.wingman)
        return True

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        self.__invalid_session = not self.__claim()
        if self.__invalid_session:
            # Not an error: the Wingman says so on a tool call, and takes over once the owner is gone
            self.__helper.get_handler_debug().write(
                f"Please ensure that only one instance of UEXCorp skill is initialized at a time, that's a current limitation. Currently activated in {self.__helper.get_owner()}",
                True,
            )
            return errors

        errors = await self.__helper.get_handler_config().validate(
            errors, self.retrieve_custom_property_value
        )
        return errors

    async def prepare(self) -> None:
        await super().prepare()
        if self.__invalid_session or not self.__helper:
            return
        await self.__start()

    async def __start(self) -> None:
        self.__helper.set_loaded()
        # The preload import started in __init__ may still run (even at 0 %, during its first table)
        if self.__helper.get_handler_import().is_running():
            self.__helper.get_handler_import().request_completion()
            self.__helper.get_handler_debug().write(
                "Skill is still in preload phase, skipping initial import on load and removing preload flag.",
            )
        else:
            self.wingman.run_in_thread(self.threaded_prepare)
        self.wingman.run_in_thread(self.loop_master)
        # A trade run survives restarts: show its current stop again
        from skills.uexcorp.uexcorp.active_trade_route import ActiveTradeRoute
        await ActiveTradeRoute(self.__helper).refresh_hud()

    async def unload(self) -> None:
        await super().unload()
        # Only the owner ends the shared helper (by identity: a reloaded Wingman of the same name
        # may already have claimed it)
        if self.__invalid_session or not self.__helper or self.__helper.get_wingmen() is not self.wingman:
            return
        self.__helper.set_loaded(False)
        try:
            from skills.uexcorp.uexcorp.active_trade_route import HUD_TITLE
            await self.wingman.hud.remove_info(HUD_TITLE)
        except Exception:
            pass
        # destroy() stops a running import and waits until its current request/DB writes are done
        await asyncio.to_thread(Helper.destroy_instance)

    REFRESH_EVERY = 600  # seconds, with data
    RETRY_EVERY = 60  # seconds, while there is no data (source unreachable on a fresh install)

    def loop_master(self):
        helper = self.__helper
        helper.get_handler_debug().write(
            f"Starting master loop: refresh every {self.REFRESH_EVERY}s, every {self.RETRY_EVERY}s without data"
        )
        last_run = time.monotonic()
        # wait() returns True on unload: the loop ends right away instead of after a cycle
        while helper.is_loaded() and not helper.wait(self.RETRY_EVERY):
            try:
                importer = helper.get_handler_import()
                if importer.is_running():
                    continue
                due = self.REFRESH_EVERY if importer.has_data() else self.RETRY_EVERY
                if time.monotonic() - last_run < due:
                    continue
                last_run = time.monotonic()
                helper.get_handler_debug().write("Automated import data refresh by master loop.")
                helper.ensure_version_parity()
                importer.import_data()
            except Exception as e:
                # One failed round must not end the refreshes for the rest of the session
                helper.get_handler_error().write("UEXCorp.loop_master", [], e)
                helper.get_handler_debug().write(f"Master loop round failed, trying again next round: {e}")
        helper.get_handler_debug().write("Stopping master loop")

    def threaded_prepare(self, preload: bool = False) -> None:
        self.__helper.get_handler_debug().write(
            "Threaded prepare started | Preload: " + str(preload),
        )
        self.__helper.get_handler_import().prepare(preload)

    def get_tools(self) -> list[tuple[str, dict]]:
        if not self.__helper:
            return []
        tools = self.__helper.get_handler_tool().get_tools()
        return tools

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any], benchmark: Benchmark
    ) -> tuple[str, str]:
        if self.__invalid_session:
            # The owner may be gone since (Wingman disabled, config switched): then take over
            if not self.__claim():
                return (
                    f"Inform the user, that the UEXCorp skill is already initialized with '{self.__helper.get_owner()}'. The user should ensure only one wingman has an activated UEXCorp skill. Currently activated in another wingman named '{self.__helper.get_owner()}'.",
                    "",
                )
            self.__invalid_session = False
            # This Wingman's own settings (validate() stopped at the claim back then)
            await self.__helper.get_handler_config().validate([], self.retrieve_custom_property_value)
            await self.__start()

        benchmark.start_snapshot(f"UEXCorp: {tool_name}")
        function_response, instant_response = (
            await self.__helper.get_handler_tool().execute_tool(tool_name, parameters)
        )
        benchmark.finish_snapshot()
        return function_response, instant_response

    async def is_waiting_response_needed(self, tool_name: str) -> bool:
        return True

    async def get_prompt(self) -> str:
        prompt = self.config.prompt or ""
        if self.__helper:
            prompt += self.__helper.get_context()
        return prompt
