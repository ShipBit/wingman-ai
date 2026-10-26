"""Sends `/showlocation` to Star Citizen and reads the answer from the clipboard.

The game answers the chat command by putting `Coordinates: x:… y:… z:…` on
the clipboard. The command itself also goes through the clipboard: it is
pasted, not typed. When the chat has no focus, typed letters would land in
the game as key presses; a paste there is two keys instead of fourteen.

The chat window is hidden for most players. Its toggle key is a toggle, and
nothing tells us its state, so the user tells us (the "Chat is hidden"
setting). With the chat hidden the sequence shows it first and hides it
again after. There is no trying the other state when no answer comes: a
sequence sent to a chat that has no focus reaches the game instead, and
Ctrl, V and Enter do things there (crouch, for one). The user sees the
failure, checks the setting, and the next call is right.

Whatever was on the clipboard before is put back. Every key press, clipboard
call, sleep and clock is injected, so the sequence runs in tests without a
game.
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
    """The chat was shown for the command and hidden again."""


class PositionReader:
    def __init__(
        self,
        *,
        press: Callable[[str], Awaitable[None]],
        read_clipboard: Callable[[], Awaitable[str]],
        write_clipboard: Callable[[str], Awaitable[None]],
        sleep: Callable[[float], Awaitable[None]],
        now: Callable[[], float],
        chat_hidden: bool = True,
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
        self.chat_hidden = chat_hidden
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
        answer = await self._attempt(toggle=self.chat_hidden)
        if previous and previous != COMMAND and not previous.startswith(ANSWER_PREFIX):
            try:
                await self._write_clipboard(previous)
            except RuntimeError:
                pass
        if answer is None:
            if self.chat_hidden:
                hint = "If the chat is visible in the game, switch off 'Chat is hidden' in the skill's settings."
            else:
                hint = (
                    f"If the chat is hidden in the game ({self.chat_toggle_key.upper()}), "
                    "switch on 'Chat is hidden' in the skill's settings."
                )
            raise ReadError(
                "Star Citizen did not answer /showlocation. The game window needs the focus. " + hint
            )
        text, measured_at = answer
        return Reading(text=text, measured_at=measured_at, toggled_chat=self.chat_hidden)

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
