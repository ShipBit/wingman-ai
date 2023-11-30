import os
import shutil
from typing import Literal
import yaml
from services.printr import Printr

SYSTEM_CONFIG_PATH = "configs/system"
CONTEXT_CONFIG_PATH = "configs/contexts"
CONTEXT_CONFIG_PATH_BUNDLED = "../contexts"
DEFAULT_CONTEXT_CONFIG = "context.yaml"
EXAMPLE_CONTEXT_CONFIG = "context.example.yaml"
API_KEYS_CONFIG = "api_keys.yaml"
GUI_CONFIG = "gui.yaml"

class ConfigManager():

    def __init__(self, app_root_path:str, app_is_bundled:bool):
        self.printr = Printr()
        self.gui_config = {}
        self.api_keys = {}
        self.contexts = [""]
        self.context_config_path: str = os.path.join(
            app_root_path,
            CONTEXT_CONFIG_PATH_BUNDLED if app_is_bundled else CONTEXT_CONFIG_PATH)
        self.system_config_path: str = os.path.join(app_root_path, SYSTEM_CONFIG_PATH)
        self.load_gui_config()
        self.load_api_keys()
        self.load_context_config_names()


    def __read_config_file(self, config_name, is_system_config=True) -> dict[str, any]: # type: ignore
        parsed_config = {}

        path = self.system_config_path if is_system_config else self.context_config_path
        config_file = os.path.join(path, config_name)
        if os.path.exists(config_file) and os.path.isfile(config_file):
            with open(config_file, "r", encoding="UTF-8") as stream:
                try:
                    parsed_config = yaml.safe_load(stream)
                except yaml.YAMLError as e:
                    self.printr.print_err(f"Could not load config ({config_name})!\n{str(e)}", True)

        return parsed_config


    def __write_config_file(self, config_name, content, is_system_config=True) -> bool: # type: ignore
        path = self.system_config_path if is_system_config else self.context_config_path
        config_file = os.path.join(path, config_name)
        with open(config_file, "w", encoding="UTF-8") as stream:
            try:
                yaml.dump(content, stream)
            except yaml.YAMLError as e:
                self.printr.print_err(f"Could not write config ({config_name})!\n{str(e)}", True)
                return False

            return True

        return False


    def __append_keys_to_config(self, config):
        # TODO: just append the keys that are really needed by the current config
        # and check if all needed keys are present
        if self.api_keys:
            for key, value in self.api_keys.items():
                config[key]["api_key"] = value

        return config


    def load_api_keys(self):
        """Fetch all API keys from file and store them for future use
        """
        self.api_keys = self.__read_config_file(API_KEYS_CONFIG)
        return self.api_keys

    def save_api_keys(self):
        """Write all API keys to file
        """
        return self.__write_config_file(API_KEYS_CONFIG, self.api_keys)


    def load_gui_config(self):
        """Fetch GUI config from file and store it for future use
        """
        self.gui_config = self.__read_config_file(GUI_CONFIG)
        return self.gui_config

    def save_gui_config(self):
        """Write GUI config to file
        """
        return self.__write_config_file(GUI_CONFIG, self.gui_config)


    def load_context_config_names(self):
        default_found = False
        file_prefix, file_ending = DEFAULT_CONTEXT_CONFIG.split(".")

        # Dynamically load all user configuration files from the provided directory
        for file in os.listdir(self.context_config_path):
            # Filter out all non-yaml files
            if file.endswith(f".{file_ending}") and file.startswith(f"{file_prefix}."):
                if (file == DEFAULT_CONTEXT_CONFIG):
                    default_found = True
                else:
                    config_name = file.replace(f"{file_prefix}.", "").replace(f".{file_ending}", "")
                    self.contexts.append(config_name)

        if not default_found:
            # create default context from the systems example context config
            example_context: str = os.path.join(self.system_config_path, EXAMPLE_CONTEXT_CONFIG)
            default_context: str = os.path.join(self.context_config_path, DEFAULT_CONTEXT_CONFIG)
            if os.path.exists(example_context) and os.path.isfile(example_context):
                shutil.copyfile(example_context, default_context)


    def get_context_config(self, context="") -> dict[str, any]: #type: ignore
        # default name -> 'config.yaml'
        # context config -> 'config.{context}.yaml'
        file_name = f"context.{f'{context}.' if context else ''}yaml"
        config = self.__read_config_file(file_name, False)

        if config:
            return self.__append_keys_to_config(config)

        return {}
