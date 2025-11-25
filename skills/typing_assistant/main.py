import time
from typing import TYPE_CHECKING
from api.interface import SettingsConfig, SkillConfig
from api.enums import LogType
from skills.skill_base import Skill, tool
import keyboard.keyboard as keyboard

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class TypingAssistant(Skill):
    """
    A skill that types text into the active application window.

    Demonstrates the @tool decorator with multiple parameters,
    including an optional boolean parameter.
    """

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

    @tool(
        name="assist_with_typing",
        description="Identifies what the user wants the AI to type into an active application window. This may be either transcribing exactly what the user says or typing something the user wants the AI to imagine and then type. Also identifies whether to end the typed content with a press of the Enter / Return key, common typically for typing a response to a chat message or form field.",
    )
    def assist_with_typing(
        self, content_to_type: str, end_by_pressing_enter: bool = False
    ) -> str:
        """
        Args:
            content_to_type: The content the user wants the assistant to type.
            end_by_pressing_enter: Whether the typed content should end by pressing the enter key. Default False. Typically True when typing a response in a chat program.
        """
        if self.settings.debug_mode:
            self.printr.print(
                text=f"TypingAssistant: typing '{content_to_type[:50]}...'",
                color=LogType.INFO,
            )

        keyboard.write(content_to_type, delay=0.01, hold=0.01)

        if end_by_pressing_enter:
            keyboard.press("enter")
            time.sleep(0.2)
            keyboard.release("enter")

        return "Typed user request at active mouse cursor position."
