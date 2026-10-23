"""Microphone input: one stream, one voice gate, one state machine.

`AudioInput` owns the microphone stream and hands out fixed-size frames.
`VoiceGate` turns frames into utterances with a voice activity detector.
`ListenController` decides when the gate is open and for whom.
`TranscriptionWorker` turns utterances into text, one at a time.

Push-to-talk and voice activation differ only in who opens the gate: a key or
the detector. Everything after the gate is the same.
"""

from services.audio.input import AudioInput, FRAME_SAMPLES, SAMPLE_RATE
from services.audio.listen_controller import ListenController, ListenState
from services.audio.transcription_worker import TranscriptionWorker
from services.audio.vad import SileroVad
from services.audio.voice_gate import GateParams, Utterance, VoiceGate

__all__ = [
    "AudioInput",
    "FRAME_SAMPLES",
    "SAMPLE_RATE",
    "GateParams",
    "ListenController",
    "ListenState",
    "SileroVad",
    "TranscriptionWorker",
    "Utterance",
    "VoiceGate",
]
