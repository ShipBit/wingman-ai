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
import time
from enum import Enum
from typing import TYPE_CHECKING, Callable, Optional

import numpy as np

from services.audio.voice_gate import FRAME_MS, GateParams, Utterance, VoiceGate

if TYPE_CHECKING:
    from wingmen.wingman import Wingman

# After a push-to-talk key goes up the gate stays open this long. People let
# go while the last syllable is still in the air, and the detector answers a
# frame or two late; "stop" is short enough to lose its "p" otherwise.
RELEASE_GRACE_MS = 300

# How long a release may wait for the grace frames before it goes through
# without them. Only reached when the microphone stream stopped delivering.
RELEASE_WATCHDOG_S = 1.0

# No key is held down for this long, and no microphone test runs that long.
# A hold that lasts longer lost its release: a key-up the hook never saw, a
# client that went away with its mic button down. Without this the holder
# stays, every later key is refused, and only a restart of Core helps.
MAX_HOLD_S = 120.0


class ListenState(str, Enum):
    OFF = "off"
    MUTED = "muted"
    ARMED = "armed"
    HELD = "held"
    PAUSED = "paused"


# For how long after a playback ended a new utterance still counts as said
# during it: the finished event comes through a queue and the last words
# are still on their way out of the headset.
PLAYBACK_TAIL_S = 0.5


class ListenController:
    def __init__(
        self,
        gate: VoiceGate,
        on_utterance: Callable[[Utterance, Optional["Wingman"], bool], None],
        on_state_changed: Callable[["ListenState"], None],
        on_dropped: Optional[Callable[[Optional["Wingman"]], None]] = None,
        on_hold_expired: Optional[Callable[[str], None]] = None,
    ):
        self._gate = gate
        # A hold that lasted MAX_HOLD_S and was ended here; for the log.
        self._on_hold_expired = on_hold_expired or (lambda _source: None)
        # (utterance, held wingman or None, whether a wingman was speaking)
        self._on_utterance = on_utterance
        self._on_state_changed = on_state_changed
        # A push-to-talk clip that held no speech; for the log line.
        self._on_dropped = on_dropped or (lambda _wingman: None)
        self._lock = threading.RLock()
        # Frames still to take after a push-to-talk key went up; None when
        # no release is pending.
        self._release_in: Optional[int] = None
        # The grace frames arrive from the microphone. When the stream is dead
        # they never do, and without this timer the controller would stay HELD
        # for good: voice activation could not arm and no later key would hold.
        self._release_timer: Optional[threading.Timer] = None
        # Fires when a hold has lasted MAX_HOLD_S; see the constant.
        self._hold_timer: Optional[threading.Timer] = None
        # Clips the gate cut off a long capture (the microphone test), kept so
        # the caller gets everything it recorded and not just the tail.
        self._capture_parts: list[Utterance] = []

        self.voice_activation_enabled = False
        self.listen_while_speaking = True
        self.user_muted = False
        self.playing = False
        # When the last playback ended, monotonic; for the tail after it.
        self._playback_ended_at = float("-inf")
        # Whether a wingman spoke at any point while the current utterance was
        # in the gate. Read when the utterance ends: by then the playback is
        # usually over, so `playing` alone would say no.
        self._heard_while_playing = False
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
            self._playback_ended_at = time.monotonic()
            self._apply()

    def _playback_overlaps(self) -> bool:
        return self.playing or time.monotonic() - self._playback_ended_at < PLAYBACK_TAIL_S

    def _take_heard_while_playing(self) -> bool:
        """Whether a wingman spoke during the utterance that just ended, and
        a clean slate for the next one."""
        playing = self._heard_while_playing
        self._heard_while_playing = False
        return playing

    def ptt_down(self, source: str, wingman: "Wingman") -> bool:
        """Returns False when another source already holds the gate."""
        with self._lock:
            if self.held_source == source and self._release_in is not None:
                # Pressed again inside the grace period: keep holding.
                self._cancel_release()
                return True
            if self.held_source is not None:
                if self._release_in is None:
                    return False
                # Another source is still inside its release grace. Let its
                # clip go out now, otherwise this press would be swallowed
                # and nothing at all would be recorded for it.
                self._finish_release()
            self.held_source = source
            self.held_wingman = wingman
            self._cancel_release()
            self._watch_hold(source)
            self._apply()
            return True

    def ptt_up(self, source: str) -> bool:
        """Returns False when `source` was not the holder. The gate stays open
        for RELEASE_GRACE_MS more; the clip goes out from `feed` after that,
        or is reported through `on_dropped` when it held no speech."""
        with self._lock:
            if self.held_source != source:
                return False
            self._release_in = max(1, int(round(RELEASE_GRACE_MS / FRAME_MS)))
            self._release_timer = threading.Timer(RELEASE_WATCHDOG_S, self._release_watchdog)
            self._release_timer.daemon = True
            self._release_timer.start()
            return True

    def _release_watchdog(self) -> None:
        """No frames came in during the grace period: the microphone stream is
        gone. Release anyway, so the key is not stuck down forever."""
        with self._lock:
            if self._release_in is not None:
                self._finish_release()

    def _watch_hold(self, source: str) -> None:
        """Called under the lock. Arms the timer that ends a hold nobody
        released."""
        self._cancel_hold_watch()
        self._hold_timer = threading.Timer(MAX_HOLD_S, self._hold_watchdog, args=(source,))
        self._hold_timer.daemon = True
        self._hold_timer.start()

    def _cancel_hold_watch(self) -> None:
        if self._hold_timer is not None:
            self._hold_timer.cancel()
            self._hold_timer = None

    def _hold_watchdog(self, source: str) -> None:
        with self._lock:
            if self.held_source != source:
                return
            self._hold_timer = None
            if self.held_wingman is not None:
                # A push-to-talk key: let the clip go the normal way.
                self._finish_release()
            else:
                # A microphone test nobody stopped: drop it.
                self._gate.release()
                self._capture_parts = []
                self.held_source = None
                self._apply()
            self._on_hold_expired(source)

    def _cancel_release(self) -> None:
        """Called under the lock. Drops a pending release and its watchdog."""
        self._release_in = None
        if self._release_timer is not None:
            self._release_timer.cancel()
            self._release_timer = None

    def _finish_release(self) -> None:
        """Called under the lock from feed(), the watchdog, or a new key."""
        wingman = self.held_wingman
        utterance = self._gate.release()
        playing = self._take_heard_while_playing()
        self.held_source = None
        self.held_wingman = None
        self._cancel_release()
        self._cancel_hold_watch()
        self._apply()
        if utterance is not None and wingman is not None:
            self._on_utterance(utterance, wingman, playing)
        else:
            self._on_dropped(wingman)

    def capture_start(self, source: str) -> bool:
        """Hold the gate for a caller that wants the clip back instead of having
        it dispatched: the microphone test in Settings."""
        with self._lock:
            if self.held_source is not None:
                return False
            self.held_source = source
            self.held_wingman = None
            self._capture_parts = []
            self._watch_hold(source)
            self._apply()
            return True

    def capture_stop(self, source: str) -> Optional[Utterance]:
        with self._lock:
            if self.held_source != source:
                return None
            utterance = self._gate.release()
            parts = self._capture_parts
            self._capture_parts = []
            self.held_source = None
            self._cancel_hold_watch()
            self._apply()
            if parts:
                # The gate cut the capture at max_utterance_s one or more
                # times. The caller asked for one clip, so it gets all of it.
                if utterance is not None:
                    parts = parts + [utterance]
                return Utterance(
                    samples=np.concatenate([p.samples for p in parts]),
                    truncated=False,
                )
            return utterance

    def update_params(self, params: GateParams) -> None:
        with self._lock:
            self._gate.update_params(params)

    # --- frames from the microphone ---

    def feed(self, frame: np.ndarray) -> None:
        with self._lock:
            state = self._state
            if self._gate.is_capturing and self._playback_overlaps():
                self._heard_while_playing = True
            utterance = self._gate.feed(frame)
            if utterance is None and self._gate.is_capturing and self._playback_overlaps():
                # The frame that opened the gate counts too.
                self._heard_while_playing = True
            wingman = self.held_wingman
            playing = self._take_heard_while_playing() if utterance is not None else False
            if self._release_in is not None and utterance is None:
                self._release_in -= 1
                if self._release_in <= 0:
                    self._finish_release()
                    return
            if utterance is not None and state == ListenState.HELD and wingman is None:
                # A capture (the mic test): the caller collects the clip from
                # capture_stop, so a piece cut off here is kept, not dispatched.
                self._capture_parts.append(utterance)
                return
        if utterance is None:
            return
        if state == ListenState.HELD:
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
