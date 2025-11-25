from api.interface import WingmanInitializationError
from api.enums import LogType
from skills.skill_base import Skill, tool


class AskPerplexity(Skill):
    """
    A skill that queries the Perplexity API for up-to-date internet information.

    Demonstrates the @tool decorator with wait_response for slow API calls.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.instant_response = False

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        if not self.wingman.perplexity:
            await self.wingman.validate_and_set_perplexity(errors)

        self.instant_response = self.retrieve_custom_property_value(
            "instant_response", errors
        )

        return errors

    @tool(
        name="ask_perplexity",
        description="Expects a question that is answered with up-to-date information from the internet.",
        wait_response=True,
    )
    def ask_perplexity(self, question: str) -> tuple[str, str]:
        """
        Uses the Perplexity API to answer a question.

        Args:
            question: The question to ask Perplexity.

        Returns:
            Tuple of (function_response, instant_response)
        """
        completion = self.wingman.perplexity.ask(
            messages=[{"role": "user", "content": question}],
            model=self.wingman.config.perplexity.conversation_model.value,
        )

        if self.settings.debug_mode:
            self.printr.print(f"Perplexity answer: {completion}", color=LogType.INFO)

        if completion and completion.choices:
            response = completion.choices[0].message.content
            # Return instant_response if configured
            instant = response if self.instant_response else ""
            return response, instant
        else:
            return "Error: Unable to retrieve a response from Perplexity API.", ""
