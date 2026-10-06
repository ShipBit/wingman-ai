"""The microphone stream.

Opened once and kept open, at the device's own sample rate: asking for 16 kHz
would make PortAudio change the device's rate, and on a duplex interface the
speakers then fail to open ("cannot do in current context") and the input
goes silent. The blocks are resampled to 16 kHz here.

The audio callback copies each block into a queue and returns; a consumer
thread resamples, cuts 512-sample frames and hands them to whoever listens.
Nothing else happens here: no gain, no detection, no recording. Muting the
microphone is not this class's business, the gate downstream simply ignores
the frames.

The stream is restarted when the input device changes, and by a watchdog when
it stops delivering while it claims to be open.
"""

import queue
import threading
from typing import Callable, Optional

import numpy as np
import sounddevice

from api.enums import LogType
from services.audio.resample import Resampler
from services.printr import Printr

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512  # 32 ms, the Silero VAD frame
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE


def device_blocksize(rate: int) -> int:
    """Frames per block at this rate, one VAD frame's worth. The speakers use
    the same: on a duplex device, two streams with different block sizes make
    CoreAudio reconfigure the device under the other one, which then fails
    with "cannot do in current context" or glitches."""
    return int(round(rate * FRAME_SECONDS))
# No block for this long while the stream is open means the stream is dead.
STALL_SECONDS = 3.0


class AudioInput:
    def __init__(self, on_frame: Callable[[np.ndarray], None]):
        self.on_frame = on_frame
        self.printr = Printr()
        self._queue: "queue.Queue[Optional[np.ndarray]]" = queue.Queue(maxsize=256)
        self._stream: Optional[sounddevice.InputStream] = None
        self._consumer: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        # Whether the last attempt to open the device worked. The error toast is
        # shown once per failure, not once per retry.
        self.available = False
        self._reported = False
        self._resampler: Optional[Resampler] = None
        self.device_rate = SAMPLE_RATE
        # Set by stop(): the watchdog then stops retrying.
        self._stopped = False

    # --- lifecycle ---

    def start(self) -> bool:
        with self._lock:
            self._close_stream()
            self._stopped = False
            # Before the attempt, not after: a failed start must leave the
            # watchdog running, otherwise one bad start (device busy at boot)
            # kills the microphone for the rest of the session.
            self._ensure_consumer()
            try:
                device = sounddevice.default.device[0]
                info = sounddevice.query_devices(device, kind="input")
                self.device_rate = int(round(float(info["default_samplerate"]))) or SAMPLE_RATE
                self._resampler = Resampler(self.device_rate)
                self._stream = sounddevice.InputStream(
                    samplerate=self.device_rate,
                    channels=1,
                    dtype="float32",
                    blocksize=device_blocksize(self.device_rate),
                    device=device,
                    callback=self._callback,
                )
                self._stream.start()
            except Exception as e:
                self._stream = None
                if not self._reported:
                    self._reported = True
                    self.printr.toast_error(
                        "Unable to open the microphone. Please check your microphone, "
                        "anti-virus and privacy settings. Audio input will be disabled."
                    )
                    self.printr.print(f"Microphone: {e}", color=LogType.ERROR, server_only=True)
                self.available = False
                return False
            self.available = True
            self._reported = False
            self.printr.print(
                f"Microphone stream opened ({info['name']}, {self.device_rate} Hz).",
                color=LogType.INFO,
                server_only=True,
            )
            return True

    def restart(self) -> bool:
        """After a device change: the stream is bound to the device it was opened on."""
        return self.start()

    def _ensure_consumer(self) -> None:
        """Called under the lock. The thread runs for the whole session."""
        if self._consumer is None:
            self._consumer = threading.Thread(target=self._consume, name="audio-input", daemon=True)
            self._consumer.start()

    def stop(self) -> None:
        with self._lock:
            self._close_stream()
            self.available = False
            self._stopped = True

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    # --- audio thread ---

    def _callback(self, indata, frames, _time, status) -> None:
        if status and status.input_overflow:
            # Frames were lost in the driver. Nothing to do but know about it.
            self.printr.print("Microphone: input overflow.", server_only=True, color=LogType.WARNING)
        try:
            self._queue.put_nowait(indata[:, 0].copy())
        except queue.Full:
            # The consumer is stuck; dropping a frame is better than blocking the
            # audio thread, which would stall every stream in the process.
            pass

    # --- consumer thread ---

    def _consume(self) -> None:
        while True:
            try:
                block = self._queue.get(timeout=STALL_SECONDS)
            except queue.Empty:
                if self._stopped:
                    continue
                if self.available:
                    self.printr.print(
                        "Microphone stopped delivering audio; reopening the stream.",
                        color=LogType.WARNING,
                        server_only=True,
                    )
                    self.restart()
                else:
                    # The device was busy or missing when we last tried. Try
                    # again quietly; the toast was shown on the first failure.
                    self.restart()
                continue
            if block is None:
                return
            resampler = self._resampler
            if resampler is None:
                continue
            try:
                for frame in resampler.push(block):
                    self.on_frame(frame)
            except Exception as e:
                self.printr.print(
                    f"Audio input: frame handler failed: {e}",
                    color=LogType.ERROR,
                    server_only=True,
                )
