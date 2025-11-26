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
        description="""Types text into the user's active application window.

        WHEN TO USE:
        - User asks to type/dictate something: 'Type...', 'Write...'
        - User wants content generated and typed: 'Type a poem about...', 'Write an email about...'

        Handles both exact dictation and creative content generation.
        Can optionally press Enter after typing (common for chat messages).""",
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
