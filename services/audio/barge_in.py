"""Noticing the user talking over a wingman, by loudness alone.

Through speakers the microphone hears the wingman. What it hears is, near
enough, the playback, late by a fixed delay (buffers on both sides, the
room), scaled by one gain (volume, distance) and ringing on a little after
each sound (the room). On top of that the room's own noise. All of it is
measured rather than assumed: the noise while nothing plays, the delay and
the gain from the two loudness curves while the wingman speaks. From then
on a microphone level well above noise plus the expected echo means
somebody else is talking, and the caller stops the playback. No model and
no transcription; a few multiplications per frame and a small correlation
now and then.

Text cannot do this job: with speakers the wingman never pauses, so an
utterance said over it only ends when the wingman stops, and any decision
on its text comes after the fact.
"""

from collections import deque
from typing import Callable, Optional

import numpy as np

from services.audio.voice_gate import FRAME_MS

# The longest delay between output and its echo that is looked for.
MAX_DELAY_MS = 1000
# Loudness history on both sides; the delay is found in it.
HISTORY_MS = 3000
# How much of it has to be there before the delay is looked for the first
# time, and how often it is looked for again once the history is full.
DELAY_AFTER_MS = 1500
DELAY_EVERY_MS = 500
# The two curves have to agree this well for the delay to be believed, and
# a new estimate replaces a known one only when it agrees at least about
# as well as that one did. A short answer gives too little curve to trust
# over what a long one showed.
DELAY_MIN_CORRELATION = 0.5
DELAY_WORSE_BY = 0.1
# Over how many recent frames the gain is estimated: the median of the
# ratio microphone to delayed output, so the user's voice in part of the
# window does not move it.
GAIN_WINDOW_MS = 1500
# Output level below this is silence for the purpose of measuring.
OUTPUT_PRESENT = 1e-3
# The delay is known to a few frames only: the output is measured in the
# player's blocks, the microphone in its own, and neither lines up with
# the other. The expected echo takes the loudest output around the delay,
# further back than forward, since a delay found short is the usual error.
JITTER_BACK = 3
JITTER_FORWARD = 1
# How the expected echo dies away after the output stops: the room rings
# on. Per frame; halves in about 200 ms.
DECAY = 0.9
# The microphone has to stay this far above the expected echo ...
MARGIN = 2.0  # 6 dB
# ... and the bar rises when a hit turns out to have been the echo after
# all, up to this, and eases back a little on every real hit.
MAX_MARGIN = 4.0
FALSE_ALARM_STEP = 1.25
CONFIRMED_STEP = 1.1
# ... for this long. A door or a cough is shorter; a "stop" is not.
HOLD_MS = 150
# Below this the microphone is quiet whatever the arithmetic says; keeps a
# pause in the answer in a silent room from counting as a voice.
MIN_LEVEL = 0.005
# How the noise floor follows the microphone while nothing plays: quickly
# down, slowly up, so a sentence of the user's does not become "noise".
FLOOR_DOWN = 0.2
FLOOR_UP = 0.02


def _frames(ms: float) -> int:
    return max(1, int(round(ms / FRAME_MS)))


class BargeInDetector:
    def __init__(self, output_level: Callable[[float], float]):
        # How loud the output is right now; the player keeps that. Asked
        # per microphone frame, over one frame's worth of time.
        self._output_level = output_level
        self.enabled = True
        self.margin = MARGIN
        self._playing = False
        self._floor = 0.0
        # Delay in frames and microphone level per unit of output level.
        # Kept across playbacks: the devices, the room and the volume do
        # not change between two answers, so the next one can be judged
        # from its first word.
        self._delay: Optional[int] = None
        self._delay_score = 0.0
        self._gain = 0.0
        self._out: deque[float] = deque(maxlen=_frames(HISTORY_MS))
        self._mic: deque[float] = deque(maxlen=_frames(HISTORY_MS))
        self._ratios: deque[float] = deque(maxlen=_frames(GAIN_WINDOW_MS))
        self._heard = 0
        self._since_delay = 0
        self._expected_echo = 0.0
        self._above = 0
        self._fired = False

    # --- events ---

    def playback_started(self) -> None:
        self._playing = True
        # The loudness curves stay: the gap between two answers is quiet
        # on both sides and the answers together give the delay a longer
        # curve to be found in.
        self._ratios.clear()
        self._heard = 0
        self._since_delay = 0
        self._expected_echo = 0.0
        self._above = 0
        self._fired = False

    def playback_finished(self) -> None:
        self._playing = False

    def false_alarm(self) -> None:
        """The last hit was the echo after all: what came in was the
        wingman's own words and nothing else. This room needs more slack."""
        self.margin = min(self.margin * FALSE_ALARM_STEP, MAX_MARGIN)

    def confirmed(self) -> None:
        """The last hit was the user. The slack may ease back a little."""
        self.margin = max(MARGIN, self.margin / CONFIRMED_STEP)

    # --- frames ---

    def feed(self, frame: np.ndarray) -> bool:
        """One microphone frame. True once per playback, the moment someone
        talks over it."""
        rms = float(np.sqrt(np.mean(np.square(frame, dtype=np.float32))))
        if not self._playing:
            alpha = FLOOR_DOWN if rms < self._floor else FLOOR_UP
            self._floor += alpha * (rms - self._floor)
            return False
        if not self.enabled or self._fired:
            # After a hit nothing is measured any more: what comes in since
            # is the user, not the echo.
            return False
        out = self._output_level(FRAME_MS / 1000)
        mic = max(rms - self._floor, 0.0)
        self._out.append(out)
        self._mic.append(mic)
        self._heard += 1
        self._since_delay += 1
        enough = self._heard >= _frames(DELAY_AFTER_MS) if self._delay is None else len(self._out) == self._out.maxlen
        if enough and self._since_delay >= _frames(DELAY_EVERY_MS):
            self._since_delay = 0
            found = self._find_delay()
            if found is not None and found[1] >= self._delay_score - DELAY_WORSE_BY:
                self._delay, self._delay_score = found
        if self._delay is None:
            return False
        lagged = self._lagged_output()
        if lagged > OUTPUT_PRESENT:
            self._ratios.append(mic / lagged)
            if len(self._ratios) >= _frames(GAIN_WINDOW_MS) // 3:
                self._gain = float(np.median(self._ratios))
        if self._gain <= 0.0:
            return False
        self._expected_echo = max(self._gain * lagged, self._expected_echo * DECAY)
        expected = self._floor + self._expected_echo
        if rms > self.margin * expected and rms > MIN_LEVEL:
            self._above += 1
        else:
            self._above = 0
        if self._above >= _frames(HOLD_MS):
            self._fired = True
            return True
        return False

    # --- measuring ---

    def _lagged_output(self) -> float:
        """The output the microphone should be hearing now: what was played
        one delay ago, give or take a frame."""
        index = len(self._out) - 1 - self._delay
        if index < 0:
            return 0.0
        window = list(self._out)[max(0, index - JITTER_BACK) : index + JITTER_FORWARD + 1]
        return max(window) if window else 0.0

    def _find_delay(self) -> Optional[tuple[int, float]]:
        """The lag at which the microphone curve follows the output curve
        best, with how well it does. None when they do not clearly follow
        each other, e.g. with a headset, where nothing echoes at all."""
        out = np.array(self._out, dtype=np.float32)
        mic = np.array(self._mic, dtype=np.float32)
        if out.std() <= 0.0 or mic.std() <= 0.0:
            return None
        out = (out - out.mean()) / out.std()
        mic = (mic - mic.mean()) / mic.std()
        best_lag, best = None, DELAY_MIN_CORRELATION
        for lag in range(0, min(_frames(MAX_DELAY_MS), len(out) - 8) + 1):
            a = out[: len(out) - lag] if lag else out
            b = mic[lag:]
            score = float(np.dot(a, b) / len(a))
            if score > best:
                best_lag, best = lag, score
        return None if best_lag is None else (best_lag, best)
