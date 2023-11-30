from wingmen.open_ai_wingman import OpenAiWingman
from wingmen.wingman import Wingman
from services.printr import Printr


class Tower:

    def __init__(self, config: dict[str, any]):
        self.config = config
        self.key_wingman_dict: dict[str, Wingman] = {}
        self.broken_wingmen = []

        self.wingmen = self.__instantiate_wingmen()
        self.key_wingman_dict: dict[str, Wingman] = {}
        for wingman in self.wingmen:
            self.key_wingman_dict[wingman.get_record_key()] = wingman

        self.wingmen_prepared = False

    def __instantiate_wingmen(self) -> list[Wingman]:
        wingmen = []
        for wingman_name, wingman_config in self.config["wingmen"].items():
            if wingman_config.get("disabled") is True:
                continue

            global_config = {
                "openai": self.config["openai"],
                "features": self.config["features"],
                "edge_tts": self.config["edge_tts"],
                "commands": self.config["commands"],
                "elevenlabs": self.config["elevenlabs"],
            }
            merged_config = self.__merge_configs(global_config, wingman_config)
            class_config = merged_config.get("class")

            wingman = None
            # it's a custom Wingman
            try:
                if class_config:
                    kwargs = class_config.get("args", {})
                    wingman = Wingman.create_dynamically(
                        name=wingman_name,
                        config=merged_config,
                        module_path=class_config.get("module"),
                        class_name=class_config.get("name"),
                        **kwargs
                    )
                else:
                    wingman = OpenAiWingman(wingman_name, merged_config)
            except Exception as e:
                # just in case we missed something
                self.broken_wingmen.append({"name": wingman_name, "error": e})
            else:
                # additional validation check if no exception was raised
                errors = wingman.validate()
                if not errors or len(errors) == 0:
                    wingmen.append(wingman)
                else:
                    self.broken_wingmen.append(
                        {"name": wingman_name, "error": ", ".join(errors)}
                    )

        return wingmen

    def prepare_wingmen(self):
        if not self.wingmen_prepared:
            for wingman in self.wingmen:
                wingman.prepare()
        else:
            Printr.warn_print(
                "Tower tried to prepare Wingmen multiple times. That should never happen."
            )
        self.wingmen_prepared = True

    def get_wingman_from_key(self, key: any) -> Wingman | None:
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

    def __deep_merge(self, source, updates):
        """Recursively merges updates into source."""
        for key, value in updates.items():
            if isinstance(value, dict):
                node = source.setdefault(key, {})
                self.__deep_merge(node, value)
            else:
                source[key] = value
        return source

    def __merge_command_lists(self, general_commands, wingman_commands):
        """Merge two lists of commands, where wingman-specific commands override or get added based on the 'name' key."""
        # Use a dictionary to ensure unique names and allow easy overrides
        merged_commands = {cmd["name"]: cmd for cmd in general_commands}
        for cmd in wingman_commands:
            merged_commands[
                cmd["name"]
            ] = cmd  # Will override or add the wingman-specific command
        # Convert merged commands back to a list since that's the expected format
        return list(merged_commands.values())

    def __merge_configs(self, general, wingman):
        """Merge general settings with a specific wingman's overrides, including commands."""
        # Start with a copy of the wingman's specific config to keep it intact.
        merged = wingman.copy()
        # Update 'openai', 'features', and 'edge_tts' sections from general config into wingman's config.
        for key in ["openai", "features", "edge_tts", "elevenlabs"]:
            if key in general:
                merged[key] = self.__deep_merge(
                    general[key].copy(), wingman.get(key, {})
                )

        # Special handling for merging the commands lists
        if "commands" in general and "commands" in wingman:
            merged["commands"] = self.__merge_command_lists(
                general["commands"], wingman["commands"]
            )
        elif "commands" in general:
            # If the wingman config does not have commands, use the general ones
            merged["commands"] = general["commands"]
        # No else needed; if 'commands' is not in general, we simply don't set it

        return merged
