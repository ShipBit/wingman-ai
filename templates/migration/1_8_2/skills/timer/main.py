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
from services.benchmark import Benchmark
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman

class ActualTimer:
    def __init__(
        self,
        delay: int,
        is_loop: bool,
        loops: int,
        silent: bool,
        function: str,
        parameters: dict[str, any],
    ) -> None:
        self.delay = delay
        self.is_loop = is_loop
        self.loops = loops
        self.silent = silent
        self.function = function
        self.parameters = parameters
        letters_and_digits = string.ascii_letters + string.digits
        self.id = "".join(random.choice(letters_and_digits) for _ in range(7))
        self.last_run = self.update_last_run()
        self.deleted = False

    @property
    def delay(self) -> int:
        return int(self._delay)

    @delay.setter
    def delay(self, value: int) -> None:
        self._delay = value

    @property
    def is_loop(self) -> bool:
        return bool(self._is_loop)

    @is_loop.setter
    def is_loop(self, value: bool) -> None:
        self._is_loop = value

    @property
    def loops(self) -> int:
        return int(self._loops)

    @loops.setter
    def loops(self, value: int) -> None:
        self._loops = value

    @property
    def silent(self) -> bool:
        return bool(self._silent)

    @silent.setter
    def silent(self, value: bool) -> None:
        self._silent = value

    @property
    def function(self) -> str:
        return str(self._function)

    @function.setter
    def function(self, value: str) -> None:
        self._function = value

    @property
    def parameters(self) -> dict[str, any]:
        return dict(self._parameters)

    @parameters.setter
    def parameters(self, value: dict[str, any]) -> None:
        self._parameters = value

    @property
    def id(self) -> str:
        return str(self._timer_id)

    @id.setter
    def id(self, value: str) -> None:
        self._timer_id = value

    @property
    def last_run(self) -> int:
        return int(self._last_run)

    @last_run.setter
    def last_run(self, value: int) -> None:
        self._last_run = value

    @property
    def deleted(self) -> bool:
        return bool(self._deleted)

    @deleted.setter
    def deleted(self, value: bool) -> None:
        self._deleted = value

    def update_last_run(self) -> int:
        self.last_run = time.time()
        return self.last_run

    def __str__(self) -> str:
        return f"Timer: {self.function} with parameters: {self.parameters} in {self.delay} seconds."

class Timer(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        self.timers: dict[str, ActualTimer] = {}
        self.available_tools = []
        self.active = False

    async def prepare(self) -> None:
        self.active = True
        self.threaded_execution(self.start_timer_worker)

    async def unload(self) -> None:
        self.active = False

    async def get_prompt(self) -> str | None:
        prompt = await super().get_prompt()
        prompt = f"{prompt or ''}\n\nActive timers:\n{await self.get_timer_status()}"
        return prompt

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
                                "silent": {
                                    "type": "boolean",
                                    "description": "For silent operation. This must be used with loops with a quick cycle (delay) to prevent constant message spamming.",
                                },
                                "function": {
                                    "type": "string",
                                    # "enum": self._get_available_tools(), # end up being a recursive nightmare
                                    "description": "The name of the function to execute after the delay. Must be a function name from the available tools.",
                                },
                                "parameters": {
                                    "type": "object",
                                    "description": "The parameters for the function to execute after the delay. Must be a valid object with the required properties to their values. Can not be empty.",
                                },
                            },
                            "required": ["delay", "function", "parameters"],
                            "optional": ["is_loop", "loops", "silent"],
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
                                "silent": {
                                    "type": "boolean",
                                    "description": "Change the timer to be silent or not.",
                                },
                            },
                            "required": ["id", "delay", "is_loop", "loops", "silent"],
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
        self, tool_name: str, parameters: dict[str, any], benchmark: Benchmark
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
            benchmark.start_snapshot(f"Timer: {tool_name}")
            if self.settings.debug_mode:
                message = f"Timer: executing tool '{tool_name}'"
                if parameters:
                    message += f" with params: {parameters}"
                await self.printr.print_async(text=message, color=LogType.INFO)

            if tool_name == "set_timer":
                function_response = await self.set_timer(
                    delay=parameters.get("delay", None),
                    is_loop=parameters.get("is_loop", False),
                    loops=parameters.get("loops", 1),
                    silent=parameters.get("silent", False),
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
                    is_loop=parameters.get("is_loop", None),
                    loops=parameters.get("loops", None),
                    silent=parameters.get("silent", None),
                )
            elif tool_name == "remind_me":
                function_response = await self.reminder(
                    message=parameters.get("message", None)
                )

            benchmark.finish_snapshot()

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
                if (timer.is_loop and timer.loops == 0) or timer.deleted:
                    timer.deleted = True
                    timers_to_delete.append(timer_id)
                    continue

                if time.time() - timer.last_run >= timer.delay:
                    await self.execute_timer(timer_id)

            # delete timers marked for deletion
            for timer_id in timers_to_delete:
                del self.timers[timer_id]

        # clear timers after unload
        self.timers = {}

    async def execute_timer(self, timer_id: str) -> None:
        if timer_id not in self.timers:
            return

        timer = self.timers[timer_id]

        function_response, instant_response, used_skill = await self.wingman.execute_command_by_function_call(
            timer.function, timer.parameters
        )
        response = instant_response or function_response
        if response:
            summary = await self._summarize_timer_execution(
                timer, response
            )
            if summary:
                await self.wingman.add_assistant_message(summary)
                await self.printr.print_async(
                    f"{summary}",
                    color=LogType.POSITIVE,
                    source=LogSource.WINGMAN,
                    source_name=self.wingman.name,
                    skill_name=self.name,
                )
                await self.wingman.play_to_user(summary, True)

        if not timer.is_loop or timer.loops == 1:
            # we cant delete it here, because we are iterating over the timers in a sepereate thread
            timer.deleted = True
            return

        timer.update_last_run()
        if timer.loops > 0:
            timer.loops -= 1

    async def set_timer(
        self,
        delay: int = None,
        is_loop: bool = False,
        loops: int = -1,
        silent: bool = False,
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
                if tool_call.get("function", False) and tool_call.get("function", {}).get("parameters", False):
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
                        "silent": silent,
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

                            Provide me an answer **only containing a valid JSON object** with the following structure for example, values are just placeholders:
                            {
                                "delay": 10,
                                "is_loop": false,
                                "loops": 1,
                                "silent": false,
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
                    silent = data.get("silent", False)
                    function = data.get("function", False)
                    parameters = data.get("parameters", {})

        if errors:
            return f"""
                No timer set. Communicate these errors to the user.
                But make sure to align them with the message history so far: {errors}
            """

        # set timer
        timer = ActualTimer(
            delay=delay,
            is_loop=is_loop,
            loops=loops,
            silent=silent,
            function=function,
            parameters=parameters,
        )
        self.timers[timer.id] = timer
        return f"Timer set with id {timer.id}.\n\n{await self.get_timer_status()}"

    async def _summarize_timer_execution(
        self, timer: ActualTimer, response: str
    ) -> str | None:
        if timer.silent:
            return None
        messages = self.wingman.messages
        messages.append(
            {
                "role": "user",
                "content": f"""
                    Timed "{timer.function}" with "{timer.parameters}" was executed.
                    Create a small summary of what was executed.
                    Dont mention it was a function call, go by the meaning.
                    For example dont say command 'LandingGearUp' was executed, say 'Landing gear retracted'.
                    The summary should must be in the same message as the previous user message.
                    The function response:
                    ```
                    {response}
                    ```
                """,
            },
        )
        try:
            completion = await self.llm_call(messages)
            answer = (
                completion.choices[0].message.content
                if completion and completion.choices
                else ""
            )
            return answer
        except Exception:
            return None

    async def get_timer_status(self) -> list[dict[str, any]]:
        timers = []
        for timer_id, timer in self.timers.items():
            if timer.deleted:
                continue

            timers.append(
                {
                    "id": timer.id,
                    "delay": timer.delay,
                    "is_loop": timer.is_loop,
                    "remaining_loops": (
                        (timer.loops if timer.loops > 0 else "infinite")
                        if timer.is_loop
                        else "N/A"
                    ),
                    "remaining_time_in_seconds": round(
                        max(0, int(timer.delay - (time.time() - timer.last_run)))
                    ),
                }
            )
        return timers

    async def cancel_timer(self, timer_id: str|None = None) -> str:
        if not timer_id or timer_id not in self.timers:
            return f"Timer with id '{str(timer_id)}' not found."

        # we cant delete it here, because we are iterating over the timers in a separate thread
        # so we just mark it for deletion
        self.timers[timer_id].deleted = True
        return f"Timer with id {timer_id} cancelled.\n\n{await self.get_timer_status()}"

    async def change_timer_settings(
        self,
        timer_id: str|None,
        delay: any,
        is_loop: any,
        loops: any,
        silent: any,
    ) -> str:
        if not timer_id or timer_id not in self.timers:
            return f"Timer with id '{str(timer_id)}' not found."

        timer = self.timers[timer_id]
        if delay is not None:
            timer.delay = int(delay)
        if is_loop is not None:
            timer.is_loop = bool(is_loop)
        if loops is not None:
            timer.loops = int(loops)
        if silent is not None:
            timer.silent = bool(silent)
        return f"Timer with id '{timer_id}' settings have been changed.\n\n{await self.get_timer_status()}"

    async def reminder(self, message: str|None = None) -> str:
        if not message:
            return "This is your reminder, no message was given."
        return message
