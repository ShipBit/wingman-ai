from api.interface import (
    WingmanInitializationError,
)
from services.benchmark import Benchmark
from skills.skill_base import Skill


class AskPerplexity(Skill):

    def __init__(
        self,
        *args,
        **kwargs,
    ) -> None:
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

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "ask_perplexity",
                {
                    "type": "function",
                    "function": {
                        "name": "ask_perplexity",
                        "description": "Expects a question that is answered with up-to-date information from the internet.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "question": {"type": "string"},
                            },
                            "required": ["question"],
                        },
                    },
                },
            ),
        ]
        return tools

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any], benchmark: Benchmark
    ) -> tuple[str, str]:
        function_response = ""
        instant_response = ""

        if tool_name in ["ask_perplexity"]:
            if tool_name == "ask_perplexity" and "question" in parameters:
                benchmark.start_snapshot("Ask Perplexity")
                function_response = self.ask_perplexity(parameters["question"])
                if self.instant_response:
                    instant_response = function_response
                benchmark.finish_snapshot()

            if self.settings.debug_mode:
                await self.printr.print_async(f"Perplexity answer: {function_response}")

        return function_response, instant_response

    def ask_perplexity(self, question: str) -> str:
        """Uses the Perplexity API to answer a question."""

        completion = self.wingman.perplexity.ask(
            messages=[{"role": "user", "content": question}],
            model=self.wingman.config.perplexity.conversation_model.value,
        )

        if completion and completion.choices:
            return completion.choices[0].message.content
        else:
            return "Error: Unable to retrieve a response from Perplexity API."
