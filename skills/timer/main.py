import json
import random
import string
import asyncio
import time
from typing import TYPE_CHECKING, Optional
from api.interface import SettingsConfig, SkillConfig
from api.enums import (
    LogSource,
    LogType,
)
from services.benchmark import Benchmark
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class ActualTimer:
    def __init__(
        self,
        delay: int,
        is_loop: bool,
        loops: int,
        silent: bool,
        function_name: str,
        function_arguments: dict[str, any],
    ) -> None:
        self._delay = delay
        self._is_loop = is_loop
        self._loops = loops
        self._silent = silent
        self._function_name = function_name
        self._function_arguments = function_arguments
        letters_and_digits = string.ascii_letters + string.digits
        self._timer_id = "".join(random.choice(letters_and_digits) for _ in range(7))
        self._last_run = self.update_last_run()
        self._deleted = False

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
    def function_name(self) -> str:
        return str(self._function_name)

    @function_name.setter
    def function_name(self, value: str) -> None:
        self._function_name = value

    @property
    def function_arguments(self) -> dict[str, any]:
        return dict(self._function_arguments)

    @function_arguments.setter
    def function_arguments(self, value: dict[str, any]) -> None:
        self._function_arguments = value

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
        return f"Timer: {self.function_name} with parameters: {self.function_arguments} in {self.delay} seconds."


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
        await super().prepare()
        self.active = True
        self.threaded_execution(self.start_timer_worker)

    async def unload(self) -> None:
        await super().unload()
        self.active = False

    async def get_prompt(self) -> str | None:
        prompt = await super().get_prompt()
        prompt = f"{prompt or ''}\n\nActive timers:\n{await self.get_timer_status()}"
        return prompt

    @tool(
        description="Set a timer to execute a function after a delay, in background or a loop. Use for scheduling future actions, recurring tasks, or delayed execution. Supports looping for periodic operations. Use silent for example in quick loops."
    )
    async def set_timer(
        self,
        delay: float,
        function_name: str,
        function_arguments_json: str,
        is_loop: bool = False,
        loop_counts: int = -1,
        silent: bool = False,
    ) -> str:
        """
        Set a timer to execute a function after a delay.

        Args:
            delay: The delay in seconds.
            function_name: The name of the function to execute.
            function_arguments_json: The parameters for the function in json format.
            is_loop: Whether the timer should loop.
            loop_counts: Number of loops (-1 for infinite).
            silent: Whether to suppress output.
        """
        if delay < 0:
            return "Error: Delay must be greater than 0."

        if "." in function_name:
            function_name = function_name.split(".")[1]

        # check if tool call exists
        tool_call = next(
            (
                tool
                for tool in self.wingman.build_tools()
                if tool.get("function", {}).get("name", False) == function_name
            ),
            None,
        )

        # if not valid it might be a command
        if not tool_call and self.wingman.get_command(function_name):
            function_arguments_json = json.dumps({"command_name": function_name})
            function_name = "execute_command"
            tool_call = True  # Mark as found

        if not tool_call:
            return f"Error: Function '{function_name}' does not exist."

        try:
            function_arguments = json.loads(function_arguments_json)
        except json.JSONDecodeError:
            return "Error: Invalid JSON in function_arguments_json."

        # set timer
        timer = ActualTimer(
            delay=int(delay),
            is_loop=is_loop,
            loops=loop_counts,
            silent=silent,
            function_name=function_name,
            function_arguments=function_arguments,
        )
        self.timers[timer.id] = timer
        return f"Timer set with id {timer.id}.\n\n{await self.get_timer_status()}"

    @tool(description="Get a list of all running timers. Keep IDs to yourself.")
    async def get_timer_status(self) -> list[dict[str, any]]:
        """Get a list of all running timers and their remaining time and id."""
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

    @tool(description="Cancel a running timer by its id.")
    async def cancel_timer(self, id: str) -> str:
        """
        Cancel a running timer by its id.

        Args:
            id: The id of the timer to cancel.
        """
        if not id or id not in self.timers:
            return f"Timer with id '{str(id)}' not found."

        # we cant delete it here, because we are iterating over the timers in a separate thread
        # so we just mark it for deletion
        self.timers[id].deleted = True
        return f"Timer with id {id} cancelled.\n\n{await self.get_timer_status()}"

    @tool(description="Change a timer's settings.")
    async def change_timer_settings(
        self,
        id: str,
        delay: Optional[float] = None,
        is_loop: Optional[bool] = None,
        loops: Optional[int] = None,
        silent: Optional[bool] = None,
    ) -> str:
        """
        Change a timer's loop and delay settings.

        Args:
            id: The id of the timer to change.
            delay: The new delay in seconds.
            is_loop: Whether the timer should loop.
            loops: Number of remaining loops (-1 for infinite).
            silent: Whether the timer should be silent.
        """
        if not id or id not in self.timers:
            return f"Timer with id '{str(id)}' not found."

        timer = self.timers[id]
        if delay is not None:
            timer.delay = int(delay)
        if is_loop is not None:
            timer.is_loop = bool(is_loop)
        if loops is not None:
            timer.loops = int(loops)
        if silent is not None:
            timer.silent = bool(silent)
        return f"Timer with id '{id}' settings have been changed.\n\n{await self.get_timer_status()}"

    @tool(
        description="Remind the user with a message. Use as 'function_name' in 'set_timer'-tool when user says 'remind me to...', 'don't let me forget...', or needs to be notified about something later."
    )
    async def remind_me(self, message: str) -> str:
        """
        Remind the user with the given message.

        Args:
            message: The message to remind the user with.
        """
        if not message:
            return "This is your reminder, no message was given."
        return message

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
        function_response, instant_response, used_skill, tool_label = (
            await self.wingman.execute_command_by_function_call(
                timer.function_name, timer.function_arguments
            )
        )

        response = instant_response or function_response
        if response:
            summary = await self._summarize_timer_execution(timer, response)
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
            # we cant delete it here, because we are iterating over the timers in a separate thread
            timer.deleted = True
            return

        timer.update_last_run()
        if timer.loops > 0:
            timer.loops -= 1

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
                    Timed "{timer.function_name}" with "{timer.function_arguments}" was executed.
                    Create a small summary of what was executed.
                    Dont mention it was a function call, go by the meaning.
                    For example dont say command 'LandingGearUp' was executed, say 'Landing gear retracted'.
                    The summary language must be in the same language as the previous user message.
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
