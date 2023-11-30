import os
import shutil
import yaml
from services.printr import Printr

SYSTEM_CONFIG_PATH = "configs/system"
CONTEXT_CONFIG_PATH = "configs/contexts"
CONTEXT_CONFIG_PATH_BUNDLED = "../contexts"
DEFAULT_CONTEXT_CONFIG = "context.yaml"
EXAMPLE_CONTEXT_CONFIG = "context.example.yaml"
API_KEYS_CONFIG = "api_keys.yaml"

class ConfigManager():
    def __init__(self, app_root_path:str, app_is_bundled:bool):
        # all paths are one folder above executable file, if bundled
        self.user_configs = {}
        self.api_keys = {}
        self.contexts = [""]
        self.context_config_path: str = os.path.join(
            app_root_path,
            CONTEXT_CONFIG_PATH_BUNDLED if app_is_bundled else CONTEXT_CONFIG_PATH)
        self.system_config_path: str = os.path.join(app_root_path, SYSTEM_CONFIG_PATH)
        self.load_api_keys()
        self.load_context_config_names()


    def __get_api_keys(self):
        filename: str = os.path.join(self.system_config_path, API_KEYS_CONFIG)
        # Check if file exists
        if os.path.exists(filename) and os.path.isfile(filename):
            with open(filename, "r", encoding="UTF-8") as file:
                data = yaml.safe_load(file)
                return data

        return {}


    def __append_keys_to_config(self, config):
        # TODO: just append the keys that are really needed by the current config
        # and check if all needed keys are present
        if self.api_keys:
            for key, value in self.api_keys.items():
                config[key]["api_key"] = value.get("api_key")

        return config


    def __read_context_config(self, context=None) -> dict[str, any]: # type: ignore
        context_config = {}

        # default name -> 'config.yaml'
        # context config -> 'config.{context}.yaml'
        file_name = f"context.{f'{context}.' if context else ''}yaml"
        context_file = os.path.join(self.context_config_path, file_name)
        with open(context_file, "r", encoding="UTF-8") as stream:
            try:
                context_config = yaml.safe_load(stream)
            except yaml.YAMLError as e:
                # TODO: show in gui
                Printr.err_print(e)

        return context_config


    def load_api_keys(self):
        """Fetch all API keys from files and store them for future use
        """
        self.api_keys = self.__get_api_keys()


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


    def get_context_config(self, context=None) -> dict[str, any]: #type: ignore
        config = self.__read_context_config(context)

        if config:
            return self.__append_keys_to_config(config)

        return {}


    def write_to_config(self, config, data):
        pass
