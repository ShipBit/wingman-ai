import threading
import time
from typing import TYPE_CHECKING
from api.enums import LogType, WingmanInitializationErrorType
from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanInitializationError,
)
from services.printr import Printr
from services.secret_keeper import SecretKeeper

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class Skill:
    """DO NOT cache wingman.config or other wingman properties in your skill! Access them when needed using self.wingman.config.property_name."""

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
        self.secret_keeper.secret_events.subscribe("secrets_saved", self.secret_changed)
        self.name = self.__class__.__name__
        self.printr = Printr()
        self.execution_start: None | float = None
        """Used for benchmarking executon times. The timer is (re-)started whenever the process function starts."""

    async def secret_changed(self, secrets: dict[str, any]):
        """Called when a secret is changed."""
        pass

    async def validate(self) -> list[WingmanInitializationError]:
        """Validates the skill configuration."""
        return []

    async def unload(self) -> None:
        """Unload the skill. Use this hook to clear background tasks, etc."""
        self.secret_keeper.secret_events.unsubscribe(
            "secrets_saved", self.secret_changed
        )

    async def prepare(self) -> None:
        """Prepare the skill. Use this hook to initialize background tasks, etc."""
        pass

    def get_tools(self) -> list[tuple[str, dict]]:
        """Returns a list of tools available in the skill."""
        return []

    async def get_prompt(self) -> str | None:
        """Returns additional context for this skill. Will be injected into the the system prompt. Can be overridden by the skill to add dynamic data to context."""
        return self.config.prompt or None

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        """Execute a tool by name with parameters."""
        pass

    async def on_add_user_message(self, message: str) -> None:
        """Called when a user message is added to the system."""
        pass

    async def on_add_assistant_message(self, message: str, tool_calls: list) -> None:
        """Called when a system message is added to the system."""
        pass

    async def is_summarize_needed(self, tool_name: str) -> bool:
        """Returns whether a tool needs to be summarized."""
        return True

    async def is_waiting_response_needed(self, tool_name: str) -> bool:
        """Returns whether a tool probably takes long and a message should be printet in between."""
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

    async def print_execution_time(self, reset_timer=False):
        """Prints the current time since the execution started (in seconds)."""
        if self.execution_start:
            execution_stop = time.perf_counter()
            elapsed_seconds = execution_stop - self.execution_start
            await self.printr.print_async(
                f"...took {elapsed_seconds:.2f}s", color=LogType.INFO
            )
        if reset_timer:
            self.start_execution_benchmark()

    def start_execution_benchmark(self):
        """Starts the execution benchmark timer."""
        self.execution_start = time.perf_counter()

    def threaded_execution(self, function, *args) -> threading.Thread:
        """Execute a function in a separate thread."""
        pass
