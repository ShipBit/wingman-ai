import base64
from contextlib import contextmanager
from importlib import import_module, util
import inspect
from os import path
import os
import sys
from typing import TYPE_CHECKING
import yaml
from api.interface import (
    SettingsConfig,
    SkillBase,
    SkillConfig,
    SkillToolInfo,
    WingmanConfig,
)
from providers.faster_whisper import FasterWhisper
from providers.whispercpp import Whispercpp
from providers.xvasynth import XVASynth
from services.audio_library import AudioLibrary
from services.audio_player import AudioPlayer
from services.file import get_writable_dir, get_custom_skills_dir
from services.printr import Printr
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.wingman import Wingman
    from services.tower import Tower

SKILLS_DIR = "skills"

# Global variable to store the bundled skills path (set by main.py)
_bundled_skills_dir: str | None = None


def set_bundled_skills_dir(skills_dir: str):
    """Set the path to bundled skills directory. Called from main.py after determining app_root_path."""
    global _bundled_skills_dir
    _bundled_skills_dir = skills_dir


def get_bundled_skills_dir() -> str | None:
    """Get the path to bundled skills directory."""
    return _bundled_skills_dir


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
        audio_library: AudioLibrary,
        whispercpp: Whispercpp,
        fasterwhisper: FasterWhisper,
        xvasynth: XVASynth,
        tower: "Tower",
    ):
        """Dynamically creates a Wingman instance from a module path and class name

        Args:
            name (str): The name of the wingman. This is the key you gave it in the config, e.g. "atc"
            config (WingmanConfig): All "general" config entries merged with the specific Wingman config settings. The Wingman takes precedence and overrides the general config. You can just add new keys to the config and they will be available here.
            settings (SettingsConfig): The general user settings.
            audio_player (AudioPlayer): The audio player handling the playback of audio files.
            audio_library (AudioLibrary): The audio library handling the storage and retrieval of audio files.
            whispercpp (Whispercpp): The Whispercpp provider for speech-to-text.
            fasterwhisper (FasterWhisper): The FasterWhisper provider for speech-to-text.
            xvasynth (XVASynth): The XVASynth provider for text-to-speech.
            tower (Tower): The Tower instance, that manages loaded Wingmen.
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
            audio_library=audio_library,
            whispercpp=whispercpp,
            fasterwhisper=fasterwhisper,
            xvasynth=xvasynth,
            tower=tower,
        )
        return instance

    @staticmethod
    def load_skill(
        config: SkillConfig, settings: SettingsConfig, wingman: "Wingman"
    ) -> Skill:

        @contextmanager
        def add_to_sys_path(path_to_add: str):
            sys.path.insert(0, path_to_add)
            try:
                yield
            finally:
                sys.path.remove(path_to_add)

        skill_name, skill_path = ModuleManager.get_module_name_and_path(config.module)
        module = None

        # 1. Try import_module first (works for dev mode or bundled skills in sys.path)
        try:
            dependencies_dir = (
                path.join(skill_path, "venv", "lib", "python3.11", "site-packages")
                if sys.platform == "darwin"
                else path.join(skill_path, "venv", "Lib", "site-packages")
            )
            dependencies_dir = path.abspath(dependencies_dir)
            with add_to_sys_path(dependencies_dir):
                module = import_module(config.module)
        except ModuleNotFoundError:
            pass

        # 2. Try bundled skills directory (for release mode)
        if module is None:
            bundled_dir = get_bundled_skills_dir()
            if bundled_dir:
                # skill_path is like "skills/spotify", we need just "spotify"
                skill_folder = skill_path.replace("skills/", "").replace("skills\\", "")
                bundled_skill_path = path.join(bundled_dir, skill_folder)
                plugin_module_path = path.join(bundled_skill_path, "main.py")

                if path.isfile(plugin_module_path):
                    dependencies_dir = (
                        path.join(
                            bundled_skill_path,
                            "venv",
                            "lib",
                            "python3.11",
                            "site-packages",
                        )
                        if sys.platform == "darwin"
                        else path.join(
                            bundled_skill_path, "venv", "Lib", "site-packages"
                        )
                    )
                    with add_to_sys_path(dependencies_dir):
                        spec = util.spec_from_file_location(
                            skill_name, plugin_module_path
                        )
                        module = util.module_from_spec(spec)
                        spec.loader.exec_module(module)

        # 3. Try custom skills directory (for user-created skills)
        if module is None:
            custom_skills_dir = get_custom_skills_dir()
            skill_folder = skill_path.replace("skills/", "").replace("skills\\", "")
            custom_skill_path = path.join(custom_skills_dir, skill_folder)
            plugin_module_path = path.join(custom_skill_path, "main.py")

            if path.isfile(plugin_module_path):
                dependencies_dir = path.join(custom_skill_path, "dependencies")
                with add_to_sys_path(dependencies_dir):
                    spec = util.spec_from_file_location(skill_name, plugin_module_path)
                    module = util.module_from_spec(spec)
                    spec.loader.exec_module(module)

        if module is None:
            raise FileNotFoundError(
                f"Skill '{skill_name}' not found in bundled skills or custom skills directory"
            )

        DerivedSkillClass = getattr(module, config.name)
        instance = DerivedSkillClass(config=config, settings=settings, wingman=wingman)
        return instance

    @staticmethod
    def _get_untracked_skill_folders(skills_dir: str) -> set[str] | None:
        """Get skill folder names that are NOT tracked by git.

        Used to detect in-development custom skills placed in the source ./skills/
        directory during development. These are skills the developer is working on
        but haven't committed to the repo yet.

        Returns:
            set[str]: Untracked folder names when git detection succeeds.
            None: When git is unavailable or the directory is not in a git repo.
        """
        import subprocess

        try:
            result = subprocess.run(
                [
                    "git",
                    "ls-files",
                    "--others",
                    "--directory",
                    "--exclude-standard",
                    ".",
                ],
                capture_output=True,
                text=True,
                cwd=skills_dir,
                timeout=5,
            )
            if result.returncode == 0:
                return {
                    line.rstrip("/")
                    for line in result.stdout.strip().split("\n")
                    if line and "/" not in line.rstrip("/")
                }
        except Exception:
            pass
        return None

    @staticmethod
    def read_available_skill_configs() -> list[tuple[str, str, bool, bool]]:
        """Read skill configs from bundled skills and custom skills directories.

        Built-in skills are read from:
        - Bundled location (_internal/skills/ in release, ./skills/ in dev)

        Custom skills are read from:
        - APPDATA/WingmanAI/custom_skills/ (NOT versioned - persists across updates)

        Priority order (later entries override earlier):
        1. Bundled skills (base, read-only)
        2. Dev mode local skills (for development)
        3. Custom skills (user-created, override built-in)

        Note: Legacy versioned APPDATA/skills is NO LONGER checked. Custom skills
        should be migrated to the non-versioned custom_skills/ directory.

        Returns:
            List of tuples: (skill_folder_name, config_path, is_custom, is_local)
            - is_custom: True for skills from custom_skills/ directory
            - is_local: True for untracked dev skills in the source ./skills/ directory
        """
        # Source: "bundled" | "local" | "custom"
        # bundled = bundled/dev dir, git-tracked or release mode
        # local = bundled/dev dir, NOT git-tracked (dev-in-progress)
        # custom = custom_skills/ directory
        skill_dirs = []

        # 1. Add bundled skills directory (set by main.py)
        bundled_dir = get_bundled_skills_dir()
        if bundled_dir and os.path.isdir(bundled_dir):
            skill_dirs.append((bundled_dir, "bundled"))

        # 2. Fallback: dev mode - check local skills directory
        # In dev mode, bundled_dir IS the local skills dir, so this is a no-op
        # But we keep it for explicitness
        if os.path.isdir(SKILLS_DIR) and SKILLS_DIR not in [
            d for d, _ in skill_dirs
        ]:
            if bundled_dir != os.path.abspath(SKILLS_DIR):
                skill_dirs.append((SKILLS_DIR, "bundled"))

        # 3. Add custom skills directory (user-created skills, NOT versioned)
        # These can override built-in skills for customization
        custom_skills_dir = get_custom_skills_dir()
        if os.path.isdir(custom_skills_dir):
            skill_dirs.append((custom_skills_dir, "custom"))

        # Detect untracked (in-development) skill folders in the bundled/dev dir.
        # In dev mode, skills in ./skills/ that are NOT committed to git are
        # "local" dev skills the developer is working on.
        untracked_folders: set[str] | None = None
        is_dev_mode = not getattr(sys, "frozen", False)
        for dir_path, source in skill_dirs:
            if source == "bundled":
                untracked_folders = ModuleManager._get_untracked_skill_folders(
                    dir_path
                )
                break  # Only check the first bundled dir

        skills_default_configs = {}
        for skills_dir, source in skill_dirs:
            # Traverse the skills directory
            try:
                for skill_name in os.listdir(skills_dir):
                    # Construct the path to the skill's directory
                    skill_path = os.path.join(skills_dir, skill_name)

                    # Check if the path is a directory (to avoid non-folder files)
                    if os.path.isdir(skill_path):
                        # Construct the path to the default_config.yaml file
                        default_config_path = os.path.join(
                            skill_path, "default_config.yaml"
                        )

                        # Check if the default_config.yaml file exists
                        if os.path.isfile(default_config_path):
                            # Determine is_custom and is_local flags
                            is_custom = source == "custom"
                            is_local = False
                            if source == "bundled":
                                if untracked_folders is not None:
                                    # Git available: precise detection
                                    is_local = skill_name in untracked_folders
                                elif is_dev_mode:
                                    # Git unavailable but running from source:
                                    # can't distinguish bundled from dev skills,
                                    # so disable uninstall for all source skills
                                    is_local = True

                            # Later entries (custom skills) override earlier ones
                            skills_default_configs.update(
                                {
                                    skill_name: (
                                        skill_name,
                                        default_config_path,
                                        is_custom,
                                        is_local,
                                    )
                                }
                            )
            except OSError:
                # Directory might not exist or be inaccessible
                pass

        return list(skills_default_configs.values())

    @staticmethod
    def read_available_skills() -> list[SkillBase]:
        printr = Printr()
        skills = []
        # Get the list of available skill configs
        available_skill_configs = ModuleManager.read_available_skill_configs()
        # Load each skill from its config
        for skill_folder_name, skill_config_path, is_custom, is_local in available_skill_configs:
            skill_config = ModuleManager.read_config(skill_config_path)

            logo = None
            logo_path = path.join(path.dirname(skill_config_path), "logo.png")
            if path.exists(logo_path):
                logo = ModuleManager.load_image_as_base64(logo_path)

            # Extract tool definitions from the skill class
            tools = ModuleManager.extract_skill_tools(skill_folder_name, skill_config)

            # If we have @tool decorated tools, strip config metadata to minimize payload
            # Legacy skills keep their config metadata (prompt, examples) for UI display
            # Note: hint is always kept - it's UI-only info not covered by @tool descriptions
            if tools:
                skill_config.pop("prompt", None)
                skill_config.pop("examples", None)

            try:
                skill = SkillBase(
                    name=skill_config["name"],
                    config=skill_config,
                    logo=logo,
                    tools=tools if tools else None,
                    is_custom=is_custom,
                    is_local=is_local,
                    folder_name=skill_folder_name,
                )
                skills.append(skill)
            except Exception as e:
                printr.toast_error(
                    f"Could not load skill from '{skill_config_path}': {str(e)}"
                )
        return skills

    @staticmethod
    def extract_skill_tools(
        skill_folder_name: str, skill_config: dict
    ) -> list[SkillToolInfo]:
        """
        Extract tool definitions from a skill class without instantiating it.

        This introspects the skill module's class to find @tool decorated methods.
        """
        tools = []
        try:
            skill_path = skill_config.get("module", f"skills.{skill_folder_name}.main")

            # Try to import the module
            module = None
            try:
                module = import_module(skill_path)
            except Exception:
                # Try loading from bundled/custom skills directories
                bundled_dir = get_bundled_skills_dir()
                custom_skills_dir = get_custom_skills_dir()

                for base_dir in [bundled_dir, custom_skills_dir, SKILLS_DIR]:
                    if base_dir and path.isdir(base_dir):
                        plugin_module_path = path.join(
                            base_dir, skill_folder_name, "main.py"
                        )
                        if path.isfile(plugin_module_path):
                            try:
                                spec = util.spec_from_file_location(
                                    skill_folder_name, plugin_module_path
                                )
                                module = util.module_from_spec(spec)
                                spec.loader.exec_module(module)
                                break
                            except Exception:
                                continue

            if module is None:
                return tools

            # Get the skill class
            skill_name = skill_config.get("name", skill_folder_name)
            skill_class = getattr(module, skill_name, None)
            if skill_class is None:
                return tools

            # Scan class methods for @tool decorators
            for name, method in inspect.getmembers(
                skill_class, predicate=inspect.isfunction
            ):
                if hasattr(method, "_tool_definition"):
                    tool_def = method._tool_definition
                    description = tool_def.description or ""
                    if not description and tool_def.func.__doc__:
                        # Use first line of docstring
                        description = tool_def.func.__doc__.split("\n")[0].strip()
                    tools.append(
                        SkillToolInfo(
                            name=tool_def.name,
                            description=description or f"Execute {tool_def.name}",
                        )
                    )

        except Exception:
            # If we can't introspect, just return empty list
            pass

        return tools

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
