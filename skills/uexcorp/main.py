import sys
import os
import uuid

from api.enums import WingmanInitializationErrorType
from services.benchmark import Benchmark

# add skill to sys path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import TYPE_CHECKING
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill
from skills.uexcorp.uexcorp.helper import Helper

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class UEXCorp(Skill):
    """Wingman AI Skill to utilize uexcorp api for bidirectional information transmission"""

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        self.random_seed = uuid.uuid4()
        super().__init__(config=config, settings=settings, wingman=wingman)
        self.__helper: Helper = Helper.get_instance()
        self.__helper.prepare(self.threaded_execution, self.wingman)
        self.__invalid_session = False
        self.__initialized = False

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        # Lazy initialization of Helper singleton - only when skill is actually validated/activated
        if not self.__initialized:
            if (
                self.__helper.get_wingmen() is not None
                and self.__helper.get_wingmen() != self.wingman
            ):
                self.__helper.get_handler_debug().write(
                    f"Please ensure that only one instance of UEXCorp skill is initialized at a time, that's a current limitation. Currently activated in {self.__helper.get_wingmen().name}",
                    True,
                )
                self.__invalid_session = True
            self.__initialized = True
        if self.__invalid_session:
            # We will let it slide here but inform on skill call.
            # errors.append(
            #     WingmanInitializationError(
            #         wingman_name=self.wingman.name,
            #         message=f"The UEXCorp skill is already initialized with '{self.__helper.get_wingmen().name}'.",
            #         error_type=WingmanInitializationErrorType.UNKNOWN,
            #     )
            # )
            return errors

        errors = await self.__helper.get_handler_config().validate(
            errors, self.retrieve_custom_property_value
        )
        return errors

    async def prepare(self) -> None:
        await super().prepare()
        if self.__invalid_session or not self.__helper:
            return
        self.__helper.set_loaded()
        self.threaded_execution(self.threaded_prepare)
        self.threaded_execution(self.loop_master)

    async def unload(self) -> None:
        await super().unload()
        if self.__invalid_session or not self.__helper:
            return
        self.__helper.set_loaded(False)
        Helper.destroy_instance()

    def loop_master(self):
        cycle = 600
        self.__helper.wait(cycle)
        self.__helper.get_handler_debug().write(
            f"Starting master loop with a {cycle}s cycle"
        )
        while self.__helper.is_loaded():
            if (
                self.__helper.is_ready()
                and self.__helper.get_handler_import().get_imported_percent() == 100
            ):
                self.__helper.get_handler_debug().write(
                    "Automated import data refresh by master loop."
                )
                self.__helper.ensure_version_parity()
                self.__helper.get_handler_import().import_data()
            self.__helper.wait(cycle)
        self.__helper.get_handler_debug().write("Stopping master loop")

    def threaded_prepare(self):
        self.__helper.get_handler_import().prepare()

    def get_tools(self) -> list[tuple[str, dict]]:
        if not self.__helper:
            return []
        tools = self.__helper.get_handler_tool().get_tools()
        return tools

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any], benchmark: Benchmark
    ) -> tuple[str, str]:
        if self.__invalid_session:
            return (
                f"Inform the user, that the UEXCorp skill is already initialized with '{self.__helper.get_wingmen().name}'. The user should ensure only one wingman has an activated UEXCorp skill. Currently activated in another wingman named '{self.__helper.get_wingmen().name}'.",
                "",
            )

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
