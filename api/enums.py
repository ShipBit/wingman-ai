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


class AzureApiVersion(Enum):
    A2022_12_01 = "2022-12-01"
    A2023_03_15_PREVIEW = "2023-03-15-preview"
    A2023_05_15 = "2023-05-15"
    A2023_06_01_PREVIEW = "2023-06-01-preview"
    A2023_07_01_PREVIEW = "2023-07-01-preview"
    A2023_08_01_PREVIEW = "2023-08-01-preview"
    A2023_09_01_PREVIEW = "2023-09-01-preview"


class ElevenlabsModel(Enum):
    ELEVEN_MULTILINGUAL_V2 = "eleven_multilingual_v2"
    ELEVEN_TURBO_V2 = "eleven_turbo_v2"
    ELEVEN_MONOLINGUAL_V1 = "eleven_monolingual_v1"


class EdgeTtsVoiceGender(Enum):
    MALE = "Male"
    FEMALE = "Female"


class OpenAiModel(Enum):
    GPT_35_TURBO_1106 = "gpt-3.5-turbo-1106"
    GPT_4_1106_PREVIEW = "gpt-4-1106-preview"


class OpenAiTtsVoice(Enum):
    NOVA = "nova"
    ALLOY = "alloy"
    ECHO = "echo"
    FABLE = "fable"
    ONYX = "onyx"
    SHIMMER = "shimmer"


class SoundEffect(Enum):
    ROBOT = "ROBOT"
    RADIO = "RADIO"
    INTERIOR_HELMET = "INTERIOR_HELMET"
    INTERIOR_SMALL = "INTERIOR_SMALL"
    INTERIOR_MEDIUM = "INTERIOR_MEDIUM"
    INTERIOR_LARGE = "INTERIOR_LARGE"


class TtsProvider(Enum):
    OPENAI = "openai"
    ELEVENLABS = "elevenlabs"
    EDGE_TTS = "edge_tts"
    AZURE = "azure"


class SttProvider(Enum):
    OPENAI = "openai"
    AZURE = "azure"
    AZURE_SPEECH = "azure_speech"


class ConversationProvider(Enum):
    OPENAI = "openai"
    AZURE = "azure"


class SummarizeProvider(Enum):
    OPENAI = "openai"
    AZURE = "azure"


# Pydantic models for enums
class BaseEnumModel(BaseModel):
    class Config:
        # fix pydantic serialization of enums
        json_encoders = {
            Enum: lambda v: v.value,
        }


class LogTypeEnumModel(BaseEnumModel):
    log_type: LogType


class LogSourceEnumModel(BaseEnumModel):
    log_source: LogSource


class ToastTypeEnumModel(BaseEnumModel):
    toast_type: ToastType


class AzureApiVersionEnumModel(BaseEnumModel):
    api_version: AzureApiVersion


class ElevenlabsModelEnumModel(BaseEnumModel):
    model: ElevenlabsModel


class EdgeTtsVoiceGenderEnumModel(BaseEnumModel):
    gender: EdgeTtsVoiceGender


class OpenAiModelEnumModel(BaseEnumModel):
    model: OpenAiModel


class OpenAiTtsVoiceEnumModel(BaseEnumModel):
    voice: OpenAiTtsVoice


class SoundEffectEnumModel(BaseEnumModel):
    sound_effect: SoundEffect


class TtsProviderEnumModel(BaseEnumModel):
    tts_provider: TtsProvider


class SttProviderEnumModel(BaseEnumModel):
    stt_provider: SttProvider


class ConversationProviderEnumModel(BaseEnumModel):
    conversation_provider: ConversationProvider


class SummarizeProviderEnumModel(BaseEnumModel):
    summarize_provider: SummarizeProvider


# Add all additional Pydantic models for enums as needed


# Enums and their corresponding model classes for dynamic schema generation
ENUM_TYPES = {
    "LogType": LogTypeEnumModel,
    "LogSource": LogSourceEnumModel,
    "ToastType": ToastTypeEnumModel,
    "AzureApiVersion": AzureApiVersionEnumModel,
    "ElevenlabsModel": ElevenlabsModelEnumModel,
    "EdgeTtsVoiceGender": EdgeTtsVoiceGenderEnumModel,
    "OpenAiModel": OpenAiModelEnumModel,
    "OpenAiTtsVoice": OpenAiTtsVoiceEnumModel,
    "SoundEffect": SoundEffectEnumModel,
    "TtsProvider": TtsProviderEnumModel,
    "SttProvider": SttProviderEnumModel,
    "ConversationProvider": ConversationProviderEnumModel,
    "SummarizeProvider": SummarizeProviderEnumModel,
    # Add new enums here as key-value pairs
}
