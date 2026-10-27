"""A skill takes over a Wingman's conversation.

While a takeover is active, what the user says goes to the skill's handler
instead of the model and the Wingman says nothing. That is how a skill voices
someone else: an NPC at a counter, a caller on the radio, a trainer. The user
talks to them directly, and the Wingman reads afterwards what was said, since
both sides land in the history as notes (wingmen/wingman.py, _takeover_turn).

It ends when the handler says the conversation is over, when the user
addresses the Wingman by name, when nobody has said anything for `idle_s`,
or when the skill calls release().
"""

import time
from typing import Awaitable, Callable

Handler = Callable[[str], Awaitable[bool]]
"""Gets what the user said, answers in the speaker's name, and returns False
when the conversation is over."""

Opener = Callable[[str, str], Awaitable[bool]]
"""Gets the name the user used and what they said; returns True when it
handled the sentence (usually by taking over), False to leave it to the model."""

TAKEOVER_IDLE_S = 300.0
"""Without a word for this long, the conversation counts as over."""


class Takeover:
    __slots__ = ("speaker", "idle_s", "active", "last_at", "_handler", "_on_release")

    def __init__(
        self,
        speaker: str,
        handler: Handler,
        idle_s: float,
        on_release: Callable[["Takeover"], None],
    ) -> None:
        self.speaker = speaker
        self.idle_s = idle_s
        self.active = True
        self.last_at = time.monotonic()
        self._handler = handler
        self._on_release = on_release

    def idle(self, now: float | None = None) -> bool:
        return (time.monotonic() if now is None else now) - self.last_at > self.idle_s

    async def handle(self, text: str) -> bool:
        """Give the handler what the user said. True when the conversation goes on."""
        self.last_at = time.monotonic()
        keep = bool(await self._handler(text))
        if not keep:
            self.release()
        return keep

    def release(self) -> None:
        """End the takeover. Safe to call more than once."""
        if self.active:
            self.active = False
            self._on_release(self)
