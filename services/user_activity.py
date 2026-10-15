"""Whether the user is in a conversation with a wingman right now.

Things a wingman says on its own (a reaction to a game event, a timer) must
not land in the middle of that: over a held push-to-talk key the line ends up
in the user's own transcript, and in the middle of a turn it lands between
the question and the answer.

One for all wingmen: the user holding the key for Ledger is as busy as the
user holding it for KAT.
"""

import threading
import time

# After an utterance was heard, how long it takes at most until its turn
# starts: transcription and the System One check.
HEARD_GRACE_S = 3.0


class UserActivity:
    def __init__(self):
        self._lock = threading.Lock()
        self._holding = False
        self._turns = 0
        self._heard_at = float("-inf")

    def set_holding(self, holding: bool) -> None:
        """A push-to-talk key is down (or its release grace is running)."""
        self._holding = holding

    def heard(self) -> None:
        """An utterance just ended and goes to transcription."""
        self._heard_at = time.monotonic()

    def turn_started(self) -> None:
        with self._lock:
            self._turns += 1

    def turn_finished(self) -> None:
        with self._lock:
            self._turns = max(0, self._turns - 1)

    @property
    def busy(self) -> bool:
        return (
            self._holding
            or self._turns > 0
            or time.monotonic() - self._heard_at < HEARD_GRACE_S
        )


user_activity = UserActivity()
