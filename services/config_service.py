import asyncio
import shutil
from typing import Optional
from fastapi import APIRouter, HTTPException
from api.enums import LogSource, LogType
from api.interface import (
    ConfigDirInfo,
    ConfigWithDirInfo,
    ConfigsInfo,
    DuplicateWingmanRequest,
    DuplicateWingmanResult,
    McpConfig,
    McpConnectResult,
    McpServerConfig,
    McpServerState,
    NestedConfig,
    NewWingmanTemplate,
    CommandCategoryConfig,
    SkillConfig,
    SkillBase,
    WingmanConfig,
    WingmanConfigFileInfo,
    WingmanSkillState,
)
from services.config_manager import ConfigManager
from services.config_migration_service import ConfigMigrationService
from services.file import get_custom_skills_dir
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
            path="/config/wingman/duplicate",
            endpoint=self.duplicate_wingman,
            response_model=DuplicateWingmanResult,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/config/wingman/restore-defaults",
            endpoint=self.restore_wingman_defaults,
            response_model=ConfigWithDirInfo,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/config/wingman/can-restore-defaults",
            endpoint=self.can_restore_wingman_defaults,
            response_model=bool,
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
            path="/config/save-commands",
            endpoint=self.save_commands,
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
            path="/wingman-skills",
            endpoint=self.get_wingman_skills,
            response_model=list[WingmanSkillState],
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/wingman-skills/toggle",
            endpoint=self.toggle_wingman_skill,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["DELETE"],
            path="/custom-skills",
            endpoint=self.uninstall_skill,
            tags=tags,
        )
        # MCP server endpoints
        self.router.add_api_route(
            methods=["GET"],
            path="/wingman-mcps",
            endpoint=self.get_wingman_mcps,
            response_model=list[McpServerState],
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/wingman-mcps/toggle",
            endpoint=self.toggle_wingman_mcp,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/wingman-mcps/connect",
            endpoint=self.connect_wingman_mcp,
            response_model=McpConnectResult,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/mcp-servers",
            endpoint=self.save_mcp_server,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["DELETE"],
            path="/mcp-servers",
            endpoint=self.delete_mcp_server,
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
        self.router.add_api_route(
            methods=["POST"],
            path="/config/wingman/command-category",
            endpoint=self.add_command_category,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["PATCH"],
            path="/config/wingman/command-category",
            endpoint=self.update_command_category,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["DELETE"],
            path="/config/wingman/command-category",
            endpoint=self.delete_command_category,
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

    # GET /wingman-skills
    async def get_wingman_skills(
        self,
        config_name: str,
        wingman_name: str,
    ) -> list[WingmanSkillState]:
        """Get all skills with their enabled/disabled state for a specific wingman."""
        import sys

        try:
            # Get all available skills
            all_skills = ModuleManager.read_available_skills()

            # Get the wingman's config to check discoverable_skills
            config_dir = self.config_manager.get_config_dir(config_name)
            wingman_files = self.config_manager.get_wingmen_configs(config_dir)

            # Find the wingman file
            wingman_file = next(
                (f for f in wingman_files if f.name == wingman_name), None
            )
            if not wingman_file:
                self.printr.toast_error(f"Wingman '{wingman_name}' not found.")
                return []

            # Load the wingman config
            wingman_config = self.config_manager.load_wingman_config(
                config_dir=config_dir, wingman_file=wingman_file
            )

            discoverable_skills = wingman_config.discoverable_skills

            # Get current platform for filtering
            current_platform = sys.platform
            platform_map = {"win32": "windows", "darwin": "darwin", "linux": "linux"}
            normalized_platform = platform_map.get(current_platform, current_platform)

            # Build response with enabled state
            result = []
            skipped_platform = []
            for skill in all_skills:
                # Check platform compatibility
                platforms = skill.config.platforms
                if platforms and normalized_platform not in platforms:
                    skipped_platform.append(skill.name)
                    continue  # Skip platform-incompatible skills

                is_enabled = skill.name in discoverable_skills
                result.append(WingmanSkillState(skill=skill, is_enabled=is_enabled))

            if skipped_platform:
                self.printr.print(
                    f"Skills not available on {normalized_platform}: {', '.join(skipped_platform)}",
                    color=LogType.WARNING,
                    server_only=True,
                )

            return result

        except Exception as e:
            self.printr.toast_error(str(e))
            raise e

    # POST /wingman-skills/toggle
    async def toggle_wingman_skill(
        self,
        config_dir: ConfigDirInfo,
        wingman_file: WingmanConfigFileInfo,
        skill_name: str,
        enabled: bool,
    ):
        """Enable or disable a skill for a specific wingman.

        Uses incremental skill toggle to avoid reinitializing all skills,
        which improves performance and prevents resource accumulation.
        """
        try:
            # Load the wingman config
            wingman_config = self.config_manager.load_wingman_config(
                config_dir=config_dir, wingman_file=wingman_file
            )

            # Initialize discoverable_skills if needed (should always be present as non-optional)
            if (
                not hasattr(wingman_config, "discoverable_skills")
                or wingman_config.discoverable_skills is None
            ):
                wingman_config.discoverable_skills = []

            if enabled:
                # Add to discoverable list (enable the skill)
                if skill_name not in wingman_config.discoverable_skills:
                    wingman_config.discoverable_skills.append(skill_name)
            else:
                # Remove from discoverable list (disable the skill)
                if skill_name in wingman_config.discoverable_skills:
                    wingman_config.discoverable_skills.remove(skill_name)

            # Save the config WITHOUT reinitializing all skills
            await self.save_wingman_config(
                config_dir=config_dir,
                wingman_file=wingman_file,
                wingman_config=wingman_config,
                silent=True,  # We'll show our own message
            )

            # Incrementally toggle just this skill on the active wingman
            wingman = (
                self.tower.get_wingman_by_name(wingman_file.name)
                if self.tower
                else None
            )
            if wingman:
                if enabled:
                    success, message = await wingman.enable_skill(skill_name)
                else:
                    success, message = await wingman.disable_skill(skill_name)

                if not success:
                    self.printr.toast_error(message)
                    return

            action = "enabled" if enabled else "disabled"
            self.printr.print(
                f"Skill '{skill_name}' {action} for {wingman_file.name}.",
                server_only=True,
            )

        except Exception as e:
            self.printr.toast_error(str(e))
            raise e

    # DELETE /custom-skills
    async def uninstall_skill(self, skill_name: str):
        """Uninstall a custom skill globally: disable it on all wingmen, remove all
        custom property overrides from every wingman config, and delete the skill
        directory from custom_skills.

        Args:
            skill_name: The skill's folder name in custom_skills (e.g. 'heads_up'),
                        NOT the internal class name (e.g. 'HeadsUp').

        This is a cross-wingman, cross-config operation designed to allow users to
        cleanly remove a custom skill version before installing a new one.
        """
        import os

        # 1. Verify the skill is actually a custom skill
        custom_skills_dir = get_custom_skills_dir()
        skill_dir_path = os.path.join(custom_skills_dir, skill_name)

        if not os.path.isdir(skill_dir_path):
            msg = f"Custom skill '{skill_name}' not found in custom_skills directory."
            self.printr.toast_error(msg)
            raise HTTPException(status_code=404, detail=msg)

        self.printr.print(
            f"Starting uninstall of custom skill '{skill_name}'...",
            color=LogType.WARNING,
            source=LogSource.SYSTEM,
            source_name=self.source_name,
            server_only=True,
        )

        try:
            # 2. Determine the skill's internal name from its default_config.yaml
            skill_internal_name = skill_name  # fallback to folder name
            default_config_path = os.path.join(skill_dir_path, "default_config.yaml")
            if os.path.isfile(default_config_path):
                try:
                    skill_default_config = self.config_manager.read_config(
                        default_config_path
                    )
                    if skill_default_config and "name" in skill_default_config:
                        skill_internal_name = skill_default_config["name"]
                except Exception:
                    pass  # use folder name as fallback

            skill_module_prefix = f"skills.{skill_name}.main"
            affected_wingmen = []

            # 3. Disable on all active wingmen in the tower (runtime)
            if self.tower:
                for wingman in self.tower.wingmen:
                    skill_was_active = any(
                        s.config.name == skill_internal_name for s in wingman.skills
                    )
                    if skill_was_active:
                        try:
                            success, msg = await wingman.disable_skill(
                                skill_internal_name
                            )
                            self.printr.print(
                                f"  Runtime disable '{skill_internal_name}' on '{wingman.name}': {msg}",
                                server_only=True,
                            )
                        except Exception as e:
                            self.printr.print(
                                f"  Warning: could not runtime-disable '{skill_internal_name}' on '{wingman.name}': {e}",
                                color=LogType.WARNING,
                                server_only=True,
                            )

            # 4. Remove skill from ALL wingman configs across ALL config dirs
            for config_dir in self.config_manager.get_config_dirs():
                if config_dir.is_deleted:
                    continue

                wingman_files = self.config_manager.get_wingmen_configs(config_dir)
                for wingman_file in wingman_files:
                    if wingman_file.is_deleted:
                        continue

                    try:
                        wingman_config = self.config_manager.load_wingman_config(
                            config_dir=config_dir, wingman_file=wingman_file
                        )
                    except Exception as e:
                        self.printr.print(
                            f"  Warning: could not load config for '{wingman_file.name}' in '{config_dir.name}': {e}",
                            color=LogType.WARNING,
                            server_only=True,
                        )
                        continue

                    modified = False

                    # Remove from discoverable_skills list
                    if (
                        wingman_config.discoverable_skills
                        and skill_internal_name in wingman_config.discoverable_skills
                    ):
                        wingman_config.discoverable_skills.remove(skill_internal_name)
                        modified = True
                        self.printr.print(
                            f"  Removed '{skill_internal_name}' from discoverable_skills of '{wingman_file.name}' in '{config_dir.name}'.",
                            server_only=True,
                        )

                    # Remove skill overrides from skills list (match by name OR module)
                    if wingman_config.skills:
                        original_count = len(wingman_config.skills)
                        wingman_config.skills = [
                            s
                            for s in wingman_config.skills
                            if s.name != skill_internal_name
                            and s.module != skill_module_prefix
                        ]
                        if len(wingman_config.skills) < original_count:
                            modified = True
                            self.printr.print(
                                f"  Removed skill config overrides for '{skill_internal_name}' from '{wingman_file.name}' in '{config_dir.name}'.",
                                server_only=True,
                            )
                        if not wingman_config.skills:
                            wingman_config.skills = None

                    if modified:
                        affected_wingmen.append(
                            f"{wingman_file.name} ({config_dir.name})"
                        )
                        # Save the cleaned config (wrapped in try/except so one failure
                        # doesn't prevent cleanup of remaining configs)
                        try:
                            self.config_manager.save_wingman_config(
                                config_dir=config_dir,
                                wingman_file=wingman_file,
                                wingman_config=wingman_config,
                            )
                        except Exception as e:
                            self.printr.print(
                                f"  Warning: failed to save cleaned config for '{wingman_file.name}' in '{config_dir.name}': {e}",
                                color=LogType.WARNING,
                                server_only=True,
                            )

            # 5. Delete the custom skill directory
            try:
                shutil.rmtree(skill_dir_path)
                self.printr.print(
                    f"  Deleted custom skill directory: {skill_dir_path}",
                    color=LogType.WARNING,
                    server_only=True,
                )
            except Exception as e:
                msg = f"Failed to delete skill directory '{skill_dir_path}': {e}"
                self.printr.toast_error(msg)
                raise HTTPException(status_code=500, detail=msg) from e

            # 6. Summary logging and toast
            if affected_wingmen:
                affected_list = ", ".join(affected_wingmen)
                self.printr.print(
                    f"Custom skill '{skill_internal_name}' uninstalled. Affected Wingmen: {affected_list}",
                    color=LogType.WARNING,
                    server_only=True,
                )
                self.printr.toast(
                    f"Custom skill '{skill_internal_name}' uninstalled. Cleaned up configs for: {affected_list}"
                )
            else:
                self.printr.print(
                    f"Custom skill '{skill_internal_name}' uninstalled. No Wingman configs were affected.",
                    color=LogType.WARNING,
                    server_only=True,
                )
                self.printr.toast(
                    f"Custom skill '{skill_internal_name}' uninstalled successfully."
                )

        except HTTPException:
            raise
        except Exception as e:
            self.printr.toast_error(f"Failed to uninstall skill '{skill_name}': {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to uninstall skill '{skill_name}': {e}",
            ) from e

    # GET /wingman-mcps
    async def get_wingman_mcps(
        self,
        config_name: str,
        wingman_name: str,
    ) -> list[McpServerState]:
        """Get all MCP servers with their enabled/connected state for a specific wingman."""
        try:
            # Get the wingman's config
            config_dir = self.config_manager.get_config_dir(config_name)
            wingman_files = self.config_manager.get_wingmen_configs(config_dir)

            # Find the wingman file
            wingman_file = next(
                (f for f in wingman_files if f.name == wingman_name), None
            )
            if not wingman_file:
                self.printr.toast_error(f"Wingman '{wingman_name}' not found.")
                return []

            # Load the wingman config
            wingman_config = self.config_manager.load_wingman_config(
                config_dir=config_dir, wingman_file=wingman_file
            )

            # Get MCP servers from central mcp.yaml
            mcp_config = self.config_manager.mcp_config
            mcp_servers = mcp_config.servers if mcp_config else []
            discoverable_mcps = wingman_config.discoverable_mcps

            # Get connection state and tools from the active wingman if available
            wingman = (
                self.tower.get_wingman_by_name(wingman_name) if self.tower else None
            )
            registry = None
            if wingman and hasattr(wingman, "mcp_registry") and wingman.mcp_registry:
                registry = wingman.mcp_registry

                # Brief wait for MCP connections to complete if wingman just initialized
                # MCPs connect asynchronously, so we give them a moment to finish
                if registry.server_count == 0:
                    await asyncio.sleep(0.5)

            # Build response with enabled/connected state, tools, and errors
            result = []
            for mcp_server in mcp_servers:
                # Determine if enabled: if in discoverable_mcps whitelist, it's enabled
                # Otherwise it's disabled (the server's default discoverable_by_default state only affects
                # initial wingman creation, not runtime state)
                is_enabled = mcp_server.name in discoverable_mcps

                is_connected = False
                tools = None
                error = None

                if registry:
                    is_connected = (
                        mcp_server.name in registry.get_connected_server_names()
                    )
                    if is_connected:
                        tools = registry.get_server_tools(mcp_server.name)
                    else:
                        error = registry.get_server_error(mcp_server.name)

                result.append(
                    McpServerState(
                        config=mcp_server,
                        is_enabled=is_enabled,
                        is_connected=is_connected,
                        tools=tools,
                        error=error,
                    )
                )

            return result

        except Exception as e:
            self.printr.toast_error(str(e))
            raise e

    # POST /wingman-mcps/toggle
    async def toggle_wingman_mcp(
        self,
        config_dir: ConfigDirInfo,
        wingman_file: WingmanConfigFileInfo,
        mcp_name: str,
        enabled: bool,
    ):
        """Enable or disable an MCP server for a specific wingman.

        Uses incremental MCP toggle to avoid reinitializing all MCP connections,
        which improves performance and prevents unnecessary disconnections.
        """
        try:
            # Load the wingman config
            wingman_config = self.config_manager.load_wingman_config(
                config_dir=config_dir, wingman_file=wingman_file
            )

            # Initialize discoverable_mcps if needed (should always be present as non-optional)
            if (
                not hasattr(wingman_config, "discoverable_mcps")
                or wingman_config.discoverable_mcps is None
            ):
                wingman_config.discoverable_mcps = []

            if enabled:
                # Add to discoverable list (enable the MCP)
                if mcp_name not in wingman_config.discoverable_mcps:
                    wingman_config.discoverable_mcps.append(mcp_name)
            else:
                # Remove from discoverable list (disable the MCP)
                if mcp_name in wingman_config.discoverable_mcps:
                    wingman_config.discoverable_mcps.remove(mcp_name)

            # Save the config WITHOUT reinitializing all MCPs
            await self.save_wingman_config(
                config_dir=config_dir,
                wingman_file=wingman_file,
                wingman_config=wingman_config,
                silent=True,  # We'll show our own message
            )

            # Incrementally toggle just this MCP on the active wingman
            wingman = (
                self.tower.get_wingman_by_name(wingman_file.name)
                if self.tower
                else None
            )
            if wingman:
                if enabled:
                    if hasattr(wingman, "enable_mcp"):
                        success, message = await wingman.enable_mcp(mcp_name)
                    else:
                        # Fallback for wingmen without incremental MCP support
                        if hasattr(wingman, "init_mcps"):
                            await wingman.init_mcps()
                        success, message = True, f"MCP server '{mcp_name}' enabled."
                else:
                    if hasattr(wingman, "disable_mcp"):
                        success, message = await wingman.disable_mcp(mcp_name)
                    else:
                        # Fallback for wingmen without incremental MCP support
                        if hasattr(wingman, "init_mcps"):
                            await wingman.init_mcps()
                        success, message = True, f"MCP server '{mcp_name}' disabled."

                if not success:
                    self.printr.toast_error(message)
                    return

            action = "enabled" if enabled else "disabled"
            self.printr.print(
                f"MCP server '{mcp_name}' {action}.",
                server_only=True,
                source_name=wingman_file.name,
            )

        except Exception as e:
            self.printr.toast_error(str(e))
            raise e

    # POST /mcp-servers
    async def save_mcp_server(self, mcp_server: McpServerConfig):
        """Save an MCP server to the central mcp.yaml and refresh all active wingmen."""
        try:
            mcp_config = self.config_manager.mcp_config
            if not mcp_config:
                mcp_config = McpConfig(servers=[])
                self.config_manager.mcp_config = mcp_config

            # Check if server already exists (update) or is new (add)
            existing_index = next(
                (
                    i
                    for i, s in enumerate(mcp_config.servers)
                    if s.name == mcp_server.name
                ),
                None,
            )

            if existing_index is not None:
                # Update existing server
                mcp_config.servers[existing_index] = mcp_server
                self.printr.print(
                    f"Updated MCP server '{mcp_server.name}' in mcp.yaml",
                    server_only=True,
                )
            else:
                # Add new server
                mcp_config.servers.append(mcp_server)
                self.printr.print(
                    f"Added MCP server '{mcp_server.name}' to mcp.yaml",
                    server_only=True,
                )

            # Save to file
            self.config_manager.save_mcp_config()

            # Refresh MCPs on all active wingmen so they can use the new/updated server
            if self.tower:
                for wingman in self.tower.wingmen:
                    if hasattr(wingman, "init_mcps"):
                        await wingman.init_mcps()

            self.printr.toast(
                f"MCP server '{mcp_server.display_name or mcp_server.name}' saved."
            )

        except Exception as e:
            self.printr.toast_error(str(e))
            raise e

    # DELETE /mcp-servers
    async def delete_mcp_server(self, mcp_name: str):
        """Delete an MCP server from the central mcp.yaml and refresh all active wingmen."""
        try:
            mcp_config = self.config_manager.mcp_config
            if not mcp_config or not mcp_config.servers:
                self.printr.toast_error(f"MCP server '{mcp_name}' not found.")
                return

            # Find and remove the server
            original_count = len(mcp_config.servers)
            mcp_config.servers = [s for s in mcp_config.servers if s.name != mcp_name]

            if len(mcp_config.servers) == original_count:
                self.printr.toast_error(f"MCP server '{mcp_name}' not found.")
                return

            # Save to file
            self.config_manager.save_mcp_config()

            # Refresh MCPs on all active wingmen to disconnect from removed server
            if self.tower:
                for wingman in self.tower.wingmen:
                    if hasattr(wingman, "init_mcps"):
                        await wingman.init_mcps()

            self.printr.toast(f"MCP server '{mcp_name}' deleted.")

        except Exception as e:
            self.printr.toast_error(str(e))
            raise e

    # POST /wingman-mcps/connect
    async def connect_wingman_mcp(
        self,
        config_dir: ConfigDirInfo,
        wingman_file: WingmanConfigFileInfo,
        mcp_name: str,
    ) -> McpConnectResult:
        """Connect (or reconnect) to a specific MCP server and return immediate feedback."""
        try:
            wingman = (
                self.tower.get_wingman_by_name(wingman_file.name)
                if self.tower
                else None
            )
            if not wingman:
                return McpConnectResult(
                    success=False,
                    server_name=mcp_name,
                    error=f"Wingman '{wingman_file.name}' not found or not active.",
                )

            if not hasattr(wingman, "mcp_registry") or not wingman.mcp_registry:
                return McpConnectResult(
                    success=False,
                    server_name=mcp_name,
                    error="MCP registry not available on this wingman.",
                )

            # Find the MCP config from central mcp.yaml
            mcp_config = self.config_manager.mcp_config
            server_config = None
            if mcp_config and mcp_config.servers:
                for cfg in mcp_config.servers:
                    if cfg.name == mcp_name:
                        server_config = cfg
                        break

            if not server_config:
                return McpConnectResult(
                    success=False,
                    server_name=mcp_name,
                    error=f"MCP server '{mcp_name}' not found in mcp.yaml.",
                )

            # Build headers with secrets (same logic as init_mcps)
            headers = {}
            if server_config.headers:
                headers.update(server_config.headers)

            # Check for API key in secrets
            if hasattr(wingman, "secret_keeper"):
                secret_key = f"mcp_{server_config.name}"
                api_key = await wingman.secret_keeper.retrieve(
                    requester=wingman.name,
                    key=secret_key,
                    prompt_if_missing=False,
                )
                if api_key:
                    if not any(
                        k.lower() in ["authorization", "api-key", "x-api-key"]
                        for k in headers.keys()
                    ):
                        headers["Authorization"] = f"Bearer {api_key}"

            # Try to connect
            import asyncio

            default_timeout = 60.0 if server_config.type.value == "stdio" else 30.0
            timeout = (
                float(server_config.timeout)
                if server_config.timeout
                else default_timeout
            )

            try:
                connection = await asyncio.wait_for(
                    wingman.mcp_registry.register_server(
                        config=server_config,
                        headers=headers if headers else None,
                    ),
                    timeout=timeout,
                )

                if connection:
                    tools = wingman.mcp_registry.get_server_tools(mcp_name)
                    tool_count = len(tools) if tools else 0
                    self.printr.print(
                        f"🌐 MCP '{server_config.display_name}' connected with {tool_count} tools.",
                        source_name=wingman_file.name,
                        server_only=True,
                    )
                    return McpConnectResult(
                        success=True,
                        server_name=mcp_name,
                        tools=tools,
                    )
                else:
                    error = wingman.mcp_registry.get_server_error(mcp_name)
                    return McpConnectResult(
                        success=False,
                        server_name=mcp_name,
                        error=error or "Connection returned no result.",
                    )

            except asyncio.TimeoutError:
                error_msg = f"Connection timed out ({int(timeout)}s)."
                wingman.mcp_registry.set_server_error(mcp_name, error_msg)
                return McpConnectResult(
                    success=False,
                    server_name=mcp_name,
                    error=error_msg,
                )

        except Exception as e:
            self.printr.toast_error(str(e))
            return McpConnectResult(
                success=False,
                server_name=mcp_name,
                error=str(e),
            )

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
            color=LogType.STARTUP,
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

    # POST /config/wingman/duplicate
    async def duplicate_wingman(self, request: DuplicateWingmanRequest):
        """Duplicate a Wingman into a chosen target config/context.

        Server-side responsibilities:
        - Validate name with the same constraints as the client
        - Ensure the new name does not exist in the target context
        - Copy all settings from the source Wingman
        - Ensure YAML filename stem matches wingman_config.name
        - Reload the selected target config so the copy is available immediately
        """

        try:
            new_wingman_file = self.config_manager.duplicate_wingman_config(
                source_config_dir=request.source_config_dir,
                source_wingman_file=request.source_wingman_file,
                target_config_dir=request.target_config_dir,
                new_name=request.new_name,
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except FileExistsError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            # Keep unexpected errors visible
            raise HTTPException(status_code=500, detail=str(e)) from e

        await self.load_config(request.target_config_dir)
        return DuplicateWingmanResult(
            config_dir=request.target_config_dir,
            wingman_file=new_wingman_file,
        )

    # POST /config/wingman/restore-defaults
    async def restore_wingman_defaults(
        self, config_dir: ConfigDirInfo, wingman_file: WingmanConfigFileInfo
    ) -> ConfigWithDirInfo:
        """Restore a Wingman to its shipped default configuration.

        The shipped default is determined by scanning template files under
        templates/configs/ (installation templates in release, repo templates in dev).
        After restoring, the config is reloaded so the active context reflects the reset.
        """

        try:
            self.config_manager.restore_wingman_from_template(
                config_dir=config_dir, wingman_file=wingman_file
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        return await self.load_config(config_dir)

    # POST /config/wingman/can-restore-defaults
    async def can_restore_wingman_defaults(
        self, config_dir: ConfigDirInfo, wingman_file: WingmanConfigFileInfo
    ) -> bool:
        """Return whether a Wingman has shipped template defaults in this context."""

        can_restore = self.config_manager.can_restore_wingman_from_template(
            config_dir=config_dir,
            wingman_file=wingman_file,
        )
        return can_restore

    # POST config/save-wingman
    async def save_wingman_config(
        self,
        config_dir: ConfigDirInfo,
        wingman_file: WingmanConfigFileInfo,
        wingman_config: WingmanConfig,
        silent: bool = False,
        skip_config_validation: bool = True,
    ):
        """Save wingman configuration and optionally update the active wingman.

        This is the single authoritative save path for Wingman configuration.

        IMPORTANT:
        - Skill + MCP activation state is controlled via dedicated toggle endpoints
          and stored in `discoverable_skills` / `discoverable_mcps`.
        - Some client flows (e.g. saving Skill custom properties) may send a partial
          WingmanConfig payload. Since `discoverable_*` default to an empty list,
          persisting the raw payload can unintentionally deactivate skills/MCPs.
                - To protect against partial payloads, activation state is preserved from the
                    on-disk config ONLY when the incoming payload omits `discoverable_skills`
                    and/or `discoverable_mcps`.

        Args:
            config_dir: The config directory info
            wingman_file: The wingman file info
            wingman_config: The wingman configuration to save
            silent: If True, don't show toast notification
            skip_config_validation: If False, validate the config before applying
        """

        # Check if tower is available
        if not self.tower:
            self.printr.toast_error(
                "Cannot save wingman config: Tower not initialized. Please wait for the config to fully load."
            )
            return

        # Load current on-disk config for merge/preservation
        existing_config: WingmanConfig | None = None
        try:
            existing_config = self.config_manager.load_wingman_config(
                config_dir=config_dir,
                wingman_file=wingman_file,
            )
        except Exception:
            # Fallback to trusting the incoming config if disk read fails
            existing_config = None

        merged_config = wingman_config
        if existing_config:
            # Merge partial payloads: prefer incoming values, but keep existing values
            # for fields that are omitted from the request.
            merged_data = existing_config.model_dump()
            merged_data.update(wingman_config.model_dump(exclude_unset=True))
            merged_config = WingmanConfig(**merged_data)

            # Special-case merge for Skill overrides: clients may send only a subset
            # (e.g. when editing custom properties of a single skill). Replacing the
            # entire list would drop unrelated overrides.
            if "skills" in wingman_config.model_fields_set:
                merged_config.skills = self._merge_skill_configs(
                    existing=existing_config.skills,
                    incoming=wingman_config.skills,
                )

            # Protect against partial client payloads inadvertently deactivating
            # skills/MCPs. Preserve from disk only when the incoming payload omitted
            # these fields entirely.
            if "discoverable_skills" not in wingman_config.model_fields_set:
                merged_config.discoverable_skills = existing_config.discoverable_skills
            if "discoverable_mcps" not in wingman_config.model_fields_set:
                merged_config.discoverable_mcps = existing_config.discoverable_mcps

        # update the wingman
        wingman = self.tower.get_wingman_by_name(wingman_file.name)
        if not wingman:
            # try to enable a previously disabled wingman
            disabled_config = self.tower.get_disabled_wingman_by_name(
                merged_config.name
            )
            if disabled_config and not merged_config.disabled:
                enabled = await self.tower.enable_wingman(
                    wingman_name=merged_config.name,
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
            config=merged_config,
            skip_config_validation=skip_config_validation,
        )

        if not updated:
            self.printr.toast_error(
                f"New config for Wingman '{merged_config.name}' is invalid."
            )
            return

        # save the config file
        self.config_manager.save_wingman_config(
            config_dir=config_dir,
            wingman_file=wingman_file,
            wingman_config=merged_config,
        )

        message = f"Wingman {merged_config.name}'s config changed."
        if not silent:
            self.printr.toast(message)
        else:
            self.printr.print(text=message, server_only=True)

        # Notify listeners that a wingman config was saved (for input hook refresh)
        await self.config_events.publish("wingman_config_saved", merged_config)

    @staticmethod
    def _merge_skill_configs(
        existing: list[SkillConfig] | None,
        incoming: list[SkillConfig] | None,
    ) -> list[SkillConfig] | None:
        if incoming is None:
            return existing
        if existing is None:
            return incoming

        def _key(skill_cfg: SkillConfig) -> str:
            return f"{skill_cfg.module}:{skill_cfg.name}"

        merged_by_key: dict[str, SkillConfig] = {_key(s): s for s in existing}
        for skill_cfg in incoming:
            merged_by_key[_key(skill_cfg)] = skill_cfg

        # Preserve existing order, then append new incoming entries
        ordered: list[SkillConfig] = []
        seen: set[str] = set()
        for skill_cfg in existing:
            k = _key(skill_cfg)
            ordered.append(merged_by_key[k])
            seen.add(k)
        for skill_cfg in incoming:
            k = _key(skill_cfg)
            if k not in seen:
                ordered.append(skill_cfg)
                seen.add(k)

        return ordered

    # POST config/save-commands
    async def save_commands(
        self,
        wingman_name: str,
        silent: bool = True,
    ):
        """Save only the commands section of a wingman config.

        This is a targeted save operation for skills that modify commands
        (e.g., QuickCommands adding instant_activation phrases).

        Args:
            wingman_name: Name of the wingman whose commands to save
            silent: If True, don't show toast notification (default: True)
        """
        if not self.tower:
            self.printr.toast_error("Cannot save commands: Tower not initialized.")
            return

        wingman = self.tower.get_wingman_by_name(wingman_name)
        if not wingman:
            self.printr.toast_error(f"Wingman '{wingman_name}' not found.")
            return

        # Get the wingman file info
        wingman_file = None
        for wf in self.config_manager.get_wingmen_configs(
            self.config_manager.config_dir
        ):
            if wf.name == wingman_name:
                wingman_file = wf
                break

        if not wingman_file:
            self.printr.toast_error(f"Config file for '{wingman_name}' not found.")
            return

        # Use targeted save that only updates the commands field in YAML
        # This avoids full config serialization and preserves other fields
        self.config_manager.save_wingman_commands(
            config_dir=self.config_manager.config_dir,
            wingman_file=wingman_file,
            commands=wingman.config.commands,
        )

        message = f"Commands saved for {wingman_name}."
        if not silent:
            self.printr.toast(message)
        else:
            self.printr.print(text=message, server_only=True)

    # POST /config/wingman/command-category
    async def add_command_category(
        self,
        config_dir: ConfigDirInfo,
        wingman_file: WingmanConfigFileInfo,
        category: CommandCategoryConfig,
    ):
        """Add a new command category to a wingman."""
        try:
            # Load config
            wingman_config = self.config_manager.load_wingman_config(
                config_dir=config_dir, wingman_file=wingman_file
            )

            # Initialize categories if needed
            if wingman_config.command_categories is None:
                wingman_config.command_categories = []

            # Check if ID exists
            if any(c.id == category.id for c in wingman_config.command_categories):
                raise HTTPException(
                    status_code=400,
                    detail=f"Category with ID {category.id} already exists.",
                )

            wingman_config.command_categories.append(category)

            # Save
            await self.save_wingman_config(
                config_dir=config_dir,
                wingman_file=wingman_file,
                wingman_config=wingman_config,
                silent=True,
            )
            self.printr.print(
                f"Added category '{category.name}' to {wingman_file.name}",
                server_only=True,
            )

        except Exception as e:
            self.printr.toast_error(str(e))
            raise HTTPException(status_code=500, detail=str(e))

    # PATCH /config/wingman/command-category
    async def update_command_category(
        self,
        config_dir: ConfigDirInfo,
        wingman_file: WingmanConfigFileInfo,
        category: CommandCategoryConfig,
    ):
        """Update an existing command category (rename)."""
        try:
            # Load config
            wingman_config = self.config_manager.load_wingman_config(
                config_dir=config_dir, wingman_file=wingman_file
            )

            if not wingman_config.command_categories:
                raise HTTPException(status_code=404, detail="Category not found.")

            found = False
            for c in wingman_config.command_categories:
                if c.id == category.id:
                    c.name = category.name
                    found = True
                    break

            if not found:
                raise HTTPException(status_code=404, detail="Category not found.")

            # Save
            await self.save_wingman_config(
                config_dir=config_dir,
                wingman_file=wingman_file,
                wingman_config=wingman_config,
                silent=True,
            )
            self.printr.print(
                f"Updated category '{category.name}' in {wingman_file.name}",
                server_only=True,
            )

        except Exception as e:
            self.printr.toast_error(str(e))
            raise HTTPException(status_code=500, detail=str(e))

    # DELETE /config/wingman/command-category
    async def delete_command_category(
        self,
        config_dir: ConfigDirInfo,
        wingman_file: WingmanConfigFileInfo,
        category_id: str,
    ):
        """Delete a command category and un-assign commands."""
        try:
            # Load config
            wingman_config = self.config_manager.load_wingman_config(
                config_dir=config_dir, wingman_file=wingman_file
            )

            if not wingman_config.command_categories:
                raise HTTPException(status_code=404, detail="Category not found.")

            # Remove category
            original_len = len(wingman_config.command_categories)
            wingman_config.command_categories = [
                c for c in wingman_config.command_categories if c.id != category_id
            ]

            if len(wingman_config.command_categories) == original_len:
                raise HTTPException(status_code=404, detail="Category not found.")

            # Un-assign commands
            if wingman_config.commands:
                for cmd in wingman_config.commands:
                    if cmd.category_id == category_id:
                        cmd.category_id = None

            # Save
            await self.save_wingman_config(
                config_dir=config_dir,
                wingman_file=wingman_file,
                wingman_config=wingman_config,
                silent=True,
            )
            self.printr.print(
                f"Deleted category {category_id} from {wingman_file.name}",
                server_only=True,
            )

        except Exception as e:
            self.printr.toast_error(str(e))
            raise HTTPException(status_code=500, detail=str(e))

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
        skip_config_validation: bool = True,
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
                        skip_config_validation=skip_config_validation,
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
            config_manager=self.config_manager,
            system_manager=system_manager,
        )
        migration_service.migrate_to_latest()
        # Reload defaults config after migration in case schema changed
        self.config_manager.default_config = self.config_manager.load_defaults_config()
