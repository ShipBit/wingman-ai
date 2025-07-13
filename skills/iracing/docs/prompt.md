# Task: iRacing Skill Development

You are an expert Python and AI developer with extensive experience in creating skills for the Wingman AI platform. Your task is to develop a skill for the iRacing simulator that allows users to interact with the game through natural language commands.
You are also an expert racing driver and PC gamer, so you understand the context and requirements of the iRacing simulator and how players typically interact with it.

The skill will utilize the `pyirsdk` library, which provides an interface to interact with iRacing's live telemetry and session data.

## irsdk Documentation

You find the official documentation for the irsdk library in `/skills/iracing/docs/docs.md`. Use this documentation to understand how to use the library effectively.

The implementation of the irsdk library is in `/skills/iracing/docs/irsdk.py`. Never change this file, it is just a reference for you to understand how the library works.

Finally, `skills/iracing/vars.txt` contains a list of available variables that can be used in the skill, along with their descriptions.

## Wingman AI Skills

The skill will be implemented as a Wingman AI Skill, which allows users to interact with the iRacing simulator through natural language commands. A minimal Skill derives from the `Skill` class defined in `/skills/skill_base.py` and should implement at least the constructor and the `validate` function.

Skills are configured with a `default_config.yaml` file, which contains the necessary settings for the skill to function properly. It also defines "user variables" that Wingman AI users can later customize in the Wingman AI app.

A typical skill implements the `get_tools` function which returns a list of function definitons in OpenAI format. These functions are AI tools fd to a LLM and used to interact with the iRacing simulator, such as retrieving telemetry data or controlling sessions. The AI will later decide if and when to call these tools based on user input.

A skeleton for the iRacing skill would look like this and is already provided in the `skills/iracing/main.py` file:

```py
from typing import TYPE_CHECKING, Any, Dict, Tuple
from api.enums import LogType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from services.benchmark import Benchmark
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class IRacing(Skill):
    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        return errors

    def get_tools(self) -> list[Tuple[str, Dict[str, Any]]]:
        return []


async def execute_tool(
    self, tool_name: str, parameters: dict[str, any], benchmark: Benchmark
) -> tuple[str, str]:
    instant_response = ""  # not used here
    function_response = "Unable to execute iRacing tool."

    if tool_name in []:
        benchmark.start_snapshot(f"iRacing: {tool_name}")

        if self.settings.debug_mode:
            message = f"iRacing: executing tool '{tool_name}'"
            if parameters:
                message += f" with params: {parameters}"
            await self.printr.print_async(text=message, color=LogType.INFO)

        action = parameters.get("action", None)
        parameters.pop("action", None)
        function = getattr(self, action if action else tool_name)
        function_response = function(**parameters)

        benchmark.finish_snapshot()

    return function_response, instant_response

```

## The actual iRacing Skill

Players will use the iRacing skill ingame to interact with the simulator, such as retrieving telemetry data, controlling sessions, or getting information. The "Wingman" is their AI assistant that will help them with these tasks. This Wingman has access to the iRacing skill and can call its tools based on user input.

You will implement the iRacing skill in the `skills/iracing/main.py` file. This file already contains a skeleton for the skill, including the constructor and the `validate` function. You will need to implement the `get_tools` function to return a list of tools that the AI can use to interact with iRacing.

As expert driver and gamer, you will decide which telemetry data and session controls are most useful for players. You will also implement the `execute_tool` function to handle the execution of these tools based on user input.

You will also implement a "watchdog" that monitors the iRacing session and updates the telemetry data in real-time. This will allow the AI to provide up-to-date information to the player. We already have a similar skill for American Truck Simulator in `/skills/ats_telemetry/main.py`, which you can use as a reference for implementing the watchdog functionality. Don't copy the code or coding style, but use it as a reference to understand how to implement the watchdog for iRacing. A good example for a well structured skill and implementation of the `execute_tool` function is the Spotify skill in `/skills/spotify/main.py`. You can use this as a reference for implementing the iRacing skill.

In the first phase, read all the information I have provided you and understand the requirements. Do not implement any code yet. Once you have a clear understanding of the task, plan out which telemetry data and tools you want to implement in the iRacing skill. Consider what would be most useful for players and how they typically interact with the simulator.

Create this plan now.
