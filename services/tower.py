from api.interface import Config
from wingmen.open_ai_wingman import OpenAiWingman
from wingmen.wingman import Wingman
from services.printr import Printr


printr = Printr()


class Tower:
    def __init__(self, config: Config, app_root_dir: str):
        self.config = config
        self.app_root_dir = app_root_dir
        self.key_wingman_dict: dict[str, Wingman] = {}
        self.broken_wingmen = []
        self.wingmen: list[Wingman] = []
        self.key_wingman_dict: dict[str, Wingman] = {}

    async def instantiate_wingmen(self):
        wingmen = []
        if not self.config.wingmen:
            return wingmen

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
                msg = str(e).strip()
                if not msg:
                    msg = type(e).__name__
                self.broken_wingmen.append({"name": wingman_name, "error": msg})
            else:
                # additional validation check if no exception was raised
                errors = await wingman.validate()
                if not errors or len(errors) == 0:
                    wingman.prepare()
                    wingmen.append(wingman)
                else:
                    self.broken_wingmen.append(
                        {"name": wingman_name, "error": ", ".join(errors)}
                    )

        for wingman in wingmen:
            self.key_wingman_dict[wingman.get_record_key()] = wingman

        self.wingmen = wingmen

    def get_wingman_from_key(self, key: any) -> Wingman | None:  # type: ignore
        if hasattr(key, "char"):
            wingman = self.key_wingman_dict.get(key.char, None)
        else:
            wingman = self.key_wingman_dict.get(key.name, None)
        return wingman

    def get_wingmen(self):
        return self.wingmen

    def get_broken_wingmen(self):
        return self.broken_wingmen

    def get_config(self):
        return self.config
