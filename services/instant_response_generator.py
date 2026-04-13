"""InstantResponseGenerator service.

Generates a list of short generic filler phrases via an LLM call (used during
long tool-call turns) and provides a random non-repeating selection from that
list.
"""

import json
import random
import traceback

from api.enums import LogType
from services.printr import Printr

printr = Printr()


class InstantResponseGenerator:
    """Generates and serves generic instant-filler phrases.

    Construct once per Wingman, then call :meth:`generate` from
    ``prepare()`` (wrapped in ``threaded_execution``) and
    :meth:`get_random_filler` from the turn loop.
    """

    def __init__(
        self,
        wingman_name: str,
        llm_call_fn,
        get_context_fn,
    ):
        """
        Args:
            wingman_name: Used for log messages.
            llm_call_fn: Async callable matching ``actual_llm_call(messages, tools=None)``
                         returning a ``ChatCompletion | None``.
            get_context_fn: Async callable matching ``get_context() -> str``.
        """
        self.wingman_name = wingman_name
        self._llm_call = llm_call_fn
        self._get_context = get_context_fn
        self.instant_responses: list[str] = []
        self.last_used_instant_responses: list[int] = []

    async def generate(self) -> None:
        """Populate ``self.instant_responses`` via an LLM call.

        Called by ``Wingman.prepare()`` when
        ``config.features.use_generic_instant_responses`` is enabled.
        """
        context = await self._get_context()
        messages = [
            {
                "role": "system",
                "content": """
                Generate a list in JSON format of at least 20 short direct text responses.
                Make sure the response only contains the JSON, no additional text.
                They must fit the described character in the given context by the user.
                Every generated response must be generally usable in every situation.
                Responses must show its still in progress and not in a finished state.
                The user request this response is used on is unknown. Therefore it must be generic.
                Good examples:
                    - "Processing..."
                    - "Stand by..."

                Bad examples:
                    - "Generating route..." (too specific)
                    - "I'm sorry, I can't do that." (too negative)

                Response example:
                [
                    "OK",
                    "Generating results...",
                    "Roger that!",
                    "Stand by..."
                ]
            """,
            },
            {"role": "user", "content": context},
        ]
        try:
            completion = await self._llm_call(messages)
            if completion is None:
                return
            if completion.choices[0].message.content:
                retry_limit = 3
                retry_count = 1
                valid = False
                while not valid and retry_count <= retry_limit:
                    try:
                        responses = json.loads(completion.choices[0].message.content)
                        valid = True
                        for response in responses:
                            if response not in self.instant_responses:
                                self.instant_responses.append(str(response))
                    except json.JSONDecodeError:
                        messages.append(completion.choices[0].message)
                        messages.append(
                            {
                                "role": "user",
                                "content": "The response could not be parsed as JSON. Return only valid JSON with no additional text.",
                            }
                        )
                        if retry_count <= retry_limit:
                            completion = await self._llm_call(messages)
                        retry_count += 1
        except Exception as e:
            await printr.print_async(
                f"Error while generating instant responses: {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

    def get_random_filler(self) -> str | None:
        """Return a random non-recently-used filler phrase.

        Returns ``None`` when no responses have been generated yet.
        """
        if not self.instant_responses:
            return None

        if len(self.last_used_instant_responses) > 2:
            self.last_used_instant_responses = self.last_used_instant_responses[-2:]

        random_index = random.randint(0, len(self.instant_responses) - 1)
        while random_index in self.last_used_instant_responses:
            random_index = random.randint(0, len(self.instant_responses) - 1)

        self.last_used_instant_responses.append(random_index)
        return self.instant_responses[random_index]
