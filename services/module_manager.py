import base64
from contextlib import contextmanager
from importlib import import_module, util
from os import path
import os
import sys

import yaml
from api.interface import SettingsConfig, SkillBase, SkillConfig, WingmanConfig
from services.audio_player import AudioPlayer
from services.file import get_writable_dir
from services.printr import Printr
from skills.skill_base import Skill

SKILLS_DIR = "skills"


class ModuleManager:

    @staticmethod
    def get_module_name_and_path(module_string: str) -> tuple[str, str]:
        """Splits a module path into its name and path components.

        Args:
            module_path (str): The path to the module, e.g. "skills.spotify.main"

        Returns:
            tuple[str, str]: The name of the module and the path to it, e.g. ("main", "skills/spotify/main.py")
        """
        module_name = module_string.split(".")[-1]
        module_path = ""
        for sub_dir in module_string.split(".")[:-1]:
            module_path = path.join(module_path, sub_dir)
        # module_path = path.join(module_path, module_name + ".py")
        return module_name, module_path

    @staticmethod
    def create_wingman_dynamically(
        name: str,
        config: WingmanConfig,
        settings: SettingsConfig,
        audio_player: AudioPlayer,
    ):
        """Dynamically creates a Wingman instance from a module path and class name

        Args:
            name (str): The name of the wingman. This is the key you gave it in the config, e.g. "atc"
            config (WingmanConfig): All "general" config entries merged with the specific Wingman config settings. The Wingman takes precedence and overrides the general config. You can just add new keys to the config and they will be available here.
            settings (SettingsConfig): The general user settings.
            audio_player (AudioPlayer): The audio player handling the playback of audio files.
        """

        try:
            # try to load from app dir first
            module = import_module(config.custom_class.module)
        except ModuleNotFoundError:
            # split module into name and path
            module_name, module_path = ModuleManager.get_module_name_and_path(
                config.custom_class.module
            )
            module_path = path.join(get_writable_dir(module_path), module_name + ".py")
            # load from alternative absolute file path
            spec = util.spec_from_file_location(module_name, module_path)
            module = util.module_from_spec(spec)
            spec.loader.exec_module(module)
        DerivedWingmanClass = getattr(module, config.custom_class.name)
        instance = DerivedWingmanClass(
            name=name,
            config=config,
            settings=settings,
            audio_player=audio_player,
        )
        return instance

    @staticmethod
    def load_skill(
        config: SkillConfig, wingman_config: WingmanConfig, settings: SettingsConfig
    ) -> Skill:

        @contextmanager
        def add_to_sys_path(path_to_add: str):
            sys.path.insert(0, path_to_add)
            try:
                yield
            finally:
                sys.path.remove(path_to_add)

        try:
            # try to load from app dir first
            skill_name, skill_path = ModuleManager.get_module_name_and_path(
                config.module
            )
            dependencies_dir = path.join(skill_path, "venv", "lib", "site-packages")
            dependencies_dir = path.abspath(dependencies_dir)
            with add_to_sys_path(dependencies_dir):
                module = import_module(config.module)
        except ModuleNotFoundError:
            skill_name, skill_path = ModuleManager.get_module_name_and_path(
                config.module
            )
            skill_path = get_writable_dir(skill_path)
            # Add the dependencies directory to sys.path so the plugin can load them
            dependencies_dir = get_writable_dir(path.join(skill_path, "dependencies"))
            # sys.path.insert(0, dependencies_dir)
            with add_to_sys_path(dependencies_dir):
                # Path to the plugin's main module file (e.g., plugin.py)
                plugin_module_path = get_writable_dir(path.join(skill_path, "main.py"))

                if path.exists(plugin_module_path):
                    # Load the plugin module dynamically
                    spec = util.spec_from_file_location(skill_name, plugin_module_path)
                    module = util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                else:
                    raise FileNotFoundError(
                        f"Plugin '{skill_name}' not found in directory '{skill_path}'"
                    )

        DerivedSkillClass = getattr(module, config.name)
        instance = DerivedSkillClass(
            config=config, wingman_config=wingman_config, settings=settings
        )
        return instance

    @staticmethod
    def read_available_skill_configs() -> list[tuple[str, str]]:
        if os.path.isdir(SKILLS_DIR):
            skills_dir = SKILLS_DIR
        else:
            skills_dir = get_writable_dir(SKILLS_DIR)

        skills_default_configs = []
        # Traverse the skills directory
        for skill_name in os.listdir(skills_dir):
            # Construct the path to the skill's directory
            skill_path = os.path.join(skills_dir, skill_name)

            # Check if the path is a directory (to avoid non-folder files)
            if os.path.isdir(skill_path):
                # Construct the path to the default_config.yaml file
                default_config_path = os.path.join(skill_path, "default_config.yaml")

                # Check if the default_config.yaml file exists
                if os.path.isfile(default_config_path):
                    # Add the skill name and the default_config.yaml file path to the list
                    skills_default_configs.append((skill_name, default_config_path))

        return skills_default_configs

    @staticmethod
    def read_available_skills() -> list[SkillBase]:
        printr = Printr()
        skills = []
        # Get the list of available skill configs
        available_skill_configs = ModuleManager.read_available_skill_configs()
        # Load each skill from its config
        for _, skill_config_path in available_skill_configs:
            skill_config = ModuleManager.read_config(skill_config_path)

            logo = None
            logo_path = path.join(path.dirname(skill_config_path), "logo.png")
            if path.exists(logo_path):
                logo = ModuleManager.load_image_as_base64(logo_path)

            try:
                skill = SkillBase(
                    name=skill_config["name"],
                    config=skill_config,
                    description=skill_config["description"],
                    logo=logo,
                )
                skills.append(skill)
            except Exception as e:
                printr.toast_error(
                    f"Could not load skill from '{skill_config_path}': {str(e)}"
                )
        return skills

    @staticmethod
    def load_image_as_base64(file_path: str):
        with open(file_path, "rb") as image_file:
            image_bytes = image_file.read()

        base64_encoded_data = base64.b64encode(image_bytes)
        base64_string = base64_encoded_data.decode("utf-8")
        base64_data_uri = f"data:image/png;base64,{base64_string}"

        return base64_data_uri

    @staticmethod
    def read_config(file_path: str):
        """Loads a config file (without validating it)"""
        printr = Printr()
        with open(file_path, "r", encoding="UTF-8") as stream:
            try:
                parsed = yaml.safe_load(stream)
                return parsed
            except yaml.YAMLError as e:
                printr.toast_error(
                    f"Could not read skill config '{file_path}':\n{str(e)}"
                )
        return None
