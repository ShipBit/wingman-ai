from api.enums import LogSource, LogType, WingmanInitializationErrorType
from api.interface import (
    Config,
    SettingsConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from services.audio_player import AudioPlayer
from services.module_manager import ModuleManager
from services.printr import Printr
from wingmen.open_ai_wingman import OpenAiWingman
from wingmen.wingman import Wingman


printr = Printr()


class Tower:
    def __init__(self, config: Config, audio_player: AudioPlayer):
        self.audio_player = audio_player
        self.config = config
        self.mouse_wingman_dict: dict[str, Wingman] = {}
        self.wingmen: list[Wingman] = []
        self.disabled_wingmen: list[WingmanConfig] = []
        self.log_source_name = "Tower"

    async def instantiate_wingmen(self, settings: SettingsConfig):
        errors: list[WingmanInitializationError] = []

        if not self.config.wingmen:
            return errors

        for wingman_name, wingman_config in self.config.wingmen.items():
            if wingman_config.disabled is True:
                self.disabled_wingmen.append(wingman_config)
                printr.print(
                    f"Skipped instantiating disabled wingman {wingman_config.name}.",
                    color=LogType.WARNING,
                    server_only=True,
                    source_name=self.log_source_name,
                    source=LogSource.SYSTEM,
                )
                continue

            _wingman = await self.__instantiate_wingman(
                wingman_name=wingman_name,
                wingman_config=wingman_config,
                settings=settings,
                errors=errors,
            )

        printr.print(
            f"Instantiated wingmen: {', '.join([w.name for w in self.wingmen])}.",
            color=LogType.INFO,
            server_only=True,
            source_name=self.log_source_name,
            source=LogSource.SYSTEM,
        )
        return errors

    async def __instantiate_wingman(
        self,
        wingman_name: str,
        wingman_config: WingmanConfig,
        settings: SettingsConfig,
        errors: list[WingmanInitializationError],
    ):
        wingman = None
        try:
            # it's a custom Wingman
            if wingman_config.custom_class:
                wingman = ModuleManager.create_wingman_dynamically(
                    name=wingman_name,
                    config=wingman_config,
                    settings=settings,
                    audio_player=self.audio_player,
                )
            else:
                wingman = OpenAiWingman(
                    name=wingman_name,
                    config=wingman_config,
                    settings=settings,
                    audio_player=self.audio_player,
                )
        except FileNotFoundError as e:  # pylint: disable=broad-except
            wingman_config.disabled = True
            self.disabled_wingmen.append(wingman_config)
            printr.print(
                f"Could not instantiate {wingman_name}:\n{str(e)}",
                color=LogType.WARNING,
                server_only=True,
                source_name=self.log_source_name,
                source=LogSource.SYSTEM,
            )
        except Exception as e:  # pylint: disable=broad-except
            wingman_config.disabled = True
            self.disabled_wingmen.append(wingman_config)
            # just in case we missed something
            msg = str(e).strip() or type(e).__name__
            errors.append(
                WingmanInitializationError(
                    wingman_name=wingman_name,
                    message=msg,
                    error_type=WingmanInitializationErrorType.UNKNOWN,
                )
            )
        else:
            # additional validation check if no exception was raised
            validation_errors = await wingman.validate()
            errors.extend(validation_errors)

            # init and validate skills
            skill_errors = await wingman.init_skills()

            if not errors or len(errors) == 0:
                await wingman.prepare()
                self.wingmen.append(wingman)

            # Mouse
            button = wingman.get_record_button()
            if button:
                self.mouse_wingman_dict[button] = wingman

        return wingman

    def get_wingman_from_mouse(self, mouse: any) -> Wingman | None:  # type: ignore
        wingman = self.mouse_wingman_dict.get(mouse, None)
        return wingman

    def get_wingman_from_text(self, text: str) -> Wingman | None:
        for wingman in self.wingmen:
            # Check if a wingman name is in the text
            if wingman.config.name.lower() in text.lower():
                return wingman

        # Check if there is a default wingman defined in the config
        for wingman in self.wingmen:
            if wingman.config.is_voice_activation_default:
                return wingman

        return None

    def get_wingman_by_name(self, wingman_name: str):
        for wingman in self.wingmen:
            if wingman.config.name == wingman_name:
                return wingman
        return None

    def get_disabled_wingman_by_name(self, wingman_name: str):
        for wingman_config in self.disabled_wingmen:
            if wingman_config.name == wingman_name:
                return wingman_config
        return None

    async def enable_wingman(
        self,
        wingman_name: str,
        settings: SettingsConfig,
    ):
        errors: list[WingmanInitializationError] = []
        wingman_config = self.get_disabled_wingman_by_name(wingman_name)
        if wingman_config:
            wingman = await self.__instantiate_wingman(
                wingman_name=wingman_name,
                wingman_config=wingman_config,
                settings=settings,
                errors=errors,
            )
            if wingman:
                wingman_config.disabled = False
                self.disabled_wingmen.remove(wingman_config)
                printr.print(
                    f"Enabled wingman {wingman_name}.",
                    color=LogType.INFO,
                    server_only=True,
                    source_name=self.log_source_name,
                    source=LogSource.SYSTEM,
                )
                return True
        return False

    def disable_wingman(self, wingman_name: str):
        for wingman in self.wingmen:
            if wingman.name == wingman_name:
                wingman.config.disabled = True
                self.disabled_wingmen.append(wingman.config)
                self.wingmen.remove(wingman)
                printr.print(
                    f"Disabled wingman {wingman_name}.",
                    color=LogType.INFO,
                    server_only=True,
                    source_name=self.log_source_name,
                    source=LogSource.SYSTEM,
                )
                return True
        return False
