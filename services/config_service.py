from typing import Optional
from fastapi import APIRouter
from api.enums import OpenAiTtsVoice
from api.interface import (
    BasicWingmanConfig,
    ConfigDirInfo,
    ConfigWithDirInfo,
    ConfigsInfo,
    NewWingmanTemplate,
    SkillBase,
    WingmanConfig,
    WingmanConfigFileInfo,
)
from services.config_manager import ConfigManager
from services.module_manager import ModuleManager
from services.printr import Printr
from services.pub_sub import PubSub


class ConfigService:
    def __init__(self, config_manager: ConfigManager):
        self.printr = Printr()
        self.config_manager = config_manager
        self.config_events = PubSub()

        self.current_config_dir: ConfigDirInfo = (
            self.config_manager.find_default_config()
        )
        self.current_config = None

        self.router = APIRouter()
        tags = ["config"]
        self.router.add_api_route(
            methods=["GET"],
            path="/configs",
            endpoint=self.get_config_dirs,
            response_model=ConfigsInfo,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/configs/templates",
            endpoint=self.get_config_templates,
            response_model=list[ConfigDirInfo],
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/config",
            endpoint=self.get_config,
            response_model=ConfigWithDirInfo,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/config-dir-path",
            endpoint=self.get_config_dir_path,
            response_model=str,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"], path="/config", endpoint=self.load_config, tags=tags
        )
        self.router.add_api_route(
            methods=["DELETE"], path="/config", endpoint=self.delete_config, tags=tags
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/config/wingmen",
            endpoint=self.get_wingmen_config_files,
            response_model=list[WingmanConfigFileInfo],
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/config/new-wingman",
            endpoint=self.get_new_wingmen_template,
            response_model=NewWingmanTemplate,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/config/new-wingman",
            endpoint=self.add_new_wingman,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/config/wingman/default",
            endpoint=self.set_default_wingman,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["DELETE"],
            path="/config/wingman",
            endpoint=self.delete_wingman_config,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/config/create",
            endpoint=self.create_config,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/config/rename",
            endpoint=self.rename_config,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/config/default",
            endpoint=self.set_default_config,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/config/save-wingman",
            endpoint=self.save_wingman_config,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/config/save-wingman-basic",
            endpoint=self.save_basic_wingman_config,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/available-skills",
            endpoint=self.get_available_skills,
            response_model=list[SkillBase],
            tags=tags,
        )

    # GET /available-skills
    def get_available_skills(self):
        try:
            skills = ModuleManager.read_available_skills()
        except Exception as e:
            self.printr.toast_error(str(e))
            raise e

        return skills

    # GET /configs
    def get_config_dirs(self):
        return ConfigsInfo(
            config_dirs=self.config_manager.get_config_dirs(),
            current_config_dir=self.current_config_dir,
        )

    # GET /configs/templates
    def get_config_templates(self):
        return self.config_manager.get_config_template_dirs()

    # GET /config
    async def get_config(self, config_name: Optional[str] = "") -> ConfigWithDirInfo:
        if config_name and len(config_name) > 0:
            config_dir = self.config_manager.get_config_dir(config_name)

        config_info = await self.load_config(config_dir)

        return config_info

    # GET /config-dir-path
    def get_config_dir_path(self, config_name: Optional[str] = ""):
        return self.config_manager.get_config_dir_path(config_name)

    # POST /config
    async def load_config(
        self, config_dir: Optional[ConfigDirInfo] = None
    ) -> ConfigWithDirInfo:
        try:
            loaded_config_dir, config = self.config_manager.load_config(config_dir)
        except Exception as e:
            self.printr.toast_error(str(e))
            raise e

        self.current_config_dir = loaded_config_dir
        self.current_config = config

        config_dir_info = ConfigWithDirInfo(config=config, config_dir=loaded_config_dir)
        await self.config_events.publish("config_loaded", config_dir_info)

        return config_dir_info

    # POST config/create
    async def create_config(
        self, config_name: str, template: Optional[ConfigDirInfo] = None
    ):
        new_dir = self.config_manager.create_config(
            config_name=config_name, template=template
        )
        await self.load_config(new_dir)

    # POST config/rename
    async def rename_config(self, config_dir: ConfigDirInfo, new_name: str):
        new_config_dir = self.config_manager.rename_config(
            config_dir=config_dir, new_name=new_name
        )
        if new_config_dir and config_dir.name == self.current_config_dir.name:
            await self.load_config(new_config_dir)

    # POST config/default
    def set_default_config(self, config_dir: ConfigDirInfo):
        self.config_manager.set_default_config(config_dir=config_dir)

    # DELETE config
    async def delete_config(self, config_dir: ConfigDirInfo):
        self.config_manager.delete_config(config_dir=config_dir)
        if config_dir.name == self.current_config_dir.name:
            await self.load_config()

    # GET config/wingmen
    async def get_wingmen_config_files(self, config_name: str):
        config_dir = self.config_manager.get_config_dir(config_name)
        return self.config_manager.get_wingmen_configs(config_dir)

    # DELETE config/wingman
    async def delete_wingman_config(
        self, config_dir: ConfigDirInfo, wingman_file: WingmanConfigFileInfo
    ):
        self.config_manager.delete_wingman_config(config_dir, wingman_file)
        await self.load_config(config_dir)  # refresh

    # GET config/new-wingman/
    async def get_new_wingmen_template(self):
        return self.config_manager.get_new_wingman_template()

    # POST config/new-wingman
    async def add_new_wingman(
        self, config_dir: ConfigDirInfo, wingman_config: WingmanConfig, avatar: str
    ):
        wingman_file = WingmanConfigFileInfo(
            name=wingman_config.name,
            file=f"{wingman_config.name}.yaml",
            is_deleted=False,
            avatar=avatar,
        )

        await self.save_wingman_config(
            config_dir=config_dir,
            wingman_file=wingman_file,
            wingman_config=wingman_config,
            auto_recover=False,
        )

    # POST config/save-wingman
    async def save_wingman_config(
        self,
        config_dir: ConfigDirInfo,
        wingman_file: WingmanConfigFileInfo,
        wingman_config: WingmanConfig,
        auto_recover: bool = False,
        silent: bool = False,
    ):
        self.config_manager.save_wingman_config(
            config_dir=config_dir,
            wingman_file=wingman_file,
            wingman_config=wingman_config,
        )
        try:
            if not silent:
                await self.load_config(config_dir)
                self.printr.toast("Wingman saved successfully.")
        except Exception:
            error_message = "Invalid Wingman configuration."
            if auto_recover:
                deleted = self.config_manager.delete_wingman_config(
                    config_dir, wingman_file
                )
                if deleted:
                    self.config_manager.copy_templates()

                await self.load_config(config_dir)

                restored_message = (
                    "Deleted broken config (and restored default if there is a template for it)."
                    if deleted
                    else ""
                )
                self.printr.toast_error(f"{error_message} {restored_message}")
            else:
                self.printr.toast_error(f"{error_message}")

    # POST config/save-wingman-basic
    async def save_basic_wingman_config(
        self,
        config_dir: ConfigDirInfo,
        wingman_file: WingmanConfigFileInfo,
        basic_config: BasicWingmanConfig,
        silent: bool = False,
    ):
        # get the current config
        wingman_config = self.config_manager.load_wingman_config(
            config_dir=config_dir, wingman_file=wingman_file
        )

        wingman_config.name = basic_config.name
        wingman_config.disabled = basic_config.disabled
        wingman_config.record_key = basic_config.record_key
        wingman_config.record_key_codes = basic_config.record_key_codes
        wingman_config.sound = basic_config.sound
        wingman_config.prompts.backstory = basic_config.backstory
        try:
            wingman_config.openai.tts_voice = OpenAiTtsVoice(basic_config.voice)
        except ValueError:
            wingman_config.azure.tts.voice = basic_config.voice

        self.config_manager.save_wingman_config(
            config_dir=config_dir,
            wingman_file=wingman_file,
            wingman_config=wingman_config,
        )
        try:
            if not silent:
                await self.load_config(config_dir)
                self.printr.toast("Wingman saved successfully.")
        except Exception as e:
            self.printr.toast_error(f"Invalid Wingman configuration: {str(e)}")

    # POST config/wingman/default
    async def set_default_wingman(
        self,
        config_dir: ConfigDirInfo,
        wingman_name: str,
    ):
        _dir, config = self.config_manager.load_config(config_dir)
        wingman_config_files = await self.get_wingmen_config_files(config_dir.name)

        # Check if the wingman_name is already the default
        already_default = any(
            (
                config.wingmen[file.name].name == wingman_name
                and config.wingmen[file.name].is_voice_activation_default
            )
            for file in wingman_config_files
        )

        for wingman_config_file in wingman_config_files:
            wingman_config = config.wingmen[wingman_config_file.name]

            if already_default:
                # If wingman_name is already default, undefault it
                wingman_config.is_voice_activation_default = False
            else:
                # Set the new default
                wingman_config.is_voice_activation_default = (
                    wingman_config.name == wingman_name
                )

            await self.save_wingman_config(
                config_dir=config_dir,
                wingman_file=wingman_config_file,
                wingman_config=wingman_config,
                silent=True,
            )

        await self.load_config(config_dir)
