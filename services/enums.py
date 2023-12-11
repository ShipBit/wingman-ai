from enum import auto
from strenum import LowercaseStrEnum


class LogType(LowercaseStrEnum):
    SUBTLE = auto()
    INFO = auto()
    HIGHLIGHT = auto()
    POSITIVE = auto()
    WARNING = auto()
    ERROR = auto()
    PURPLE = auto()


class LogSource(LowercaseStrEnum):
    SYSTEM = auto()
    USER = auto()
    WINGMAN = auto()


class ToastType(LowercaseStrEnum):
    NORMAL = auto()
    ERROR = auto()
    WARNING = auto()
    INFO = auto()
