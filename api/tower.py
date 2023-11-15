from api.wingman import WingmanBase


class Tower:
    def __init__(self, config: dict[str, any]):
        self.config = config
        self.key_wingman_map: dict[str, WingmanBase] = {}
        self.wingmen = self.__get_wingmen()

        for wingman in self.wingmen:
            self.key_wingman_map[wingman.get_record_key()] = wingman

    def __get_wingmen(self) -> list[WingmanBase]:
        wingmen = []
        for wingman_name in self.config["wingmen"]:
            wingman = WingmanBase(
                wingman_name, self.config["wingmen"].get(wingman_name)
            )
            wingmen.append(wingman)
        return wingmen

    def get_wingman_from_key(self, key: any) -> WingmanBase | None:
        if hasattr(key, "char"):
            wingman = self.key_wingman_map.get(key.char, None)
        else:
            wingman = self.key_wingman_map.get(key.name, None)
        return wingman
