from api.interface import (
    SettingsConfig,
    WingmanConfig,
)
from providers.xvasynth import XVASynth
from providers.whispercpp import Whispercpp
from services.audio_player import AudioPlayer
from services.printr import Printr
from wingmen.open_ai_wingman import OpenAiWingman

printr = Printr()


class TutorialWingman(OpenAiWingman):
    """Tutorial Wingman
    """

    def __init__(
        self,
        name: str,
        config: WingmanConfig,
        settings: SettingsConfig,
        audio_player: AudioPlayer,
        whispercpp: Whispercpp,
        xvasynth: XVASynth,
    ):
        super().__init__(
            name=name,
            config=config,
            audio_player=audio_player,
            settings=settings,
            whispercpp=whispercpp,
            xvasynth=xvasynth,
        )

    async def validate(self):
        errors = await super().validate()

        return errors

    def build_tools(self) -> list[dict]:
        """
        Builds a tool for each command that is not instant_activation.

        Returns:
            list[dict]: A list of tool descriptors in OpenAI format.
        """
        tools = super().build_tools()

        return tools
