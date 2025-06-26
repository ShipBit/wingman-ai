from __future__ import annotations

"""Audio recording with a permanent low‑latency stream and configurable pre‑roll.

Fix #2 implementation: the input device is opened exactly **once**.  All incoming
blocks are pushed into a bounded deque (ring buffer).  When a recording session
starts we splice a *copy* of that pre‑roll in front of the live data, ensuring
that nothing spoken immediately after the hot‑key is lost.

The memory footprint is bounded (pre‑roll * blocksize) and CPU‑overhead is
negligible because we never re‑open/close the device.
"""

import numpy as np
import sounddevice as sd
import soundfile as sf

from collections import deque
from pathlib import Path
from typing import Deque, Optional, List
from services.memory_logger import log_memory_usage

from services.printr import Printr
from services.file_creator import FileCreator

RECORDING_PATH = "audio_output"
RECORDING_FILE = "recording.wav"


class AudioRecorder(FileCreator):
    """High‑performance audio recorder that supports *instant* capture.

    The stream lives for the lifetime of the object.  For every block that
    arrives we push a copy into :pyattr:`ring_buffer` (bounded) so we always
    retain the last *N* milliseconds (``pre_roll_ms``).  When
    :py:meth:`start_recording` is called we begin copying subsequent blocks into
    :pyattr:`recording_chunks` and *prepend* the current contents of
    :pyattr:`ring_buffer` – voilà, zero‑loss capture.
    """

    def __init__(
        self,
        app_root_dir: str,
        samplerate: int = 44_100,
        channels: int = 1,
        *,
        pre_roll_ms: int = 100,
        blocksize: int = 256,
    ) -> None:
        super().__init__(app_root_dir, RECORDING_PATH)

        # ☞ Public configuration -------------------------------------------------
        self.samplerate: int = samplerate
        self.channels: int = channels
        self.blocksize: int = blocksize
        self.pre_roll_ms: int = pre_roll_ms

        # ☞ Internal state -------------------------------------------------------
        max_blocks = int((samplerate * pre_roll_ms / 1000) / blocksize) + 1
        self.ring_buffer: Deque[np.ndarray] = deque(maxlen=max_blocks)
        self.recording_chunks: List[np.ndarray] = []
        self.is_recording: bool = False

        # ☞ I/O ------------------------------------------------------------------
        self.file_path: Path = Path(self.get_full_file_path(RECORDING_FILE))
        self.printr = Printr()

        # Single input stream for the whole application lifecycle
        self._stream = sd.InputStream(
            callback=self._handle_input_stream,
            samplerate=self.samplerate,
            channels=self.channels,
            blocksize=self.blocksize,
            latency="low",  # WASAPI/ASIO low‑latency path where available
        )
        self._stream.start()

    # ---------------------------------------------------------------------
    # Public API expected by the rest of the application
    # ---------------------------------------------------------------------
    def start_recording(self) -> None:
        """Begin a new recording session, seeding it with the current pre‑roll."""
        if self.is_recording:
            return  # already capturing

        # Snapshot pre‑roll *now* so subsequent blocks are not duplicated
        self.recording_chunks = list(self.ring_buffer)
        self.is_recording = True
        self.printr.print("Recording started", tags="grey")
        log_memory_usage("audio_start")

    def stop_recording(self) -> Optional[str]:
        """Stop capture – returns the written WAV path or *None* if discarded."""
        if not self.is_recording:
            return None

        self.is_recording = False
        self.printr.print("Recording stopped", tags="grey")
        log_memory_usage("audio_stop")

        if not self.recording_chunks:
            self.printr.print("Ignored empty recording", tags="warn")
            return None

        recording = np.concatenate(self.recording_chunks, axis=0)
        self.recording_chunks.clear()

        # Ignore extremely short blips (<150 ms) to avoid false triggers
        if (len(recording) / self.samplerate) < 0.15:
            self.printr.print(
                "Recording was too short to be handled by the AI", tags="warn"
            )
            return None

        sf.write(self.file_path, recording, self.samplerate)
        return str(self.file_path)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _handle_input_stream(self, indata, _frames, _time, _status):  # noqa: N802
        """Stream callback – runs in the PortAudio thread."""
        # Keep the *last* pre‑roll window
        self.ring_buffer.append(indata.copy())

        # If recording is active, stash the current block
        if self.is_recording:
            self.recording_chunks.append(indata.copy())

    # ------------------------------------------------------------------
    # Cleanup helpers – good citizenship, especially for PyInstaller build
    # ------------------------------------------------------------------
    def close(self) -> None:
        """Stop the permanent stream – call this exactly once at shutdown."""
        try:
            self._stream.stop()
            self._stream.close()
        except sd.PortAudioError:
            pass  # already closed or failed silently

    def __del__(self):
        # Fail‑safe: free the device even if the caller forgot to invoke close()
        self.close()
