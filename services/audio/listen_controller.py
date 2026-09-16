"""Who may speak into the microphone right now, and for whom.

The state is not stored, it is derived from four facts, in this order:

    HELD    a push-to-talk source holds the gate (key, mouse, joystick, GUI)
    OFF     voice activation is switched off
    MUTED   voice activation is on, the user muted it
    PAUSED  voice activation is on, a wingman is speaking
    ARMED   voice activation is on and listening

Deriving instead of storing is what makes "return to the previous state after
push-to-talk" or "resume after playback" fall out for free: release the key,
the facts are unchanged, the state is what it was.

Every transition is a flag change. The stream never stops, so muting takes no
time and nothing waits on a thread.

PAUSED only exists when `listen_while_speaking` is off. With it on (the
default) the gate stays ARMED while a wingman speaks and every utterance is
handed on with `during_playback=True`; the core then decides by its text
whether it was "stop", the wingman's own voice, or the user talking on.
"""

import threading
from enum import Enum
from typing import TYPE_CHECKING, Callable, Optional

import numpy as np

from services.audio.voice_gate import GateParams, Utterance, VoiceGate

if TYPE_CHECKING:
    from wingmen.wingman import Wingman

class ListenState(str, Enum):
    OFF = "off"
    MUTED = "muted"
    ARMED = "armed"
    HELD = "held"
    PAUSED = "paused"


class ListenController:
    def __init__(
        self,
        gate: VoiceGate,
        on_utterance: Callable[[Utterance, Optional["Wingman"], bool], None],
        on_state_changed: Callable[["ListenState"], None],
    ):
        self._gate = gate
        # (utterance, held wingman or None, whether a wingman was speaking)
        self._on_utterance = on_utterance
        self._on_state_changed = on_state_changed
        self._lock = threading.RLock()

        self.voice_activation_enabled = False
        self.listen_while_speaking = True
        self.user_muted = False
        self.playing = False
        self.held_source: Optional[str] = None
        self.held_wingman: Optional["Wingman"] = None
        self._state = ListenState.OFF

    # --- reading ---

    @property
    def state(self) -> ListenState:
        return self._state

    # --- events ---

    def set_voice_activation(self, enabled: bool) -> None:
        with self._lock:
            self.voice_activation_enabled = enabled
            if enabled:
                # Switching it on means listening, not "on but muted".
                self.user_muted = False
            self._apply()

    def set_listen_while_speaking(self, enabled: bool) -> None:
        with self._lock:
            self.listen_while_speaking = enabled
            self._apply()

    def set_muted(self, muted: bool) -> None:
        with self._lock:
            self.user_muted = muted
            self._apply()

    def toggle_muted(self) -> None:
        with self._lock:
            self.set_muted(not self.user_muted)

    def playback_started(self) -> None:
        with self._lock:
            self.playing = True
            self._apply()

    def playback_finished(self) -> None:
        with self._lock:
            self.playing = False
            self._apply()

    def ptt_down(self, source: str, wingman: "Wingman") -> bool:
        """Returns False when another source already holds the gate."""
        with self._lock:
            if self.held_source is not None:
                return False
            self.held_source = source
            self.held_wingman = wingman
            self._apply()
            return True

    def ptt_up(self, source: str) -> Optional[bool]:
        """None when `source` was not the holder, True when an utterance went
        out, False when the clip held no speech and was dropped."""
        with self._lock:
            if self.held_source != source:
                return None
            wingman = self.held_wingman
            playing = self.playing
            utterance = self._gate.release()
            self.held_source = None
            self.held_wingman = None
            self._apply()
        if utterance is not None and wingman is not None:
            self._on_utterance(utterance, wingman, playing)
            return True
        return False

    def capture_start(self, source: str) -> bool:
        """Hold the gate for a caller that wants the clip back instead of having
        it dispatched: the microphone test in Settings."""
        with self._lock:
            if self.held_source is not None:
                return False
            self.held_source = source
            self.held_wingman = None
            self._apply()
            return True

    def capture_stop(self, source: str) -> Optional[Utterance]:
        with self._lock:
            if self.held_source != source:
                return None
            utterance = self._gate.release()
            self.held_source = None
            self._apply()
            return utterance

    def update_params(self, params: GateParams) -> None:
        with self._lock:
            self._gate.update_params(params)

    # --- frames from the microphone ---

    def feed(self, frame: np.ndarray) -> None:
        with self._lock:
            state = self._state
            utterance = self._gate.feed(frame)
            wingman = self.held_wingman
            playing = self.playing
        if utterance is None:
            return
        if state == ListenState.HELD:
            if wingman is not None:  # a capture for the mic test keeps its clips
                self._on_utterance(utterance, wingman, playing)
        elif state == ListenState.ARMED:
            self._on_utterance(utterance, None, playing)

    # --- derive ---

    def _derive(self) -> ListenState:
        if self.held_source is not None:
            return ListenState.HELD
        if not self.voice_activation_enabled:
            return ListenState.OFF
        if self.user_muted:
            return ListenState.MUTED
        if self.playing and not self.listen_while_speaking:
            return ListenState.PAUSED
        return ListenState.ARMED

    def _apply(self) -> None:
        new = self._derive()
        if new == self._state:
            return
        self._state = new
        if new == ListenState.HELD:
            self._gate.hold()
        elif new == ListenState.ARMED:
            self._gate.arm()
        else:
            self._gate.close()
        self._on_state_changed(new)
