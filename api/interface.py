from typing_extensions import TypedDict
from pydantic import BaseModel


class ContextInfo(BaseModel):
    contexts: list[str]
    currentContext: str


class SystemCore(TypedDict):
    version: str
    latest: str
    isLatest: bool


class SystemInfo(BaseModel):
    os: str
    core: SystemCore


# from sounddevice lib
class AudioDevice(BaseModel):
    name: str
    index: int
    hostapi: int
    max_input_channels: int
    max_output_channels: int
    default_low_input_latency: float
    default_low_output_latency: float
    default_high_input_latency: float
    default_high_output_latency: float
    default_samplerate: int


class AudioDevices(BaseModel):
    input: int | None
    output: int | None
