import datetime
from typing import TYPE_CHECKING
from api.interface import SettingsConfig, SkillConfig
from api.enums import LogType
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class TimeAndDateRetriever(Skill):
    """
    A simple skill that retrieves the current date and time.

    This skill demonstrates the new @tool decorator pattern which automatically
    generates the OpenAI tool schema from the function signature and docstring.
    """

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config, settings, wingman)

    @tool()
    def get_current_time_and_date(self) -> str:
        """Retrieves the current date and time for the user."""
        if self.settings.debug_mode:
            self.printr.print(
                text="DateTime Retriever: executing get_current_time_and_date",
                color=LogType.INFO,
            )

        now = datetime.datetime.now()
        return now.strftime("%Y-%m-%d %H:%M:%S")
