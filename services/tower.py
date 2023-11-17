from wingmen.open_ai_wingman import OpenAiWingman
from wingmen.wingman import Wingman


class Tower:
    def __init__(self, config: dict[str, any]):
        self.config = config
        self.key_wingman_dict: dict[str, Wingman] = {}
        self.wingmen = self.__get_wingmen()

        for wingman in self.wingmen:
            self.key_wingman_dict[wingman.get_record_key()] = wingman

    def merge_configs(self, general, overrides):
        merged = overrides.copy()
        if not merged.get("openai"):
            merged["openai"] = {}
        merged["openai"].update(general["openai"])
        return merged

    def __get_wingmen(self) -> list[Wingman]:
        wingmen = []
        for wingman_name, wingman_config in self.config["wingmen"].items():
            if self.config.get("disabled") == True:
                continue
            merged_config = self.merge_configs(self.config, wingman_config)
            class_config = merged_config.get("class")
            if class_config:
                kwargs = class_config.get("args", {})
                wingmen.append(
                    Wingman.create_dynamically(
                        name=wingman_name,
                        config=merged_config,
                        module_path=class_config.get("module"),
                        class_name=class_config.get("name"),
                        **kwargs
                    )
                )
            else:
                wingmen.append(OpenAiWingman(wingman_name, merged_config))
        return wingmen

    def get_wingman_from_key(self, key: any) -> Wingman | None:
        if hasattr(key, "char"):
            wingman = self.key_wingman_dict.get(key.char, None)
        else:
            wingman = self.key_wingman_dict.get(key.name, None)
        return wingman
