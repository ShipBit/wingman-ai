"""Noticing the user talking over a wingman, by loudness alone.

Through speakers the microphone hears the wingman. What it hears is, near
enough, the playback scaled by one gain (volume, distance, room) on top of
the room's own noise. Both are measured rather than assumed: the noise
while nothing plays, the gain while the wingman speaks. From then on a
microphone level well above noise plus the expected echo means somebody
else is talking, and the caller stops the playback. No model and no
transcription; a few multiplications per frame.

Text cannot do this job: with speakers the wingman never pauses, so an
utterance said over it only ends when the wingman stops, and any decision
on its text comes after the fact.
"""

from collections import deque
from typing import Callable

import numpy as np

from services.audio.voice_gate import FRAME_MS

# Output that has to be heard in a playback before its own gain estimate is
# trusted. Until then the gain of the last playback serves, if there was one.
WARMUP_MS = 500
# Over how much recent output the gain is estimated. The median of it: the
# user's voice in part of the window does not move it, the echo in most of
# it does.
GAIN_WINDOW_MS = 1500
# Output level below this is silence for the purpose of measuring the gain.
OUTPUT_PRESENT = 1e-3
# The microphone has to stay this far above the expected echo ...
MARGIN = 2.0  # 6 dB
# ... for this long. A door or a cough is shorter; a "stop" is not.
HOLD_MS = 150
# Below this the microphone is quiet whatever the arithmetic says; keeps a
# pause in the answer in a silent room from counting as a voice.
MIN_LEVEL = 0.005
# How the noise floor follows the microphone while nothing plays: quickly
# down, slowly up, so a sentence of the user's does not become "noise".
FLOOR_DOWN = 0.2
FLOOR_UP = 0.02


class BargeInDetector:
    def __init__(self, output_level: Callable[[], float]):
        # The loudest the playback has been over the last moments; the
        # player keeps that. A window rather than an instant, because the
        # echo arrives late, up to a few hundred milliseconds on Bluetooth.
        self._output_level = output_level
        self.enabled = True
        self._playing = False
        self._floor = 0.0
        # Microphone level per unit of output level. Kept across playbacks:
        # the room and the volume do not change between two answers, so the
        # next one can be judged from its first word.
        self._gain = 0.0
        self._ratios: deque[float] = deque(maxlen=max(1, int(GAIN_WINDOW_MS / FRAME_MS)))
        self._heard_ms = 0.0
        self._above_ms = 0.0
        self._fired = False

    # --- events ---

    def playback_started(self) -> None:
        self._playing = True
        self._ratios.clear()
        self._heard_ms = 0.0
        self._above_ms = 0.0
        self._fired = False

    def playback_finished(self) -> None:
        self._playing = False

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
            # After a hit the gain stays as it was measured before it: what
            # came in since is the user, not the echo.
            return False
        out = self._output_level()
        if out > OUTPUT_PRESENT:
            self._ratios.append(max(rms - self._floor, 0.0) / out)
            self._heard_ms += FRAME_MS
            if self._heard_ms >= WARMUP_MS:
                self._gain = float(np.median(self._ratios))
        if self._gain <= 0.0:
            # Nothing measured yet, in this playback or an earlier one.
            return False
        expected = self._floor + self._gain * out
        if rms > MARGIN * expected and rms > MIN_LEVEL:
            self._above_ms += FRAME_MS
        else:
            self._above_ms = 0.0
        if self._above_ms >= HOLD_MS:
            self._fired = True
            return True
        return False
