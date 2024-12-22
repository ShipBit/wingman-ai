from typing import TYPE_CHECKING
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill
try:
    from skills.uexcorp_beta.uexcorp.helper import Helper
except ImportError:
    from uexcorp_beta.uexcorp.helper import Helper

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman

class UEXCorpBeta(Skill):
    """Wingman AI Skill to utilize uexcorp api for bidirectional information transmission"""

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        self.__helper = Helper.get_instance()
        self.__helper.prepare(self.threaded_execution, self.wingman)
        self.__helper.get_handler_config().set_wingman(wingman)

    async def prepare(self) -> None:
        await super().prepare()
        self.__helper.set_loaded()
        self.threaded_execution(self.threaded_prepare)
        self.threaded_execution(self.loop_master)

    async def unload(self) -> None:
        await super().unload()
        self.__helper.set_loaded(False)

    def loop_master(self):
        # wait 2 minutes before starting the loop
        self.__helper.wait(120)
        self.__helper.get_handler_debug().write("Starting master loop with a 300s cycle")
        while self.__helper.is_loaded():
            if self.__helper.is_ready() and self.__helper.get_handler_import().get_imported_percent() == 100:
                self.__helper.get_handler_debug().write("Automated import data refresh by master loop.")
                self.__helper.ensure_version_parity()
                self.__helper.get_handler_import().import_data()
            self.__helper.wait(300)
        self.__helper.get_handler_debug().write("Stopping master loop")

    def threaded_prepare(self):
        self.__helper.get_handler_import().prepare()

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        errors = await self.__helper.get_handler_config().validate(errors, self.retrieve_custom_property_value)
        return errors

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = self.__helper.get_handler_tool().get_tools()
        return tools

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        function_response, instant_response = await self.__helper.get_handler_tool().execute_tool(tool_name, parameters)
        return function_response, instant_response

    async def is_waiting_response_needed(self, tool_name: str) -> bool:
        return True

    async def get_prompt(self) -> str:
        prompt = self.config.prompt or ""
        prompt += self.__helper.get_context()
        return prompt
