import keyboard.keyboard as keyboard
from api.enums import WingmanInitializationErrorType
from api.interface import Config, WingmanInitializationError
from wingmen.open_ai_wingman import OpenAiWingman
from wingmen.wingman import Wingman
from services.printr import Printr


printr = Printr()


class Tower:
    def __init__(self, config: Config):
        self.config = config
        self.key_wingman_dict: dict[str, Wingman] = {}
        self.wingmen: list[Wingman] = []

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
                    )
                else:
                    wingman = OpenAiWingman(name=wingman_name, config=wingman_config)
            except Exception as e:  # pylint: disable=broad-except
                # just in case we missed something
                msg = str(e).strip() or type(e).__name__
                errors.append(
                    WingmanInitializationError(
                        wingman_name=wingman_name,
                        msg=msg,
                        error_type=WingmanInitializationErrorType.UNKNOWN,
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
            scan_codes = keyboard.key_to_scan_codes(wingman.get_record_key())
            if len(scan_codes) > 0:
                scan_code = scan_codes[0]
                self.key_wingman_dict[scan_code] = wingman

        return errors

    def get_wingman_from_key(self, key: any) -> Wingman | None:  # type: ignore
        wingman = self.key_wingman_dict.get(key.scan_code, None)
        return wingman
