"""Utterances become text here, one after the other.

A single worker thread: two utterances that arrive close together are
transcribed in order, the second waits, none is dropped. What happens with the
text is the caller's business; the callback runs on the worker thread too.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from os import path
from typing import TYPE_CHECKING, Callable, Optional

import soundfile

from api.enums import LogType
from services.benchmark import Benchmark
from services.file import get_writable_dir
from services.printr import Printr

if TYPE_CHECKING:
    from api.interface import BenchmarkResult
    from services.audio.voice_gate import Utterance
    from services.stt_service import SttService

RECORDING_PATH = "audio_output"
# A ring of files: an utterance may be written while the previous one is still
# being read by the transcriber.
FILE_SLOTS = 8
SAMPLE_RATE = 16000


class TranscriptionWorker:
    def __init__(self, stt_service: "SttService"):
        self.stt_service = stt_service
        self.printr = Printr()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")
        self._slot = 0
        self._slot_lock = threading.Lock()

    def submit_utterance(
        self,
        utterance: "Utterance",
        on_text: Callable[[str, "BenchmarkResult"], None],
    ) -> None:
        wav_path = self.write(utterance)
        self.submit_file(wav_path, on_text)

    def submit_file(
        self,
        wav_path: str,
        on_text: Callable[[str, "BenchmarkResult"], None],
    ) -> None:
        """A recording that arrived as a file, e.g. from an ESP32 device."""
        self._executor.submit(self._run, wav_path, on_text)

    def write(self, utterance: "Utterance") -> str:
        """Write the utterance to the next slot and return the path."""
        with self._slot_lock:
            slot = self._slot
            self._slot = (self._slot + 1) % FILE_SLOTS
        wav_path = path.join(get_writable_dir(RECORDING_PATH), f"utterance_{slot}.wav")
        soundfile.write(wav_path, utterance.samples, SAMPLE_RATE, subtype="PCM_16")
        return wav_path

    def _run(self, wav_path: str, on_text: Callable) -> None:
        benchmark = Benchmark(label="Voice transcription")
        try:
            text: Optional[str] = self.stt_service.transcribe(wav_path)
        except Exception as e:
            self.printr.print(
                f"Transcription failed: {e}", color=LogType.ERROR, server_only=True
            )
            return
        if not text:
            return
        try:
            on_text(text, benchmark.finish())
        except Exception as e:
            self.printr.print(
                f"Handling a transcript failed: {e}", color=LogType.ERROR, server_only=True
            )
