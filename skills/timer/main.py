import random
import string
import asyncio
import threading
import time
from typing import TYPE_CHECKING
from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.wingman import Wingman

class Timer(Skill):

    def __init__(
        self,
        config: SkillConfig,
        wingman_config: WingmanConfig,
        settings: SettingsConfig,
        wingman: "Wingman",
    ) -> None:

        self.timers = {}
        self.wingman = wingman

        super().__init__(
            config=config, wingman_config=wingman_config, settings=settings, wingman=wingman
        )

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        return errors

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "set_timer",
                {
                    "type": "function",
                    "function": {
                        "name": "set_timer",
                        "description": "set_timer function to delay other available functions.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "delay": {
                                    "type": "number",
                                    "description": "The delay/timer in seconds.",
                                },
                                "function": {
                                    "type": "string",
                                    "description": "The name of the function to execute after the delay. Must be a function name from the available tools.",
                                },
                                "parameters": {
                                    "type": "object",
                                    "description": "The parameters for the function to execute after the delay. Must be a valid object with the required properties to their values. Can not be empty.",
                                },
                            },
                            "required": ["detlay", "function", "parameters"],
                        },
                    },
                }
            ),
            (
                "get_timer_status",
                {
                    "type": "function",
                    "function": {
                        "name": "get_timer_status",
                        "description": "Get a list of all running timers and their remaining time and id.",
                    },
                }
            ),
            (
                "cancel_timer",
                {
                    "type": "function",
                    "function": {
                        "name": "cancel_timer",
                        "description": "Cancel a running timer by its id.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": "The id of the timer to cancel.",
                                },
                            },
                            "required": ["id"],
                        },
                    },
                }
            ),
            (
                "remind_me",
                {
                    "type": "function",
                    "function": {
                        "name": "remind_me",
                        "description": "Say something to the user. Should only be used, when delay is requested. Like setting a reminder.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "message": {
                                    "type": "string",
                                    "description": "The message to say to the user. Must be given as a string.",
                                },
                            },
                            "required": ["message"],
                        },
                    },
                }
            ),

        ]
        return tools

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        function_response = ""
        instant_response = ""

        if tool_name in ["set_timer", "get_timer_status", "cancel_timer", "remind_me"]:
            if self.settings.debug_mode:
                self.start_execution_benchmark()

            if tool_name == "set_timer":
                function_response = await self.set_timer(
                    delay=parameters.get("delay", None),
                    function=parameters.get("function", None),
                    parameters=parameters.get("parameters", {}),
                )
            elif tool_name == "get_timer_status":
                function_response = await self.get_timer_status()
            elif tool_name == "cancel_timer":
                function_response = await self.cancel_timer(timer_id=parameters.get("id", None))
            elif tool_name == "remind_me":
                function_response = await self.reminder(message=parameters.get("message", None))

            if self.settings.debug_mode:
                await self.print_execution_time()

        return function_response, instant_response

    async def set_timer(self, delay: int = None, function: str = None, parameters: dict[str, any] = None) -> str:
        if delay is None or function is None:
            return "No timer set, missing delay or function."

        if delay < 0:
            return "No timer set, delay must be greater than 0."
        
        if "." in function:
            function = function.split(".")[1]

        # generate a unique id for the timer
        letters_and_digits = string.ascii_letters + string.digits
        timer_id = ''.join(random.choice(letters_and_digits) for _ in range(10))

        # set timer
        current_time = time.time()
        self.timers[timer_id] = [delay, function, parameters, current_time]

        # time execution
        def timed_execution(timer_id: str):
            async def execute_timer(timer_id: str) -> None:
                if timer_id not in self.timers:
                    print(f"Timer with id {timer_id} not found.")
                    return
                timer = self.timers[timer_id]
                delay = timer[0]
                function = timer[1]
                parameters = timer[2]

                await asyncio.sleep(delay)

                if timer_id not in self.timers:
                    print(f"Timer with id {timer_id} not found.")
                    return

                print(f"Executing timer with id {timer_id}: {function} with parameters {parameters}.")
                await self.wingman.execute_command_by_function_call(function, parameters)
                del self.timers[timer_id]

            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            new_loop.run_until_complete(execute_timer(timer_id))
            new_loop.close()
        threading.Thread(target=timed_execution, args=(timer_id,)).start()

        print(f"Setting timer for {delay} seconds.")
        print(f"Function to execute: {function}")
        print(f"Parameters: {parameters}")

        return "Timer set with id {timer_id}."

    async def get_timer_status(self) -> list[dict[str, any]]:
        timers = []
        for timer_id, timer in self.timers.items():
            timers.append(
                {
                    "id": timer_id,
                    "delay": timer[0],
                    "remaining_time_in_seconds": max(0, timer[0] - (time.time() - timer[3])),
                }
            )
        print(f"Running timers: {timers}")
        return timers

    async def cancel_timer(self, timer_id: str) -> str:
        if timer_id not in self.timers:
            return f"Timer with id {timer_id} not found."
        del self.timers[timer_id]
        print(f"Timer with id {timer_id} cancelled.")
        return f"Timer with id {timer_id} cancelled."

    async def reminder(self, message: str = None) -> str:
        if not message:
            return "No reminder content set."
        print("Reminder played to user.")
        await self.wingman.play_to_user(message, True)
        return "Reminder played to user."
