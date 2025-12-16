import traceback
from copy import deepcopy
import time
import asyncio
import threading
from typing import (
    Any,
    Dict,
    Optional,
    TYPE_CHECKING,
)
from openai.types.chat import ChatCompletion
from api.interface import (
    CommandConfig,
    SettingsConfig,
    SkillConfig,
    SoundConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from api.enums import (
    CommandTag,
    LogSource,
    LogType,
    TtsProvider,
    SttProvider,
    ConversationProvider,
    WingmanInitializationErrorType,
)
from api.commands import McpStateChangedCommand
from providers.xvasynth import XVASynth
from services.audio_player import AudioPlayer
from services.benchmark import Benchmark
from services.command_manager import CommandManager
from services.conversation_manager import ConversationManager
from services.markdown import cleanup_text
from services.module_manager import ModuleManager
from services.provider_registry import ProviderRegistry
from services.skill_registry import SkillRegistry
from services.mcp_client import McpClient
from services.mcp_registry import McpRegistry
from services.capability_registry import CapabilityRegistry
from services.tool_executor import ToolExecutor
from services.secret_keeper import SecretKeeper
from services.printr import Printr
from services.audio_library import AudioLibrary
from skills.skill_base import Skill

if TYPE_CHECKING:
    from services.tower import Tower

printr = Printr()


def _get_skill_folder_from_module(module: str) -> str:
    """Extract folder name from module path like 'skills.star_head.main' -> 'star_head'"""
    return module.replace(".main", "").replace(".", "/").split("/")[1]


class Wingman:
    """Unified Wingman class with multi-provider support and modular service architecture.

    Architecture:
    - Supports multiple providers (OpenAI, Azure, Google, Anthropic, OpenRouter, WingmanPro, etc.)
    - Uses ProviderRegistry for STT, TTS, and LLM provider management
    - CommandManager for all command-related operations
    - ConversationManager for history, context building, and instant responses
    - Implements progressive tool disclosure (skills/MCPs activated on-demand)
    - MCP (Model Context Protocol) support for external tool servers

    Key Features:
    - Multi-provider transcription, TTS, and LLM
    - Skills with progressive activation
    - MCP server integration
    - Instant activation commands
    - Benchmark tracking
    """

    AZURE_SERVICES = {
        "tts": TtsProvider.AZURE,
        "whisper": [SttProvider.AZURE, SttProvider.AZURE_SPEECH],
        "conversation": ConversationProvider.AZURE,
    }

    def __init__(
        self,
        name: str,
        config: WingmanConfig,
        settings: SettingsConfig,
        audio_player: AudioPlayer,
        audio_library: AudioLibrary,
        xvasynth: XVASynth,
        tower: "Tower",
        app_root_path: str = None,
        app_is_bundled: bool = False,
    ):
        """The constructor of the Wingman class. You can override it in your custom wingman.

        Args:
            name (str): The name of the wingman. This is the key you gave it in the config, e.g. "atc"
            config (WingmanConfig): All "general" config entries merged with the specific Wingman config settings. The Wingman takes precedence and overrides the general config. You can just add new keys to the config and they will be available here.
            app_root_path: Root path of the application (for FasterWhisper models)
            app_is_bundled: Whether the app is bundled (PyInstaller)
        """

        self.config = config
        """All "general" config entries merged with the specific Wingman config settings. The Wingman takes precedence and overrides the general config. You can just add new keys to the config and they will be available here."""

        self.settings = settings
        """The general user settings."""

        self.secret_keeper = SecretKeeper()
        """A service that allows you to store and retrieve secrets like API keys. It can prompt the user for secrets if necessary."""
        self.secret_keeper.secret_events.subscribe(
            "secrets_saved", self.handle_secret_saved
        )

        self.name = name
        """The name of the wingman. This is the key you gave it in the config, e.g. "atc"."""

        self.audio_player = audio_player
        """A service that allows you to play audio files and add sound effects to them."""

        self.audio_library = audio_library
        """A service that allows you to play and manage audio files from the audio library."""

        self.execution_start: None | float = None
        """Used for benchmarking executon times. The timer is (re-)started whenever the process function starts."""

        self.xvasynth = xvasynth
        """A class that handles the communication with the XVASynth server for TTS."""

        self.tower = tower
        """The Tower instance that manages all Wingmen in the same config dir."""

        self.app_root_path = app_root_path
        """Root path of the application (for FasterWhisper models)."""

        self.app_is_bundled = app_is_bundled
        """Whether the app is bundled (PyInstaller)."""

        self.skills: list[Skill] = []

        # Provider registry (manages STT, TTS, LLM providers)
        self.provider_registry: ProviderRegistry | None = None

        # Conversation management (messages, context building, instant responses)
        # Initialized with wingman_name for context building
        self.conversation = ConversationManager(
            skills=self.skills,
            settings=self.settings,
            wingman_name=self.name,
        )

        # Command management
        self.command_manager = CommandManager(
            wingman_name=self.name,
            audio_library=self.audio_library,
            settings=self.settings,
        )

        # Tool management and progressive disclosure
        self.last_gpt_call = None  # Timestamp for call cancellation detection
        self.tool_skills: dict[str, Skill] = {}  # Mapping from tool names to skills
        self.skill_tools: list[dict] = []  # List of tool descriptors

        # Progressive tool disclosure registry
        self.skill_registry = SkillRegistry()

        # MCP (Model Context Protocol) support
        self.mcp_client = McpClient(wingman_name=self.name)
        self.mcp_registry = McpRegistry(
            self.mcp_client,
            wingman_name=self.name,
            on_state_changed=self._broadcast_mcp_state_changed,
        )

        # Unified capability registry (combines skills and MCPs)
        self.capability_registry = CapabilityRegistry(
            self.skill_registry, self.mcp_registry
        )

        # Tool executor (routes and executes tool calls)
        # Initialized in validate() after provider registry is set up
        self.tool_executor: ToolExecutor | None = None

    # Backward-compatible properties for skills that may access messages directly
    @property
    def messages(self) -> list:
        """Access conversation messages (delegates to ConversationManager)."""
        if self.conversation is None:
            return []
        return self.conversation.messages

    @property
    def pending_tool_calls(self) -> list:
        """Access pending tool calls (delegates to ConversationManager)."""
        if self.conversation is None:
            return []
        return self.conversation.pending_tool_calls

    def _broadcast_mcp_state_changed(self):
        """Broadcast MCP state change to UI via WebSocket."""
        printr.ensure_async(
            printr.broadcast(McpStateChangedCommand(wingman_name=self.name))
        )

    def get_record_key(self) -> str | int:
        """Returns the activation or "push-to-talk" key for this Wingman."""
        return self.config.record_key_codes or self.config.record_key

    def get_record_mouse_button(self) -> str:
        """Returns the activation or "push-to-talk" mouse button for this Wingman."""
        return self.config.record_mouse_button

    def get_record_joystick_button(self) -> str:
        """Returns the activation or "push-to-talk" joystick button for this Wingman."""
        if not self.config.record_joystick_button:
            return None
        return f"{self.config.record_joystick_button.guid}{self.config.record_joystick_button.button}"

    async def handle_secret_saved(self, _secrets: Dict[str, Any]):
        await printr.print_async(
            text="Secret saved",
            source_name=self.name,
            command_tag=CommandTag.SECRET_SAVED,
        )
        await self.validate()

    # ──────────────────────────────────── Hooks ─────────────────────────────────── #

    async def validate(self) -> list[WingmanInitializationError]:
        """Validate configuration and initialize all providers and services.

        This method:
        1. Initializes ProviderRegistry with configured providers
        2. Sets up ToolExecutor with all registries and callbacks
        3. Validates legacy providers (whispercpp, fasterwhisper, xvasynth)

        Returns:
            List of WingmanInitializationError if any validation fails
        """
        errors = []

        try:
            # Initialize provider registry (handles all BaseProvider-migrated providers)
            self.provider_registry = ProviderRegistry(
                config=self.config,
                secret_keeper=self.secret_keeper,
                wingman_name=self.name,
                settings=self.settings,
            )
            await self.provider_registry.initialize_from_config()

            # Initialize tool executor with registries and callbacks
            self.tool_executor = ToolExecutor(
                capability_registry=self.capability_registry,
                skill_registry=self.skill_registry,
                mcp_registry=self.mcp_registry,
                tool_skills=self.tool_skills,
                get_command_func=self.get_command,
                execute_command_func=self._execute_command,
                select_command_response_func=self._select_command_response,
                play_to_user_func=self.play_to_user,
                settings=self.settings,
            )

        except Exception as e:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.name,
                    message=f"Error during provider validation: {str(e)}",
                    error_type=WingmanInitializationErrorType.UNKNOWN,
                )
            )
            printr.print(
                f"Error during provider validation: {str(e)}",
                color=LogType.ERROR,
                server_only=True,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

        return errors

    async def retrieve_secret(self, secret_name, errors):
        """Use this method to retrieve secrets like API keys from the SecretKeeper.
        If the key is missing, the user will be prompted to enter it.
        """
        try:
            api_key = await self.secret_keeper.retrieve(
                requester=self.name,
                key=secret_name,
                prompt_if_missing=True,
            )
            if not api_key:
                errors.append(
                    WingmanInitializationError(
                        wingman_name=self.name,
                        message=f"Missing secret '{secret_name}'.",
                        error_type=WingmanInitializationErrorType.MISSING_SECRET,
                        secret_name=secret_name,
                    )
                )
        except Exception as e:
            printr.print(
                f"Error retrieving secret ''{secret_name}: {e}",
                color=LogType.ERROR,
                server_only=True,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.name,
                    message=f"Could not retrieve secret '{secret_name}': {str(e)}",
                    error_type=WingmanInitializationErrorType.MISSING_SECRET,
                    secret_name=secret_name,
                )
            )
            api_key = None

        return api_key

    async def prepare(self):
        """Prepare the wingman for operation.

        Hook for subclasses to perform initialization.
        """
        try:
            pass  # Reserved for future use
        except Exception as e:
            await printr.print_async(
                f"Error while preparing: {str(e)}",
                color=LogType.ERROR,
                source_name=self.name,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

    async def unload(self):
        """This method is called when the Wingman is unloaded by Tower. You can override it if you need to clean up resources."""
        # Unsubscribe from secret events to prevent duplicate handlers
        self.secret_keeper.secret_events.unsubscribe(
            "secrets_saved", self.handle_secret_saved
        )
        await self.unload_skills()

    async def unload_skills(self):
        """Unload all skills and clear registries."""
        for skill in self.skills:
            # Only unload skills that were actually prepared (activated)
            if not skill.is_prepared:
                continue
            try:
                await skill.unload()
            except Exception as e:
                await printr.print_async(
                    f"Error unloading skill '{skill.name}': {str(e)}",
                    color=LogType.ERROR,
                )
                printr.print(
                    traceback.format_exc(), color=LogType.ERROR, server_only=True
                )

        # Clear registries
        self.tool_skills = {}
        self.skill_tools = []
        self.skill_registry.clear()

    async def unload_mcps(self):
        """Disconnect from all MCP servers."""
        await self.mcp_registry.clear()

    async def init_skills(self) -> list[WingmanInitializationError]:
        """Load all available skills with lazy validation.

        Skills are loaded but NOT validated during init. Validation happens
        on first activation via the SkillRegistry. User config overrides from
        self.config.skills are merged with default configs.

        Platform-incompatible skills are skipped entirely.
        """
        import sys

        current_platform = sys.platform  # 'win32', 'darwin', 'linux'
        platform_map = {"win32": "windows", "darwin": "darwin", "linux": "linux"}
        normalized_platform = platform_map.get(current_platform, current_platform)

        if self.skills:
            await self.unload_skills()

        errors = []
        self.skills = []

        # Build a lookup of user config overrides by skill folder name
        # The key must be the folder name (e.g., 'star_head') not the class name (e.g., 'StarHead')
        user_skill_configs: dict[str, "SkillConfig"] = {}
        if self.config.skills:
            for skill_config in self.config.skills:
                folder_name = _get_skill_folder_from_module(skill_config.module)
                user_skill_configs[folder_name] = skill_config

        # Get all available skill configs
        available_skills = ModuleManager.read_available_skill_configs()

        # Get discoverable skills list (whitelist)
        discoverable_skills = self.config.discoverable_skills

        for skill_folder_name, skill_config_path in available_skills:
            try:
                # Load default skill config first to get the display name
                skill_config_dict = ModuleManager.read_config(skill_config_path)
                if not skill_config_dict:
                    continue

                # Import SkillConfig here to avoid circular imports
                from api.interface import SkillConfig

                # Check if user has overrides for this skill
                if skill_folder_name in user_skill_configs:
                    # Merge user overrides into default config
                    user_config = user_skill_configs[skill_folder_name]
                    # User config takes precedence - merge custom_properties especially
                    if user_config.custom_properties:
                        skill_config_dict["custom_properties"] = [
                            prop.model_dump() for prop in user_config.custom_properties
                        ]
                    if user_config.prompt:
                        skill_config_dict["prompt"] = user_config.prompt

                skill_config = SkillConfig(**skill_config_dict)

                # Check if skill is discoverable for this wingman (whitelist - must be in list)
                if skill_config.name not in discoverable_skills:
                    continue

                # Check platform compatibility BEFORE loading the module
                if skill_config.platforms:
                    if normalized_platform not in skill_config.platforms:
                        printr.print(
                            f"Skipping skill '{skill_config.name}' - not supported on {normalized_platform}",
                            color=LogType.WARNING,
                            server_only=True,
                        )
                        continue

                # Load the skill module
                skill = ModuleManager.load_skill(
                    config=skill_config,
                    settings=self.settings,
                    wingman=self,
                )
                if skill:
                    # Set up skill methods
                    skill.threaded_execution = self.threaded_execution

                    # Add to skills list WITHOUT validation
                    # Validation will happen lazily on first activation
                    self.skills.append(skill)
                    await self.prepare_skill(skill)

            except Exception as e:
                skill_name = skill_folder_name
                error_msg = f"Error loading skill '{skill_name}': {str(e)}"
                await printr.print_async(
                    error_msg,
                    color=LogType.ERROR,
                )
                printr.print(
                    traceback.format_exc(), color=LogType.ERROR, server_only=True
                )
                errors.append(
                    WingmanInitializationError(
                        wingman_name=self.name,
                        message=error_msg,
                        error_type=WingmanInitializationErrorType.SKILL_INITIALIZATION_FAILED,
                    )
                )

        # Log summary of discoverable skills for this wingman
        if self.skills:
            skill_names = [s.config.name for s in self.skills]
            await printr.print_async(
                f"Discoverable skills ({len(skill_names)}): {', '.join(skill_names)}",
                color=LogType.WINGMAN,
                source=LogSource.WINGMAN,
                source_name=self.name,
                server_only=not self.settings.debug_mode,
            )

        return errors

    async def prepare_skill(self, skill: Skill):
        """Prepare a skill and register it with the skill registry.

        Args:
            skill: The skill to prepare and register
        """
        # Register skill tools
        # get_tools() returns list[tuple[str, dict]] where tuple is (tool_name, tool_definition)
        for tool_name, tool_definition in skill.get_tools():
            if tool_name:
                self.tool_skills[tool_name] = skill
                self.skill_tools.append(tool_definition)

        # Register with skill registry for progressive disclosure
        if skill.config.auto_activate:
            # Auto-activated skills are immediately available
            self.skill_registry.register_skill(skill)
        else:
            # Normal skills use progressive disclosure
            self.skill_registry.register_skill(skill)

    async def unprepare_skill(self, skill: Skill):
        """Remove a skill's registration.

        Args:
            skill: The skill to unregister
        """
        # Remove from tool_skills mapping
        tools_to_remove = []
        for tool_name, registered_skill in self.tool_skills.items():
            if registered_skill == skill:
                tools_to_remove.append(tool_name)

        for tool_name in tools_to_remove:
            del self.tool_skills[tool_name]

        # Remove from skill_tools list
        # skill_tools contains tool definitions (dicts), not tuples
        self.skill_tools = [
            tool
            for tool in self.skill_tools
            if self.tool_skills.get(tool.get("function", {}).get("name")) != skill
        ]

        # Unregister from skill registry
        self.skill_registry.unregister_skill(skill)

    async def init_mcps(self) -> list[WingmanInitializationError]:
        """
        Initialize MCP (Model Context Protocol) server connections.

        Loads MCP servers from central mcp.yaml config, only connecting those in wingman's discoverable_mcps.
        MCP servers provide external tools similar to skills.

        Returns:
            list[WingmanInitializationError]: Errors encountered (non-fatal, wingman still loads)
        """
        errors = []

        # Check if MCP SDK is available
        if not self.mcp_client.is_available:
            printr.print(
                f"[{self.name}] MCP SDK not installed, skipping MCP initialization.",
                color=LogType.WARNING,
                server_only=True,
            )
            return errors

        # Disconnect existing MCP servers
        await self.unload_mcps()

        # Get MCP configs from central mcp.yaml
        central_mcp_config = self.tower.config_manager.mcp_config
        mcp_configs = central_mcp_config.servers if central_mcp_config else []
        if not mcp_configs:
            return errors

        # Get discoverable MCPs list (whitelist) from wingman config
        discoverable_mcps = self.config.discoverable_mcps

        # Filter to only discoverable MCPs
        mcps_to_connect = [mcp for mcp in mcp_configs if mcp.name in discoverable_mcps]

        if not mcps_to_connect:
            return errors

        # Prepare connection tasks for parallel execution
        async def connect_mcp(mcp_config):
            """Connect to a single MCP server. Returns (success, connection_info, errors)."""
            local_errors = []
            try:
                # Build headers with secrets
                headers = {}
                if mcp_config.headers:
                    headers.update(mcp_config.headers)

                # Check for API key in secrets (using mcp_ prefix)
                secret_key = f"mcp_{mcp_config.name}"
                api_key = await self.secret_keeper.retrieve(
                    requester=self.name,
                    key=secret_key,
                    prompt_if_missing=False,
                )
                if api_key:
                    printr.print(
                        f"MCP secret '{secret_key}' found ({len(api_key)} chars)",
                        color=LogType.INFO,
                        source_name=self.name,
                        server_only=True,
                    )
                    if not any(
                        k.lower() in ["authorization", "api-key", "x-api-key"]
                        for k in headers.keys()
                    ):
                        headers["Authorization"] = f"Bearer {api_key}"

                # Connect with timeout
                default_timeout = 60.0 if mcp_config.type.value == "stdio" else 30.0
                timeout = (
                    float(mcp_config.timeout) if mcp_config.timeout else default_timeout
                )

                try:
                    connection = await asyncio.wait_for(
                        self.mcp_registry.register_server(
                            config=mcp_config,
                            headers=headers if headers else None,
                        ),
                        timeout=timeout,
                    )
                except asyncio.TimeoutError:
                    error_msg = f"MCP '{mcp_config.display_name}' connection timed out ({int(timeout)}s)."
                    printr.print(
                        error_msg,
                        color=LogType.WARNING,
                        source_name=self.name,
                        server_only=True,
                    )
                    local_errors.append(
                        WingmanInitializationError(
                            wingman_name=self.name,
                            message=error_msg,
                            error_type=WingmanInitializationErrorType.MCP_CONNECTION_FAILED,
                        )
                    )
                    return (False, None, local_errors)

                if connection.is_connected:
                    return (
                        True,
                        f"{mcp_config.display_name} ({len(connection.tools)} tools)",
                        local_errors,
                    )
                else:
                    error_msg = f"MCP '{mcp_config.display_name}' failed to connect: {connection.error}"
                    local_errors.append(
                        WingmanInitializationError(
                            wingman_name=self.name,
                            message=error_msg,
                            error_type=WingmanInitializationErrorType.MCP_CONNECTION_FAILED,
                        )
                    )
                    return (False, None, local_errors)

            except Exception as e:
                error_msg = f"MCP '{mcp_config.name}' initialization error: {str(e)}"
                printr.print(
                    error_msg,
                    color=LogType.ERROR,
                    source_name=self.name,
                    server_only=True,
                )
                printr.print(
                    traceback.format_exc(), color=LogType.ERROR, server_only=True
                )
                local_errors.append(
                    WingmanInitializationError(
                        wingman_name=self.name,
                        message=error_msg,
                        error_type=WingmanInitializationErrorType.MCP_CONNECTION_FAILED,
                    )
                )
                return (False, None, local_errors)

        # Connect to all MCPs in parallel
        connection_tasks = [connect_mcp(mcp) for mcp in mcps_to_connect]
        results = await asyncio.gather(*connection_tasks)

        # Collect results
        connected_count = 0
        connected_names = []
        for success, connection_info, mcp_errors in results:
            if success:
                connected_count += 1
                connected_names.append(connection_info)
            errors.extend(mcp_errors)

        # Log consolidated MCP status for this wingman
        if connected_count > 0:
            await printr.print_async(
                f"Discoverable MCP servers connected ({connected_count}): {', '.join(connected_names)}",
                color=LogType.WINGMAN,
                source=LogSource.WINGMAN,
                source_name=self.name,
                server_only=not self.settings.debug_mode,
            )

        return errors

    async def enable_mcp(self, mcp_name: str) -> tuple[bool, str]:
        """Enable and connect to a single MCP server.

        Args:
            mcp_name: Name of the MCP server to enable

        Returns:
            (success, message) tuple
        """
        if not self.mcp_client.is_available:
            return False, "MCP SDK not available"

        if mcp_name in self.mcp_registry.get_connected_server_names():
            return True, f"MCP '{mcp_name}' is already connected"

        # Find config
        central_mcp_config = self.tower.config_manager.mcp_config
        if not central_mcp_config:
            return False, "No MCP configuration found"

        mcp_config = None
        for cfg in central_mcp_config.servers:
            if cfg.name == mcp_name:
                mcp_config = cfg
                break

        if not mcp_config:
            return False, f"MCP '{mcp_name}' not found in configuration"

        try:
            await self.mcp_registry.register_server(mcp_config)
            return True, f"MCP '{mcp_name}' connected successfully"
        except Exception as e:
            return False, f"Failed to connect to MCP '{mcp_name}': {str(e)}"

    async def disable_mcp(self, mcp_name: str) -> tuple[bool, str]:
        """Disconnect from a single MCP server.

        Args:
            mcp_name: Name of the MCP server to disable

        Returns:
            (success, message) tuple
        """
        if mcp_name not in self.mcp_registry.get_connected_server_names():
            return True, f"MCP '{mcp_name}' is already disconnected"

        try:
            await self.mcp_registry.unregister_server(mcp_name)
            return True, f"MCP '{mcp_name}' disconnected successfully"
        except Exception as e:
            return False, f"Failed to disconnect from MCP '{mcp_name}': {str(e)}"

    async def enable_skill(self, skill_name: str) -> tuple[bool, str]:
        """Enable a single skill without reinitializing all skills.

        Args:
            skill_name: The display name of the skill to enable

        Returns:
            (success, message) tuple
        """
        import sys

        current_platform = sys.platform
        platform_map = {"win32": "windows", "darwin": "darwin", "linux": "linux"}
        normalized_platform = platform_map.get(current_platform, current_platform)

        # Check if skill is already enabled
        for existing_skill in self.skills:
            if existing_skill.config.name == skill_name:
                return True, f"Skill '{skill_name}' is already enabled."

        # Find the skill config
        available_skills = ModuleManager.read_available_skill_configs()

        # Build user config lookup by skill folder name
        user_skill_configs: dict[str, "SkillConfig"] = {}
        if self.config.skills:
            for skill_config in self.config.skills:
                folder_name = _get_skill_folder_from_module(skill_config.module)
                user_skill_configs[folder_name] = skill_config

        for skill_folder_name, skill_config_path in available_skills:
            try:
                skill_config_dict = ModuleManager.read_config(skill_config_path)
                if not skill_config_dict:
                    continue

                from api.interface import SkillConfig

                # Apply user overrides
                if skill_folder_name in user_skill_configs:
                    user_config = user_skill_configs[skill_folder_name]
                    if user_config.custom_properties:
                        skill_config_dict["custom_properties"] = [
                            prop.model_dump() for prop in user_config.custom_properties
                        ]
                    if user_config.prompt:
                        skill_config_dict["prompt"] = user_config.prompt

                skill_config = SkillConfig(**skill_config_dict)

                if skill_config.name != skill_name:
                    continue

                # Check platform compatibility
                if skill_config.platforms:
                    if normalized_platform not in skill_config.platforms:
                        return (
                            False,
                            f"Skill '{skill_name}' is not supported on {normalized_platform}.",
                        )

                # Load and register the skill
                skill = ModuleManager.load_skill(
                    config=skill_config,
                    settings=self.settings,
                    wingman=self,
                )
                if skill:
                    skill.threaded_execution = self.threaded_execution
                    self.skills.append(skill)
                    await self.prepare_skill(skill)

                    printr.print(
                        f"Skill '{skill_name}' activated (loaded and made discoverable).",
                        color=LogType.POSITIVE,
                        server_only=True,
                    )
                    return True, f"Skill '{skill_name}' activated successfully."

            except Exception as e:
                error_msg = f"Error activating skill '{skill_name}': {str(e)}"
                await printr.print_async(error_msg, color=LogType.ERROR)
                printr.print(
                    traceback.format_exc(), color=LogType.ERROR, server_only=True
                )
                return False, error_msg

        return False, f"Skill '{skill_name}' not found."

    async def disable_skill(self, skill_name: str) -> tuple[bool, str]:
        """Disable a single skill without reinitializing all skills.

        Args:
            skill_name: The display name of the skill to disable

        Returns:
            (success, message) tuple
        """
        # Find the skill in our list
        skill_to_remove = None
        for skill in self.skills:
            if skill.config.name == skill_name:
                skill_to_remove = skill
                break

        if not skill_to_remove:
            return True, f"Skill '{skill_name}' is already deactivated."

        try:
            # Unload the skill (cleanup resources, unsubscribe events)
            await skill_to_remove.unload()

            # Remove from skill list
            self.skills.remove(skill_to_remove)

            # Remove skill-specific registrations (tools, registry, etc.)
            await self.unprepare_skill(skill_to_remove)

            printr.print(
                f"Skill '{skill_name}' deactivated (unloaded and removed from discoverable skills).",
                color=LogType.WARNING,
                server_only=True,
            )
            return True, f"Skill '{skill_name}' deactivated successfully."

        except Exception as e:
            error_msg = f"Error deactivating skill '{skill_name}': {str(e)}"
            await printr.print_async(error_msg, color=LogType.ERROR)
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return False, error_msg

    def reset_conversation_history(self):
        """Reset conversation history and skill/MCP activation state.

        When conversation is reset, we must also reset progressive disclosure state
        so the LLM's memory matches the activation state.
        """
        self.conversation.reset()
        self.skill_registry.reset_activations()
        self.mcp_registry.reset_activations()

    # ──────────────────────────── The main processing loop ──────────────────────────── #

    async def process(self, audio_input_wav: str = None, transcript: str = None):
        """The main method that gets called when the wingman is activated. This method controls what your wingman actually does and you can override it if you want to.

        The base implementation here triggers the transcription and processing of the given audio input.
        If you don't need even transcription, you can just override this entire process method. If you want transcription but then do something in addition, you can override the listed hooks.

        Async so you can do async processing, e.g. send a request to an API.

        Args:
            audio_input_wav (str): The path to the audio file that contains the user's speech. This is a recording of what you you said.

        Hooks:
            - async _transcribe: transcribe the audio to text
            - async _get_response_for_transcript: process the transcript and return a text response
            - async play_to_user: do something with the response, e.g. play it as audio
        """

        try:
            process_result = None

            benchmark_transcribe = None
            if not transcript:
                # transcribe the audio.
                benchmark_transcribe = Benchmark(label="Voice transcription")
                transcript = await self._transcribe(audio_input_wav)

            interrupt = None
            if transcript:
                await printr.print_async(
                    f"{transcript}",
                    color=LogType.USER,
                    source_name="User",
                    source=LogSource.USER,
                    benchmark_result=(
                        benchmark_transcribe.finish() if benchmark_transcribe else None
                    ),
                )

                # Further process the transcript.
                # Return a string that is the "answer" to your passed transcript.

                benchmark_llm = Benchmark(label="Command/AI Processing")
                process_result, instant_response, skill, interrupt = (
                    await self._get_response_for_transcript(
                        transcript=transcript, benchmark=benchmark_llm
                    )
                )

                actual_response = instant_response or process_result

                if actual_response:
                    await printr.print_async(
                        f"{actual_response}",
                        color=LogType.POSITIVE,
                        source=LogSource.WINGMAN,
                        source_name=self.name,
                        skill_name=skill.name if skill else "",
                        benchmark_result=benchmark_llm.finish(),
                    )

            if process_result:
                if self.settings.streamer_mode:
                    self.tower.save_last_message(self.name, process_result)

                # the last step in the chain. You'll probably want to play the response to the user as audio using a TTS provider or mechanism of your choice.
                await self.play_to_user(str(process_result), not interrupt)
        except Exception as e:
            await printr.print_async(
                f"Error during processing of Wingman '{self.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

    # ───────────────── virtual methods / hooks ───────────────── #

    async def _transcribe(self, audio_input_wav: str) -> str | None:
        """Transcribes the audio to text. You can override this method if you want to use a different transcription service.

        Args:
            audio_input_wav (str): The path to the audio file that contains the user's speech. This is a recording of what you you said.

        Returns:
            str | None: The transcript of the audio file and the detected language as locale (if determined).
        """
        return None

    async def _get_response_for_transcript(
        self, transcript: str, benchmark: Benchmark
    ) -> tuple[str | None, str | None, Skill | None, bool | None]:
        """Processes the transcript and return a response as text. This where you'll do most of your work.
        Pass the transcript to AI providers and build a conversation. Call commands or APIs. Play temporary results to the user etc.


        Args:
            transcript (str): The user's spoken text transcribed as text.

        Returns:
            A tuple of strings representing the response to a function call and/or an instant response.
        """
        return "", "", None, None

    # ───────────────────────────────── Commands ─────────────────────────────── #

    def get_command(self, command_name: str) -> CommandConfig | None:
        """Extracts the command with the given name.

        Delegates to CommandManager for actual lookup.

        Args:
            command_name: Name of the command to retrieve

        Returns:
            CommandConfig or None if not found
        """
        return self.command_manager.get_command(self.config.commands, command_name)

    def _select_command_response(self, command: CommandConfig) -> str | None:
        """Returns one of the configured responses of the command.

        Delegates to CommandManager.

        Args:
            command: The command object

        Returns:
            Random response string or None
        """
        return self.command_manager.select_response(command)

    async def _execute_instant_activation_command(
        self, transcript: str
    ) -> list[CommandConfig] | None:
        """Match transcript against instant activation phrases and execute commands.

        Delegates to CommandManager.

        Args:
            transcript: User's spoken text

        Returns:
            List of executed commands or None if no match
        """
        return await self.command_manager.try_instant_activation(
            commands=self.config.commands,
            transcript=transcript,
        )

    async def _execute_command(self, command: CommandConfig, is_instant=False) -> str:
        """Execute a command's actions and return a response.

        Delegates to CommandManager.

        Args:
            command: Command to execute
            is_instant: Whether this is an instant activation command

        Returns:
            Command response string
        """
        return await self.command_manager.execute_command(
            command=command,
            is_instant=is_instant,
            reset_conversation_callback=self.reset_conversation_history,
        )

    async def execute_action(self, command: CommandConfig):
        """Execute the actions defined in a command.

        Delegates to CommandManager.

        Args:
            command: Command containing actions to execute
        """
        await self.command_manager.execute_actions(command)

    async def _transcribe(self, audio_input_wav: str) -> str | None:
        """Transcribe recorded audio to text using configured STT provider.

        All STT providers (including Whispercpp and FasterWhisper) are now
        managed through the provider registry.

        Args:
            audio_input_wav: Path to the audio file containing user speech

        Returns:
            Transcript text or None if transcription failed
        """
        transcript = None

        try:
            # Use provider registry for all STT providers
            provider = self.provider_registry.get_stt_provider()
            if provider:
                transcript = await provider.transcribe(filename=audio_input_wav)
        except Exception as e:
            await printr.print_async(
                f"Error during transcription using '{self.config.features.stt_provider}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

        # All STT providers should return str per SttProvider protocol
        # If None, transcription failed
        return transcript if transcript else None

    def threaded_execution(self, function, *args) -> threading.Thread | None:
        """Execute a function in a separate thread."""
        try:

            def start_thread(function, *args):
                if asyncio.iscoroutinefunction(function):
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    new_loop.run_until_complete(function(*args))
                    new_loop.close()
                else:
                    function(*args)

            thread = threading.Thread(target=start_thread, args=(function, *args))
            thread.name = function.__name__
            thread.start()
            return thread
        except Exception as e:
            printr.print(
                f"Error starting threaded execution: {str(e)}", color=LogType.ERROR
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return None

    async def _get_response_for_transcript(
        self, transcript: str, benchmark: Benchmark
    ) -> tuple[str | None, str | None, Skill | None, bool]:
        """Get the LLM response for a given transcript.

        This is the main conversation loop that:
        1. Adds user message to history
        2. Checks for instant activation commands
        3. Calls LLM (possibly multiple times if tools are used)
        4. Executes tool calls
        5. Returns the final response

        Args:
            transcript: The user's spoken text transcribed
            benchmark: Benchmark tracker for performance measurement

        Returns:
            tuple: (final_response, instant_response, used_skill, interrupt_audio)
        """
        await self.conversation.add_user_message(
            transcript, self.config.features.remember_messages
        )

        benchmark.start_snapshot("Instant activation commands")
        instant_response, instant_command_executed = await self._try_instant_activation(
            transcript=transcript
        )
        if instant_response:
            await self.conversation.add_simple_assistant_message(instant_response)
            benchmark.finish_snapshot()
            # "." means "don't show a response in the UI"
            if instant_response == ".":
                instant_response = None
            return instant_response, instant_response, None, True
        benchmark.finish_snapshot()

        # Track cumulative LLM and tool execution times
        llm_processing_time_ms = 0.0
        tool_execution_time_ms = 0.0
        tool_timings: list[tuple[str, float]] = (
            []
        )  # (label, time_ms) for individual tools

        # Make initial LLM call with conversation history
        # Prevent tool calls if instant command was executed to avoid duplicate execution
        llm_start = time.perf_counter()
        completion = await self._llm_call(instant_command_executed is False)
        llm_processing_time_ms += (time.perf_counter() - llm_start) * 1000

        if completion is None:
            benchmark.add_snapshot("LLM Processing", llm_processing_time_ms)
            return None, None, None, True

        response_message, tool_calls = await self._process_completion(completion)

        # Add message and dummy tool responses to conversation history
        await self.conversation.add_assistant_message(response_message, tool_calls)

        # Check if tools need follow-up LLM call (summarization)
        is_summarize_needed = False
        if tool_calls:
            for tool_call in tool_calls:
                if not tool_call.id:
                    continue
                function_name = tool_call.function.name

                # Meta-tools (activate_capability, etc.) always need follow-up LLM call
                # so the LLM can use the newly activated tools
                if self.skill_registry.is_meta_tool(function_name):
                    is_summarize_needed = True
                elif function_name in self.tool_skills:
                    skill = self.tool_skills[function_name]
                    if await skill.is_summarize_needed(function_name):
                        is_summarize_needed = True

        # Tool execution loop
        while tool_calls:
            # Execute tools and collect timings
            tool_start = time.perf_counter()
            instant_response, skill, iteration_timings = await self._handle_tool_calls(
                tool_calls
            )
            tool_execution_time_ms += (time.perf_counter() - tool_start) * 1000
            tool_timings.extend(iteration_timings)

            # If tool returns instant response, return early
            if instant_response:
                # Add snapshots before returning
                benchmark.add_snapshot("LLM Processing", llm_processing_time_ms)
                if tool_execution_time_ms > 0:
                    benchmark.add_tool_execution(tool_execution_time_ms, tool_timings)
                return None, instant_response, None, True

            # Follow-up LLM call to summarize tool results
            if is_summarize_needed:
                # Time the follow-up LLM call
                llm_start = time.perf_counter()
                completion = await self._llm_call(True)
                llm_processing_time_ms += (time.perf_counter() - llm_start) * 1000

                if completion is None:
                    benchmark.add_snapshot("LLM Processing", llm_processing_time_ms)
                    if tool_execution_time_ms > 0:
                        benchmark.add_tool_execution(
                            tool_execution_time_ms, tool_timings
                        )
                    return None, None, None, True

                response_message, tool_calls = await self._process_completion(
                    completion
                )
                # Add message
                await self.conversation.add_assistant_message(
                    response_message, tool_calls
                )

                # Check if new tools need summarization
                is_summarize_needed = False
                if tool_calls:
                    for tool_call in tool_calls:
                        if not tool_call.id:
                            continue
                        function_name = tool_call.function.name
                        if self.skill_registry.is_meta_tool(function_name):
                            is_summarize_needed = True
                        elif function_name in self.tool_skills:
                            skill = self.tool_skills[function_name]
                            if await skill.is_summarize_needed(function_name):
                                is_summarize_needed = True
            else:
                # No summarization needed, exit loop
                break

        # Add final snapshots
        benchmark.add_snapshot("LLM Processing", llm_processing_time_ms)
        if tool_execution_time_ms > 0:
            benchmark.add_tool_execution(tool_execution_time_ms, tool_timings)
        return response_message.content, response_message.content, None, True

    async def update_config(
        self, config: WingmanConfig, skip_config_validation: bool = True
    ) -> bool:
        """Update the config of the Wingman.

        This method should always be called if the config of the Wingman has changed.

        Args:
            config: The new wingman configuration
            skip_config_validation: If False, validate the config and rollback on error

        Returns:
            True if config was updated successfully, False otherwise
        """
        try:
            if not skip_config_validation:
                old_config = deepcopy(self.config)

            self.config = config

            # Propagate skill config changes to loaded skills
            await self._update_skill_configs(config)

            if not skip_config_validation:
                errors = await self.validate()

                for error in errors:
                    if (
                        error.error_type
                        != WingmanInitializationErrorType.MISSING_SECRET
                    ):
                        self.config = old_config
                        return False

            return True
        except Exception as e:
            await printr.print_async(
                f"Error updating config for wingman '{self.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return False

    async def _update_skill_configs(self, wingman_config: WingmanConfig) -> None:
        """Propagate skill config changes to loaded skills.

        When the wingman config changes (e.g., user updates custom_properties for a skill),
        we need to update the SkillConfig on each loaded skill instance so they see the new values.
        """
        if not self.skills or not wingman_config.skills:
            return

        # Build lookup of new skill configs by folder name
        new_skill_configs: dict[str, "SkillConfig"] = {}
        for skill_config in wingman_config.skills:
            try:
                folder_name = _get_skill_folder_from_module(skill_config.module)
            except Exception:
                printr.print(
                    f"Skipping skill config override with unexpected module format: '{skill_config.module}'",
                    color=LogType.WARNING,
                    server_only=True,
                )
                continue
            new_skill_configs[folder_name] = skill_config

        # Update each loaded skill if its config changed
        for skill in self.skills:
            # Get the folder name for this skill
            try:
                skill_folder = _get_skill_folder_from_module(skill.config.module)
            except Exception:
                printr.print(
                    f"Skipping loaded skill with unexpected module format: '{skill.config.module}'",
                    color=LogType.WARNING,
                    server_only=True,
                )
                continue

            if skill_folder in new_skill_configs:
                user_override = new_skill_configs[skill_folder]

                fields_set = getattr(user_override, "model_fields_set", None)
                if fields_set is None:
                    # Pydantic v1 fallback
                    fields_set = getattr(user_override, "__fields_set__", set())

                # Create updated config by copying current and applying overrides
                # This preserves all default values while applying user overrides
                updated_config = deepcopy(skill.config)

                # Apply overrides even if they're explicitly empty.
                # This allows users to clear custom properties/prompt in the UI.
                if "custom_properties" in fields_set:
                    updated_config.custom_properties = user_override.custom_properties
                if "prompt" in fields_set:
                    updated_config.prompt = user_override.prompt

                # Let the skill handle the config update (will compare old vs new)
                await skill.update_config(updated_config)

    async def save_config(self):
        """Save the config of the Wingman."""
        self.tower.save_wingman(self.name)

    async def save_commands(self):
        """Save only the commands section of this wingman's config.

        This performs a partial YAML update - only the commands field is modified
        in the config file, avoiding full config serialization. This is much safer
        than save_config() for command-only changes as it won't accidentally
        overwrite other fields.

        Use this instead of save_config() when you only changed command definitions,
        instant_activation phrases, or other command-related fields.

        Example use cases:
        - QuickCommands learning instant activation phrases
        - Skills dynamically adding/modifying commands
        - Skills updating command responses or actions
        """
        self.tower.save_wingman_commands(self.name)

    async def update_settings(self, settings: SettingsConfig):
        """Update wingman settings and reinitialize affected services.

        When settings change (e.g., WingmanPro region, API keys, provider selection),
        this method reinitializes the ProviderRegistry to pick up new configurations.

        Args:
            settings: New settings configuration to apply
        """
        try:
            self.settings = settings

            # Reinitialize provider registry to pick up new settings
            # (e.g., WingmanPro region changes, API key updates, etc.)
            if self.provider_registry:
                await self.provider_registry.initialize_from_config()
                printr.print(
                    "Reinitialized providers with new settings",
                    source_name=self.name,
                    server_only=True,
                )

            # Reload skills and MCPs
            await self.init_skills()
            if hasattr(self, "init_mcps"):
                await self.init_mcps()

            printr.print(f"Wingman {self.name}'s settings changed", server_only=True)
        except Exception as e:
            await printr.print_async(
                f"Error while updating settings: {str(e)}",
                color=LogType.ERROR,
                source_name=self.name,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

    # ========== LLM and Tool Execution Methods ==========

    async def actual_llm_call(self, messages, tools: list[dict] = None):
        """Perform the actual LLM API call using the configured conversation provider.

        Routes the call to the appropriate provider (OpenAI, Azure, WingmanPro, etc.)
        through the ProviderRegistry.

        Args:
            messages: List of conversation messages in OpenAI format
            tools: Optional list of tool definitions in OpenAI format

        Returns:
            ChatCompletion object or None if the call fails
        """
        try:
            completion = None

            # Use provider registry for all LLM providers (including WingmanPro)
            provider = self.provider_registry.get_llm_provider()
            if provider:
                completion = await provider.complete(messages=messages, tools=tools)
        except Exception as e:
            await printr.print_async(
                f"Error during LLM call: {str(e)}", color=LogType.ERROR
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return None

        return completion

    async def _llm_call(self, allow_tool_calls: bool = True):
        """Make the primary LLM call with conversation history and context.

        This method:
        1. Timestamps the call (for cancellation detection)
        2. Builds tool definitions (if allowed)
        3. Adds system context to messages
        4. Calls actual_llm_call()
        5. Handles call cancellation (if newer call supersedes this one)

        Args:
            allow_tool_calls: Whether to include tool definitions in the call

        Returns:
            ChatCompletion object or None if the call fails or is cancelled
        """
        # Save request time for later comparison
        thiscall = time.time()
        self.last_gpt_call = thiscall

        # Build tools
        tools = self.build_tools() if allow_tool_calls else None

        if self.settings.debug_mode:
            await printr.print_async(
                f"Calling LLM with {(len(self.conversation.messages))} messages (excluding context) and {len(tools) if tools else 0} tools.",
                color=LogType.INFO,
            )

        messages = self.conversation.get_messages_copy()
        await self.add_context(messages)

        completion = await self.actual_llm_call(messages, tools)

        # If request isn't most recent, ignore the response
        if self.last_gpt_call != thiscall:
            await printr.print_async(
                "LLM call was cancelled due to a new call.", color=LogType.WARNING
            )
            return None

        return completion

    async def add_context(self, messages: list):
        """Add system context to messages using ConversationManager.

        Builds the system prompt with backstory, skill prompts, TTS instructions,
        and user metadata (timezone, config name, etc.).

        Args:
            messages: The message list to prepend context to
        """
        tower_config_name = (
            self.tower.config_dir.name if self.tower and self.tower.config_dir else None
        )
        system_context = await self.conversation.build_system_context(
            config=self.config,
            capability_registry=self.capability_registry,
            tower_config_name=tower_config_name,
        )
        # Prepend system context as first message
        messages.insert(0, {"role": "system", "content": system_context})

    async def _process_completion(self, completion: ChatCompletion):
        """Process the completion returned by the LLM call.

        Args:
            completion: The completion object from an OpenAI call

        Returns:
            tuple: (response_message, tool_calls)
        """
        response_message = completion.choices[0].message

        content = response_message.content
        if content is None:
            response_message.content = ""

        # Fix tool calls that have a command name as function name
        if response_message.tool_calls:
            response_message.tool_calls = await self.tool_executor.fix_tool_calls(
                response_message.tool_calls
            )

        return response_message, response_message.tool_calls

    async def _handle_tool_calls(self, tool_calls):
        """Process all the tool calls identified in the response message.

        Args:
            tool_calls: The list of tool calls to process

        Returns:
            tuple: (instant_response, skill, tool_timings) where tool_timings is a list of (label, time_ms) tuples
        """
        # Use tool executor to process all tool calls
        instant_response, used_skill, tool_timings, results = (
            await self.tool_executor.execute_batch(tool_calls)
        )

        # Update conversation with all tool responses
        for tool_call, function_response in results:
            if tool_call.id:
                await self.conversation.update_tool_response(
                    tool_call.id, function_response
                )
            else:
                self.conversation.add_tool_response(tool_call, function_response)

        return instant_response, used_skill, tool_timings

    def build_tools(self) -> list[dict]:
        """Build the tool list for the LLM call using progressive disclosure.

        Returns tools in this order:
        1. execute_command: For non-instant-activation commands
        2. Meta-tools: activate_capability (for discovering skills/MCPs)
        3. Active skill tools: Tools from skills activated in this conversation
        4. Active MCP tools: Tools from MCP servers activated in this conversation

        Progressive disclosure means the LLM only sees tools from activated capabilities,
        reducing token usage and improving context focus.

        Returns:
            List of tool descriptors in OpenAI function calling format
        """

        def _command_has_effective_actions(command: CommandConfig) -> bool:
            if command.is_system_command:
                return True

            if not command.actions:
                return False

            for action in command.actions:
                if not action:
                    continue
                if (
                    action.keyboard is not None
                    or action.mouse is not None
                    or action.joystick is not None
                    or action.audio is not None
                    or action.write is not None
                    or action.wait is not None
                ):
                    return True

            return False

        commands = [
            command.name
            for command in self.config.commands
            if (not command.force_instant_activation)
            and _command_has_effective_actions(command)
        ]
        tools: list[dict] = []
        if commands:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "execute_command",
                        "description": "Executes a command",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command_name": {
                                    "type": "string",
                                    "description": "The name of the command to execute",
                                    "enum": commands,
                                },
                            },
                            "required": ["command_name"],
                        },
                    },
                }
            )

        # Unified capability discovery: single activate_capability meta-tool
        # Combines skills and MCP servers - LLM doesn't need to know the difference
        for _, tool in self.capability_registry.get_meta_tools():
            tools.append(tool)

        # Add tools from activated capabilities (both skills and MCPs)
        for _, tool in self.skill_registry.get_active_tools():
            tools.append(tool)

        for _, tool in self.mcp_registry.get_active_tools():
            tools.append(tool)

        return tools

    async def _try_instant_activation(self, transcript: str) -> tuple[str | None, bool]:
        """Try to match transcript against instant activation commands.

        Args:
            transcript: User's spoken text

        Returns:
            tuple: (response, command_executed) - response if matched, command_executed True if command ran
        """
        commands = await self._execute_instant_activation_command(transcript)
        if commands:
            return ".", True  # "." = silent response (no UI output)
        return None, False

    # ========== TTS Methods ==========

    async def play_to_user(
        self,
        text: str,
        no_interrupt: bool = False,
        sound_config: Optional[SoundConfig] = None,
    ):
        """Play audio to the user using the configured TTS provider.

        This method:
        1. Cleans up markdown, links, and code blocks from text
        2. Waits for current audio to finish (if no_interrupt=True)
        3. Calls skill hooks (for text modification by activated skills)
        4. Synthesizes speech using configured TTS provider
        5. Applies sound effects if enabled

        Args:
            text: The text to convert to speech and play
            no_interrupt: If True, wait for current audio to finish before playing
            sound_config: Optional custom sound configuration (volume, effects, etc.)
        """
        if sound_config:
            printr.print(
                "Using custom sound config for playback", LogType.INFO, server_only=True
            )
        else:
            sound_config = self.config.sound

        # Remove Markdown, links, emotes and code blocks
        text, contains_links, contains_code_blocks = cleanup_text(text)

        # Wait for audio player to finish playing
        if no_interrupt and self.audio_player.is_playing:
            while self.audio_player.is_playing:
                await asyncio.sleep(0.1)

        # Call skill hooks (only for prepared/activated skills)
        changed_text = text
        for skill in self.skills:
            if skill.is_prepared:
                changed_text = await skill.on_play_to_user(text, sound_config)
                if changed_text != text:
                    printr.print(
                        f"Skill '{skill.config.display_name}' modified the text to: '{changed_text}'",
                        LogType.INFO,
                    )
                    text = changed_text

        if sound_config.volume == 0.0:
            printr.print(
                "Volume modifier is set to 0. Skipping TTS processing.",
                LogType.WARNING,
                server_only=True,
            )
            return

        if "{SKIP-TTS}" in text:
            printr.print(
                "Skip TTS phrase found in input. Skipping TTS processing.",
                LogType.WARNING,
                server_only=True,
            )
            return

        try:
            # Handle legacy providers (not yet migrated to registry)
            if self.config.features.tts_provider == TtsProvider.XVASYNTH:
                await self.xvasynth.play_audio(
                    text=text,
                    config=self.config.xvasynth,
                    sound_config=sound_config,
                    audio_player=self.audio_player,
                    wingman_name=self.name,
                )
            else:
                # Use provider registry for all TTS providers (including WingmanPro)
                provider = self.provider_registry.get_tts_provider()
                if provider:
                    await provider.synthesize(
                        text=text,
                        sound_config=sound_config,
                        audio_player=self.audio_player,
                        wingman_name=self.name,
                    )
        except Exception as e:
            await printr.print_async(
                f"TTS error: {str(e)}", color=LogType.ERROR, source_name=self.name
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

    # ========== Helper Methods ==========

    async def generate_image(self, text: str) -> str:
        """Generate an image from text using the configured image generation provider.

        Uses the provider registry to get the configured image generation provider,
        similar to how STT, TTS, and LLM providers are accessed.

        Args:
            text: Text description of the image to generate

        Returns:
            str: URL or path to the generated image, or empty string on error
        """
        try:
            provider = self.provider_registry.get_image_provider()
            if provider:
                return await provider.generate_image(text)
            else:
                await printr.print_async(
                    f"No image generation provider configured (current: {self.config.features.image_generation_provider})",
                    color=LogType.ERROR,
                )
        except Exception as e:
            await printr.print_async(
                f"Error during image generation: {str(e)}", color=LogType.ERROR
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

        return ""
