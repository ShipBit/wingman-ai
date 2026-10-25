"""@tool builds the schema the model sees from the method's docstring.

The summary becomes the tool description, the `Args:` section the parameter
descriptions. Other sections never reach the model.
"""

import asyncio

from skills.skill_base import tool


def _function(method):
    return method._tool_definition.tool_schema["function"]


def test_args_section_describes_the_parameters():
    @tool()
    def set_timer(self, seconds: int, label: str = "Timer", loop: bool = False) -> str:
        """Start a timer.

        Args:
            seconds: How long the timer runs.
            label (str): What the timer is called. Said aloud
                when it rings.

        Returns:
            A confirmation.
        """

    function = _function(set_timer)
    properties = function["parameters"]["properties"]
    assert function["description"] == "Start a timer."
    assert properties["seconds"]["description"] == "How long the timer runs."
    assert properties["label"]["description"] == "What the timer is called. Said aloud when it rings."
    assert properties["loop"]["description"] == "The loop"
    assert function["parameters"]["required"] == ["seconds"]


def test_explicit_description_still_takes_the_args_from_the_docstring():
    @tool(description="Take a screenshot.")
    def take_screenshot(self, reason: str) -> str:
        """
        Args:
            reason: Why the screenshot is taken.
        """

    function = _function(take_screenshot)
    assert function["description"] == "Take a screenshot."
    assert function["parameters"]["properties"]["reason"]["description"] == "Why the screenshot is taken."


def test_a_parameter_the_model_invented_is_dropped_not_fatal():
    @tool()
    async def minecraft(self, action: str = "status") -> str:
        """Do something in the game.

        Args:
            action: What to do.
        """
        return action

    definition = minecraft._tool_definition
    assert asyncio.run(definition.execute({"action": "halt", "details": {}}, object())) == "halt"
    assert asyncio.run(definition.execute({"details": {}}, object())) == "status"
