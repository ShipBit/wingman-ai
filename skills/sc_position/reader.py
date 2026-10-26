"""Sends `/showlocation` to Star Citizen and reads the answer from the clipboard.

The game answers the chat command by putting `Coordinates: x:… y:… z:…` on
the clipboard. The command itself also goes through the clipboard: it is
pasted, not typed. When the chat has no focus, typed letters would land in
the game as key presses; a paste there does nothing.

The chat window may be hidden (most players hide it). Its toggle key is a
toggle, and nothing tells us its state, so the clipboard does: the first
attempt runs without the toggle. If the clipboard still holds the command
afterwards, the chat was hidden; the second attempt shows it first and hides
it again after. Whatever was on the clipboard before is put back.

Every key press, clipboard call, sleep and clock is injected, so the
sequence runs in tests without a game.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

COMMAND = "/showlocation"
ANSWER_PREFIX = "Coordinates:"


class ReadError(RuntimeError):
    """The game did not answer; the message says what to check."""


@dataclass(frozen=True)
class Reading:
    text: str
    """The clipboard line, starting with `Coordinates:`."""
    measured_at: float
    """Unix time the answer appeared on the clipboard."""
    toggled_chat: bool
    """The chat was hidden and had to be shown for the command."""


class PositionReader:
    def __init__(
        self,
        *,
        press: Callable[[str], Awaitable[None]],
        read_clipboard: Callable[[], Awaitable[str]],
        write_clipboard: Callable[[str], Awaitable[None]],
        sleep: Callable[[float], Awaitable[None]],
        now: Callable[[], float],
        chat_input_key: str = "enter",
        chat_toggle_key: str = "f12",
        paste_key: str = "ctrl+v",
        delay: float = 0.15,
        answer_timeout: float = 2.0,
        poll: float = 0.05,
    ) -> None:
        self._press = press
        self._read_clipboard = read_clipboard
        self._write_clipboard = write_clipboard
        self._sleep = sleep
        self._now = now
        self.chat_input_key = chat_input_key
        self.chat_toggle_key = chat_toggle_key
        self.paste_key = paste_key
        self.delay = delay
        self.answer_timeout = answer_timeout
        self.poll = poll

    async def read(self) -> Reading:
        try:
            previous = await self._read_clipboard()
        except RuntimeError:
            previous = ""
        await self._write_clipboard(COMMAND)
        toggled = False
        answer = await self._attempt(toggle=False)
        if answer is None:
            toggled = True
            answer = await self._attempt(toggle=True)
        if previous and previous != COMMAND and not previous.startswith(ANSWER_PREFIX):
            try:
                await self._write_clipboard(previous)
            except RuntimeError:
                pass
        if answer is None:
            raise ReadError(
                "Star Citizen did not answer /showlocation. The game window needs the "
                "focus, and the chat must be available (its toggle key is "
                f"{self.chat_toggle_key.upper()})."
            )
        text, measured_at = answer
        return Reading(text=text, measured_at=measured_at, toggled_chat=toggled)

    async def _attempt(self, toggle: bool):
        """One run of the key sequence. The answer and its time, or None."""
        if toggle:
            await self._press(self.chat_toggle_key)
            await self._sleep(self.delay)
        await self._press(self.chat_input_key)
        await self._sleep(self.delay)
        await self._press(self.paste_key)
        await self._sleep(self.delay)
        await self._press(self.chat_input_key)
        answer = None
        waited = 0.0
        while waited < self.answer_timeout:
            await self._sleep(self.poll)
            waited += self.poll
            text = await self._read_clipboard()
            if text.startswith(ANSWER_PREFIX):
                answer = (text.strip(), self._now())
                break
        if toggle:
            await self._sleep(self.delay)
            await self._press(self.chat_toggle_key)
        return answer
