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


def _run(method, arguments):
    return asyncio.run(method._tool_definition.execute(arguments, object()))


def test_a_wrong_argument_name_is_answered_not_raised():
    # Seen in the wild: the model called open_folder with `folder_path`, the
    # parameter name of a sibling tool. Python raised a TypeError, the call
    # failed with "ERROR DURING PROCESSING", and the model never learned why.
    @tool()
    async def open_folder(self, folder_name: str, directory_path: str = None) -> str:
        return f"opened {folder_name}"

    answer = _run(open_folder, {"folder_path": "C:\\Games", "folder_name": "Zoe"})

    assert "folder_path" in answer
    assert "folder_name" in answer and "directory_path" in answer


def test_a_missing_argument_is_answered_not_raised():
    @tool()
    async def open_folder(self, folder_name: str, directory_path: str = None) -> str:
        return f"opened {folder_name}"

    answer = _run(open_folder, {"directory_path": "C:\\"})

    assert "folder_name" in answer


def test_correct_arguments_still_reach_the_tool():
    @tool()
    async def open_folder(self, folder_name: str, directory_path: str = None) -> str:
        return f"opened {folder_name}"

    assert _run(open_folder, {"folder_name": "Zoe"}) == "opened Zoe"


def test_a_tool_taking_kwargs_accepts_any_argument():
    @tool()
    async def anything(self, **kwargs) -> str:
        return ",".join(sorted(kwargs))

    assert _run(anything, {"a": 1, "b": 2}) == "a,b"
