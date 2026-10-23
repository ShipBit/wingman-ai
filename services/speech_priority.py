"""Who may talk over whom.

One audio player serves every wingman, and a new playback used to stop
whatever played. Radio chatter that took ten seconds to synthesize then cut
off the answer the user had asked for in the meantime.

The order is fixed:

- ANSWER: what the user asked for. The answer, the filler line while a tool
  runs, a command's spoken response. Stops anything else.
- EVENT: what a wingman says on its own about something that happened. A
  game event, a timer. Never talks over an answer or over the user; it waits
  and is said once they are done.
- BACKGROUND: atmosphere, radio chatter. Never talks over anything; when it
  cannot be said now it is not said.

The decision falls when the audio is about to start, not when the text is
handed over: synthesis takes seconds, and the user may have started talking
meanwhile. The player reads the priority of the speech it is about to start
from ``current_speech``, which ``Wingman.play_to_user`` sets.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from api.enums import SpeechPriority


# How long an EVENT waits for its turn before it is dropped. After that the
# moment it was about has passed.
EVENT_WAIT_S = 60.0


@dataclass
class SpeechSlot:
    """One line on its way to the speakers. The player sets ``yielded`` when
    it did not start the line because something more important came first."""

    priority: SpeechPriority = SpeechPriority.ANSWER
    yielded: bool = False


current_speech: ContextVar[Optional[SpeechSlot]] = ContextVar("current_speech", default=None)


def must_yield(
    priority: SpeechPriority,
    playing: bool,
    playing_priority: SpeechPriority,
    user_busy: bool,
) -> bool:
    """Whether a line of ``priority`` must not start now. An answer always
    starts. Anything else waits for the user and for a playback at least as
    important as itself."""
    if priority == SpeechPriority.ANSWER:
        return False
    if user_busy:
        return True
    return playing and playing_priority <= priority
