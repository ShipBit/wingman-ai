from api.enums import WingmanInitializationErrorType
from api.interface import SkillConfig, WingmanInitializationError
from services.printr import Printr
from services.secret_keeper import SecretKeeper


class Skill:
    def __init__(self, config: SkillConfig) -> None:

        self.config = config
        self.secret_keeper = SecretKeeper()
        self.name = self.__class__.__name__
        self.printr = Printr()

    async def validate(self) -> list[WingmanInitializationError]:
        """Validate the skill configuration."""
        return []

    def get_tools(self) -> list[tuple[str, dict]]:
        """Return a list of tools available in the skill."""
        return []

    async def get_additional_context(self) -> str | None:
        """Return additional context. Can be overridden by the skill to add dynamic data to context."""
        return self.config.additional_context or None

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        """Execute a tool by name with parameters."""

    async def gpt_call(self, messages, tools: list[dict] = None) -> any:
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
                    message=f"Missing secret '{secret_name}'. {hint}",
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
        if not p or (p.required and not p.value):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.name,
                    message=f"Missing custom property '{property_id}'. {hint}",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
            return None
        return p.value
