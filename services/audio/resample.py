"""Between the devices' rates and ours, block by block.

The microphone is opened at its own rate. Asking PortAudio for 16 kHz makes it
set the device to 16 kHz, and on a duplex interface (one box for mic and
speakers, a headset, an EVO4) the speakers then cannot open at their rate:
CoreAudio answers "cannot do in current context" and the input goes silent.
At the native rate nothing is changed on the device.

The same holds the other way round: the speakers are opened at their own
rate too, and what a voice provider sends at 16 or 24 kHz is converted on
the way out (RateConverter). On a duplex device the output opening at the
provider's rate would switch the device and cut the microphone off, right
when the wingman starts to speak.

The conversion is a stateful low-pass followed by linear interpolation. That
is enough for speech at 16 kHz and needs nothing beyond numpy and scipy, which
ship anyway. Blocks of any length go in; frames of exactly FRAME_SAMPLES come
out, as many as are complete.
"""

import numpy as np
from scipy.signal import firwin, lfilter, lfilter_zi

TARGET_RATE = 16000
FRAME_SAMPLES = 512


class Resampler:
    def __init__(self, source_rate: int, target_rate: int = TARGET_RATE, frame: int = FRAME_SAMPLES):
        self.source_rate = int(source_rate)
        self.target_rate = int(target_rate)
        self.frame = frame
        self.identity = self.source_rate == self.target_rate
        if not self.identity:
            # Cut just under the lower of the two Nyquists. 7 kHz keeps
            # everything speech has; an 8 kHz headset is below that and would
            # make firwin raise, so the source rate caps the cutoff too.
            cutoff = min(7000.0, self.target_rate * 0.45, self.source_rate * 0.45)
            self._taps = firwin(numtaps=63, cutoff=cutoff, fs=self.source_rate)
            self._zi = lfilter_zi(self._taps, 1.0) * 0.0
            self._step = self.source_rate / self.target_rate
            self._pos = 0.0  # fractional read position into the carried input
            self._carry = np.zeros(0, dtype=np.float32)
        self._out = np.zeros(0, dtype=np.float32)

    def push(self, block: np.ndarray) -> list[np.ndarray]:
        """Feed one block of source samples; get every complete 16 kHz frame."""
        block = np.asarray(block, dtype=np.float32).reshape(-1)
        if self.identity:
            converted = block
        else:
            filtered, self._zi = lfilter(self._taps, 1.0, block, zi=self._zi)
            converted = self._interpolate(filtered.astype(np.float32, copy=False))
        self._out = np.concatenate([self._out, converted]) if self._out.size else converted
        frames = []
        while self._out.size >= self.frame:
            frames.append(self._out[: self.frame].copy())
            self._out = self._out[self.frame :]
        return frames

    def _interpolate(self, samples: np.ndarray) -> np.ndarray:
        # Keep one sample from the previous block so interpolation can cross
        # the block boundary without a seam.
        buffer = np.concatenate([self._carry, samples]) if self._carry.size else samples
        if buffer.size < 2:
            self._carry = buffer
            return np.zeros(0, dtype=np.float32)
        last = buffer.size - 1
        positions = np.arange(self._pos, last, self._step)
        if positions.size == 0:
            self._carry = buffer[-1:]
            self._pos -= last
            return np.zeros(0, dtype=np.float32)
        idx = positions.astype(np.int64)
        frac = (positions - idx).astype(np.float32)
        out = buffer[idx] * (1.0 - frac) + buffer[idx + 1] * frac
        next_pos = positions[-1] + self._step
        keep_from = int(next_pos)
        self._carry = buffer[keep_from:]
        self._pos = next_pos - keep_from
        return out.astype(np.float32, copy=False)


class RateConverter:
    """Any rate to any rate, block by block, for one channel of output. The
    same interpolation as the Resampler, with the low-pass only when going
    down; going up there is nothing to alias. Every converted sample comes
    back, no framing."""

    def __init__(self, source_rate: int, target_rate: int):
        self._inner = Resampler(source_rate, target_rate, frame=1)
        if not self._inner.identity and target_rate > source_rate:
            self._inner._taps = None

    def convert(self, block: np.ndarray) -> np.ndarray:
        block = np.asarray(block, dtype=np.float32).reshape(-1)
        inner = self._inner
        if inner.identity:
            return block
        if inner._taps is not None:
            block, inner._zi = lfilter(inner._taps, 1.0, block, zi=inner._zi)
            block = block.astype(np.float32, copy=False)
        return inner._interpolate(block)
