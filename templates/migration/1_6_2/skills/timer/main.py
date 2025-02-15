import random
import string
import asyncio
import time
import json
from typing import TYPE_CHECKING
from api.interface import SettingsConfig, SkillConfig
from api.enums import (
    LogSource,
    LogType,
)
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class Timer(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        self.timers = {}
        self.available_tools = []
        self.active = False

    async def prepare(self) -> None:
        self.active = True
        self.threaded_execution(self.start_timer_worker)

    async def unload(self) -> None:
        self.active = False

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
                                "is_loop": {
                                    "type": "boolean",
                                    "description": "If the timer should loop or not.",
                                },
                                "loops": {
                                    "type": "number",
                                    "description": "The amount of loops the timer should do. -1 for infinite loops.",
                                },
                                "function": {
                                    "type": "string",
                                    # "enum": self._get_available_tools(), # end up beeing a recursive nightmare
                                    "description": "The name of the function to execute after the delay. Must be a function name from the available tools.",
                                },
                                "parameters": {
                                    "type": "object",
                                    "description": "The parameters for the function to execute after the delay. Must be a valid object with the required properties to their values. Can not be empty.",
                                },
                            },
                            "required": ["delay", "function", "parameters"],
                            "optional": ["is_loop", "loops"],
                        },
                    },
                },
            ),
            (
                "get_timer_status",
                {
                    "type": "function",
                    "function": {
                        "name": "get_timer_status",
                        "description": "Get a list of all running timers and their remaining time and id.",
                    },
                },
            ),
            (
                "cancel_timer",
                {
                    "type": "function",
                    "function": {
                        "name": "cancel_timer",
                        "description": "Cancel a running timer by its id. Use this in combination with set_timer to change timers.",
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
                },
            ),
            (
                "change_timer_settings",
                {
                    "type": "function",
                    "function": {
                        "name": "change_timer_settings",
                        "description": "Change a timers loop and delay settings. Requires the id of the timer to change.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": "The id of the timer to change.",
                                },
                                "delay": {
                                    "type": "number",
                                    "description": "The new delay/timer in seconds.",
                                },
                                "is_loop": {
                                    "type": "boolean",
                                    "description": "If the timer should loop or not.",
                                },
                                "loops": {
                                    "type": "number",
                                    "description": "The amount of remaining loops the timer should do. -1 for infinite loops.",
                                },
                            },
                            "required": ["id", "delay", "is_loop", "loops"],
                        },
                    },
                },
            ),
            (
                "remind_me",
                {
                    "type": "function",
                    "function": {
                        "name": "remind_me",
                        "description": "Must only be called with the set_timer function. Will remind the user with the given message.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "message": {
                                    "type": "string",
                                    "description": 'The message of the reminder to say to the user. For example User: "Remind me to take a break." -> Message: "This is your reminder to take a break."',
                                },
                            },
                            "required": ["message"],
                        },
                    },
                },
            ),
        ]
        return tools

    async def is_waiting_response_needed(self, tool_name: str) -> bool:
        return tool_name in ["set_timer"]

    def _get_available_tools(self) -> list[dict[str, any]]:
        tools = self.wingman.build_tools()
        tool_names = []
        for tool in tools:
            name = tool.get("function", {}).get("name", None)
            if name:
                tool_names.append(name)

        return tool_names

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        function_response = ""
        instant_response = ""

        if tool_name in [
            "set_timer",
            "get_timer_status",
            "cancel_timer",
            "change_timer_settings",
            "remind_me",
        ]:
            if self.settings.debug_mode:
                self.start_execution_benchmark()

            if tool_name == "set_timer":
                function_response = await self.set_timer(
                    delay=parameters.get("delay", None),
                    is_loop=parameters.get("is_loop", False),
                    loops=parameters.get("loops", 1),
                    function=parameters.get("function", None),
                    parameters=parameters.get("parameters", {}),
                )
            elif tool_name == "get_timer_status":
                function_response = await self.get_timer_status()
            elif tool_name == "cancel_timer":
                function_response = await self.cancel_timer(
                    timer_id=parameters.get("id", None)
                )
            elif tool_name == "change_timer_settings":
                function_response = await self.change_timer_settings(
                    timer_id=parameters.get("id", None),
                    delay=parameters.get("delay", None),
                    is_loop=parameters.get("is_loop", False),
                    loops=parameters.get("loops", 1),
                )
            elif tool_name == "remind_me":
                function_response = await self.reminder(
                    message=parameters.get("message", None)
                )

            if self.settings.debug_mode:
                await self.print_execution_time()

        return function_response, instant_response

    async def _get_tool_parameter_type_by_name(self, type_name: str) -> any:
        if type_name == "object":
            return dict
        elif type_name == "string":
            return str
        elif type_name == "number":
            return int
        elif type_name == "boolean":
            return bool
        elif type_name == "array":
            return list
        else:
            return None

    async def start_timer_worker(self) -> None:
        while self.active:
            await asyncio.sleep(2)
            timers_to_delete = []
            for timer_id, timer in self.timers.items():
                delay = timer[0]
                # function = timer[1]
                # parameters = timer[2]
                start_time = timer[3]
                is_loop = timer[4]
                loops = timer[5]

                if is_loop and loops == 0:
                    timers_to_delete.append(timer_id)
                    continue  # skip timers marked for deletion

                if time.time() - start_time >= delay:
                    if self.settings.debug_mode:
                        self.start_execution_benchmark()
                    await self.execute_timer(timer_id)
                    if self.settings.debug_mode:
                        await self.print_execution_time(True)

            # delete timers marked for deletion
            for timer_id in timers_to_delete:
                del self.timers[timer_id]

        self.timers = {}  # clear timers

    async def execute_timer(self, timer_id: str) -> None:
        if timer_id not in self.timers:
            return

        # delay = self.timers[timer_id][0]
        function = self.timers[timer_id][1]
        parameters = self.timers[timer_id][2]
        # start_time = self.timers[timer_id][3]
        is_loop = self.timers[timer_id][4]
        loops = self.timers[timer_id][5]

        response = await self.wingman.execute_command_by_function_call(
            function, parameters
        )
        if response:
            summary = await self._summarize_timer_execution(
                function, parameters, response
            )
            await self.wingman.add_assistant_message(summary)
            await self.printr.print_async(
                f"{summary}",
                color=LogType.POSITIVE,
                source=LogSource.WINGMAN,
                source_name=self.wingman.name,
                skill_name=self.name,
            )
            await self.wingman.play_to_user(summary, True)

        if not is_loop or loops == 1:
            # we cant delete it here, because we are iterating over the timers in a sepereate thread
            self.timers[timer_id][4] = True
            self.timers[timer_id][5] = 0
            return

        self.timers[timer_id][3] = time.time()  # reset start time
        if loops > 0:
            self.timers[timer_id][5] -= 1  # decrease remaining loops

    async def set_timer(
        self,
        delay: int = None,
        is_loop: bool = False,
        loops: int = -1,
        function: str = None,
        parameters: dict[str, any] = None,
    ) -> str:
        check_counter = 0
        max_checks = 2
        errors = []

        while (check_counter == 0 or errors) and check_counter < max_checks:
            errors = []

            if delay is None or function is None:
                errors.append("Missing delay or function.")
            elif delay < 0:
                errors.append("No timer set, delay must be greater than 0.")

            if "." in function:
                function = function.split(".")[1]

            # check if tool call exists
            tool_call = None
            tool_call = next(
                (
                    tool
                    for tool in self.wingman.build_tools()
                    if tool.get("function", {}).get("name", False) == function
                ),
                None,
            )

            # if not valid it might be a command
            if not tool_call and self.wingman.get_command(function):
                parameters = {"command_name": function}
                function = "execute_command"

            if not tool_call:
                errors.append(f"Function {function} does not exist.")
            else:
                if tool_call.get("function", False) and tool_call.get(
                    "function", {}
                ).get("parameters", False):
                    properties = (
                        tool_call.get("function", {})
                        .get("parameters", {})
                        .get("properties", {})
                    )
                    required_parameters = (
                        tool_call.get("function", {})
                        .get("parameters", {})
                        .get("required", [])
                    )

                    for name, value in properties.items():
                        if name in parameters:
                            real_type = await self._get_tool_parameter_type_by_name(
                                value.get("type", "string")
                            )
                            if not isinstance(parameters[name], real_type):
                                errors.append(
                                    f"Parameter {name} must be of type {value.get('type', None)}, but is {type(parameters[name])}."
                                )
                            elif value.get("enum", False) and parameters[
                                name
                            ] not in value.get("enum", []):
                                errors.append(
                                    f"Parameter {name} must be one of {value.get('enum', [])}, but is {parameters[name]}."
                                )
                            if name in required_parameters:
                                required_parameters.remove(name)

                    if required_parameters:
                        errors.append(
                            f"Missing required parameters: {required_parameters}."
                        )

            check_counter += 1
            if errors:
                # try to let it fix itself
                message_history = []
                for message in self.wingman.messages:
                    role = (
                        message.role
                        if hasattr(message, "role")
                        else message.get("role", False)
                    )
                    if role in ["user", "assistant", "system"]:
                        message_history.append(
                            {
                                "role": role,
                                "content": (
                                    message.content
                                    if hasattr(message, "content")
                                    else message.get("content", False)
                                ),
                            }
                        )
                data = {
                    "original_set_timer_call": {
                        "delay": delay,
                        "is_loop": is_loop,
                        "loops": loops,
                        "function": function,
                        "parameters": parameters,
                    },
                    "message_history": (
                        message_history
                        if len(message_history) <= 10
                        else message_history[:1] + message_history[-9:]
                    ),
                    "tool_calls_definition": self.wingman.build_tools(),
                    "errors": errors,
                }

                messages = [
                    {
                        "role": "system",
                        "content": """
                            The **set_timer** tool got called by a request with parameters that are incomplete or do not match the given requirements.
                            Please adjust the parameters "function" and "parameters" to match the requirements of the designated tool.
                            Make use of the message_history with the user previously to figure out missing parameters or wrong types.
                            And the tool_calls_definition to see the available tools and their requirements.
                            Use the **errors** information to figure out what it missing or wrong.

                            Provide me an answer **only containing a valid JSON object** with the following structure for example:
                            {
                                "delay": 10,
                                "is_loop": false,
                                "loops": 1,
                                "function": "function_name",
                                "parameters": {
                                    "parameter_name": "parameter_value"
                                }
                            }
                        """,
                    },
                    {"role": "user", "content": json.dumps(data, indent=4)},
                ]
                json_retry = 0
                max_json_retries = 1
                valid_json = False
                while not valid_json and json_retry < max_json_retries:
                    completion = await self.llm_call(messages)
                    data = completion.choices[0].message.content
                    messages.append(
                        {
                            "role": "assistant",
                            "content": data,
                        }
                    )
                    # check if data is valid json
                    try:
                        if data.startswith("```json") and data.endswith("```"):
                            data = data[len("```json") : -len("```")].strip()
                        data = json.loads(data)
                    except json.JSONDecodeError:
                        messages.append(
                            {
                                "role": "user",
                                "content": "Data is not valid JSON. Please provide valid JSON data.",
                            }
                        )
                        json_retry += 1
                        continue

                    valid_json = True
                    delay = data.get("delay", False)
                    is_loop = data.get("is_loop", False)
                    loops = data.get("loops", 1)
                    function = data.get("function", False)
                    parameters = data.get("parameters", {})

        if errors:
            return f"""
                No timer set. Communicate these errors to the user.
                But make sure to align them with the message history so far: {errors}
            """

        # generate a unique id for the timer
        letters_and_digits = string.ascii_letters + string.digits
        timer_id = "".join(random.choice(letters_and_digits) for _ in range(10))

        # set timer
        current_time = time.time()
        self.timers[timer_id] = [
            delay,
            function,
            parameters,
            current_time,
            is_loop,
            loops,
        ]

        return f"Timer set with id {timer_id}.\n\n{await self.get_timer_status()}"

    async def _summarize_timer_execution(
        self, function: str, parameters: dict[str, any], response: str
    ) -> str:
        self.wingman.messages.append(
            {
                "role": "user",
                "content": f"""
                    Timed "{function}" with "{parameters}" was executed.
                    Summarize the respone while you must stay in character!
                    Dont mention it was a function call, go by the meaning:
                    {response}
                """,
            },
        )
        await self.wingman.add_context(self.wingman.messages)
        completion = await self.llm_call(self.wingman.messages)
        answer = (
            completion.choices[0].message.content
            if completion and completion.choices
            else ""
        )
        return answer

    async def get_timer_status(self) -> list[dict[str, any]]:
        timers = []
        for timer_id, timer in self.timers.items():
            if timer[4] and timer[5] == 0:
                continue  # skip timers marked for deletion
            timers.append(
                {
                    "id": timer_id,
                    "delay": timer[0],
                    "is_loop": timer[4],
                    "remaining_loops": (
                        (timer[5] if timer[5] > 0 else "infinite")
                        if timer[4]
                        else "N/A"
                    ),
                    "remaining_time_in_seconds": round(
                        max(0, timer[0] - (time.time() - timer[3]))
                    ),
                }
            )
        return timers

    async def cancel_timer(self, timer_id: str) -> str:
        if timer_id not in self.timers:
            return f"Timer with id {timer_id} not found."
        # we cant delete it here, because we are iterating over the timers in a sepereate thread
        self.timers[timer_id][4] = True
        self.timers[timer_id][5] = 0
        return f"Timer with id {timer_id} cancelled.\n\n{await self.get_timer_status()}"

    async def change_timer_settings(
        self, timer_id: str, delay: int, is_loop: bool, loops: int
    ) -> str:
        if timer_id not in self.timers:
            return f"Timer with id {timer_id} not found."
        self.timers[timer_id][0] = delay
        self.timers[timer_id][4] = is_loop
        self.timers[timer_id][5] = loops
        return f"Timer with id {timer_id} settings changed.\n\n{await self.get_timer_status()}"

    async def reminder(self, message: str = None) -> str:
        if not message:
            return "This is your reminder, no message was given."
        return message
