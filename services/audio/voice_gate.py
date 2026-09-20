"""Frames in, utterances out.

The gate has three modes:

- closed: frames are looked at only to keep the pre-roll ring warm.
- armed: the detector opens and closes utterances by itself (voice activation).
- held: something else opened the gate and will close it (push-to-talk). The
  detector still runs, so leading and trailing silence are trimmed and a clip
  without any speech is dropped rather than sent to a model that would invent
  words for it.

Whatever the mode, an utterance is the same thing: float32 samples at 16 kHz,
speech only, with a little room before and after, normalised to a sane level.
Downstream cannot tell how it came about.

The gate is not thread-safe on its own; the ListenController serialises access.
"""

from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512
FRAME_MS = FRAME_SAMPLES * 1000 / SAMPLE_RATE  # 32

# Keep this much silence after the last speech frame. Enough for a trailing
# consonant, not enough to feed a model a second of nothing.
TAIL_MS = 250
# Hysteresis, as in Silero's own iterator: once speaking, a frame has to fall
# this far below the threshold to count as silence. A breath between two words
# dips the score; it must not end the sentence.
NEG_MARGIN = 0.15
# When an utterance hits max_utterance_s, prefer cutting at the last pause of at
# least this length instead of mid-word.
SPLIT_PAUSE_MS = 100
# Utterances quieter than this are amplified up to this factor; louder ones are
# scaled down. A whisper into a distant mic still has to reach the model.
TARGET_PEAK = 0.9
MAX_GAIN = 20.0


@dataclass
class GateParams:
    """The user-facing knobs, taken from settings.voice_activation."""

    sensitivity: float = 0.5
    """0 = only unmistakable speech opens the gate, 1 = almost anything does."""
    end_pause_ms: int = 500
    """Silence that ends an utterance."""
    min_speech_ms: int = 200
    """Shorter bursts of speech are noise."""
    max_utterance_s: float = 160.0
    """Cut here even mid-sentence; what follows starts a new utterance."""
    pre_roll_ms: int = 300
    """Audio kept from before the detector noticed speech."""

    @property
    def threshold(self) -> float:
        # Silero's own default is 0.5. Sensitivity 0.5 lands slightly above
        # it; 1.0 opens on a whisper, 0.0 needs a clear voice.
        return 0.85 - 0.6 * min(max(self.sensitivity, 0.0), 1.0)


@dataclass
class Utterance:
    samples: np.ndarray
    """float32, 16 kHz, mono."""
    truncated: bool = False
    """True when max_utterance_s cut it; the speaker was still talking."""

    @property
    def duration_s(self) -> float:
        return len(self.samples) / SAMPLE_RATE


class VoiceGate:
    def __init__(self, vad: Callable[[np.ndarray], float], params: GateParams,
                 on_reset: Optional[Callable[[], None]] = None):
        self._vad = vad
        # Called when a fresh utterance begins so a stateful detector can forget
        # the previous one. SileroVad.reset; tests pass nothing.
        self._on_reset = on_reset
        self.params = params
        self.mode = "closed"
        self._pre_roll: deque[np.ndarray] = deque()
        self._set_pre_roll_length()
        self._reset_capture()
        self._reset_diagnostics()

    # --- configuration ---

    def update_params(self, params: GateParams) -> None:
        self.params = params
        self._set_pre_roll_length()

    def _set_pre_roll_length(self) -> None:
        # The ring must hold the pre-roll *and* the speech frames the detector
        # needs before it opens; those are still "before onset" from its view.
        self._pre_frames = max(1, int(round(self.params.pre_roll_ms / FRAME_MS)))
        onset = int(round(self.params.min_speech_ms / FRAME_MS)) + 1
        self._pre_roll = deque(self._pre_roll, maxlen=self._pre_frames + onset)

    # --- mode changes ---

    def arm(self) -> None:
        if self.mode != "armed":
            self._begin("armed")

    def hold(self) -> None:
        if self.mode != "held":
            self._begin("held")
            # People start talking a little before the key is down.
            self._frames = list(self._pre_roll)

    def close(self) -> Optional[Utterance]:
        """Closing while armed drops what was in flight; that is deliberate. A
        mute mid-sentence means "do not act on this"."""
        self.mode = "closed"
        self._reset_capture()
        return None

    def release(self) -> Optional[Utterance]:
        """Push-to-talk key up. Returns the utterance if there was speech."""
        if self.mode != "held":
            return None
        utterance = self._finish(truncated=False)
        self.mode = "closed"
        self._reset_capture()
        return utterance

    def _begin(self, mode: str) -> None:
        self.mode = mode
        self._reset_capture()
        self._reset_diagnostics()
        if self._on_reset:
            self._on_reset()

    def _reset_diagnostics(self) -> None:
        """How loud the clip was and how sure the detector was at best. Kept
        past close() so the log line for a dropped clip can read them."""
        self.last_peak = 0.0
        self.last_best_score = 0.0

    def _reset_capture(self) -> None:
        self._frames: list[np.ndarray] = []
        self._speaking = False
        self._speech_run = 0
        self._silence_run = 0
        self._candidate: list[np.ndarray] = []
        self._first_speech: Optional[int] = None
        self._last_speech: Optional[int] = None
        self._split_at: Optional[int] = None

    @property
    def is_capturing(self) -> bool:
        """Whether there is speech in the gate right now: an utterance under
        way, or the first frames of one that may still turn out to be noise."""
        return self._speaking or self._first_speech is not None or bool(self._candidate)

    # --- frames ---

    def feed(self, frame: np.ndarray) -> Optional[Utterance]:
        if self.mode == "closed":
            self._pre_roll.append(frame)
            return None
        score = self._vad(frame)
        threshold = self.params.threshold
        if self._speaking or (self.mode == "held" and self._first_speech is not None):
            threshold -= NEG_MARGIN
        is_speech = score >= threshold
        self.last_best_score = max(self.last_best_score, score)
        self.last_peak = max(self.last_peak, float(np.max(np.abs(frame))))
        if self.mode == "held":
            return self._feed_held(frame, is_speech)
        return self._feed_armed(frame, is_speech)

    def _feed_armed(self, frame: np.ndarray, is_speech: bool) -> Optional[Utterance]:
        if not self._speaking:
            self._pre_roll.append(frame)
            if is_speech:
                self._candidate.append(frame)
                self._speech_run += 1
                if self._speech_run * FRAME_MS >= self.params.min_speech_ms:
                    # The candidate frames are already in the ring; take the
                    # ring as it is so the onset keeps its context.
                    self._frames = list(self._pre_roll)
                    self._speaking = True
                    self._silence_run = 0
                    self._first_speech = max(0, len(self._frames) - self._speech_run)
                    self._last_speech = len(self._frames) - 1
            else:
                self._candidate = []
                self._speech_run = 0
            return None

        self._frames.append(frame)
        if is_speech:
            self._silence_run = 0
            self._last_speech = len(self._frames) - 1
        else:
            self._silence_run += 1
            if self._silence_run * FRAME_MS >= SPLIT_PAUSE_MS:
                self._split_at = len(self._frames)

        if self._silence_run * FRAME_MS >= self.params.end_pause_ms:
            utterance = self._finish(truncated=False)
            self._after_emit()
            return utterance
        if len(self._frames) * FRAME_MS >= self.params.max_utterance_s * 1000:
            return self._split_long()
        return None

    def _feed_held(self, frame: np.ndarray, is_speech: bool) -> Optional[Utterance]:
        self._frames.append(frame)
        if is_speech:
            if self._first_speech is None:
                self._first_speech = len(self._frames) - 1
            self._last_speech = len(self._frames) - 1
            self._silence_run = 0
        elif self._first_speech is not None:
            self._silence_run += 1
            if self._silence_run * FRAME_MS >= SPLIT_PAUSE_MS:
                self._split_at = len(self._frames)
        if len(self._frames) * FRAME_MS >= self.params.max_utterance_s * 1000:
            return self._split_long()
        return None

    def _split_long(self) -> Optional[Utterance]:
        """The utterance reached max length. Cut at the last pause of at least
        SPLIT_PAUSE_MS if there was one in the second half, so no word is cut in
        two; the frames after the cut open the next utterance."""
        split = self._split_at
        # Where the speech the carry starts with sits in the carry's own frame
        # numbering. Without it a speaker who stops right after the cut loses
        # those frames: _finish needs a last speech frame to emit anything.
        carry_last: Optional[int] = None
        if split is not None and split > len(self._frames) // 2:
            carry = self._frames[split:]
            self._frames = self._frames[:split]
            if self._last_speech is not None and self._last_speech >= split:
                carry_last = self._last_speech - split
                self._last_speech = split - 1
        else:
            carry = []
        utterance = self._finish(truncated=True)
        self._after_emit()
        if carry:
            # Continue with what came after the pause, as if it had just arrived.
            self._frames = carry
            self._first_speech = 0 if carry_last is not None else None
            self._last_speech = carry_last
            if self.mode == "armed":
                # Still inside speech: keep the speaking state so the pause
                # logic carries on instead of waiting for a new onset.
                self._speaking = True
                self._first_speech = 0
        return utterance

    def _after_emit(self) -> None:
        """Start the next utterance in the same mode, keeping the ring."""
        mode = self.mode
        self._reset_capture()
        self._reset_diagnostics()
        self.mode = mode

    def _finish(self, truncated: bool) -> Optional[Utterance]:
        if self._first_speech is None or self._last_speech is None:
            return None
        pre = self._pre_frames
        tail = int(round(TAIL_MS / FRAME_MS))
        start = max(0, self._first_speech - pre)
        end = min(len(self._frames), self._last_speech + 1 + tail)
        frames = self._frames[start:end]
        speech_ms = (self._last_speech - self._first_speech + 1) * FRAME_MS
        if not frames or speech_ms < self.params.min_speech_ms:
            return None
        samples = np.concatenate(frames).astype(np.float32, copy=False)
        return Utterance(samples=_normalise(samples), truncated=truncated)


def _normalise(samples: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak <= 0.0:
        return samples
    gain = min(TARGET_PEAK / peak, MAX_GAIN)
    return samples * np.float32(gain)
