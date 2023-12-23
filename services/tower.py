from api.enums import WingmanInitializationErrorType
from api.interface import Config, WingmanInitializationError
from wingmen.open_ai_wingman import OpenAiWingman
from wingmen.wingman import Wingman
from services.printr import Printr


printr = Printr()


class Tower:
    def __init__(self, config: Config, app_root_dir: str):
        self.config = config
        self.app_root_dir = app_root_dir
        self.key_wingman_dict: dict[str, Wingman] = {}
        self.wingmen: list[Wingman] = []
        self.key_wingman_dict: dict[str, Wingman] = {}

    async def instantiate_wingmen(self):
        errors: list[WingmanInitializationError] = []

        if not self.config.wingmen:
            return errors

        for wingman_name, wingman_config in self.config.wingmen.items():
            if wingman_config.disabled is True:
                continue

            wingman = None
            try:
                # it's a custom Wingman
                if wingman_config.custom_class:
                    wingman = Wingman.create_dynamically(
                        name=wingman_name,
                        config=wingman_config,
                        app_root_dir=self.app_root_dir,
                    )
                else:
                    wingman = OpenAiWingman(
                        name=wingman_name,
                        config=wingman_config,
                        app_root_dir=self.app_root_dir,
                    )
            except Exception as e:  # pylint: disable=broad-except
                # just in case we missed something
                msg = str(e).strip() or type(e).__name__
                errors.append(
                    WingmanInitializationError(
                        wingman_name=wingman_name,
                        msg=msg,
                        errorType=WingmanInitializationErrorType.UNKNOWN,
                    )
                )
                printr.toast_error(f"Could not instantiate {wingman_name}:\n{str(e)}")
            else:
                # additional validation check if no exception was raised
                errors.extend(await wingman.validate())
                if not errors or len(errors) == 0:
                    wingman.prepare()
                    self.wingmen.append(wingman)

        for wingman in self.wingmen:
            self.key_wingman_dict[wingman.get_record_key()] = wingman

        return errors

    def get_wingman_from_key(self, key: any) -> Wingman | None:  # type: ignore
        if hasattr(key, "char"):
            wingman = self.key_wingman_dict.get(key.char, None)
        else:
            wingman = self.key_wingman_dict.get(key.name, None)
        return wingman
