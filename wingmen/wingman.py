"""Unified Wingman class.

Merges the former base ``Wingman`` and its only subclass ``OpenAiWingman``
into a single class that delegates to extracted services and provider
interfaces for STT, TTS, and LLM.
"""

import time
import asyncio
import traceback
import threading
from copy import deepcopy
from typing import (
    Any,
    Dict,
    Optional,
    TYPE_CHECKING,
)
from openai import APIConnectionError
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
from services.threading_utils import threaded_execution
from services.mcp_client import McpClient
from services.capability_registry import CapabilityRegistry
from services.wingman_mcp_manager import WingmanMcpManager
from services.wingman_skill_manager import WingmanSkillManager, _get_skill_folder_from_module
from services.tool_response_cache import ToolResponseCompressor
from services.turn_metrics import TurnMetrics
from services.instant_response_generator import InstantResponseGenerator
from skills.skill_base import Skill

if TYPE_CHECKING:
    from services.tower import Tower

printr = Printr()


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
            on_add_forced_commands=self.conversation.add_forced_assistant_command_calls,
        )

        # --- Metrics service ---
        self.metrics = TurnMetrics(
            wingman_name=name,
            config=config,
            conversation=self.conversation,
        )

        self.execution_start: None | float = None

        # --- Skills ---
        self.skill_registry = SkillRegistry()
        self.skill_manager = WingmanSkillManager(
            wingman=self,
            config=config,
            settings=settings,
            skill_registry=self.skill_registry,
        )

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

        # --- Image generation (lazy) ---
        self._image_subscription = None

        # --- Instant response generator ---
        self.instant_response_generator = InstantResponseGenerator(
            wingman_name=name,
            llm_call_fn=self.actual_llm_call,
            get_context_fn=self.get_context,
        )

        # --- Conversation state ---
        self.last_gpt_call = None

    # ──────────────────────────────── Backward-compat properties ──────────────── #

    @property
    def mcp_registry(self):
        """Backward-compat: many callers access wingman.mcp_registry directly."""
        return self.mcp_manager.mcp_registry

    @property
    def skills(self):
        return self.skill_manager.skills

    @property
    def tool_skills(self):
        return self.skill_manager.tool_skills

    @property
    def skill_tools(self):
        return self.skill_manager.skill_tools

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
                self.threaded_execution(self.instant_response_generator.generate)
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
        return await self.skill_manager.unload_skills()

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

    # ──────────────────────────────── Skills (forwarding) ─────────────────────── #

    async def init_skills(self) -> list[WingmanInitializationError]:
        return await self.skill_manager.init_skills()

    async def enable_skill(self, skill_name: str) -> tuple[bool, str]:
        return await self.skill_manager.enable_skill(skill_name)

    async def disable_skill(self, skill_name: str) -> tuple[bool, str]:
        return await self.skill_manager.disable_skill(skill_name)

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
                    if self.metrics.last_turn_prompt_tokens or self.metrics.last_turn_completion_tokens:
                        token_usage = (
                            self.metrics.last_turn_prompt_tokens,
                            self.metrics.last_turn_completion_tokens,
                        )
                        self.metrics.reset_token_counters()
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
            await self.conversation.add_assistant_message(instant_response)
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
            self.metrics.add_benchmark_snapshot(
                benchmark, "LLM Processing", llm_processing_time_ms
            )
            return None, None, None, True

        response_message, tool_calls, usage = await self._process_completion(
            completion, instant_command_executed is False
        )

        turn_prompt_tokens = usage[0]
        turn_completion_tokens = usage[1]

        is_waiting_response_needed, is_summarize_needed = await self.conversation.add_gpt_response(
            response_message, tool_calls
        )
        interrupt = True

        while tool_calls:
            if is_waiting_response_needed:
                message = None
                if response_message.content:
                    message = response_message.content
                else:
                    filler = self.instant_response_generator.get_random_filler()
                    if filler:
                        message = filler
                        is_summarize_needed = True
                if message:
                    self.threaded_execution(self.play_to_user, message, not interrupt)
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
                await self.conversation.trim_tool_responses(max_tokens=500, is_condensing=self.condenser.is_condensing)
                self.metrics.add_benchmark_snapshot(
                    benchmark, "LLM Processing", llm_processing_time_ms
                )
                if tool_execution_time_ms > 0:
                    self.metrics.add_tool_execution_snapshot(
                        benchmark, tool_execution_time_ms, tool_timings
                    )
                await self.metrics.broadcast_token_usage(
                    turn_prompt_tokens, turn_completion_tokens
                )
                return None, instant_response, None, interrupt

            if is_summarize_needed:
                llm_start = time.perf_counter()
                completion = await self._llm_call(True)
                llm_processing_time_ms += (time.perf_counter() - llm_start) * 1000

                if completion is None:
                    await self.conversation.trim_tool_responses(max_tokens=500, is_condensing=self.condenser.is_condensing)
                    self.metrics.add_benchmark_snapshot(
                        benchmark, "LLM Processing", llm_processing_time_ms
                    )
                    if tool_execution_time_ms > 0:
                        self.metrics.add_tool_execution_snapshot(
                            benchmark, tool_execution_time_ms, tool_timings
                        )
                    await self.metrics.broadcast_token_usage(
                        turn_prompt_tokens, turn_completion_tokens
                    )
                    return None, None, None, True

                response_message, tool_calls, usage = await self._process_completion(
                    completion
                )
                turn_prompt_tokens = usage[0]
                turn_completion_tokens += usage[1]

                is_waiting_response_needed, is_summarize_needed = (
                    await self.conversation.add_gpt_response(response_message, tool_calls)
                )
                if tool_calls:
                    interrupt = False
            elif is_waiting_response_needed:
                await self.conversation.trim_tool_responses(max_tokens=500, is_condensing=self.condenser.is_condensing)
                self.metrics.add_benchmark_snapshot(
                    benchmark, "LLM Processing", llm_processing_time_ms
                )
                if tool_execution_time_ms > 0:
                    self.metrics.add_tool_execution_snapshot(
                        benchmark, tool_execution_time_ms, tool_timings
                    )
                await self.metrics.broadcast_token_usage(
                    turn_prompt_tokens, turn_completion_tokens
                )
                return None, None, None, interrupt

        await self.conversation.trim_tool_responses(max_tokens=500, is_condensing=self.condenser.is_condensing)

        self.metrics.add_benchmark_snapshot(
            benchmark, "LLM Processing", llm_processing_time_ms
        )
        if tool_execution_time_ms > 0:
            self.metrics.add_tool_execution_snapshot(
                benchmark, tool_execution_time_ms, tool_timings
            )
        await self.metrics.broadcast_token_usage(turn_prompt_tokens, turn_completion_tokens)
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
        self, function_name: str, function_args: dict[str, Any]
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

    async def add_user_message(self, content: str, images: list[tuple[str, str]] = None):
        """Thin wrapper: resets memory-recall state then delegates to ConversationManager."""
        self._memory_recall_notified = False
        self.context_builder.reset_memory_notification()
        await self.conversation.add_user_message(
            content,
            images=images,
            condense_fn=lambda: self.condenser.maybe_condense(self.local_ai_service),
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
            != ImageGenerationProvider.WINGMAN_PRO
        ):
            return ""
        try:
            if self._image_subscription is None:
                from providers.wingman_subscription import WingmanSubscription

                self._image_subscription = WingmanSubscription(
                    wingman_name=self.name, settings=self.settings.wingman_pro
                )
            return await self._image_subscription.generate_image(text)
        except Exception as e:
            await printr.print_async(
                f"Error during image generation: {str(e)}", color=LogType.ERROR
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
        return ""

    # ───────────────── Build tools ───────────────── #

    def build_tools(self) -> list[dict]:
        """Assemble the full tool list for LLM calls."""
        tools: list[dict] = []

        command_tool = self.command_executor.get_tool_definition()
        if command_tool:
            tools.append(command_tool)

        for _, tool in self.capability_registry.get_meta_tools():
            tools.append(tool)

        for _, tool in self.skill_registry.get_active_tools():
            tools.append(tool)

        for _, tool in self.mcp_registry.get_active_tools():
            tools.append(tool)

        if self.persistent_memory_service:
            tools.extend(self.persistent_memory_service.get_tool_definitions())

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
        return threaded_execution(function, *args)

    # ───────────────── Config management ─────────────────────── #

    async def update_config(
        self, config: WingmanConfig, skip_config_validation: bool = True
    ) -> bool:
        try:
            if not skip_config_validation:
                old_config = deepcopy(self.config)

            self.config = config

            # Propagate to all services that hold a config reference
            self.command_executor.config = config
            self.conversation._config = config
            self.condenser._config = config
            self.context_builder._config = config
            self.tool_executor._config = config
            self.metrics.config = config
            self.mcp_manager.config = config
            self.skill_manager.config = config

            await self._update_skill_configs(config)

            if not skip_config_validation:
                errors = await self.validate()

                for error in errors:
                    if (
                        error.error_type
                        != WingmanInitializationErrorType.MISSING_SECRET
                    ):
                        # Roll back config on all services
                        self.config = old_config
                        self.command_executor.config = old_config
                        self.conversation._config = old_config
                        self.condenser._config = old_config
                        self.context_builder._config = old_config
                        self.tool_executor._config = old_config
                        self.metrics.config = old_config
                        self.mcp_manager.config = old_config
                        self.skill_manager.config = old_config
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

            # Propagate to all services that hold a settings reference
            self.conversation._settings = settings
            self.context_builder._settings = settings
            self.tool_executor._settings = settings
            self.mcp_manager.settings = settings
            self.skill_manager.settings = settings

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
