"""The microphone stream.

Opened once and kept open. The audio callback copies each frame into a queue
and returns; a consumer thread takes the frames out and hands them to whoever
listens. Nothing else happens here: no gain, no detection, no recording.
Muting the microphone is not this class's business, the gate downstream simply
ignores the frames.

The stream is restarted only when the input device changes.
"""

import queue
import threading
from typing import Callable, Optional

import numpy as np
import sounddevice

from api.enums import LogType
from services.printr import Printr

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512  # 32 ms, the Silero VAD frame


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

    # --- lifecycle ---

    def start(self) -> bool:
        with self._lock:
            self._close_stream()
            try:
                self._stream = sounddevice.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                    blocksize=FRAME_SAMPLES,
                    device=sounddevice.default.device[0],
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
            if self._consumer is None:
                self._consumer = threading.Thread(
                    target=self._consume, name="audio-input", daemon=True
                )
                self._consumer.start()
            self.printr.print("Microphone stream opened.", color=LogType.INFO, server_only=True)
            return True

    def restart(self) -> bool:
        """After a device change: the stream is bound to the device it was opened on."""
        return self.start()

    def stop(self) -> None:
        with self._lock:
            self._close_stream()
            self.available = False

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
        frame = indata[:, 0].copy()
        if frame.shape[0] != FRAME_SAMPLES:
            return
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            # The consumer is stuck; dropping a frame is better than blocking the
            # audio thread, which would stall every stream in the process.
            pass

    # --- consumer thread ---

    def _consume(self) -> None:
        while True:
            frame = self._queue.get()
            if frame is None:
                return
            try:
                self.on_frame(frame)
            except Exception as e:
                self.printr.print(
                    f"Audio input: frame handler failed: {e}",
                    color=LogType.ERROR,
                    server_only=True,
                )
