import asyncio
import inspect
import threading
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Literal,
    Optional,
    Union,
    get_type_hints,
    get_origin,
    get_args,
)
import warnings
from api.enums import LogType, WingmanInitializationErrorType
from api.interface import (
    SettingsConfig,
    SkillConfig,
    SoundConfig,
    WingmanInitializationError,
)
from services.benchmark import Benchmark
from services.printr import Printr
from services.secret_keeper import SecretKeeper

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


# Type mapping from Python types to JSON Schema types
_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    type(None): "null",
}


def _python_type_to_json_schema(py_type: Any) -> dict:
    """
    Convert a Python type annotation to a JSON Schema type definition.
    Inspired by FastMCP's func_metadata.py approach.
    """
    # Handle None
    if py_type is None or py_type is type(None):
        return {"type": "null"}

    # Handle basic types
    if py_type in _TYPE_MAP:
        return {"type": _TYPE_MAP[py_type]}

    # Handle Optional[X] which is Union[X, None]
    origin = get_origin(py_type)
    args = get_args(py_type)

    # Handle Literal types for static enums
    if origin is Literal:
        # Get all literal values
        literal_values = list(args)
        # Determine the type from the first value
        if literal_values:
            first_val = literal_values[0]
            if isinstance(first_val, str):
                return {"type": "string", "enum": literal_values}
            elif isinstance(first_val, int):
                return {"type": "integer", "enum": literal_values}
            elif isinstance(first_val, float):
                return {"type": "number", "enum": literal_values}
        return {"type": "string", "enum": literal_values}

    if origin is Union:
        # Filter out None from union
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1:
            # This is Optional[X]
            return _python_type_to_json_schema(non_none_args[0])
        else:
            # This is a real union
            return {"anyOf": [_python_type_to_json_schema(a) for a in args]}

    # Handle List[X]
    if origin is list:
        if args:
            return {"type": "array", "items": _python_type_to_json_schema(args[0])}
        return {"type": "array"}

    # Handle Dict[K, V]
    if origin is dict:
        return {"type": "object"}

    # Fallback for unknown types
    return {"type": "string"}


def _generate_tool_schema(
    func: Callable,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> tuple[str, dict]:
    """
    Generate an OpenAI-compatible tool schema from a function's signature and type hints.

    This implements the same pattern as FastMCP's Tool.from_function(), automatically
    generating inputSchema from the function signature.

    Args:
        func: The function to generate a schema for
        name: Override the function name
        description: Override the docstring description

    Returns:
        Tuple of (tool_name, tool_definition_dict)
    """
    tool_name = name or func.__name__
    tool_description = description or func.__doc__ or f"Execute {tool_name}"

    # Clean up multiline docstrings
    if tool_description:
        tool_description = " ".join(tool_description.split())

    # Get function signature and type hints
    sig = inspect.signature(func)
    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {}

    # Build parameters schema
    properties = {}
    required = []

    for param_name, param in sig.parameters.items():
        # Skip self, cls, and special parameters
        if param_name in ("self", "cls", "benchmark", "kwargs"):
            continue

        # Get type from hints or default to string
        param_type = hints.get(param_name, str)
        param_schema = _python_type_to_json_schema(param_type)

        # Add description from default if it's annotated (future enhancement)
        # For now, use parameter name as hint
        param_schema["description"] = f"The {param_name.replace('_', ' ')}"

        properties[param_name] = param_schema

        # Required if no default value
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    # Build the tool definition in OpenAI format
    tool_def = {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": tool_description,
            "parameters": {
                "type": "object",
                "properties": properties,
            },
        },
    }

    if required:
        tool_def["function"]["parameters"]["required"] = required

    return tool_name, tool_def


class ToolDefinition:
    """
    Stores metadata about a tool registered via @tool decorator.
    """

    def __init__(
        self,
        func: Callable,
        name: Optional[str] = None,
        description: Optional[str] = None,
        summarize: bool = True,
        wait_response: bool = False,
    ):
        self.func = func
        self.name = name or func.__name__
        self.description = description
        self.summarize = summarize
        self.wait_response = wait_response
        self.is_async = asyncio.iscoroutinefunction(func)

        # Generate the schema
        self.tool_name, self.tool_schema = _generate_tool_schema(
            func, name=self.name, description=self.description
        )

    async def execute(self, parameters: dict[str, Any], skill_instance: "Skill") -> Any:
        """Execute the tool function with the given parameters."""
        # Bind self if this is an instance method
        if self.is_async:
            return await self.func(skill_instance, **parameters)
        else:
            return self.func(skill_instance, **parameters)


def tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    summarize: bool = True,
    wait_response: bool = False,
):
    """
    Decorator to register a method as a tool in a Skill.

    Inspired by FastMCP's @mcp.tool() decorator, this automatically generates
    the OpenAI tool schema from the function signature and type hints.

    **This is the PREFERRED way to define tools in new skills.**

    **Auto-Generation:**
    - Tool name: Method name (or override with `name` parameter)
    - Parameter types: From type hints (required: no default, optional: has default)
    - Parameter descriptions: From docstring Args section or auto-generated
    - Tool description: From method docstring (or override with `description` parameter)

    **Requirements:**
    - Method must have type hints for all parameters (except self)
    - Method should return a string (the result shown to the LLM)
    - For async operations, use async def

    **Note:** Don't mix this decorator with legacy get_tools() override in the same skill.

    Args:
        name: Override the tool name (defaults to function name)
        description: Override the description (defaults to docstring)
        summarize: Whether the LLM should summarize after this tool (default True)
        wait_response: Whether to show a "please wait" message (default False)

    Example:
        class MySkill(Skill):
            @tool()
            def get_weather(self, city: str, units: str = "celsius") -> str:
                '''Get the current weather for a city.'''
                return f"Weather in {city}: 22°{units[0].upper()}"

            @tool(name="add_numbers", description="Add two numbers together")
            def add(self, a: int, b: int) -> int:
                return a + b
    """

    def decorator(func: Callable) -> Callable:
        # Store tool metadata on the function
        func._tool_definition = ToolDefinition(
            func=func,
            name=name,
            description=description,
            summarize=summarize,
            wait_response=wait_response,
        )
        return func

    return decorator


class Skill:
    """
    Base class for all Wingman AI skills.

    DO NOT cache wingman.config or other wingman properties in your skill!
    Access them when needed using self.wingman.config.property_name.

    Tool Registration:
        Skills can define tools in two ways:

        1. Legacy pattern (override get_tools and execute_tool):
            def get_tools(self) -> list[tuple[str, dict]]:
                return [("my_tool", {...schema...})]

            async def execute_tool(self, tool_name, parameters, benchmark):
                if tool_name == "my_tool":
                    return "result", ""

        2. New decorator pattern (recommended):
            @tool()
            def my_tool(self, param: str) -> str:
                '''Tool description from docstring.'''
                return "result"

            The schema is auto-generated from type hints!
    """

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        self.config = config
        self.settings = settings
        self.wingman = wingman

        self.secret_keeper = SecretKeeper()
        # Note: secret_events subscription moved to prepare() to avoid listener accumulation
        self.name = self.__class__.__name__
        self.printr = Printr()
        self.execution_start: None | float = None
        """Used for benchmarking executon times. The timer is (re-)started whenever the process function starts."""

        # Lazy validation state
        self.is_validated: bool = False
        """Whether validate() has been called and passed."""
        self.validation_errors: list[WingmanInitializationError] = []
        """Cached validation errors if validation failed."""
        self.is_prepared: bool = False
        """Whether prepare() has been called."""
        self.is_unloaded: bool = False
        """Whether unload() has been called. Check this in __del__ before calling unload()."""

        # Collect @tool decorated methods
        self._decorated_tools: dict[str, ToolDefinition] = {}
        self._collect_decorated_tools()

    def needs_activation(self) -> bool:
        """Check if this skill still needs validation and preparation.

        Returns True when:
        - Skill is first loaded (initial state)
        - After update_config() is called (validation reset)
        - If validation or preparation previously failed

        Returns False only when both validation and preparation have completed successfully.
        """
        return not self.is_validated or not self.is_prepared

    async def update_config(self, new_config: SkillConfig) -> None:
        """Update the skill's configuration at runtime.

        Called when the user changes skill settings at runtime (e.g., custom properties).
        By default, this updates self.config and invalidates validation state so the skill
        will be revalidated on next use.

        **Important:** Skills should NOT cache config values. Instead, retrieve properties
        just-in-time when needed. This ensures runtime changes take effect immediately.
        See the validate() method documentation for the recommended pattern.

        Args:
            new_config: The updated SkillConfig with new custom_properties or prompt.
        """
        old_config = self.config
        self.config = new_config

        # Check if custom_properties actually changed (not just the same object)
        old_props = {p.id: p.value for p in (old_config.custom_properties or [])}
        new_props = {p.id: p.value for p in (new_config.custom_properties or [])}

        if old_props != new_props:
            # Custom properties changed - invalidate validation so skill re-reads config
            self.is_validated = False
            self.printr.print(
                f"Skill '{self.config.display_name}' config updated, will revalidate on next use.",
                color=LogType.INFO,
                server_only=True,
            )

    async def secret_changed(self, secrets: dict[str, any]):
        """Called when a secret is changed."""
        pass

    def _collect_decorated_tools(self) -> None:
        """
        Collect all methods decorated with @tool and register them.
        Called during __init__ to auto-discover tools.
        """
        for attr_name in dir(self):
            if attr_name.startswith("_"):
                continue
            try:
                attr = getattr(self, attr_name, None)
                if attr is None:
                    continue
                # Get the underlying function (unwrap bound method)
                func = getattr(attr, "__func__", attr)
                if hasattr(func, "_tool_definition"):
                    tool_def: ToolDefinition = func._tool_definition
                    self._decorated_tools[tool_def.tool_name] = tool_def
            except Exception:
                # Skip attributes that can't be inspected
                pass

    async def validate(self) -> list[WingmanInitializationError]:
        """
        Validates the skill configuration at startup and reload.

        This method should:
        1. Call retrieve_custom_property_value() for all custom properties to validate they exist
           and are properly configured. This reports errors for missing or invalid properties.
        2. Perform any initialization that requires the properties (e.g., provider setup).
        3. NOT cache property values in instance variables for runtime use.

        Property values should be retrieved fresh at runtime using helper methods that call
        retrieve_custom_property_value() just-in-time. This ensures changes made in the UI
        are immediately reflected without requiring skill reactivation.

        Example pattern:
            async def validate(self):
                errors = await super().validate()
                # Validate properties exist (don't cache)
                self.retrieve_custom_property_value("audio_config", errors)
                self.retrieve_custom_property_value("volume", errors)
                return errors

            def _get_audio_config(self):
                # Retrieve fresh at runtime
                errors = []
                return self.retrieve_custom_property_value("audio_config", errors)

        Returns:
            List of initialization errors found during validation.
        """
        return []

    async def ensure_activated(self) -> tuple[bool, str]:
        """
        Ensure the skill is validated and prepared for use.
        Called lazily on first activation via SkillRegistry.

        Returns:
            (success, message) tuple
        """
        import asyncio

        # Already validated and prepared?
        if self.is_validated and self.is_prepared:
            return True, f"Skill '{self.config.display_name}' is ready."

        # Run validation if not done yet
        if not self.is_validated:
            self.validation_errors = await self.validate()

            # Handle missing secrets with retry
            if any(e.error_type == "missing_secret" for e in self.validation_errors):
                for _attempt in range(2):
                    await asyncio.sleep(5)
                    self.validation_errors = await self.validate()
                    if not self.validation_errors:
                        break

            if self.validation_errors:
                error_msgs = "; ".join(e.message for e in self.validation_errors)
                return (
                    False,
                    f"Skill '{self.config.display_name}' validation failed: {error_msgs}",
                )

            self.is_validated = True

        # Run prepare if not done yet
        if not self.is_prepared:
            await self.prepare()
            self.is_prepared = True
            self.printr.print(
                f"Skill '{self.config.name}' validated and prepared.",
                color=LogType.POSITIVE,
                server_only=True,
            )

        return True, f"Skill '{self.config.display_name}' activated successfully."

    async def unload(self) -> None:
        """Unload the skill. Use this hook to clear background tasks, etc.

        This is always called when a skill is removed, regardless of whether
        prepare() was ever called. Safe to call multiple times.

        Custom skills with __del__ should check self.is_unloaded before calling unload():
            def __del__(self):
                if not self.is_unloaded:
                    # handle cleanup synchronously, don't use asyncio.run()
        """
        if self.is_unloaded:
            return  # Already unloaded, skip

        self.is_unloaded = True

        # Safely unsubscribe - the handler may not be subscribed if prepare() was never called
        try:
            self.secret_keeper.secret_events.unsubscribe(
                "secrets_saved", self.secret_changed
            )
        except ValueError:
            # Handler wasn't subscribed, that's fine
            pass

    async def prepare(self) -> None:
        """Prepare the skill. Use this hook to initialize background tasks, etc.

        Called once when the skill is first activated (lazy initialization).
        Subscribe to events here, not in __init__.
        """
        # Subscribe to secret changes - will be unsubscribed in unload()
        self.secret_keeper.secret_events.subscribe("secrets_saved", self.secret_changed)

    def get_tools(self) -> list[tuple[str, dict]]:
        """
        Returns a list of tools available in the skill.

        .. deprecated::
            Use the @tool decorator instead. This method is maintained for backward
            compatibility with existing skills but will be removed in a future version.

        **For new skills:** Use the @tool decorator instead of overriding this method.
        The @tool decorator provides automatic schema generation and cleaner code.

        **Legacy pattern (for compatibility only):**
        Override this method to manually provide tools. By default, returns tools from
        @tool decorated methods.

        **Migration guidance:**
        - New skills: Use @tool decorator exclusively, don't override this method
        - Existing skills: Can continue using this pattern or migrate to @tool decorator
        - Mixed approach: NOT recommended - choose one pattern per skill

        Returns:
            List of (tool_name, tool_definition) tuples
        """
        # Only warn if get_tools is overridden in a subclass
        if type(self).get_tools is not Skill.get_tools:
            warnings.warn(
                "get_tools() is deprecated. Use the @tool decorator instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        # Return tools from @tool decorated methods
        tools = []
        for tool_def in self._decorated_tools.values():
            tools.append((tool_def.tool_name, tool_def.tool_schema))
        return tools

    def get_tools_description(self) -> str:
        """
        Auto-generate a prompt section describing all tools in this skill.

        This is used for progressive disclosure - the ToolRegistry includes
        these descriptions in skill manifests so the LLM can search for
        relevant skills without loading all tool definitions upfront.

        Returns:
            A formatted string listing all tools and their descriptions.
        """
        tools = self.get_tools()
        if not tools:
            return ""

        lines = []
        for tool_name, tool_def in tools:
            # Extract description from tool definition
            if isinstance(tool_def, dict):
                func_def = tool_def.get("function", tool_def)
                desc = func_def.get("description", "No description")
                # Use first line only for brevity
                desc = desc.split("\n")[0].strip()
                lines.append(f"- {tool_name}: {desc}")
            else:
                lines.append(f"- {tool_name}: No description")

        return "\n".join(lines)

    async def get_prompt(self) -> str | None:
        """
        Returns additional context for this skill.

        By default, returns the config.prompt if set. Skills with @tool decorated
        methods will have their tool descriptions auto-generated by the ToolRegistry
        for progressive disclosure, so explicit prompts are optional.

        Override this method to add dynamic data to context.
        """
        return self.config.prompt or None

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any], benchmark: Benchmark
    ) -> tuple[str, str]:
        """
        Execute a tool by name with parameters.

        By default, handles tools registered via @tool decorator.
        Override this method for the legacy pattern or to add custom logic.

        Args:
            tool_name: Name of the tool to execute
            parameters: Dictionary of parameters passed by the LLM
            benchmark: Benchmark instance for timing

        Returns:
            Tuple of (function_response, instant_response)
            - function_response: Text result to return to the LLM
            - instant_response: Optional text to speak immediately
        """
        # Check if this is a @tool decorated method
        if tool_name in self._decorated_tools:
            tool_def = self._decorated_tools[tool_name]
            benchmark.start_snapshot(f"{self.name}: {tool_name}")

            try:
                result = await tool_def.execute(parameters, self)

                # Support tuple returns for (function_response, instant_response)
                if isinstance(result, tuple) and len(result) == 2:
                    func_response, instant_response = result
                    if func_response is None:
                        func_response = ""
                    elif not isinstance(func_response, str):
                        func_response = str(func_response)
                    if instant_response is None:
                        instant_response = ""
                    elif not isinstance(instant_response, str):
                        instant_response = str(instant_response)
                    return func_response, instant_response

                # Convert single result to string
                if result is None:
                    result = ""
                elif not isinstance(result, str):
                    result = str(result)

                return result, ""
            finally:
                benchmark.finish_snapshot()

        # No matching tool found
        return "", ""

    async def on_add_user_message(self, message: str) -> None:
        """Called when a user message is added to the system."""
        pass

    async def on_add_assistant_message(self, message: str, tool_calls: list) -> None:
        """Called when a system message is added to the system."""
        pass

    async def on_play_to_user(self, text: str, sound_config: SoundConfig) -> str:
        """Called before the text is synthetized to speech by the TTS provider.
        You can modify the text if needed. Add {SKIP-TTS} to the text to to skip playback.
        """
        return text

    async def is_summarize_needed(self, tool_name: str) -> bool:
        """Returns whether a tool needs to be summarized."""
        # Check @tool decorator setting
        if tool_name in self._decorated_tools:
            return self._decorated_tools[tool_name].summarize
        return True

    async def is_waiting_response_needed(self, tool_name: str) -> bool:
        """Returns whether a tool probably takes long and a message should be printed in between."""
        # Check @tool decorator setting
        if tool_name in self._decorated_tools:
            return self._decorated_tools[tool_name].wait_response
        return False

    async def llm_call(self, messages, tools: list[dict] = None) -> any:
        return any

    async def retrieve_secret(
        self,
        secret_name: str,
        errors: list[WingmanInitializationError],
        hint: str = None,
    ):
        """Use this method to retrieve secrets like API keys from the SecretKeeper.
        If the key is missing, the user will be prompted to enter it.
        """
        secret = await self.secret_keeper.retrieve(
            requester=self.name,
            key=secret_name,
            prompt_if_missing=True,
        )
        if not secret:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.name,
                    message=f"Missing secret '{secret_name}'. {hint or ''}",
                    error_type=WingmanInitializationErrorType.MISSING_SECRET,
                    secret_name=secret_name,
                )
            )
        return secret

    def retrieve_custom_property_value(
        self,
        property_id: str,
        errors: list[WingmanInitializationError],
        hint: str = None,
    ):
        """Use this method to retrieve custom properties from the Skill config."""
        p = next(
            (prop for prop in self.config.custom_properties if prop.id == property_id),
            None,
        )
        if p is None or (p.required and p.value is None):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.name,
                    message=f"Missing custom property '{property_id}'. {hint}",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
            return None
        return p.value

    def threaded_execution(self, function, *args) -> threading.Thread:
        """Execute a function in a separate thread."""
        pass

    def get_generated_files_dir(self) -> str:
        """Get the path to this skill's generated files directory.

        Returns the absolute path to a directory where this skill can store generated files.
        The directory is automatically created if it doesn't exist and persists across
        Wingman AI updates (not versioned).

        Example paths:
        - macOS: /Users/username/Library/Application Support/WingmanAI/generated_files/AutoScreenshot
        - Windows: C:\\Users\\username\\AppData\\Roaming\\ShipBit\\WingmanAI\\generated_files\\AutoScreenshot

        Returns:
            The absolute path to this skill's generated files directory
        """
        from services.file import get_generated_files_dir

        return get_generated_files_dir(self.name)
