"""
Tool Executor Service

Handles execution of tool calls from LLM responses, routing to appropriate handlers:
- Meta-tools (capability/skill/MCP discovery and activation)
- Skill tools (user-defined skill functions)
- Commands (instant activation commands)
- MCP tools (Model Context Protocol server tools)

Extracts tool execution logic from Wingman for better separation of concerns.
"""

import json
import time
import traceback
from api.enums import LogType
from services.benchmark import Benchmark
from services.printr import Printr

printr = Printr()


class ToolExecutor:
    """Executes tool calls by routing to meta-tools, skills, commands, or MCP tools."""

    def __init__(
        self,
        capability_registry,
        skill_registry,
        mcp_registry,
        tool_skills: dict,
        get_command_func,
        execute_command_func,
        select_command_response_func,
        play_to_user_func,
        settings,
    ):
        """Initialize the tool executor with required registries and callbacks.

        Args:
            capability_registry: Unified capability registry (skills + MCP)
            skill_registry: Skill registry for progressive disclosure
            mcp_registry: MCP server registry
            tool_skills: Dict mapping tool names to skill instances
            get_command_func: Function to get command by name
            execute_command_func: Function to execute a command
            select_command_response_func: Function to select command response
            play_to_user_func: Function to play audio to user
            settings: Configuration settings (for debug mode)
        """
        self.capability_registry = capability_registry
        self.skill_registry = skill_registry
        self.mcp_registry = mcp_registry
        self.tool_skills = tool_skills
        self.get_command = get_command_func
        self._execute_command = execute_command_func
        self._select_command_response = select_command_response_func
        self.play_to_user = play_to_user_func
        self.settings = settings

    async def fix_tool_calls(self, tool_calls):
        """Fixes tool calls that have a command name as function name.

        Some LLMs incorrectly return command names directly as function names
        instead of using the execute_command function. This method fixes those
        by converting them to proper execute_command calls.

        Args:
            tool_calls (list): The tool calls to fix.

        Returns:
            list: The fixed tool calls.
        """
        if not tool_calls or len(tool_calls) == 0:
            return tool_calls

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
            if (len(function_args) == 0 and self.get_command(function_name)) or (
                len(function_args) == 1
                and "command_name" in function_args
                and self.get_command(function_args["command_name"])
                and function_name == function_args["command_name"]
            ):
                function_args["command_name"] = function_name
                function_name = "execute_command"

                # update the tool call
                tool_call.function.name = function_name
                tool_call.function.arguments = json.dumps(function_args)

                if self.settings.debug_mode:
                    await printr.print_async(
                        "Applied command call fix.", color=LogType.WARNING
                    )

        return tool_calls

    async def execute_tool_call(
        self, function_name: str, function_args: dict
    ) -> tuple[str, str | None, object | None, str | None]:
        """Execute a single tool call.

        Args:
            function_name: The name of the function/tool to execute
            function_args: The arguments to pass to the function

        Returns:
            tuple: (function_response, instant_response, used_skill, tool_label)
            - function_response (str): Text response for LLM conversation history
            - instant_response (str | None): Immediate audio response to play to user
            - used_skill (Skill | None): The skill that was used, if any
            - tool_label (str | None): Label for benchmark timing, or None for meta-tools
        """
        # Handle unified capability meta-tools (activate_capability, list_active_capabilities)
        if self.capability_registry.is_meta_tool(function_name):
            return await self._execute_capability_meta_tool(
                function_name, function_args
            )

        # Handle legacy meta-tools for backward compatibility
        if self.skill_registry.is_meta_tool(function_name):
            return await self._execute_skill_meta_tool(function_name, function_args)

        # Handle MCP meta-tools for server discovery/activation
        if self.mcp_registry.is_meta_tool(function_name):
            return await self._execute_mcp_meta_tool(function_name, function_args)

        # Handle MCP server tools (prefixed with mcp_)
        if self.mcp_registry.is_mcp_tool(function_name):
            return await self._execute_mcp_tool(function_name, function_args)

        # Handle instant activation commands
        if function_name == "execute_command":
            return await self._execute_instant_command(function_args)

        # Handle skill tools
        if function_name in self.tool_skills:
            return await self._execute_skill_tool(function_name, function_args)

        # Unknown tool
        return f"Unknown tool: {function_name}", None, None, None

    async def execute_batch(
        self, tool_calls
    ) -> tuple[str | None, object | None, list[tuple[str, float]]]:
        """Execute a batch of tool calls.

        Args:
            tool_calls: List of tool call objects with id, function.name, and function.arguments

        Returns:
            tuple: (instant_response, used_skill, tool_timings, results)
            - instant_response (str | None): First instant response encountered (stops batch)
            - used_skill (Skill | None): Last skill that was used
            - tool_timings (list): List of (label, time_ms) tuples for benchmark tracking
            - results (list): List of (tool_call, function_response) tuples
        """
        instant_response = None
        used_skill = None
        tool_timings: list[tuple[str, float]] = []
        results: list[tuple[object, str]] = []

        for tool_call in tool_calls:
            try:
                function_name = tool_call.function.name
                function_args = self._parse_arguments(tool_call.function.arguments)

                # Time the individual tool execution
                tool_start = time.perf_counter()
                (
                    function_response,
                    instant_resp,
                    skill,
                    tool_label,
                ) = await self.execute_tool_call(function_name, function_args)
                tool_time_ms = (time.perf_counter() - tool_start) * 1000

                # Add timing if we got a label (actual tool execution, not meta-tool)
                if tool_label:
                    tool_timings.append((tool_label, tool_time_ms))

                # Update skill tracking
                if skill:
                    used_skill = skill

                # Store result
                results.append((tool_call, function_response))

                # If we got an instant response, store it and stop processing
                if instant_resp:
                    instant_response = instant_resp
                    break

            except Exception as e:
                await printr.print_async(
                    f"Error while processing tool call: {str(e)}", color=LogType.ERROR
                )
                printr.print(
                    traceback.format_exc(), color=LogType.ERROR, server_only=True
                )
                # Store error result
                results.append((tool_call, "Error"))

        return instant_response, used_skill, tool_timings, results

    def _parse_arguments(self, arguments) -> dict:
        """Parse function arguments from either dict or JSON string.

        Args:
            arguments: Either a dict (Mistral) or JSON string (OpenAI)

        Returns:
            dict: Parsed arguments
        """
        if isinstance(arguments, dict):
            return arguments
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            return {}

    async def _execute_capability_meta_tool(
        self, function_name: str, function_args: dict
    ) -> tuple[str, None, None, None]:
        """Execute a unified capability meta-tool (activate_capability, etc.)."""
        function_response, tools_changed = (
            await self.capability_registry.execute_meta_tool(
                function_name, function_args
            )
        )

        # If a skill was activated, perform lazy validation
        if tools_changed and function_name == "activate_capability":
            capability_name = function_args.get("capability_name", "")
            skill = self.skill_registry.get_skill_for_activation(capability_name)
            if skill and skill.needs_activation():
                success, validation_msg = await skill.ensure_activated()
                if not success:
                    # Validation failed - deactivate the skill
                    self.skill_registry.deactivate_skill(capability_name)
                    function_response = validation_msg
                    await printr.print_async(
                        f"Skill activation failed: {capability_name}",
                        color=LogType.ERROR,
                    )
                else:
                    # Get display name for user-friendly message
                    display_name = self.skill_registry.get_skill_display_name(
                        capability_name
                    )
                    await printr.print_async(
                        f"Skill activated: {display_name}",
                        color=LogType.SKILL,
                    )

        return function_response, None, None, None  # Meta-tool, no timing label

    async def _execute_skill_meta_tool(
        self, function_name: str, function_args: dict
    ) -> tuple[str, None, None, None]:
        """Execute a legacy skill meta-tool (activate_skill, etc.) for backward compatibility."""
        function_response, tools_changed = await self.skill_registry.execute_meta_tool(
            function_name, function_args
        )

        # If skill was activated, perform lazy validation
        if tools_changed and function_name == "activate_skill":
            skill_name = function_args.get("skill_name", "")
            skill = self.skill_registry.get_skill_for_activation(skill_name)
            if skill and skill.needs_activation():
                success, validation_msg = await skill.ensure_activated()
                if not success:
                    # Validation failed - deactivate the skill
                    self.skill_registry.deactivate_skill(skill_name)
                    function_response = validation_msg
                    await printr.print_async(
                        f"Skill activation failed: {skill_name}",
                        color=LogType.ERROR,
                    )
                else:
                    # Get display name for user-friendly message
                    display_name = self.skill_registry.get_skill_display_name(
                        skill_name
                    )
                    await printr.print_async(
                        f"Skill activated: {display_name}",
                        color=LogType.SKILL,
                    )

        return function_response, None, None, None  # Meta-tool, no timing label

    async def _execute_mcp_meta_tool(
        self, function_name: str, function_args: dict
    ) -> tuple[str, None, None, None]:
        """Execute an MCP meta-tool (list_mcp_servers, activate_mcp_server, etc.)."""
        function_response, tools_changed = await self.mcp_registry.execute_meta_tool(
            function_name, function_args
        )
        return function_response, None, None, None  # Meta-tool, no timing label

    async def _execute_mcp_tool(
        self, function_name: str, function_args: dict
    ) -> tuple[str, None, None, str]:
        """Execute an MCP server tool."""
        connection = self.mcp_registry.get_connection_for_tool(function_name)
        if not connection:
            return "MCP connection not found", None, None, None

        display_name = connection.config.display_name
        original_name = self.mcp_registry.get_original_tool_name(function_name)
        tool_label = f"🌐 {display_name}: {original_name}"

        benchmark = Benchmark(f"MCP '{connection.config.name}' - {original_name}")

        # Always show simple 'called' message in UI so users know the wingman is working
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
            function_response = await self.mcp_registry.call_tool(
                function_name, function_args
            )
        except Exception as e:
            await printr.print_async(
                f"{display_name}: `{original_name}` failed - {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            function_response = "ERROR DURING MCP TOOL EXECUTION"
        finally:
            # Detailed 'completed' with timing only in terminal/log file (or UI if debug)
            await printr.print_async(
                f"{display_name}: `{original_name}` completed",
                color=LogType.MCP,
                benchmark_result=benchmark.finish(),
                server_only=not self.settings.debug_mode,
            )

        return function_response, None, None, tool_label

    async def _execute_instant_command(
        self, function_args: dict
    ) -> tuple[str, str | None, None, str]:
        """Execute an instant activation command."""
        command = self.get_command(function_args["command_name"])
        function_response = await self._execute_command(command)
        tool_label = f"Command: {function_args.get('command_name', 'execute_command')}"

        instant_response = None
        # If the command has responses, we have to play one of them
        if command and command.responses:
            instant_response = self._select_command_response(command)
            await self.play_to_user(instant_response)

        return function_response, instant_response, None, tool_label

    async def _execute_skill_tool(
        self, function_name: str, function_args: dict
    ) -> tuple[str, str | None, object, str]:
        """Execute a skill tool."""
        skill = self.tool_skills[function_name]
        display_name = self.skill_registry.get_skill_display_name(skill.name)
        tool_label = f"⚡ {display_name}: {function_name}"

        benchmark = Benchmark(f"Skill '{skill.name}' - {function_name}")

        # Always show simple 'called' message in UI so users know the wingman is working
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
            if instant_response:
                await self.play_to_user(instant_response)
        except Exception as e:
            await printr.print_async(
                f"{display_name}: `{function_name}` failed - {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            function_response = "ERROR DURING PROCESSING"
            instant_response = None
        finally:
            await printr.print_async(
                f"{display_name}: `{function_name}` completed",
                color=LogType.SKILL,
                benchmark_result=benchmark.finish(),
                skill_name=skill.name,
                server_only=not self.settings.debug_mode,
            )

        return function_response, instant_response, skill, tool_label
