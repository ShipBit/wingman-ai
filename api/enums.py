from enum import Enum
from pydantic import BaseModel


# Enum declarations
class LogType(Enum):
    SUBTLE = "subtle"
    INFO = "info"
    HIGHLIGHT = "highlight"
    POSITIVE = "positive"
    WARNING = "warning"
    ERROR = "error"
    PURPLE = "purple"


class LogSource(Enum):
    SYSTEM = "system"
    USER = "user"
    WINGMAN = "wingman"


class ToastType(Enum):
    NORMAL = "normal"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


# Add all additional enums as needed


# Pydantic models for enums


class BaseEnumModel(BaseModel):
    class Config:
        # fix serialization of enums
        json_encoders = {
            Enum: lambda v: v.value,
        }


class LogTypeEnumModel(BaseEnumModel):
    log_type: LogType


class LogSourceEnumModel(BaseEnumModel):
    log_source: LogSource


class ToastTypeEnumModel(BaseEnumModel):
    toast_type: ToastType


# Add all additional Pydantic models for enums as needed

# Enums and their corresponding model classes for dynamic schema generation
ENUM_TYPES = {
    "LogType": LogTypeEnumModel,
    "LogSource": LogSourceEnumModel,
    "ToastType": ToastTypeEnumModel,
    # Add new enums here as key-value pairs
}
