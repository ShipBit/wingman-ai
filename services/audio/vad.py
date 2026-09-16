"""Silero VAD on onnxruntime.

One model file, about 2 MB, MIT licensed, from github.com/snakers4/silero-vad.
It answers "how likely is it that this 32 ms frame is speech" with a number
between 0 and 1 and carries a small recurrent state from frame to frame, so it
has to see the frames in order. The decision is learned, not a loudness
measurement: a quiet microphone and a loud one get the same answer.

onnxruntime is already shipped for Parakeet, so the detector costs nothing to
package and well under a millisecond per frame on a CPU.
"""

from os import path

import numpy as np
import onnxruntime as ort

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512  # 32 ms; the size the model was trained on for 16 kHz
MODEL_FILE = path.join("audio_models", "silero_vad.onnx")


class SileroVad:
    def __init__(self, app_root_path: str):
        options = ort.SessionOptions()
        # The model is tiny; more threads only add scheduling cost, and the
        # STT model next door wants the cores more than this does.
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            path.join(app_root_path, MODEL_FILE),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self._sr = np.array(SAMPLE_RATE, dtype=np.int64)
        self._state = self._fresh_state()

    @staticmethod
    def _fresh_state() -> np.ndarray:
        return np.zeros((2, 1, 128), dtype=np.float32)

    def reset(self) -> None:
        """Forget the previous frames. Call it when the gate opens, so what was
        said a minute ago does not colour the first frame of a new utterance."""
        self._state = self._fresh_state()

    def __call__(self, frame: np.ndarray) -> float:
        """Speech probability for one frame of FRAME_SAMPLES float32 samples."""
        if frame.shape[0] != FRAME_SAMPLES:
            raise ValueError(f"Silero VAD expects {FRAME_SAMPLES} samples, got {frame.shape[0]}")
        output, self._state = self._session.run(
            None,
            {
                "input": frame.reshape(1, FRAME_SAMPLES).astype(np.float32, copy=False),
                "state": self._state,
                "sr": self._sr,
            },
        )
        return float(output[0][0])
