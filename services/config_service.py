from typing import Optional
from fastapi import APIRouter
from api.enums import LogType
from api.interface import (
    BasicWingmanConfig,
    ConfigDirInfo,
    ConfigWithDirInfo,
    ConfigsInfo,
    NestedConfig,
    NewWingmanTemplate,
    SkillBase,
    WingmanConfig,
    WingmanConfigFileInfo,
)
from services.config_manager import ConfigManager
from services.config_migration_service import ConfigMigrationService
from services.module_manager import ModuleManager
from services.printr import Printr
from services.pub_sub import PubSub
from services.system_manager import SystemManager
from services.tower import Tower


class ConfigService:
    def __init__(self, config_manager: ConfigManager):
        self.printr = Printr()
        self.config_manager = config_manager
        self.config_events = PubSub()
        self.source_name = "Config Service"

        self.current_config_dir: ConfigDirInfo = (
            self.config_manager.find_default_config()
        )
        self.tower: Tower = None
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
        self.router.add_api_route(
            methods=["GET"],
            path="/config/defaults",
            endpoint=self.get_defaults_config,
            response_model=NestedConfig,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/config/defaults",
            endpoint=self.save_defaults_config,
            tags=tags,
        )

    def set_tower(self, tower: Tower):
        self.tower = tower

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

        loaded_config_dir, config = self.config_manager.parse_config(config_dir)
        return ConfigWithDirInfo(config=config, config_dir=loaded_config_dir)

    # GET /config-dir-path
    def get_config_dir_path(self, config_name: Optional[str] = ""):
        return self.config_manager.get_config_dir_path(config_name)

    # POST /config
    async def load_config(
        self, config_dir: Optional[ConfigDirInfo] = None
    ) -> ConfigWithDirInfo:
        try:
            loaded_config_dir, config = self.config_manager.parse_config(config_dir)
        except Exception as e:
            self.printr.toast_error(str(e))
            raise e

        self.current_config_dir = loaded_config_dir
        self.current_config = config

        config_dir_info = ConfigWithDirInfo(config=config, config_dir=loaded_config_dir)
        await self.config_events.publish("config_loaded", config_dir_info)

        await self.printr.print_async(
            f"Loaded config: {loaded_config_dir.name}.",
            color=LogType.HIGHLIGHT,
            source_name=self.source_name,
            command_tag="config_loaded",
        )

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

        self.config_manager.save_wingman_config(
            config_dir=config_dir,
            wingman_file=wingman_file,
            wingman_config=wingman_config,
        )
        await self.load_config(config_dir)

    # POST config/save-wingman
    async def save_wingman_config(
        self,
        config_dir: ConfigDirInfo,
        wingman_file: WingmanConfigFileInfo,
        wingman_config: WingmanConfig,
        silent: bool = False,
        validate: bool = False,
        update_skills: bool = False,
    ):
        # update the wingman
        wingman = self.tower.get_wingman_by_name(wingman_file.name)
        if not wingman:
            # try to enable a previously disabled wingman
            disabled_config = self.tower.get_disabled_wingman_by_name(
                wingman_config.name
            )
            if disabled_config and not wingman_config.disabled:
                enabled = await self.tower.enable_wingman(
                    wingman_name=wingman_config.name,
                    settings=self.config_manager.settings_config,
                )
                if enabled:
                    # now this should work
                    wingman = self.tower.get_wingman_by_name(wingman_file.name)
            # else fail
            if not wingman:
                self.printr.toast_error(f"Wingman '{wingman_file.name}' not found.")
                return

        updated = await wingman.update_config(
            config=wingman_config, validate=validate, update_skills=update_skills
        )

        if not updated:
            self.printr.toast_error(
                f"New config for Wingman '{wingman_config.name}' is invalid."
            )
            return

        # save the config file
        self.config_manager.save_wingman_config(
            config_dir=config_dir,
            wingman_file=wingman_file,
            wingman_config=wingman_config,
        )

        message = f"Wingman {wingman_config.name}'s config changed."
        if not silent:
            self.printr.toast(message)
        else:
            self.printr.print(text=message, server_only=True)

    # POST config/save-wingman-basic
    async def save_basic_wingman_config(
        self,
        config_dir: ConfigDirInfo,
        wingman_file: WingmanConfigFileInfo,
        basic_config: BasicWingmanConfig,
        silent: bool = False,
        validate: bool = False,
    ):
        # update the wingman
        wingman = self.tower.get_wingman_by_name(wingman_file.name)
        if not wingman:
            # try to enable a previously disabled wingman
            disabled_config = self.tower.get_disabled_wingman_by_name(basic_config.name)
            if disabled_config and not basic_config.disabled:
                enabled = await self.tower.enable_wingman(
                    wingman_name=basic_config.name,
                    settings=self.config_manager.settings_config,
                )
                if enabled:
                    # now this should work
                    wingman = self.tower.get_wingman_by_name(wingman_file.name)
            # else fail
            if not wingman:
                self.printr.toast_error(f"Wingman '{wingman_file.name}' not found.")
                return

        wingman_config = wingman.config
        wingman_config.name = basic_config.name
        wingman_config.disabled = basic_config.disabled
        wingman_config.record_key = basic_config.record_key
        wingman_config.record_key_codes = basic_config.record_key_codes
        wingman_config.sound = basic_config.sound
        wingman_config.prompts = basic_config.prompts

        reload_config = (
            wingman_config.record_joystick_button != basic_config.record_joystick_button
            or wingman_config.record_mouse_button != basic_config.record_mouse_button
            or wingman_file.name != wingman_config.name
        )

        wingman_config.record_joystick_button = basic_config.record_joystick_button
        wingman_config.record_mouse_button = basic_config.record_mouse_button

        wingman_config.features = basic_config.features
        wingman_config.openai = basic_config.openai
        wingman_config.mistral = basic_config.mistral
        wingman_config.groq = basic_config.groq
        wingman_config.cerebras = basic_config.cerebras
        wingman_config.google = basic_config.google
        wingman_config.openrouter = basic_config.openrouter
        wingman_config.local_llm = basic_config.local_llm
        wingman_config.edge_tts = basic_config.edge_tts
        wingman_config.elevenlabs = basic_config.elevenlabs
        wingman_config.azure = basic_config.azure
        wingman_config.xvasynth = basic_config.xvasynth
        wingman_config.hume = basic_config.hume
        wingman_config.inworld = basic_config.inworld
        wingman_config.whispercpp = basic_config.whispercpp
        wingman_config.fasterwhisper = basic_config.fasterwhisper
        wingman_config.wingman_pro = basic_config.wingman_pro
        wingman_config.perplexity = basic_config.perplexity
        wingman_config.openai_compatible_tts = basic_config.openai_compatible_tts

        updated = await wingman.update_config(config=wingman_config, validate=validate)

        if not updated:
            self.printr.toast_error(
                f"New config for Wingman '{wingman_config.name}' is invalid."
            )
            return

        # save the config file
        self.config_manager.save_wingman_config(
            config_dir=config_dir,
            wingman_file=wingman_file,
            wingman_config=wingman_config,
        )

        if reload_config:
            await self.load_config(config_dir=config_dir)

        message = f"Wingman {wingman_config.name}'s basic config changed."
        if not silent:
            self.printr.toast(message)
        else:
            self.printr.print(text=message, server_only=True)

    # POST config/wingman/default
    async def set_default_wingman(
        self,
        config_dir: ConfigDirInfo,
        wingman_name: str,
    ):
        _dir, config = self.config_manager.parse_config(config_dir)
        wingman_config_files = await self.get_wingmen_config_files(config_dir.name)

        made_changes = False

        for wingman_config_file in wingman_config_files:
            if wingman_config_file.is_deleted:
                continue

            wingman_config = config.wingmen[wingman_config_file.name]

            if wingman_config_file.name == wingman_name:
                if (
                    hasattr(wingman_config, "is_voice_activation_default")
                    and wingman_config.is_voice_activation_default
                ):
                    # Undefault the current default wingman
                    wingman_config.is_voice_activation_default = False
                    made_changes = True
                else:
                    # Set the new default if it's not already
                    wingman_config.is_voice_activation_default = True
                    made_changes = True
            else:
                if wingman_config.is_voice_activation_default:
                    # Ensure other wingmen are not default
                    wingman_config.is_voice_activation_default = False
                    made_changes = True

            # Only save if there's a change
            if made_changes:
                await self.save_wingman_config(
                    config_dir=config_dir,
                    wingman_file=wingman_config_file,
                    wingman_config=wingman_config,
                    silent=True,
                )
                made_changes = False

    # GET config/defaults
    async def get_defaults_config(self):
        return self.config_manager.load_defaults_config()

    # POST config/defaults
    async def save_defaults_config(
        self,
        config: NestedConfig,
        silent: bool = False,
        validate: bool = False,
    ):
        # save the defaults config file
        self.config_manager.default_config = config
        saved = self.config_manager.save_defaults_config()

        if not saved:
            self.printr.toast_error("Failed to save default configuration.")
            return

        message = "Default configuration changed."
        if not silent:
            self.printr.toast(message)
        else:
            self.printr.print(text=message, server_only=True)

        # rewrite the Wingman config in each config dir, building a new diff to the the new defaults
        for config_dir in self.config_manager.get_config_dirs():
            for wingman_file in await self.get_wingmen_config_files(config_dir.name):
                wingman = self.tower.get_wingman_by_name(wingman_file.name)

                if wingman:
                    # load the wingman config from file so that the new defaults take effect
                    # if we'd use wingman.config, it would still have the old defaults and detect its diffs as changes
                    wingman_config = self.config_manager.load_wingman_config(
                        config_dir=config_dir, wingman_file=wingman_file
                    )
                    # active wingman that needs to be updated and saved
                    await self.save_wingman_config(
                        config_dir=config_dir,
                        wingman_file=wingman_file,
                        wingman_config=wingman_config,
                        silent=silent,
                        validate=validate,
                    )

                else:
                    # wingman in inactive config - just save the file
                    wingman_config = self.config_manager.load_wingman_config(
                        config_dir=config_dir, wingman_file=wingman_file
                    )
                    if self.config_manager.save_wingman_config(
                        config_dir=config_dir,
                        wingman_file=wingman_file,
                        wingman_config=wingman_config,
                    ):
                        self.printr.print(
                            text=f"Inactive Wingman '{wingman_config.name}'s config saved.",
                            server_only=True,
                        )

    async def migrate_configs(self, system_manager: SystemManager):
        migration_service = ConfigMigrationService(
            config_manager=self.config_manager, system_manager=system_manager
        )
        migration_service.migrate_to_latest()
