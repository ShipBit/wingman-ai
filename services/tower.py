# --- START OF FILE tower.py ---

import traceback
import copy
from typing import Optional, Any # Import Optional and Any
from exceptions import MissingApiKeyException
from wingmen.open_ai_wingman import OpenAiWingman
from wingmen.wingman import Wingman
from services.printr import Printr
from services.secret_keeper import SecretKeeper
from services.memory_logger import log_memory_usage


printr = Printr()


class Tower:
    def __init__(self, config: dict[str, any], secret_keeper: SecretKeeper, app_root_dir: str):  # type: ignore
        self.config = config
        self.app_root_dir = app_root_dir
        self.secret_keeper = secret_keeper
        self.wingmen: list[Wingman] = [] # Initialize wingmen list
        self.key_wingman_dict: dict[str, Wingman] = {}
        self.broken_wingmen: list[dict[str, str]] = [] # Initialize broken_wingmen list

        self.wingmen = self.__instantiate_wingmen()
        # Rebuild key_wingman_dict after instantiation
        self.key_wingman_dict = {}
        for wingman in self.wingmen:
            record_key = wingman.get_record_key()
            if record_key: # Ensure key exists
                 self.key_wingman_dict[record_key] = wingman
            else:
                 printr.print_warn(f"Wingman '{wingman.name}' has no record_key configured.")


    def __instantiate_wingmen(self) -> list[Wingman]:
        wingmen = []
        if "wingmen" not in self.config or not isinstance(self.config["wingmen"], dict):
             printr.print_err("Configuration missing 'wingmen' section or it's not a dictionary.")
             return [] # Return empty list if config is wrong

        for wingman_name, wingman_config in self.config["wingmen"].items():
            if not isinstance(wingman_config, dict):
                 printr.print_warn(f"Skipping invalid wingman configuration for '{wingman_name}'. Expected a dictionary.")
                 continue

            if wingman_config.get("disabled") is True:
                printr.print(f"Wingman '{wingman_name}' is disabled in config.", tags="info")
                continue

            # Prepare global config sections safely
            global_config = {
                key: self.config.get(key, {}) for key in [
                    "sound", "openai", "local", "groq", "features",
                    "commands", "azure", "elevenlabs", "edge_tts", # Added missing tts/other configs
                    "sc-keybind-mappings" # Add SC specific global config if needed by wingmen
                ]
            }
            # Ensure commands is a list
            global_config["commands"] = self.config.get("commands", [])
            if not isinstance(global_config["commands"], list):
                 printr.print_warn("'commands' section in general config is not a list. Using empty list.")
                 global_config["commands"] = []


            merged_config = self.__merge_configs(global_config, wingman_config)
            class_config = merged_config.get("class")

            wingman = None
            try:
                if class_config and isinstance(class_config, dict):
                    module_path = class_config.get("module")
                    class_name = class_config.get("name")
                    if not module_path or not class_name:
                         raise ValueError("Custom wingman class config missing 'module' or 'name'.")

                    kwargs = class_config.get("args", {})
                    if not isinstance(kwargs, dict): kwargs = {} # Ensure kwargs is a dict

                    wingman = Wingman.create_dynamically(
                        name=wingman_name,
                        config=merged_config,
                        secret_keeper=self.secret_keeper,
                        module_path=module_path,
                        class_name=class_name,
                        app_root_dir=self.app_root_dir,
                        **kwargs
                    )
                else:
                    # Default to OpenAiWingman if no valid class config
                    wingman = OpenAiWingman(
                        name=wingman_name,
                        config=merged_config,
                        secret_keeper=self.secret_keeper,
                        app_root_dir=self.app_root_dir,
                    )

                # Validate the instantiated wingman
                errors = wingman.validate()
                if not errors:
                    wingman.prepare()
                    wingmen.append(wingman)
                    printr.print(
                        f"Successfully initialized Wingman: {wingman_name} ({type(wingman).__name__})",
                        tags="success",
                    )
                    log_memory_usage(f"after_init_{wingman_name}")
                else:
                    error_str = ", ".join(errors)
                    self.broken_wingmen.append({"name": wingman_name, "error": error_str})
                    printr.print_err(f"Validation failed for Wingman '{wingman_name}': {error_str}")

            except MissingApiKeyException as e:
                 error_msg = f"Missing API key ({e}). Please check your key config."
                 self.broken_wingmen.append({"name": wingman_name, "error": error_msg})
                 printr.print_err(f"Initialization failed for Wingman '{wingman_name}': {error_msg}")
            except ImportError as e:
                 error_msg = f"Could not import wingman module/class: {e}"
                 self.broken_wingmen.append({"name": wingman_name, "error": error_msg})
                 printr.print_err(f"Initialization failed for Wingman '{wingman_name}': {error_msg}")
                 traceback.print_exc()
            except Exception as e:
                 error_msg = f"Unexpected error: {str(e) or type(e).__name__}"
                 self.broken_wingmen.append({"name": wingman_name, "error": error_msg})
                 printr.print_err(f"Initialization failed for Wingman '{wingman_name}': {error_msg}")
                 traceback.print_exc()


        return wingmen

    def get_wingman_from_key(self, key_identifier: str) -> Optional[Wingman]:
        """
        Retrieves a wingman based on its configured record key (string).

        Args:
            key_identifier (str): The character or name of the key (e.g., 'v', 'x1').

        Returns:
            Optional[Wingman]: The corresponding Wingman instance or None if not found.
        """
        # The key_identifier is already the string we need for the dictionary lookup
        wingman = self.key_wingman_dict.get(key_identifier, None)
        # printr.print(f"Lookup Wingman for key '{key_identifier}': {'Found ' + wingman.name if wingman else 'Not Found'}", tags="debug")
        return wingman

    def get_wingmen(self) -> list[Wingman]:
        """Returns the list of successfully initialized wingmen."""
        return self.wingmen

    def get_broken_wingmen(self) -> list[dict[str, str]]:
        """Returns the list of wingmen that failed to initialize."""
        return self.broken_wingmen

    def get_config(self) -> dict[str, any]:
        """Returns the loaded configuration dictionary."""
        return self.config

    def __deep_merge(self, source: dict, updates: dict) -> dict:
        """Recursively merges updates into source dictionary."""
        # Create a copy to avoid modifying the original source dict directly
        # especially important if source comes from a shared config object.
        merged = source.copy()
        for key, value in updates.items():
            if isinstance(value, dict):
                # Get node or create one if doesn't exist
                node = merged.get(key, {})
                if isinstance(node, dict): # Ensure node is a dict before merging
                     merged[key] = self.__deep_merge(node, value)
                else: # If key exists in source but is not a dict, overwrite with update's dict
                     merged[key] = value.copy() # Copy the update dict
            else:
                # If value is not a dict, simply overwrite/add
                merged[key] = value
        return merged


    def __merge_command_lists(self, general_commands: list, wingman_commands: list) -> list:
        """Merge two lists of commands based on the 'name' key."""
        # Ensure inputs are lists
        if not isinstance(general_commands, list): general_commands = []
        if not isinstance(wingman_commands, list): wingman_commands = []

        merged_commands_dict = {cmd["name"]: cmd for cmd in general_commands if isinstance(cmd, dict) and "name" in cmd}
        for cmd in wingman_commands:
             if isinstance(cmd, dict) and "name" in cmd:
                  merged_commands_dict[cmd["name"]] = cmd # Override or add

        return list(merged_commands_dict.values())

    def __merge_configs(self, general: dict, wingman: dict) -> dict:
        """Merge general settings with wingman overrides."""
        # Start with a deep copy of the general config as the base
        merged = copy.deepcopy(general)

        # Iterate through wingman-specific config items
        for key, wingman_value in wingman.items():
            if key == "commands" and isinstance(wingman_value, list):
                # Special handling for commands list merge
                merged[key] = self.__merge_command_lists(general.get(key, []), wingman_value)
            elif isinstance(wingman_value, dict) and key in merged and isinstance(merged[key], dict):
                # If both general and wingman have a dict for the same key, deep merge them
                merged[key] = self.__deep_merge(merged[key], wingman_value)
            else:
                # Otherwise, the wingman value overrides the general value completely
                merged[key] = wingman_value

        return merged