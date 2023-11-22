from wingmen.open_ai_wingman import OpenAiWingman
from wingmen.wingman import Wingman


class Tower:
    def __init__(self, config: dict[str, any]):
        self.config = config
        self.key_wingman_dict: dict[str, Wingman] = {}
        self.wingmen = self.__get_wingmen()

        for wingman in self.wingmen:
            self.key_wingman_dict[wingman.get_record_key()] = wingman

    def __deep_merge(self, source, updates):
        """Recursively merges updates into source."""
        for key, value in updates.items():
            if isinstance(value, dict):
                node = source.setdefault(key, {})
                self.__deep_merge(node, value)
            else:
                source[key] = value
        return source

    def __merge_configs(self, general, wingman):
        """Merge general settings with a specific wingman's overrides, for the 'openai' and 'features' sections."""
        # Start with a copy of the wingman's specific config to keep it intact.
        merged = wingman.copy()
        # Update 'openai' and 'features' sections from general config into wingman's config.
        for key in ["openai", "features"]:
            if key in general:
                merged[key] = self.__deep_merge(
                    general[key].copy(), wingman.get(key, {})
                )

        return merged

    def __get_wingmen(self) -> list[Wingman]:
        wingmen = []
        for wingman_name, wingman_config in self.config["wingmen"].items():
            if wingman_config.get("disabled") is True:
                continue

            global_config = {
                "openai": self.config["openai"],
                "features": self.config["features"],
            }
            merged_config = self.__merge_configs(global_config, wingman_config)
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

    def get_wingmen(self):
        return self.wingmen

    def get_config(self):
        return self.config
