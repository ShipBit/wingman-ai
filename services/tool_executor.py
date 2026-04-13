"""Tool call dispatch -- routes function calls to memory, skills, MCP, commands, etc."""

import json
import time
import traceback
from typing import TYPE_CHECKING, Any, Callable, Awaitable

from api.enums import LogType
from services.benchmark import Benchmark
from services.printr import Printr
from services.tool_response_cache import ToolResponseCompressor

if TYPE_CHECKING:
    from api.interface import CommandConfig, WingmanConfig, SettingsConfig
    from services.capability_registry import CapabilityRegistry
    from services.mcp_registry import McpRegistry
    from services.persistent_memory import PersistentMemoryService
    from services.skill_registry import SkillRegistry
    from skills.skill_base import Skill

printr = Printr()


class ToolExecutor:
    """Dispatches tool calls to the appropriate handler (memory, skills, MCP, commands).

    This is a stateless dispatcher -- all mutable state (registries, services, callbacks)
    is passed as parameters to ``handle_tool_calls`` / ``execute_by_function_call``.
    """

    def __init__(
        self,
        config: "WingmanConfig",
        settings: "SettingsConfig",
        wingman_name: str,
    ):
        self._config = config
        self._settings = settings
        self._wingman_name = wingman_name
        self._tool_response_compressor = ToolResponseCompressor()

    # ------------------------------------------------------------------
    # fix_tool_calls  (was _fix_tool_calls)
    # ------------------------------------------------------------------

    async def fix_tool_calls(
        self,
        tool_calls,
        get_command_fn: Callable[[str], "CommandConfig | None"],
    ):
        """Fixes tool calls that have a command name as function name.

        Mistral sometimes returns the command name directly as the function name
        instead of wrapping it in ``execute_command``. This method detects that
        pattern and rewrites the tool call accordingly.

        Args:
            tool_calls: The tool calls to fix.
            get_command_fn: Callback ``(name) -> CommandConfig | None`` used to
                check whether a string is a known command name.

        Returns:
            list: The fixed tool calls.
        """
        if tool_calls and len(tool_calls) > 0:
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = (
                    tool_call.function.arguments
                    # Mistral returns a dict
                    if isinstance(tool_call.function.arguments, dict)
                    # OpenAI returns a string
                    else json.loads(tool_call.function.arguments)
                )

                # try to resolve function name to a command name
                if (len(function_args) == 0 and get_command_fn(function_name)) or (
                    len(function_args) == 1
                    and "command_name" in function_args
                    and get_command_fn(function_args["command_name"])
                    and function_name == function_args["command_name"]
                ):
                    function_args["command_name"] = function_name
                    function_name = "execute_command"

                    # update the tool call
                    tool_call.function.name = function_name
                    tool_call.function.arguments = json.dumps(function_args)

                    if self._settings.debug_mode:
                        await printr.print_async(
                            "Applied command call fix.", color=LogType.WARNING
                        )

        return tool_calls

    # ------------------------------------------------------------------
    # handle_tool_calls  (was _handle_tool_calls)
    # ------------------------------------------------------------------

    async def handle_tool_calls(
        self,
        tool_calls,
        *,
        tool_skills: dict,
        skill_registry: "SkillRegistry",
        mcp_registry: "McpRegistry",
        capability_registry: "CapabilityRegistry",
        persistent_memory_service: "PersistentMemoryService | None",
        get_command_fn: Callable[[str], "CommandConfig | None"],
        execute_command_fn: Callable[["CommandConfig", bool], Awaitable[tuple]],
        play_to_user_fn: Callable[[str], Awaitable[None]],
        local_ai_service,
        update_tool_response_fn: Callable[[str, str], Awaitable[bool]],
        add_tool_response_fn: Callable,
        pending_tool_calls: list,
    ):
        """Processes all the tool calls identified in the response message.

        Args:
            tool_calls: The list of tool calls to process.
            tool_skills: Mapping of tool name -> Skill instance.
            skill_registry: For skill search/activation.
            mcp_registry: For MCP tool execution.
            capability_registry: For capability management.
            persistent_memory_service: For memory tools (may be None).
            get_command_fn: Callback to get a Command by name.
            execute_command_fn: Callback to execute a Command.
            play_to_user_fn: Callback to play audio response.
            local_ai_service: For tool response compression.
            update_tool_response_fn: Callback to update an existing tool
                response in conversation history.
            add_tool_response_fn: Callback to add a new tool response to
                conversation history.
            pending_tool_calls: List reference for tracking pending calls.

        Returns:
            tuple: (instant_response, skill, tool_timings) where tool_timings
                is a list of (label, time_ms) tuples.
        """
        instant_response = None
        function_response = ""
        tool_timings: list[tuple[str, float]] = []

        skill = None

        for tool_call in tool_calls:
            try:
                function_name = tool_call.function.name
                function_args = (
                    tool_call.function.arguments
                    # Mistral returns a dict
                    if isinstance(tool_call.function.arguments, dict)
                    # OpenAI returns a string
                    else json.loads(tool_call.function.arguments)
                )

                # Time the individual tool execution
                tool_start = time.perf_counter()
                (
                    function_response,
                    instant_response,
                    skill,
                    tool_label,
                ) = await self.execute_by_function_call(
                    function_name,
                    function_args,
                    tool_skills=tool_skills,
                    skill_registry=skill_registry,
                    mcp_registry=mcp_registry,
                    capability_registry=capability_registry,
                    persistent_memory_service=persistent_memory_service,
                    get_command_fn=get_command_fn,
                    execute_command_fn=execute_command_fn,
                    play_to_user_fn=play_to_user_fn,
                )
                tool_time_ms = (time.perf_counter() - tool_start) * 1000

                # Add timing if we got a label (actual tool execution, not meta-tool)
                if tool_label:
                    tool_timings.append((tool_label, tool_time_ms))

                # Compress large tool responses via local AI before the cloud LLM sees them
                if (
                    tool_call.id
                    and self._config.features.compress_tool_responses
                    and local_ai_service
                    and local_ai_service.is_ready()
                    and self._tool_response_compressor.should_compress(
                        str(function_response)
                    )
                ):
                    function_response = await self._tool_response_compressor.compress(
                        response_text=str(function_response),
                        local_ai_service=local_ai_service,
                        wingman_name=self._wingman_name,
                        tool_name=function_name,
                    )

                if tool_call.id:
                    # updating the dummy tool response with the actual response
                    await update_tool_response_fn(tool_call.id, function_response)
                else:
                    # adding a new tool response
                    add_tool_response_fn(tool_call, function_response)
            except Exception as e:
                if tool_call.id:
                    await update_tool_response_fn(tool_call.id, "Error")
                else:
                    add_tool_response_fn(tool_call, "Error")
                await printr.print_async(
                    f"Error while processing tool call: {str(e)}", color=LogType.ERROR
                )
                printr.print(
                    traceback.format_exc(), color=LogType.ERROR, server_only=True
                )
        return instant_response, skill, tool_timings

    # ------------------------------------------------------------------
    # execute_by_function_call  (was execute_command_by_function_call)
    # ------------------------------------------------------------------

    async def execute_by_function_call(
        self,
        function_name: str,
        function_args: dict[str, Any],
        *,
        tool_skills: dict,
        skill_registry: "SkillRegistry",
        mcp_registry: "McpRegistry",
        capability_registry: "CapabilityRegistry",
        persistent_memory_service: "PersistentMemoryService | None",
        get_command_fn: Callable[[str], "CommandConfig | None"],
        execute_command_fn: Callable[["CommandConfig", bool], Awaitable[tuple]],
        play_to_user_fn: Callable[[str], Awaitable[None]],
    ) -> tuple[str, str | None, "Skill | None", str | None]:
        """Dispatches a single function call to the appropriate handler.

        Uses an OpenAI function call to execute a command. If it's an instant
        activation_command, one of its responses will be played.

        Args:
            function_name: The name of the function to be executed.
            function_args: The arguments to pass to the function being executed.
            tool_skills: Mapping of tool name -> Skill instance.
            skill_registry: For skill search/activation and display names.
            mcp_registry: For MCP tool execution and meta-tools.
            capability_registry: For capability meta-tools.
            persistent_memory_service: For memory tools (may be None).
            get_command_fn: Callback ``(name) -> CommandConfig | None``.
            execute_command_fn: Callback to execute a Command.
            play_to_user_fn: Callback to play audio response.

        Returns:
            A tuple containing:
            - function_response (str): The text response or result obtained
              after executing the function.
            - instant_response (str | None): An immediate response or action
              to be taken, if any (e.g., play audio).
            - used_skill (Skill | None): The skill that was used, if any.
            - tool_label (str | None): Label for benchmark timing
              (e.g., "MCP: resolve-library-id"), or None for meta-tools.
        """
        function_response = ""
        instant_response = ""
        used_skill = None
        tool_label = None

        # ── 1. Persistent memory tools ──────────────────────────────
        if (
            function_name in ("memory_remember", "memory_recall", "memory_forget")
            and persistent_memory_service
        ):
            if function_name == "memory_remember":
                text = function_args.get("text", "")
                if text:
                    await persistent_memory_service.add_memory(
                        entry_type="fact", content=text
                    )
                    function_response = f'I\'ll remember that: "{text}"'
                    await printr.print_async(
                        f"Memory stored: {text}",
                        color=LogType.MEMORY,
                        source_name=self._wingman_name,
                    )
                else:
                    function_response = "Nothing to remember -- no text provided."

            elif function_name == "memory_recall":
                query = function_args.get("query", "")
                if query:
                    results = await persistent_memory_service.search(
                        query, limit=10
                    )
                    if results:
                        lines = [f"- {r.content}" for r in results]
                        function_response = (
                            "Here's what I remember:\n" + "\n".join(lines)
                        )
                    else:
                        function_response = (
                            "I don't have any memories matching that."
                        )
                else:
                    function_response = "No query provided for memory recall."

            elif function_name == "memory_forget":
                query = function_args.get("query", "")
                if query:
                    deleted = await persistent_memory_service.forget_by_query(query)
                    if deleted:
                        function_response = (
                            f'Done -- I\'ve forgotten the memory related to "{query}".'
                        )
                    else:
                        function_response = (
                            "I couldn't find a memory closely matching that to forget."
                        )
                else:
                    function_response = "No query provided for memory forget."

            return function_response, None, None, f"💾 memory: {function_name}"

        # ── 2. Unified capability meta-tools ────────────────────────
        if capability_registry.is_meta_tool(function_name):
            function_response, tools_changed = (
                await capability_registry.execute_meta_tool(
                    function_name, function_args
                )
            )

            # If a skill was activated, perform lazy validation
            if tools_changed and function_name == "activate_capability":
                capability_name = function_args.get("capability_name", "")
                skill = skill_registry.get_skill_for_activation(capability_name)
                if skill and skill.needs_activation():
                    success, validation_msg = await skill.ensure_activated()
                    if not success:
                        # Validation failed -- deactivate the skill
                        skill_registry.deactivate_skill(capability_name)
                        function_response = validation_msg
                        tools_changed = False
                        await printr.print_async(
                            f"Skill activation failed: {capability_name}",
                            color=LogType.ERROR,
                        )
                    else:
                        # Get display name for user-friendly message
                        display_name = skill_registry.get_skill_display_name(
                            capability_name
                        )
                        await printr.print_async(
                            f"Skill activated: {display_name}",
                            color=LogType.SKILL,
                        )

            return function_response, None, None, None  # Meta-tool, no timing label

        # ── 3. Legacy skill meta-tools ──────────────────────────────
        if skill_registry.is_meta_tool(function_name):
            function_response, tools_changed = (
                await skill_registry.execute_meta_tool(function_name, function_args)
            )

            # If skill was activated, perform lazy validation
            if tools_changed and function_name == "activate_skill":
                skill_name = function_args.get("skill_name", "")
                skill = skill_registry.get_skill_for_activation(skill_name)
                if skill and skill.needs_activation():
                    success, validation_msg = await skill.ensure_activated()
                    if not success:
                        # Validation failed -- deactivate the skill
                        skill_registry.deactivate_skill(skill_name)
                        function_response = validation_msg
                        tools_changed = False
                        await printr.print_async(
                            f"Skill activation failed: {skill_name}",
                            color=LogType.ERROR,
                        )
                    else:
                        # Get display name for user-friendly message
                        display_name = skill_registry.get_skill_display_name(
                            skill_name
                        )
                        await printr.print_async(
                            f"Skill activated: {display_name}",
                            color=LogType.SKILL,
                        )

            return function_response, None, None, None  # Meta-tool, no timing label

        # ── 4. MCP meta-tools ───────────────────────────────────────
        if mcp_registry.is_meta_tool(function_name):
            function_response, tools_changed = (
                await mcp_registry.execute_meta_tool(function_name, function_args)
            )
            return function_response, None, None, None  # Meta-tool, no timing label

        # ── 5. MCP server tools (prefixed with mcp_) ────────────────
        if mcp_registry.is_mcp_tool(function_name):
            connection = mcp_registry.get_connection_for_tool(function_name)
            if connection:
                display_name = connection.config.display_name
                original_name = mcp_registry.get_original_tool_name(function_name)
                tool_label = f"🌐 {display_name}: {original_name}"

                benchmark = Benchmark(
                    f"MCP '{connection.config.name}' - {original_name}"
                )

                # Always show simple 'called' message in UI
                await printr.print_async(
                    f"{display_name}: called `{original_name}` with {function_args}",
                    color=LogType.MCP,
                )

                # Detailed 'calling' log only in terminal/log file
                await printr.print_async(
                    f"{display_name}: calling `{original_name}` with {function_args}...",
                    color=LogType.MCP,
                    server_only=True,
                )

                try:
                    function_response = await mcp_registry.call_tool(
                        function_name, function_args
                    )
                except Exception as e:
                    await printr.print_async(
                        f"{display_name}: `{original_name}` failed - {str(e)}",
                        color=LogType.ERROR,
                    )
                    printr.print(
                        traceback.format_exc(),
                        color=LogType.ERROR,
                        server_only=True,
                    )
                    function_response = "ERROR DURING MCP TOOL EXECUTION"
                finally:
                    # Detailed 'completed' with timing only in terminal/log file
                    await printr.print_async(
                        f"{display_name}: `{original_name}` completed",
                        color=LogType.MCP,
                        benchmark_result=benchmark.finish(),
                        server_only=not self._settings.debug_mode,
                    )

                return function_response, None, None, tool_label

        # ── 6. Command execution ────────────────────────────────────
        if function_name == "execute_command":
            # get the command based on the argument passed by the LLM
            command = get_command_fn(function_args["command_name"])
            # execute the command
            instant_response, function_response = await execute_command_fn(
                command
            )
            tool_label = (
                f"Command: {function_args.get('command_name', function_name)}"
            )
            # if the command has responses, we have to play one of them
            if instant_response:
                await play_to_user_fn(instant_response)

        # ── 7. Skill tool execution ─────────────────────────────────
        if function_name in tool_skills:
            skill = tool_skills[function_name]
            display_name = skill_registry.get_skill_display_name(skill.name)
            tool_label = f"⚡ {display_name}: {function_name}"

            benchmark = Benchmark(f"Skill '{skill.name}' - {function_name}")

            # Always show simple 'called' message in UI
            await printr.print_async(
                f"{display_name}: called `{function_name}` with {function_args}",
                color=LogType.SKILL,
                skill_name=skill.name,
            )

            # Detailed 'calling' log only in terminal/log file
            await printr.print_async(
                f"{display_name}: calling `{function_name}` with {function_args}...",
                color=LogType.SKILL,
                skill_name=skill.name,
                server_only=True,
            )

            try:
                function_response, instant_response = await skill.execute_tool(
                    tool_name=function_name,
                    parameters=function_args,
                    benchmark=benchmark,
                )
                used_skill = skill
                if instant_response:
                    await play_to_user_fn(instant_response)
            except Exception as e:
                await printr.print_async(
                    f"{display_name}: `{function_name}` failed - {str(e)}",
                    color=LogType.ERROR,
                )
                printr.print(
                    traceback.format_exc(), color=LogType.ERROR, server_only=True
                )
                function_response = (
                    "ERROR DURING PROCESSING"  # hints to AI that there was an error
                )
                instant_response = None
            finally:
                await printr.print_async(
                    f"{display_name}: `{function_name}` completed",
                    color=LogType.SKILL,
                    benchmark_result=benchmark.finish(),
                    skill_name=skill.name,
                    server_only=not self._settings.debug_mode,
                )

        return function_response, instant_response, used_skill, tool_label
