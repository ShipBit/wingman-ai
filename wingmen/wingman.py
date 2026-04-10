"""Unified Wingman class.

Merges the former base ``Wingman`` and its only subclass ``OpenAiWingman``
into a single class that delegates to extracted services and provider
interfaces for STT, TTS, and LLM.
"""

import json
import time
import asyncio
import random
import traceback
import threading
from copy import deepcopy
import difflib
from typing import (
    Any,
    Dict,
    Optional,
    TYPE_CHECKING,
)
from openai import APIConnectionError
from openai.types.chat import ChatCompletion
import keyboard.keyboard as keyboard
import mouse.mouse as mouse
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
    ConversationProvider,
    ImageGenerationProvider,
    LogSource,
    LogType,
    SttProvider,
    TtsProvider,
    WingmanInitializationErrorType,
)
from providers.interfaces import LlmInterface, SttInterface, TtsInterface
from services.audio_player import AudioPlayer
from services.benchmark import Benchmark
from services.markdown import cleanup_text
from services.module_manager import ModuleManager
from services.secret_keeper import SecretKeeper
from services.printr import Printr
from services.audio_library import AudioLibrary
from services.conversation_manager import ConversationManager
from services.conversation_condenser import ConversationCondenser
from services.context_builder import ContextBuilder
from services.command_executor import CommandExecutor
from services.tool_executor import ToolExecutor
from services.provider_factory import ProviderFactory
from services.skill_registry import SkillRegistry
from services.mcp_client import McpClient
from services.capability_registry import CapabilityRegistry
from services.wingman_mcp_manager import WingmanMcpManager
from services.tool_response_cache import ToolResponseCompressor
from services.token_utils import count_tokens
from skills.skill_base import Skill
from wingmen.wingman_context import WingmanContext

if TYPE_CHECKING:
    from services.tower import Tower

printr = Printr()


def _get_skill_folder_from_module(module: str) -> str:
    """Extract folder name from module path like 'skills.star_head.main' -> 'star_head'"""
    return module.replace(".main", "").replace(".", "/").split("/")[1]


class Wingman:
    """Unified Wingman class.

    Handles lifecycle, process loop, audio, command execution, config
    save/load, skill management, provider routing, conversation management,
    tool execution, context building, and condensation.

    Providers are resolved via :class:`ProviderFactory` into three
    interface slots: ``stt``, ``tts``, ``llm``.  Heavy orchestration logic
    is delegated to extracted service objects.
    """

    AZURE_SERVICES = {
        "tts": None,  # kept for potential future use
        "whisper": None,
        "conversation": None,
    }

    def __init__(
        self,
        name: str,
        config: WingmanConfig,
        settings: SettingsConfig,
        audio_player: AudioPlayer,
        audio_library: AudioLibrary,
        whispercpp=None,
        fasterwhisper=None,
        parakeet=None,
        xvasynth=None,
        pocket_tts=None,
        tower: "Tower" = None,
    ):
        self.config = config
        self.settings = settings
        self.name = name
        self.audio_player = audio_player
        self.audio_library = audio_library
        self.tower = tower

        self.secret_keeper = SecretKeeper()
        self.secret_keeper.secret_events.subscribe(
            "secrets_saved", self.handle_secret_saved
        )

        # Shared provider singletons (passed from Tower)
        self._shared_providers = {
            "whispercpp": whispercpp,
            "fasterwhisper": fasterwhisper,
            "parakeet": parakeet,
            "xvasynth": xvasynth,
            "pocket_tts": pocket_tts,
        }

        # --- Provider interface slots (populated by validate → ProviderFactory) ---
        self.stt: SttInterface | None = None
        self.tts: TtsInterface | None = None
        self.llm: LlmInterface | None = None

        # --- Backward-compat: keep old attributes for custom wingmen / skills ---
        self.whispercpp = whispercpp
        self.fasterwhisper = fasterwhisper
        self.parakeet = parakeet
        self.xvasynth = xvasynth
        self.pocket_tts = pocket_tts

        # --- Extracted services ---
        self.conversation = ConversationManager(config, settings, name)
        self.condenser = ConversationCondenser(self.conversation, config, name)
        self.context_builder = ContextBuilder(config, settings, name)
        self.tool_executor = ToolExecutor(config, settings, name)
        self.command_executor = CommandExecutor(
            config=config,
            audio_library=audio_library,
            wingman_name=name,
            on_reset_history=self.reset_conversation_history,
            on_add_forced_commands=self.add_forced_assistant_command_calls,
        )

        # --- Token tracking ---
        self.last_turn_prompt_tokens: int = 0
        self.last_turn_completion_tokens: int = 0
        self.execution_start: None | float = None
        self._last_prompt_tokens: int = 0

        # --- Skills ---
        self.skills: list[Skill] = []
        self.tool_skills: dict[str, Skill] = {}
        self.skill_tools: list[dict] = []
        self.skill_registry = SkillRegistry()

        # --- MCP ---
        self.mcp_client = McpClient(wingman_name=self.name)
        self.mcp_manager = WingmanMcpManager(
            wingman_name=self.name,
            mcp_client=self.mcp_client,
            secret_keeper=self.secret_keeper,
            get_mcp_config=lambda: self.tower.config_manager.mcp_config if self.tower else None,
            settings=self.settings,
            config=self.config,
        )

        # --- Unified capability registry ---
        self.capability_registry = CapabilityRegistry(
            self.skill_registry, self.mcp_registry
        )

        # --- Local AI / persistent memory ---
        self.local_ai_service = None
        self.persistent_memory_service = None
        self._memory_recall_notified = False
        self._background_tasks: set[asyncio.Task] = set()
        self._tool_response_compressor = ToolResponseCompressor()

        # --- Conversation state ---
        self.last_gpt_call = None
        self.instant_responses = []
        self.last_used_instant_responses = []

    # ──────────────────────────────── Backward-compat properties ──────────────── #

    @property
    def mcp_registry(self):
        """Backward-compat: many callers access wingman.mcp_registry directly."""
        return self.mcp_manager.mcp_registry

    # ──────────────────────────────── Record keys ─────────────────────────────── #

    def get_record_key(self) -> str | int:
        return self.config.record_key_codes or self.config.record_key

    def get_record_mouse_button(self) -> str:
        return self.config.record_mouse_button

    def get_record_joystick_button(self) -> str:
        if not self.config.record_joystick_button:
            return None
        return f"{self.config.record_joystick_button.guid}{self.config.record_joystick_button.button}"

    # ──────────────────────────────── Secrets ──────────────────────────────────── #

    async def handle_secret_saved(self, _secrets: Dict[str, Any]):
        await printr.print_async(
            text="Secret saved",
            source_name=self.name,
            command_tag=CommandTag.SECRET_SAVED,
        )
        await self.validate()

    async def retrieve_secret(self, secret_name, errors, is_required=True):
        try:
            api_key = await self.secret_keeper.retrieve(
                requester=self.name,
                key=secret_name,
                prompt_if_missing=is_required,
            )
            if not api_key and is_required:
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
                f"Error retrieving secret '{secret_name}': {e}",
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

    # ──────────────────────────────── Validate ─────────────────────────────────── #

    async def validate(self) -> list[WingmanInitializationError]:
        errors: list[WingmanInitializationError] = []

        try:
            factory = ProviderFactory(
                config=self.config,
                settings=self.settings,
                secret_keeper=self.secret_keeper,
                shared_providers=self._shared_providers,
                wingman_name=self.name,
            )
            self.stt = await factory.create_stt(errors)
            self.tts = await factory.create_tts(errors)
            self.llm = await factory.create_llm(errors)
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

    # ──────────────────────────────── Lifecycle ─────────────────────────────────── #

    async def prepare(self):
        try:
            if self.config.features.use_generic_instant_responses:
                printr.print(
                    "Generating AI instant responses...",
                    color=LogType.WARNING,
                    server_only=True,
                )
                self.threaded_execution(self._generate_instant_responses)
        except Exception as e:
            await printr.print_async(
                f"Error while preparing wingman '{self.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

    async def unload(self):
        # Wait for any background memory extraction tasks to finish
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

        if self.persistent_memory_service:
            from services.persistent_memory import MIN_MESSAGES_FOR_EXTRACTION

            if len(self.conversation.messages) >= MIN_MESSAGES_FOR_EXTRACTION:
                try:
                    await self.persistent_memory_service.extract_memories(
                        self.conversation.messages, generate_summary=True
                    )
                except Exception:
                    pass
            self.persistent_memory_service.close()

        # Unsubscribe from secret events to prevent duplicate handlers
        self.secret_keeper.secret_events.unsubscribe(
            "secrets_saved", self.handle_secret_saved
        )
        await self.unload_skills()

    async def unload_skills(self):
        for skill in self.skills:
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
        self.tool_skills = {}
        self.skill_tools = []
        self.skill_registry.clear()

    async def unload_mcps(self):
        return await self.mcp_manager.unload_mcps()

    # ──────────────────────────────── Memory ──────────────────────────────────── #

    def ensure_memory_initialized(self) -> bool:
        if self.persistent_memory_service and not self.config.persistent_memory:
            self.persistent_memory_service.close()
            self.persistent_memory_service = None
            return False
        if self.persistent_memory_service:
            return True
        if self.config.persistent_memory and self.local_ai_service:
            from services.persistent_memory import PersistentMemoryService

            self.persistent_memory_service = PersistentMemoryService(
                wingman_name=self.name,
                local_ai_service=self.local_ai_service,
            )
            self.persistent_memory_service.initialize()
            return True
        return False

    # ──────────────────────────────── MCP (forwarding) ─────────────────────────── #

    async def enable_mcp(self, mcp_name: str) -> tuple[bool, str]:
        return await self.mcp_manager.enable_mcp(mcp_name)

    async def disable_mcp(self, mcp_name: str) -> tuple[bool, str]:
        return await self.mcp_manager.disable_mcp(mcp_name)

    async def init_mcps(self) -> list[WingmanInitializationError]:
        return await self.mcp_manager.init_mcps()

    # ──────────────────────────────── Skills ───────────────────────────────────── #

    async def init_skills(self) -> list[WingmanInitializationError]:
        import sys

        current_platform = sys.platform
        platform_map = {"win32": "windows", "darwin": "darwin", "linux": "linux"}
        normalized_platform = platform_map.get(current_platform, current_platform)

        if self.skills:
            await self.unload_skills()

        errors = []
        self.skills = []

        user_skill_configs: dict[str, "SkillConfig"] = {}
        if self.config.skills:
            for skill_config in self.config.skills:
                folder_name = _get_skill_folder_from_module(skill_config.module)
                user_skill_configs[folder_name] = skill_config

        available_skills = ModuleManager.read_available_skill_configs()
        discoverable_skills = self.config.discoverable_skills

        for (
            skill_folder_name,
            skill_config_path,
            _is_custom,
            _is_local,
        ) in available_skills:
            try:
                skill_config_dict = ModuleManager.read_config(skill_config_path)
                if not skill_config_dict:
                    continue

                from api.interface import SkillConfig

                if skill_folder_name in user_skill_configs:
                    user_config = user_skill_configs[skill_folder_name]
                    if user_config.custom_properties:
                        skill_config_dict["custom_properties"] = [
                            prop.model_dump() for prop in user_config.custom_properties
                        ]
                    if user_config.prompt:
                        skill_config_dict["prompt"] = user_config.prompt

                skill_config = SkillConfig(**skill_config_dict)

                if skill_config.name not in discoverable_skills:
                    continue

                if skill_config.platforms:
                    if normalized_platform not in skill_config.platforms:
                        printr.print(
                            f"Skipping skill '{skill_config.name}' - not supported on {normalized_platform}",
                            color=LogType.WARNING,
                            server_only=True,
                        )
                        continue

                context = WingmanContext(self)
                skill = ModuleManager.load_skill(
                    config=skill_config,
                    settings=self.settings,
                    wingman=context,
                )
                if skill:
                    skill.threaded_execution = self.threaded_execution
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
        try:
            for tool_name, tool in skill.get_tools():
                self.tool_skills[tool_name] = skill
                self.skill_tools.append(tool)

            self.skill_registry.register_skill(skill)

            if skill.config.auto_activate:
                success, message = await skill.ensure_activated()
                if not success:
                    await printr.print_async(
                        f"Auto-activated skill '{skill.config.display_name}' failed to activate: {message}",
                        color=LogType.ERROR,
                    )
        except Exception as e:
            await printr.print_async(
                f"Error while preparing skill '{skill.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

        skill.llm_call = self.actual_llm_call

    async def unprepare_skill(self, skill: Skill):
        try:
            for tool_name, _ in skill.get_tools():
                self.tool_skills.pop(tool_name, None)
                self.skill_tools = [
                    t
                    for t in self.skill_tools
                    if t.get("function", {}).get("name") != tool_name
                ]
            self.skill_registry.unregister_skill(skill.name)
        except Exception as e:
            await printr.print_async(
                f"Error while unpreparing skill '{skill.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

    async def enable_skill(self, skill_name: str) -> tuple[bool, str]:
        import sys

        current_platform = sys.platform
        platform_map = {"win32": "windows", "darwin": "darwin", "linux": "linux"}
        normalized_platform = platform_map.get(current_platform, current_platform)

        for existing_skill in self.skills:
            if existing_skill.config.name == skill_name:
                return True, f"Skill '{skill_name}' is already enabled."

        available_skills = ModuleManager.read_available_skill_configs()
        user_skill_configs: dict[str, "SkillConfig"] = {}
        if self.config.skills:
            for skill_config in self.config.skills:
                folder_name = _get_skill_folder_from_module(skill_config.module)
                user_skill_configs[folder_name] = skill_config

        for (
            skill_folder_name,
            skill_config_path,
            _is_custom,
            _is_local,
        ) in available_skills:
            try:
                skill_config_dict = ModuleManager.read_config(skill_config_path)
                if not skill_config_dict:
                    continue

                from api.interface import SkillConfig

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

                if skill_config.platforms:
                    if normalized_platform not in skill_config.platforms:
                        return (
                            False,
                            f"Skill '{skill_name}' is not supported on {normalized_platform}.",
                        )

                context = WingmanContext(self)
                skill = ModuleManager.load_skill(
                    config=skill_config,
                    settings=self.settings,
                    wingman=context,
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
        skill_to_remove = None
        for skill in self.skills:
            if skill.config.name == skill_name:
                skill_to_remove = skill
                break

        if not skill_to_remove:
            return True, f"Skill '{skill_name}' is already deactivated."

        try:
            await skill_to_remove.unload()
            self.skills.remove(skill_to_remove)
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

    # ──────────────────────────── The main processing loop ──────────────────────── #

    async def process(self, audio_input_wav: str = None, transcript: str = None, images: list[tuple[str, str]] = None):
        try:
            process_result = None

            benchmark_transcribe = None
            if not transcript:
                benchmark_transcribe = Benchmark(label="Voice transcription")
                transcript = await self._transcribe(audio_input_wav)

            interrupt = None
            if transcript:
                additional_data = None
                if images:
                    additional_data = {"images": [b64 for b64, _mime in images]}
                await printr.print_async(
                    f"{transcript}",
                    color=LogType.USER,
                    source_name="User",
                    source=LogSource.USER,
                    benchmark_result=(
                        benchmark_transcribe.finish() if benchmark_transcribe else None
                    ),
                    additional_data=additional_data,
                )

                benchmark_llm = Benchmark(label="Command/AI Processing")
                process_result, instant_response, skill, interrupt = (
                    await self._get_response_for_transcript(
                        transcript=transcript, benchmark=benchmark_llm, images=images
                    )
                )

                actual_response = instant_response or process_result

                if actual_response:
                    token_usage = None
                    if self.last_turn_prompt_tokens or self.last_turn_completion_tokens:
                        token_usage = (
                            self.last_turn_prompt_tokens,
                            self.last_turn_completion_tokens,
                        )
                        self.last_turn_prompt_tokens = 0
                        self.last_turn_completion_tokens = 0
                    await printr.print_async(
                        f"{actual_response}",
                        color=LogType.POSITIVE,
                        source=LogSource.WINGMAN,
                        source_name=self.name,
                        skill_name=skill.name if skill else "",
                        benchmark_result=benchmark_llm.finish(),
                        token_usage=token_usage,
                    )

            if process_result:
                if self.settings.streamer_mode:
                    self.tower.save_last_message(self.name, process_result)
                await self.play_to_user(str(process_result), not interrupt)
        except Exception as e:
            await printr.print_async(
                f"Error during processing of Wingman '{self.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

    # ───────────────── Transcription ───────────────── #

    async def _transcribe(self, audio_input_wav: str) -> str | None:
        if not self.stt:
            return None
        try:
            transcript = await self.stt.transcribe(filename=audio_input_wav)
            if transcript:
                # Wingman Pro might return a serialized dict instead of a real object
                if isinstance(transcript, dict):
                    return transcript.get("_text")
                return transcript.text
        except Exception as e:
            await printr.print_async(
                f"Error during transcription using '{self.config.features.stt_provider}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
        return None

    # ───────────────── Response orchestration ───────────────── #

    async def _get_response_for_transcript(
        self, transcript: str, benchmark: Benchmark, images: list[tuple[str, str]] = None
    ) -> tuple[str | None, str | None, Skill | None, bool]:
        self.ensure_memory_initialized()

        await self.add_user_message(transcript, images=images)

        benchmark.start_snapshot("Instant activation commands")
        instant_response, instant_command_executed = await self.command_executor.try_instant_activation(
            transcript=transcript
        )
        if instant_response:
            await self.add_assistant_message(instant_response)
            benchmark.finish_snapshot()
            if instant_response == ".":
                instant_response = None
            return instant_response, instant_response, None, True
        benchmark.finish_snapshot()

        llm_processing_time_ms = 0.0
        tool_execution_time_ms = 0.0
        tool_timings: list[tuple[str, float]] = []

        llm_start = time.perf_counter()
        completion = await self._llm_call(instant_command_executed is False)
        llm_processing_time_ms += (time.perf_counter() - llm_start) * 1000

        if completion is None:
            self._add_benchmark_snapshot(
                benchmark, "LLM Processing", llm_processing_time_ms
            )
            return None, None, None, True

        response_message, tool_calls, usage = await self._process_completion(
            completion, instant_command_executed is False
        )

        turn_prompt_tokens = usage[0]
        turn_completion_tokens = usage[1]
        self._last_prompt_tokens = turn_prompt_tokens

        is_waiting_response_needed, is_summarize_needed = await self._add_gpt_response(
            response_message, tool_calls
        )
        interrupt = True

        while tool_calls:
            if is_waiting_response_needed:
                message = None
                if response_message.content:
                    message = response_message.content
                elif self.instant_responses:
                    message = self._get_random_filler()
                    is_summarize_needed = True
                if message:
                    self.threaded_execution(self.play_to_user, message, interrupt)
                    await printr.print_async(
                        f"{message}",
                        color=LogType.POSITIVE,
                        source=LogSource.WINGMAN,
                        source_name=self.name,
                        skill_name="",
                    )
                    interrupt = False
                else:
                    is_summarize_needed = True
            else:
                is_summarize_needed = True

            tool_start = time.perf_counter()
            instant_response, skill, iteration_timings = await self._handle_tool_calls(
                tool_calls
            )
            tool_execution_time_ms += (time.perf_counter() - tool_start) * 1000
            tool_timings.extend(iteration_timings)

            if instant_response:
                await self._trim_tool_responses()
                self._add_benchmark_snapshot(
                    benchmark, "LLM Processing", llm_processing_time_ms
                )
                if tool_execution_time_ms > 0:
                    self._add_tool_execution_snapshot(
                        benchmark, tool_execution_time_ms, tool_timings
                    )
                await self._broadcast_token_usage(
                    turn_prompt_tokens, turn_completion_tokens
                )
                return None, instant_response, None, interrupt

            if is_summarize_needed:
                llm_start = time.perf_counter()
                completion = await self._llm_call(True)
                llm_processing_time_ms += (time.perf_counter() - llm_start) * 1000

                if completion is None:
                    await self._trim_tool_responses()
                    self._add_benchmark_snapshot(
                        benchmark, "LLM Processing", llm_processing_time_ms
                    )
                    if tool_execution_time_ms > 0:
                        self._add_tool_execution_snapshot(
                            benchmark, tool_execution_time_ms, tool_timings
                        )
                    await self._broadcast_token_usage(
                        turn_prompt_tokens, turn_completion_tokens
                    )
                    return None, None, None, True

                response_message, tool_calls, usage = await self._process_completion(
                    completion
                )
                turn_prompt_tokens = usage[0]
                turn_completion_tokens += usage[1]
                self._last_prompt_tokens = turn_prompt_tokens

                is_waiting_response_needed, is_summarize_needed = (
                    await self._add_gpt_response(response_message, tool_calls)
                )
                if tool_calls:
                    interrupt = False
            elif is_waiting_response_needed:
                await self._trim_tool_responses()
                self._add_benchmark_snapshot(
                    benchmark, "LLM Processing", llm_processing_time_ms
                )
                if tool_execution_time_ms > 0:
                    self._add_tool_execution_snapshot(
                        benchmark, tool_execution_time_ms, tool_timings
                    )
                await self._broadcast_token_usage(
                    turn_prompt_tokens, turn_completion_tokens
                )
                return None, None, None, interrupt

        await self._trim_tool_responses()

        self._add_benchmark_snapshot(
            benchmark, "LLM Processing", llm_processing_time_ms
        )
        if tool_execution_time_ms > 0:
            self._add_tool_execution_snapshot(
                benchmark, tool_execution_time_ms, tool_timings
            )
        await self._broadcast_token_usage(turn_prompt_tokens, turn_completion_tokens)
        return response_message.content, response_message.content, None, interrupt

    # ───────────────── LLM call ───────────────── #

    async def actual_llm_call(self, messages, tools: list[dict] = None):
        if not self.llm:
            await printr.print_async(
                f"No LLM provider configured for wingman '{self.name}'.",
                color=LogType.ERROR,
                source=LogSource.WINGMAN,
                source_name=self.name,
            )
            return None

        try:
            completion = await self.llm.ask(messages=messages, tools=tools)
        except APIConnectionError as e:
            provider = self.config.features.conversation_provider.value
            cause = e.__cause__
            detail = str(cause) if cause else str(e)
            message = f"Could not connect to {provider}: {detail}"
            await printr.print_async(
                message,
                color=LogType.ERROR,
                source=LogSource.WINGMAN,
                source_name=self.name,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return None
        except Exception as e:
            await printr.print_async(
                f"Error during LLM call: {str(e)}",
                color=LogType.ERROR,
                source=LogSource.WINGMAN,
                source_name=self.name,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return None

        return completion

    async def _llm_call(self, allow_tool_calls: bool = True):
        thiscall = time.time()
        self.last_gpt_call = thiscall

        tools = self.build_tools() if allow_tool_calls else None

        if self.settings.debug_mode:
            await printr.print_async(
                f"Calling LLM with {len(self.conversation.messages)} messages (excluding context) and {len(tools) if tools else 0} tools.",
                color=LogType.INFO,
            )

        messages = self.conversation.messages.copy()
        await self.add_context(messages)

        completion = await self.actual_llm_call(messages, tools)

        if self.last_gpt_call != thiscall:
            await printr.print_async(
                "LLM call was cancelled due to a new call.", color=LogType.WARNING
            )
            return None

        return completion

    async def _process_completion(
        self, completion: ChatCompletion, allow_tool_calls: bool = True
    ):
        response_message = completion.choices[0].message

        content = response_message.content
        if content is None:
            response_message.content = ""

        if not allow_tool_calls:
            response_message.tool_calls = None

        if response_message.tool_calls:
            response_message.tool_calls = await self.tool_executor.fix_tool_calls(
                response_message.tool_calls, self.command_executor.get_command
            )

        prompt_tokens = 0
        completion_tokens = 0
        if completion.usage:
            prompt_tokens = completion.usage.prompt_tokens or 0
            completion_tokens = completion.usage.completion_tokens or 0

        return (
            response_message,
            response_message.tool_calls,
            (prompt_tokens, completion_tokens),
        )

    # ───────────────── Tool calls ───────────────── #

    async def _handle_tool_calls(self, tool_calls):
        return await self.tool_executor.handle_tool_calls(
            tool_calls,
            tool_skills=self.tool_skills,
            skill_registry=self.skill_registry,
            mcp_registry=self.mcp_registry,
            capability_registry=self.capability_registry,
            persistent_memory_service=self.persistent_memory_service,
            get_command_fn=self.command_executor.get_command,
            execute_command_fn=self.command_executor.execute_command,
            play_to_user_fn=self.play_to_user,
            local_ai_service=self.local_ai_service,
            update_tool_response_fn=self.conversation.update_tool_response,
            add_tool_response_fn=self.conversation.add_tool_response,
            pending_tool_calls=self.conversation.pending_tool_calls,
        )

    async def execute_command_by_function_call(
        self, function_name: str, function_args: dict[str, any]
    ) -> tuple[str, str | None, Skill | None, str | None]:
        """Public API kept for backward compatibility with skills."""
        return await self.tool_executor.execute_by_function_call(
            function_name,
            function_args,
            tool_skills=self.tool_skills,
            skill_registry=self.skill_registry,
            mcp_registry=self.mcp_registry,
            capability_registry=self.capability_registry,
            persistent_memory_service=self.persistent_memory_service,
            get_command_fn=self.command_executor.get_command,
            execute_command_fn=self.command_executor.execute_command,
            play_to_user_fn=self.play_to_user,
        )

    # ───────────────── Conversation delegation ───────────────── #

    async def _add_gpt_response(self, message, tool_calls) -> tuple[bool, bool]:
        return await self.conversation.add_gpt_response(
            message,
            tool_calls,
            skills=self.skills,
            skill_registry=self.skill_registry,
            tool_skills=self.tool_skills,
        )

    async def _trim_tool_responses(self, max_tokens: int = 500):
        await self.conversation.trim_tool_responses(
            max_tokens=max_tokens,
            is_condensing=self.condenser.is_condensing,
        )

    async def add_user_message(self, content: str, images: list[tuple[str, str]] = None):
        self._memory_recall_notified = False
        self.context_builder.reset_memory_notification()
        await self.conversation.add_user_message(
            content,
            images=images,
            skills=self.skills,
            condense_fn=lambda: self.condenser.maybe_condense(self.local_ai_service),
        )

    async def add_assistant_message(self, content: str):
        await self.conversation.add_assistant_message(
            content, skills=self.skills
        )

    async def add_forced_assistant_command_calls(self, commands: list[CommandConfig]):
        await self.conversation.add_forced_assistant_command_calls(
            commands,
            skills=self.skills,
            skill_registry=self.skill_registry,
            tool_skills=self.tool_skills,
        )

    async def reset_conversation_history(self):
        if self.persistent_memory_service and len(self.conversation.messages) >= 4:
            try:
                await self.persistent_memory_service.extract_memories(
                    self.conversation.messages, generate_summary=True
                )
            except Exception:
                pass

        await self.conversation.reset()
        self._last_prompt_tokens = 0
        self.skill_registry.reset_activations()
        self.mcp_registry.reset_activations()

    def get_conversation_messages(self, strip_nulls: bool = True) -> list[dict]:
        return self.conversation.get_conversation_messages(strip_nulls=strip_nulls)

    # ─── Backward-compat: expose messages directly for skills/services that access it ─── #

    @property
    def messages(self) -> list:
        return self.conversation.messages

    @messages.setter
    def messages(self, value: list):
        self.conversation.messages = value

    @property
    def conversation_summary(self) -> str:
        return self.conversation.conversation_summary

    @conversation_summary.setter
    def conversation_summary(self, value: str):
        self.conversation.conversation_summary = value

    @property
    def pending_tool_calls(self) -> list:
        return self.conversation.pending_tool_calls

    @property
    def _is_condensing(self) -> bool:
        return self.condenser.is_condensing

    # ───────────────── Context ───────────────── #

    async def get_context(self):
        config_dir_name = None
        if self.tower and self.tower.config_dir and self.tower.config_dir.name:
            config_dir_name = self.tower.config_dir.name

        return await self.context_builder.build(
            skills=self.skills,
            skill_registry=self.skill_registry,
            conversation_summary=self.conversation.conversation_summary,
            persistent_memory_service=self.persistent_memory_service,
            messages=self.conversation.messages,
            config_dir_name=config_dir_name,
        )

    def get_last_context(self) -> str:
        return self.context_builder.get_last_context()

    async def add_context(self, messages):
        context = await self.get_context()
        messages.insert(0, {"role": "system", "content": context})

    # ───────────────── TTS / play_to_user ───────────────── #

    async def play_to_user(
        self,
        text: str,
        no_interrupt: bool = False,
        sound_config: Optional[SoundConfig] = None,
    ):
        if sound_config:
            printr.print(
                "Using custom sound config for playback", LogType.INFO, server_only=True
            )
        else:
            sound_config = self.config.sound

        text, contains_links, contains_code_blocks = cleanup_text(text)

        if no_interrupt and self.audio_player.is_playing:
            while self.audio_player.is_playing:
                await asyncio.sleep(0.1)

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

        if not self.tts:
            printr.print(
                f"No TTS provider configured for wingman '{self.name}'.",
                LogType.WARNING,
                server_only=True,
            )
            return

        try:
            await self.tts.play_audio(
                text=text,
                sound_config=sound_config,
                audio_player=self.audio_player,
                wingman_name=self.name,
            )
        except Exception as e:
            await printr.print_async(
                f"Error during TTS playback: {str(e)}", color=LogType.ERROR
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

    # ───────────────── Image generation ───────────────── #

    async def generate_image(self, text: str) -> str:
        if (
            self.config.features.image_generation_provider
            == ImageGenerationProvider.WINGMAN_PRO
        ):
            try:
                from providers.wingman_subscription import WingmanSubscription

                wingman_pro = WingmanSubscription(
                    wingman_name=self.name, settings=self.settings.wingman_pro
                )
                return await wingman_pro.generate_image(text)
            except Exception as e:
                await printr.print_async(
                    f"Error during image generation: {str(e)}", color=LogType.ERROR
                )
                printr.print(
                    traceback.format_exc(), color=LogType.ERROR, server_only=True
                )
        return ""

    # ───────────────── Instant responses ───────────────── #

    async def _generate_instant_responses(self) -> None:
        context = await self.get_context()
        messages = [
            {
                "role": "system",
                "content": """
                Generate a list in JSON format of at least 20 short direct text responses.
                Make sure the response only contains the JSON, no additional text.
                They must fit the described character in the given context by the user.
                Every generated response must be generally usable in every situation.
                Responses must show its still in progress and not in a finished state.
                The user request this response is used on is unknown. Therefore it must be generic.
                Good examples:
                    - "Processing..."
                    - "Stand by..."

                Bad examples:
                    - "Generating route..." (too specific)
                    - "I'm sorry, I can't do that." (too negative)

                Response example:
                [
                    "OK",
                    "Generating results...",
                    "Roger that!",
                    "Stand by..."
                ]
            """,
            },
            {"role": "user", "content": context},
        ]
        try:
            completion = await self.actual_llm_call(messages)
            if completion is None:
                return
            if completion.choices[0].message.content:
                retry_limit = 3
                retry_count = 1
                valid = False
                while not valid and retry_count <= retry_limit:
                    try:
                        responses = json.loads(completion.choices[0].message.content)
                        valid = True
                        for response in responses:
                            if response not in self.instant_responses:
                                self.instant_responses.append(str(response))
                    except json.JSONDecodeError:
                        messages.append(completion.choices[0].message)
                        messages.append(
                            {
                                "role": "user",
                                "content": "It was tried to handle the response in its entirety as a JSON string. Fix response to be a pure, valid JSON, it was not convertable.",
                            }
                        )
                        if retry_count <= retry_limit:
                            completion = await self.actual_llm_call(messages)
                        retry_count += 1
        except Exception as e:
            await printr.print_async(
                f"Error while generating instant responses: {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

    def _get_random_filler(self):
        if len(self.last_used_instant_responses) > 2:
            self.last_used_instant_responses = self.last_used_instant_responses[-2:]

        random_index = random.randint(0, len(self.instant_responses) - 1)
        while random_index in self.last_used_instant_responses:
            random_index = random.randint(0, len(self.instant_responses) - 1)

        self.last_used_instant_responses.append(random_index)
        return self.instant_responses[random_index]

    # ───────────────── Benchmarks / token usage ───────────────── #

    def _add_benchmark_snapshot(
        self, benchmark: Benchmark, label: str, execution_time_ms: float
    ):
        if execution_time_ms >= 1000:
            formatted_time = f"{execution_time_ms/1000:.1f}s"
        else:
            formatted_time = f"{int(execution_time_ms)}ms"

        from api.interface import BenchmarkResult

        benchmark.snapshots.append(
            BenchmarkResult(
                label=label,
                execution_time_ms=execution_time_ms,
                formatted_execution_time=formatted_time,
            )
        )

    def _add_tool_execution_snapshot(
        self,
        benchmark: Benchmark,
        total_time_ms: float,
        tool_timings: list[tuple[str, float]],
    ):
        from api.interface import BenchmarkResult

        if total_time_ms >= 1000:
            formatted_time = f"{total_time_ms/1000:.1f}s"
        else:
            formatted_time = f"{int(total_time_ms)}ms"

        nested_snapshots = []
        for label, time_ms in tool_timings:
            if time_ms >= 1000:
                fmt = f"{time_ms/1000:.1f}s"
            else:
                fmt = f"{int(time_ms)}ms"
            nested_snapshots.append(
                BenchmarkResult(
                    label=label,
                    execution_time_ms=time_ms,
                    formatted_execution_time=fmt,
                )
            )

        benchmark.snapshots.append(
            BenchmarkResult(
                label="Tool Execution",
                execution_time_ms=total_time_ms,
                formatted_execution_time=formatted_time,
                snapshots=nested_snapshots if nested_snapshots else None,
            )
        )

    async def _broadcast_token_usage(self, prompt_tokens: int, completion_tokens: int):
        is_local = (
            self.config.features.conversation_provider == ConversationProvider.LOCAL_LLM
        )

        if is_local and prompt_tokens == 0:
            prompt_tokens = sum(
                count_tokens(
                    msg["content"]
                    if isinstance(msg.get("content"), str)
                    else str(msg.get("content", ""))
                )
                for msg in self.conversation.messages
            )
        if is_local and completion_tokens == 0 and self.conversation.messages:
            last = self.conversation.messages[-1]
            if last.get("role") == "assistant":
                content = last.get("content", "")
                completion_tokens = count_tokens(
                    content if isinstance(content, str) else str(content)
                )

        self.last_turn_prompt_tokens = prompt_tokens
        self.last_turn_completion_tokens = completion_tokens
        if prompt_tokens == 0 and completion_tokens == 0:
            return
        if not printr._connection_manager:
            return

        from api.commands import ConversationTokenUsageCommand

        await printr._connection_manager.broadcast(
            ConversationTokenUsageCommand(
                wingman_name=self.name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                is_local=is_local,
            )
        )

    # ───────────────── Build tools ───────────────── #

    def build_tools(self) -> list[dict]:
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

        for _, tool in self.capability_registry.get_meta_tools():
            tools.append(tool)

        for _, tool in self.skill_registry.get_active_tools():
            tools.append(tool)

        for _, tool in self.mcp_registry.get_active_tools():
            tools.append(tool)

        if self.persistent_memory_service:
            tools.append({
                "type": "function",
                "function": {
                    "name": "memory_remember",
                    "description": "Store an important fact or detail for future reference. Use when the user explicitly asks you to remember something.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "The fact or detail to remember.",
                            },
                        },
                        "required": ["text"],
                    },
                },
            })
            tools.append({
                "type": "function",
                "function": {
                    "name": "memory_recall",
                    "description": "Search your memory for relevant information. Use when the user asks what you remember or know about a topic.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "What to search for in memory.",
                            },
                        },
                        "required": ["query"],
                    },
                },
            })
            tools.append({
                "type": "function",
                "function": {
                    "name": "memory_forget",
                    "description": "Remove a specific memory. Use when the user explicitly asks you to forget something.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Description of the memory to forget.",
                            },
                        },
                        "required": ["query"],
                    },
                },
            })

        return tools

    # ───────────────── Backward-compat delegation ────────────── #

    def get_command(self, command_name: str) -> CommandConfig | None:
        """Backward-compat: delegate to command_executor."""
        return self.command_executor.get_command(command_name)

    async def execute_action(self, command: CommandConfig):
        """Backward-compat: delegate to command_executor."""
        await self.command_executor.execute_action(command)

    # ───────────────── Threading ─────────────────────────────── #

    def threaded_execution(self, function, *args) -> threading.Thread | None:
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
            thread.daemon = True
            thread.start()
            return thread
        except Exception as e:
            printr.print(
                f"Error starting threaded execution: {str(e)}", color=LogType.ERROR
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return None

    # ───────────────── Config management ─────────────────────── #

    async def update_config(
        self, config: WingmanConfig, skip_config_validation: bool = True
    ) -> bool:
        try:
            if not skip_config_validation:
                old_config = deepcopy(self.config)

            self.config = config
            self.command_executor.config = config

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
        if not self.skills or not wingman_config.skills:
            return

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

        for skill in self.skills:
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
                    fields_set = getattr(user_override, "__fields_set__", set())

                updated_config = deepcopy(skill.config)

                if "custom_properties" in fields_set:
                    updated_config.custom_properties = user_override.custom_properties
                if "prompt" in fields_set:
                    updated_config.prompt = user_override.prompt

                await skill.update_config(updated_config)

    async def update_settings(self, settings: SettingsConfig):
        try:
            self.settings = settings

            for skill in self.skills:
                skill.settings = settings

            # Re-create Wingman Pro provider when settings change
            # (subscription settings might have been updated)
            uses_wingman_pro = any([
                self.config.features.conversation_provider == ConversationProvider.WINGMAN_PRO,
                self.config.features.tts_provider == TtsProvider.WINGMAN_PRO,
                self.config.features.stt_provider == SttProvider.WINGMAN_PRO,
                self.config.features.image_generation_provider == ImageGenerationProvider.WINGMAN_PRO,
            ])
            if uses_wingman_pro:
                await self.validate()
                printr.print(
                    f"Wingman {self.name}: reinitialized providers with new settings",
                    server_only=True,
                )

            printr.print(f"Wingman {self.name}'s settings changed", server_only=True)
        except Exception as e:
            await printr.print_async(
                f"Error while updating settings for wingman '{self.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

    async def save_config(self):
        self.tower.save_wingman(self.name)

    async def save_commands(self):
        self.tower.save_wingman_commands(self.name)
